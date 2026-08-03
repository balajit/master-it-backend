"""Read-only SQL report service backing MCP triage tools."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from learning_platform.agentic_ops.contracts.mcp import (
    ColumnNullStat,
    DatabaseEntriesReportPage,
    ForeignKeyGap,
    MissingEntryTable,
    ReportScope,
    TableEntryRow,
    TableReport,
)
from learning_platform.api.deps import get_session_factory
from learning_platform.service import stable_doc_id

SeverityLevel = Literal["info", "warning", "error"]


def _lp_doc_uuid_from_storage_path(storage_path: str) -> str:
    return str(UUID(stable_doc_id(storage_path)[:32]))


class TriageReportService:
    """Generates deterministic triage report payloads using read-only SQL."""

    _TABLES: tuple[str, ...] = (
        "documents",
        "course_documents",
        "courses",
        "units",
        "sections",
        "lessons",
        "course_enrollments",
        "lp_documents",
        "lp_document_process",
        "lp_book_process",
        "lp_book_chapter",
        "lp_book_lesson",
        "lp_book_page",
        "lp_book_item",
    )

    _REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
        "documents": ("storage_path", "filename"),
        "lessons": ("title", "plan_lesson_id"),
        "lp_documents": ("source",),
        "lp_book_lesson": ("title",),
    }

    _FK_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
        (
            "course_documents.document_id->documents.id",
            "course_documents",
            "document_id",
            "documents",
            "id",
        ),
        (
            "course_documents.course_id->courses.id",
            "course_documents",
            "course_id",
            "courses",
            "id",
        ),
        ("units.course_id->courses.id", "units", "course_id", "courses", "id"),
        ("sections.unit_id->units.id", "sections", "unit_id", "units", "id"),
        (
            "lessons.section_id->sections.id",
            "lessons",
            "section_id",
            "sections",
            "id",
        ),
    )

    _EXPECTED_NON_EMPTY: tuple[dict[str, Any], ...] = (
        {
            "table_name": "documents",
            "scope_kinds": {"global"},
            "severity": "warning",
            "reason": "documents should contain at least one uploaded document",
            "expected_rule": "table_non_empty",
            "related_tables": ["course_documents", "courses"],
        },
        {
            "table_name": "course_documents",
            "scope_kinds": {"global", "course", "document"},
            "severity": "error",
            "reason": "course_documents should map documents to at least one course",
            "expected_rule": "table_non_empty",
            "related_tables": ["documents", "courses"],
        },
        {
            "table_name": "units",
            "scope_kinds": {"course", "document"},
            "severity": "warning",
            "reason": "units should exist for scoped course/document",
            "expected_rule": "table_non_empty",
            "related_tables": ["sections", "lessons"],
        },
        {
            "table_name": "sections",
            "scope_kinds": {"course", "document"},
            "severity": "warning",
            "reason": "sections should exist for scoped course/document",
            "expected_rule": "table_non_empty",
            "related_tables": ["units", "lessons"],
        },
        {
            "table_name": "lessons",
            "scope_kinds": {"course", "document"},
            "severity": "warning",
            "reason": "lessons should exist for scoped course/document",
            "expected_rule": "table_non_empty",
            "related_tables": ["sections"],
        },
        {
            "table_name": "lp_documents",
            "scope_kinds": {"document"},
            "severity": "warning",
            "reason": "lp_documents should contain canonical representation for scoped document",
            "expected_rule": "table_non_empty",
            "related_tables": ["lp_book_chapter", "lp_book_lesson"],
        },
    )

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def report_all_entries(
        self,
        *,
        scope: ReportScope,
        cursor: str | None,
        page_size: int,
        include_rows: bool,
    ) -> DatabaseEntriesReportPage:
        safe_page_size = max(1, min(page_size, len(self._TABLES)))
        page_index = self._parse_cursor(cursor)
        total_pages = max(1, ceil(len(self._TABLES) / safe_page_size))
        if page_index >= total_pages:
            raise ValueError("Cursor is out of range")

        start = page_index * safe_page_size
        end = min(len(self._TABLES), start + safe_page_size)
        table_names = self._TABLES[start:end]
        next_cursor = str(page_index + 1) if end < len(self._TABLES) else None

        async with self._session_factory() as session:
            context = await self._resolve_scope_context(session=session, scope=scope)
            reports = [
                await self._build_table_report(
                    session=session,
                    scope=scope,
                    context=context,
                    table_name=table_name,
                    include_rows=include_rows,
                )
                for table_name in table_names
            ]

            missing_tables: list[MissingEntryTable] = []
            if next_cursor is None:
                full_reports = [
                    await self._build_table_report(
                        session=session,
                        scope=scope,
                        context=context,
                        table_name=table_name,
                        include_rows=False,
                    )
                    for table_name in self._TABLES
                ]
                missing_tables = self._build_missing_entry_tables(
                    scope=scope,
                    reports=full_reports,
                )

        return DatabaseEntriesReportPage(
            report_id=self._build_report_id(scope),
            generated_at=datetime.now(UTC),
            scope=scope,
            tables=reports,
            missing_entry_tables=missing_tables,
            next_cursor=next_cursor,
        )

    async def report_missing_entries(
        self,
        *,
        scope: ReportScope,
    ) -> list[MissingEntryTable]:
        async with self._session_factory() as session:
            context = await self._resolve_scope_context(session=session, scope=scope)
            reports = [
                await self._build_table_report(
                    session=session,
                    scope=scope,
                    context=context,
                    table_name=table_name,
                    include_rows=False,
                )
                for table_name in self._TABLES
            ]
        return self._build_missing_entry_tables(scope=scope, reports=reports)

    async def report_table_page(
        self,
        *,
        scope: ReportScope,
        table_name: str,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, Any]:
        if table_name not in self._TABLES:
            raise ValueError(f"Unknown table '{table_name}'")

        row_offset = self._parse_cursor(cursor)
        safe_page_size = max(1, min(page_size, 5000))

        async with self._session_factory() as session:
            context = await self._resolve_scope_context(session=session, scope=scope)
            from_clause, where_sql, params = self._scope_sql(
                scope=scope,
                context=context,
                table_name=table_name,
            )

            count_stmt = text(f"SELECT COUNT(*) AS count FROM {from_clause} WHERE {where_sql}")
            count_value = await session.scalar(count_stmt, params)
            row_count = int(count_value or 0)

            rows_stmt = text(
                f"SELECT * FROM {from_clause} WHERE {where_sql} LIMIT :limit OFFSET :offset"
            )
            rows_result = await session.execute(
                rows_stmt,
                {
                    **params,
                    "limit": safe_page_size,
                    "offset": row_offset,
                },
            )
            rows = [
                TableEntryRow(row_data=dict(row._mapping)).model_dump(mode="json")
                for row in rows_result
            ]

        next_cursor = None
        if row_offset + safe_page_size < row_count:
            next_cursor = str(row_offset + safe_page_size)

        return {
            "table_name": table_name,
            "row_count": row_count,
            "rows": rows,
            "next_cursor": next_cursor,
        }

    async def _resolve_scope_context(
        self,
        *,
        session: AsyncSession,
        scope: ReportScope,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "scope_kind": scope.kind,
            "course_id": None,
            "document_id": None,
            "lp_document_uuid": None,
            "has_course_scope": False,
            "has_document_scope": False,
        }

        if scope.kind == "global":
            return context

        if scope.kind == "course":
            if scope.course_id is None:
                raise ValueError("course_id is required for course scope")
            context["course_id"] = scope.course_id
            context["has_course_scope"] = True
            return context

        if not scope.document_id:
            raise ValueError("document_id is required for document scope")
        context["document_id"] = scope.document_id
        context["has_document_scope"] = True

        course_id = await session.scalar(
            text(
                "SELECT cd.course_id "
                "FROM course_documents cd "
                "WHERE cd.document_id = :document_id "
                "LIMIT 1"
            ),
            {"document_id": scope.document_id},
        )
        if course_id is not None:
            context["course_id"] = int(course_id)
            context["has_course_scope"] = True

        storage_path = await session.scalar(
            text("SELECT d.storage_path FROM documents d WHERE d.id = :document_id"),
            {"document_id": scope.document_id},
        )
        if storage_path:
            context["lp_document_uuid"] = _lp_doc_uuid_from_storage_path(str(storage_path))
        return context

    async def _build_table_report(
        self,
        *,
        session: AsyncSession,
        scope: ReportScope,
        context: dict[str, Any],
        table_name: str,
        include_rows: bool,
    ) -> TableReport:
        from_clause, where_sql, params = self._scope_sql(
            scope=scope,
            context=context,
            table_name=table_name,
        )

        count_stmt = text(f"SELECT COUNT(*) AS count FROM {from_clause} WHERE {where_sql}")
        row_count = int(await session.scalar(count_stmt, params) or 0)

        required_column_stats = await self._required_column_stats(
            session=session,
            table_name=table_name,
            from_clause=from_clause,
            where_sql=where_sql,
            params=params,
        )
        foreign_key_gaps = await self._foreign_key_gaps(
            session=session,
            scope=scope,
            context=context,
            table_name=table_name,
        )

        rows: list[TableEntryRow] = []
        if include_rows:
            rows_stmt = text(f"SELECT * FROM {from_clause} WHERE {where_sql} LIMIT 25")
            rows_result = await session.execute(rows_stmt, params)
            rows = [TableEntryRow(row_data=dict(row._mapping)) for row in rows_result]

        return TableReport(
            table_name=table_name,
            row_count=row_count,
            required_column_stats=required_column_stats,
            foreign_key_gaps=foreign_key_gaps,
            rows=rows,
            is_expected_non_empty=self._is_expected_non_empty(
                scope_kind=scope.kind,
                table_name=table_name,
            ),
        )

    async def _required_column_stats(
        self,
        *,
        session: AsyncSession,
        table_name: str,
        from_clause: str,
        where_sql: str,
        params: dict[str, Any],
    ) -> list[ColumnNullStat]:
        columns = self._REQUIRED_COLUMNS.get(table_name, ())
        output: list[ColumnNullStat] = []

        for column in columns:
            null_stmt = text(
                "SELECT COUNT(*) AS count "
                f"FROM {from_clause} "
                f"WHERE ({where_sql}) AND {table_name}.{column} IS NULL"
            )
            null_count = int(await session.scalar(null_stmt, params) or 0)

            empty_count = 0
            empty_stmt = text(
                "SELECT COUNT(*) AS count "
                f"FROM {from_clause} "
                f"WHERE ({where_sql}) AND CAST({table_name}.{column} AS TEXT) = ''"
            )
            try:
                empty_count = int(await session.scalar(empty_stmt, params) or 0)
            except Exception:
                empty_count = 0

            output.append(
                ColumnNullStat(
                    column_name=column,
                    null_count=null_count,
                    empty_string_count=empty_count,
                    invalid_count=0,
                    required=True,
                )
            )

        return output

    async def _foreign_key_gaps(
        self,
        *,
        session: AsyncSession,
        scope: ReportScope,
        context: dict[str, Any],
        table_name: str,
    ) -> list[ForeignKeyGap]:
        output: list[ForeignKeyGap] = []
        for relation_name, child_table, child_col, parent_table, parent_col in self._FK_SPECS:
            if child_table != table_name:
                continue

            from_clause, where_sql, params = self._scope_sql(
                scope=scope,
                context=context,
                table_name=child_table,
            )
            orphan_stmt = text(
                "SELECT COUNT(*) AS count "
                f"FROM {from_clause} "
                "LEFT JOIN "
                f"{parent_table} ON {child_table}.{child_col} = {parent_table}.{parent_col} "
                f"WHERE ({where_sql}) AND {parent_table}.{parent_col} IS NULL"
            )
            orphan_count = int(await session.scalar(orphan_stmt, params) or 0)

            sample_stmt = text(
                (
                    "SELECT {child_table}.* "
                    f"FROM {from_clause} "
                    "LEFT JOIN "
                    f"{parent_table} ON {child_table}.{child_col} = {parent_table}.{parent_col} "
                    f"WHERE ({where_sql}) AND {parent_table}.{parent_col} IS NULL "
                    "LIMIT 5"
                ).format(child_table=child_table)
            )
            sample_result = await session.execute(sample_stmt, params)
            sample_orphans = [dict(row._mapping) for row in sample_result]

            output.append(
                ForeignKeyGap(
                    relation_name=relation_name,
                    child_table=child_table,
                    parent_table=parent_table,
                    orphan_count=orphan_count,
                    sample_orphans=sample_orphans,
                )
            )

        return output

    def _scope_sql(
        self,
        *,
        scope: ReportScope,
        context: dict[str, Any],
        table_name: str,
    ) -> tuple[str, str, dict[str, Any]]:
        if scope.kind == "global":
            return table_name, "1=1", {}

        params: dict[str, Any] = {}

        if table_name == "documents":
            if scope.kind == "document":
                params["document_id"] = context.get("document_id")
                return table_name, "documents.id = :document_id", params
            if context.get("has_course_scope"):
                params["course_id"] = context["course_id"]
                return (
                    "documents "
                    "JOIN course_documents ON course_documents.document_id = documents.id",
                    "course_documents.course_id = :course_id",
                    params,
                )
            return table_name, "1=0", params

        if table_name == "course_documents":
            if scope.kind == "document":
                params["document_id"] = context.get("document_id")
                return table_name, "course_documents.document_id = :document_id", params
            if context.get("has_course_scope"):
                params["course_id"] = context["course_id"]
                return table_name, "course_documents.course_id = :course_id", params
            return table_name, "1=0", params

        if table_name == "courses":
            if context.get("has_course_scope"):
                params["course_id"] = context["course_id"]
                return table_name, "courses.id = :course_id", params
            return table_name, "1=0", params

        if table_name == "units":
            if context.get("has_course_scope"):
                params["course_id"] = context["course_id"]
                return table_name, "units.course_id = :course_id", params
            return table_name, "1=0", params

        if table_name == "sections":
            if context.get("has_course_scope"):
                params["course_id"] = context["course_id"]
                return (
                    "sections JOIN units ON units.id = sections.unit_id",
                    "units.course_id = :course_id",
                    params,
                )
            return table_name, "1=0", params

        if table_name == "lessons":
            if context.get("has_course_scope"):
                params["course_id"] = context["course_id"]
                return (
                    "lessons "
                    "JOIN sections ON sections.id = lessons.section_id "
                    "JOIN units ON units.id = sections.unit_id",
                    "units.course_id = :course_id",
                    params,
                )
            return table_name, "1=0", params

        if table_name == "course_enrollments":
            if context.get("has_course_scope"):
                params["course_id"] = context["course_id"]
                return table_name, "course_enrollments.course_id = :course_id", params
            return table_name, "1=0", params

        lp_doc_uuid = context.get("lp_document_uuid")
        if table_name == "lp_documents":
            if lp_doc_uuid:
                params["lp_document_uuid"] = lp_doc_uuid
                return table_name, "CAST(lp_documents.id AS TEXT) = :lp_document_uuid", params
            return table_name, "1=0", params

        if table_name == "lp_document_process":
            if scope.kind == "document" and context.get("document_id"):
                params["document_id_like"] = f"%{context['document_id']}%"
                return table_name, "lp_document_process.abs_path LIKE :document_id_like", params
            return table_name, "1=1", params

        if table_name == "lp_book_process":
            if lp_doc_uuid:
                params["lp_document_uuid"] = lp_doc_uuid
                return table_name, "lp_book_process.document_id = :lp_document_uuid", params
            return table_name, "1=0", params

        if table_name == "lp_book_chapter":
            if lp_doc_uuid:
                params["lp_document_uuid"] = lp_doc_uuid
                return (
                    table_name,
                    "CAST(lp_book_chapter.document_id AS TEXT) = :lp_document_uuid",
                    params,
                )
            return table_name, "1=0", params

        if table_name == "lp_book_lesson":
            if lp_doc_uuid:
                params["lp_document_uuid"] = lp_doc_uuid
                return (
                    "lp_book_lesson "
                    "JOIN lp_book_chapter ON lp_book_chapter.id = lp_book_lesson.chapter_id",
                    "CAST(lp_book_chapter.document_id AS TEXT) = :lp_document_uuid",
                    params,
                )
            return table_name, "1=0", params

        if table_name == "lp_book_page":
            if lp_doc_uuid:
                params["lp_document_uuid"] = lp_doc_uuid
                return (
                    "lp_book_page "
                    "JOIN lp_book_lesson ON lp_book_lesson.id = lp_book_page.lesson_id "
                    "JOIN lp_book_chapter ON lp_book_chapter.id = lp_book_lesson.chapter_id",
                    "CAST(lp_book_chapter.document_id AS TEXT) = :lp_document_uuid",
                    params,
                )
            return table_name, "1=0", params

        if table_name == "lp_book_item":
            if lp_doc_uuid:
                params["lp_document_uuid"] = lp_doc_uuid
                return (
                    "lp_book_item "
                    "JOIN lp_book_page ON lp_book_page.id = lp_book_item.page_id "
                    "JOIN lp_book_lesson ON lp_book_lesson.id = lp_book_page.lesson_id "
                    "JOIN lp_book_chapter ON lp_book_chapter.id = lp_book_lesson.chapter_id",
                    "CAST(lp_book_chapter.document_id AS TEXT) = :lp_document_uuid",
                    params,
                )
            return table_name, "1=0", params

        return table_name, "1=1", params

    def _build_missing_entry_tables(
        self,
        *,
        scope: ReportScope,
        reports: list[TableReport],
    ) -> list[MissingEntryTable]:
        report_by_table = {report.table_name: report for report in reports}
        missing: list[MissingEntryTable] = []
        for spec in self._EXPECTED_NON_EMPTY:
            if scope.kind not in spec["scope_kinds"]:
                continue
            report = report_by_table.get(spec["table_name"])
            observed = int(report.row_count) if report is not None else 0
            if observed > 0:
                continue
            missing.append(
                MissingEntryTable(
                    table_name=str(spec["table_name"]),
                    severity=spec["severity"],
                    reason=str(spec["reason"]),
                    expected_rule=str(spec["expected_rule"]),
                    observed_row_count=observed,
                    related_tables=[str(item) for item in spec["related_tables"]],
                )
            )
        return missing

    def _is_expected_non_empty(self, *, scope_kind: str, table_name: str) -> bool:
        return any(
            spec["table_name"] == table_name and scope_kind in spec["scope_kinds"]
            for spec in self._EXPECTED_NON_EMPTY
        )

    def _build_report_id(self, scope: ReportScope) -> str:
        if scope.kind == "course" and scope.course_id is not None:
            return f"triage-report:course:{scope.course_id}"
        if scope.kind == "document" and scope.document_id:
            return f"triage-report:document:{scope.document_id}"
        return "triage-report:global"

    def _parse_cursor(self, cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            value = int(cursor)
        except ValueError as exc:
            raise ValueError("Invalid cursor") from exc
        if value < 0:
            raise ValueError("Cursor must be >= 0")
        return value
