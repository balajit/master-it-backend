"""Deterministic triage agent implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from learning_platform.agentic_ops.contracts.mcp import (
    DatabaseEntriesReportPage,
    MissingEntryTable,
    ReportScope,
    TableReport,
)
from learning_platform.agentic_ops.rules.models import (
    CrossTableMinimumRule,
    ForeignKeyIntegrityRule,
    RequiredColumnsRule,
    RuleSet,
    TableNonEmptyRule,
    TriageRule,
)
from learning_platform.agentic_ops.triage.models import (
    TriageFinding,
    TriageResult,
    TriageStats,
    TriageVerdict,
)


class ReportProvider(Protocol):
    """Fetches report pages and missing-entry hints for triage."""

    async def report_all_entries(
        self,
        *,
        scope: ReportScope,
        page_size: int,
        include_rows: bool,
        cursor: str | None,
    ) -> DatabaseEntriesReportPage: ...

    async def report_missing_entries(
        self,
        *,
        scope: ReportScope,
    ) -> list[MissingEntryTable]: ...


@dataclass(slots=True)
class _Context:
    table_map: dict[str, TableReport]


class TriageAgent:
    """Evaluate report payloads against versioned deterministic rules."""

    def __init__(
        self,
        *,
        provider: ReportProvider,
        rule_set: RuleSet,
        page_size: int = 500,
        include_rows: bool = False,
    ) -> None:
        self._provider = provider
        self._rule_set = rule_set
        self._page_size = page_size
        self._include_rows = include_rows

    async def run(self, scope: ReportScope) -> TriageResult:
        pages = await self._fetch_pages(scope)
        merged_page = self._merge_pages(pages)

        try:
            missing_tables = await self._provider.report_missing_entries(scope=scope)
        except Exception:
            missing_tables = merged_page.missing_entry_tables

        context = _Context(table_map={table.table_name: table for table in merged_page.tables})
        findings = self._evaluate_rules(context)
        findings.extend(self._missing_table_findings(missing_tables))

        verdict = self._compute_verdict(findings)
        stats = self._compute_stats(merged_page, findings)

        return TriageResult(
            report_id=merged_page.report_id,
            scope=merged_page.scope,
            rule_set_name=self._rule_set.name,
            rule_set_version=self._rule_set.version,
            generated_at=merged_page.generated_at,
            verdict=verdict,
            findings=findings,
            missing_entry_tables=missing_tables,
            stats=stats,
        )

    async def _fetch_pages(self, scope: ReportScope) -> list[DatabaseEntriesReportPage]:
        pages: list[DatabaseEntriesReportPage] = []
        cursor: str | None = None
        while True:
            page = await self._provider.report_all_entries(
                scope=scope,
                page_size=self._page_size,
                include_rows=self._include_rows,
                cursor=cursor,
            )
            pages.append(page)
            if not page.next_cursor:
                break
            if page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return pages

    def _merge_pages(
        self,
        pages: list[DatabaseEntriesReportPage],
    ) -> DatabaseEntriesReportPage:
        if not pages:
            raise ValueError("MCP report returned zero pages")

        base = pages[0].model_copy(deep=True)
        if len(pages) == 1:
            return base

        table_by_name: dict[str, TableReport] = {
            table.table_name: table.model_copy(deep=True) for table in base.tables
        }
        missing_by_name: dict[str, MissingEntryTable] = {
            row.table_name: row.model_copy(deep=True) for row in base.missing_entry_tables
        }

        for page in pages[1:]:
            for table in page.tables:
                table_by_name[table.table_name] = table.model_copy(deep=True)
            for missing in page.missing_entry_tables:
                missing_by_name[missing.table_name] = missing.model_copy(deep=True)

        base.tables = list(table_by_name.values())
        base.missing_entry_tables = list(missing_by_name.values())
        base.next_cursor = None
        return base

    def _evaluate_rules(self, context: _Context) -> list[TriageFinding]:
        findings: list[TriageFinding] = []
        for rule in self._rule_set.rules:
            finding = self._evaluate_rule(rule, context)
            if finding is not None:
                findings.append(finding)
        return findings

    def _evaluate_rule(
        self,
        rule: TriageRule,
        context: _Context,
    ) -> TriageFinding | None:
        if isinstance(rule, TableNonEmptyRule):
            table = context.table_map.get(rule.table_name)
            if table is None:
                return TriageFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    table_name=rule.table_name,
                    message=f"Table '{rule.table_name}' is missing from report",
                    affected_count=1,
                )
            if table.row_count <= 0:
                return TriageFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    table_name=rule.table_name,
                    message=f"Table '{rule.table_name}' has zero rows",
                    affected_count=1,
                )
            return None

        if isinstance(rule, RequiredColumnsRule):
            table = context.table_map.get(rule.table_name)
            if table is None:
                return TriageFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    table_name=rule.table_name,
                    message=f"Table '{rule.table_name}' missing for required column checks",
                    affected_count=len(rule.columns),
                )
            stats_by_column = {stat.column_name: stat for stat in table.required_column_stats}
            broken_columns: list[str] = []
            total_affected = 0
            for column in rule.columns:
                stat = stats_by_column.get(column)
                if stat is None:
                    broken_columns.append(column)
                    total_affected += 1
                    continue
                invalid_total = stat.null_count + stat.empty_string_count + stat.invalid_count
                if invalid_total > 0:
                    broken_columns.append(column)
                    total_affected += invalid_total
            if broken_columns:
                return TriageFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    table_name=rule.table_name,
                    message=(
                        "Required columns have missing/invalid values: "
                        f"{', '.join(broken_columns)}"
                    ),
                    affected_count=total_affected,
                    sample={"columns": broken_columns},
                )
            return None

        if isinstance(rule, ForeignKeyIntegrityRule):
            child_table = context.table_map.get(rule.child_table)
            if child_table is None:
                return TriageFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    table_name=rule.child_table,
                    message=(f"Child table '{rule.child_table}' missing for FK integrity rule"),
                    affected_count=1,
                )
            for gap in child_table.foreign_key_gaps:
                if (
                    gap.relation_name == rule.relation_name
                    and gap.child_table == rule.child_table
                    and gap.parent_table == rule.parent_table
                    and gap.orphan_count > 0
                ):
                    return TriageFinding(
                        rule_id=rule.id,
                        severity=rule.severity,
                        table_name=rule.child_table,
                        message=(
                            f"Foreign-key orphans detected in relation '{rule.relation_name}'"
                        ),
                        affected_count=gap.orphan_count,
                        sample={"sample_orphans": gap.sample_orphans[:5]},
                    )
            return None

        if isinstance(rule, CrossTableMinimumRule):
            driving = context.table_map.get(rule.driving_table)
            dependent = context.table_map.get(rule.dependent_table)
            if driving is None or dependent is None:
                missing = rule.driving_table if driving is None else rule.dependent_table
                return TriageFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    table_name=missing,
                    message=f"Cross-table ratio check missing table '{missing}'",
                    affected_count=1,
                )

            if driving.row_count <= 0:
                return None

            ratio = dependent.row_count / float(driving.row_count)
            if ratio < rule.minimum_ratio:
                return TriageFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    table_name=rule.dependent_table,
                    message=(
                        f"Cross-table ratio {ratio:.3f} below minimum {rule.minimum_ratio:.3f} "
                        f"for {rule.dependent_table}/{rule.driving_table}"
                    ),
                    affected_count=max(
                        0,
                        int((rule.minimum_ratio * driving.row_count) - dependent.row_count),
                    ),
                    sample={
                        "driving_count": driving.row_count,
                        "dependent_count": dependent.row_count,
                        "observed_ratio": ratio,
                        "minimum_ratio": rule.minimum_ratio,
                    },
                )
            return None

        return None

    def _missing_table_findings(
        self,
        missing_tables: list[MissingEntryTable],
    ) -> list[TriageFinding]:
        severity_map = {
            "info": "warning",
            "warning": "warning",
            "error": "error",
        }
        findings: list[TriageFinding] = []
        for entry in missing_tables:
            findings.append(
                TriageFinding(
                    rule_id=f"missing_table.{entry.table_name}",
                    severity=severity_map.get(entry.severity, "warning"),
                    table_name=entry.table_name,
                    message=entry.reason,
                    affected_count=max(0, entry.observed_row_count),
                    sample={
                        "expected_rule": entry.expected_rule,
                        "related_tables": entry.related_tables,
                    },
                )
            )
        return findings

    def _compute_verdict(self, findings: list[TriageFinding]) -> TriageVerdict:
        has_error = any(finding.severity == "error" for finding in findings)
        has_warning = any(finding.severity == "warning" for finding in findings)
        if has_error:
            return "fail"
        if has_warning:
            return "warn"
        return "pass"

    def _compute_stats(
        self,
        page: DatabaseEntriesReportPage,
        findings: list[TriageFinding],
    ) -> TriageStats:
        error_count = sum(1 for finding in findings if finding.severity == "error")
        warning_count = sum(1 for finding in findings if finding.severity == "warning")
        return TriageStats(
            table_count=len(page.tables),
            finding_count=len(findings),
            warning_count=warning_count,
            error_count=error_count,
        )
