from __future__ import annotations

from datetime import datetime, timezone

from learning_platform.agentic_ops.contracts.mcp import (
    ColumnNullStat,
    DatabaseEntriesReportPage,
    MissingEntryTable,
    ReportScope,
    TableReport,
)
from learning_platform.agentic_ops.rules.defaults import build_default_rule_set
from learning_platform.agentic_ops.triage.agent import TriageAgent


class StubProvider:
    def __init__(
        self,
        pages: list[DatabaseEntriesReportPage],
        missing: list[MissingEntryTable],
    ) -> None:
        self._pages = pages
        self._missing = missing
        self._idx = 0

    async def report_all_entries(
        self,
        *,
        scope: ReportScope,
        page_size: int,
        include_rows: bool,
        cursor: str | None,
    ) -> DatabaseEntriesReportPage:
        _ = (scope, page_size, include_rows, cursor)
        page = self._pages[self._idx]
        self._idx = min(self._idx + 1, len(self._pages) - 1)
        return page

    async def report_missing_entries(self, *, scope: ReportScope) -> list[MissingEntryTable]:
        _ = scope
        return self._missing


def _page(
    *,
    report_id: str,
    scope: ReportScope,
    tables: list[TableReport],
    missing: list[MissingEntryTable],
    next_cursor: str | None = None,
) -> DatabaseEntriesReportPage:
    return DatabaseEntriesReportPage(
        report_id=report_id,
        generated_at=datetime.now(timezone.utc),
        scope=scope,
        tables=tables,
        missing_entry_tables=missing,
        next_cursor=next_cursor,
    )


def _table(name: str, row_count: int) -> TableReport:
    return TableReport(
        table_name=name,
        row_count=row_count,
        required_column_stats=[],
        foreign_key_gaps=[],
        rows=[],
    )


def _required_table(
    *,
    name: str,
    row_count: int,
    column_name: str,
    null_count: int = 0,
    empty_count: int = 0,
    invalid_count: int = 0,
) -> TableReport:
    return TableReport(
        table_name=name,
        row_count=row_count,
        required_column_stats=[
            ColumnNullStat(
                column_name=column_name,
                null_count=null_count,
                empty_string_count=empty_count,
                invalid_count=invalid_count,
                required=True,
            )
        ],
        foreign_key_gaps=[],
        rows=[],
    )


async def test_triage_agent_returns_pass_when_all_rules_satisfied() -> None:
    scope = ReportScope(kind="global")
    tables = [
        _required_table(name="documents", row_count=10, column_name="storage_path"),
        _table("course_documents", 8),
        _table("lp_documents", 8),
        _required_table(name="lessons", row_count=12, column_name="plan_lesson_id"),
        _table("sections", 10),
        _table("courses", 2),
        _table("units", 4),
        _table("lp_book_lesson", 6),
        _table("lp_book_page", 7),
    ]
    page = _page(report_id="r1", scope=scope, tables=tables, missing=[])
    provider = StubProvider(pages=[page], missing=[])

    agent = TriageAgent(provider=provider, rule_set=build_default_rule_set())
    result = await agent.run(scope)

    assert result.verdict == "pass"
    assert result.stats.error_count == 0


async def test_triage_agent_returns_fail_for_error_findings() -> None:
    scope = ReportScope(kind="global")
    tables = [
        _table("documents", 0),
        _table("course_documents", 8),
        _table("lp_documents", 8),
        _table("sections", 10),
        _table("lessons", 5),
        _table("lp_book_lesson", 5),
        _table("lp_book_page", 4),
        TableReport(
            table_name="documents",
            row_count=0,
            required_column_stats=[
                ColumnNullStat(
                    column_name="storage_path",
                    null_count=1,
                    empty_string_count=0,
                    invalid_count=0,
                    required=True,
                )
            ],
            foreign_key_gaps=[],
            rows=[],
        ),
    ]
    missing = [
        MissingEntryTable(
            table_name="course_documents",
            severity="error",
            reason="expected rows missing",
            expected_rule="table_non_empty",
            observed_row_count=0,
            related_tables=["documents"],
        )
    ]
    page = _page(report_id="r2", scope=scope, tables=tables, missing=missing)
    provider = StubProvider(pages=[page], missing=missing)

    agent = TriageAgent(provider=provider, rule_set=build_default_rule_set())
    result = await agent.run(scope)

    assert result.verdict == "fail"
    assert result.stats.error_count >= 1


async def test_triage_agent_merges_paginated_pages() -> None:
    scope = ReportScope(kind="course", course_id=101)
    page1 = _page(
        report_id="r3",
        scope=scope,
        tables=[_table("documents", 10)],
        missing=[],
        next_cursor="cursor-2",
    )
    page2 = _page(
        report_id="r3",
        scope=scope,
        tables=[_table("course_documents", 9), _table("lp_documents", 9)],
        missing=[],
        next_cursor=None,
    )
    provider = StubProvider(pages=[page1, page2], missing=[])

    agent = TriageAgent(provider=provider, rule_set=build_default_rule_set())
    result = await agent.run(scope)

    assert result.stats.table_count >= 3
