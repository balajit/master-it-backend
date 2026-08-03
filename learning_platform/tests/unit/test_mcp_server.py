from __future__ import annotations

from datetime import datetime, timezone

from mcp.client import Client

from learning_platform.agentic_ops.contracts.mcp import (
    DatabaseEntriesReportPage,
    MissingEntryTable,
    ReportScope,
    TableReport,
)
from learning_platform.agentic_ops.mcp.client import (
    parse_tool_result_payload,
    unwrap_tool_payload,
)
from learning_platform.agentic_ops.mcp_server.action_server import create_action_mcp_server
from learning_platform.agentic_ops.mcp_server.reporting_server import create_report_mcp_server


class StubReportService:
    def __init__(self) -> None:
        self.report_all_calls = 0
        self.report_missing_calls = 0
        self.report_table_calls = 0

    async def report_all_entries(
        self,
        *,
        scope: ReportScope,
        cursor: str | None,
        page_size: int,
        include_rows: bool,
    ) -> DatabaseEntriesReportPage:
        self.report_all_calls += 1
        _ = (cursor, page_size, include_rows)
        return DatabaseEntriesReportPage(
            report_id="triage-report:global",
            generated_at=datetime.now(timezone.utc),
            scope=scope,
            tables=[
                TableReport(
                    table_name="documents",
                    row_count=3,
                    required_column_stats=[],
                    foreign_key_gaps=[],
                    rows=[],
                    is_expected_non_empty=True,
                )
            ],
            missing_entry_tables=[],
            next_cursor=None,
        )

    async def report_missing_entries(
        self,
        *,
        scope: ReportScope,
    ) -> list[MissingEntryTable]:
        self.report_missing_calls += 1
        _ = scope
        return [
            MissingEntryTable(
                table_name="course_documents",
                severity="warning",
                reason="missing mapping",
                expected_rule="table_non_empty",
                observed_row_count=0,
                related_tables=["documents", "courses"],
            )
        ]

    async def report_table_page(
        self,
        *,
        scope: ReportScope,
        table_name: str,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, object]:
        self.report_table_calls += 1
        _ = (scope, cursor, page_size)
        return {
            "table_name": table_name,
            "row_count": 1,
            "rows": [{"id": 1}],
            "next_cursor": None,
        }


class StubActionService:
    def __init__(self) -> None:
        self.prepare_calls = 0
        self.execute_calls = 0
        self.rollback_calls = 0

    async def prepare_delete_document_process_runs(self, *, request: object) -> dict[str, object]:
        self.prepare_calls += 1
        process_ids_raw = getattr(request, "process_ids", [])
        process_ids = (
            [int(item) for item in process_ids_raw] if isinstance(process_ids_raw, list) else []
        )
        return {
            "action_id": "a1",
            "action_type": "delete_document_process_runs",
            "status": "prepared",
            "precheck_passed": True,
            "requested_ids": process_ids,
            "target_process_ids": [process_ids[0]] if process_ids else [],
            "missing_process_ids": process_ids[1:],
            "affected_row_count": 3,
            "affected_file_count": 1,
            "integrity_hash": "abc123",
            "expires_at": None,
        }

    async def execute_delete_document_process_runs(self, *, request: object) -> dict[str, object]:
        self.execute_calls += 1
        action_id = str(getattr(request, "action_id", ""))
        return {
            "action_id": action_id,
            "action_type": "delete_document_process_runs",
            "status": "applied",
            "deleted_process_ids": [7],
            "missing_process_ids": [8],
            "deleted_pipeline_log_count": 2,
            "affected_row_count": 3,
            "affected_file_count": 1,
            "applied_at": None,
        }

    async def rollback_agent_action(self, *, request: object) -> dict[str, object]:
        self.rollback_calls += 1
        action_id = str(getattr(request, "action_id", ""))
        return {
            "action_id": action_id,
            "action_type": "delete_document_process_runs",
            "status": "rolled_back",
            "restored_row_count": 3,
            "rolled_back_at": None,
        }

    async def cancel_agent_action(self, *, request: object) -> dict[str, object]:
        action_id = str(getattr(request, "action_id", ""))
        return {
            "action_id": action_id,
            "action_type": "delete_document_process_runs",
            "status": "canceled",
            "canceled_at": None,
        }


class StubManagedDocsService:
    def slice_document_pages(
        self,
        *,
        mode: str,
        start_page: int,
        end_page: int,
        source_path: str | None,
        source_pdf_base64: str | None,
        filename: str | None,
    ) -> dict[str, object]:
        return {
            "doc_id": "doc-1",
            "mode": mode,
            "orig_filename": "doc-1.pdf",
            "orig_path": "/tmp/mcp/orig/doc-1.pdf",
            "sliced_filename": "doc-1.p2-3.pdf",
            "sliced_path": "/tmp/mcp/sliced/doc-1.p2-3.pdf",
            "start_page": start_page,
            "end_page": end_page,
            "total_pages": 10,
            "sliced_page_count": 2,
            "sliced_size_bytes": 1024,
            "sliced_sha256": "abc123",
            "sliced_pdf_base64": source_pdf_base64 if mode == "base64" else None,
            "source_path": source_path,
            "filename": filename,
        }

    def list_managed_documents(self) -> list[dict[str, object]]:
        return [
            {
                "doc_id": "doc-1",
                "filename": "doc-1.pdf",
                "path": "/tmp/mcp/orig/doc-1.pdf",
                "size_bytes": 100,
                "sha256": "abc123",
                "page_count": 10,
                "created_at": datetime.now(timezone.utc),
                "source_mode": "path",
                "source_path": "/tmp/source.pdf",
            }
        ]


async def test_mcp_report_server_exposes_report_all_entries_tool() -> None:
    service = StubReportService()
    server = create_report_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "db.report_all_entries",
            {
                "scope": {"kind": "global"},
                "page_size": 10,
                "include_rows": False,
                "cursor": None,
            },
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert service.report_all_calls == 1
    assert isinstance(payload, dict)
    assert payload["report_id"] == "triage-report:global"


async def test_mcp_report_server_exposes_missing_entries_tool() -> None:
    service = StubReportService()
    server = create_report_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "db.report_missing_entries",
            {"scope": {"kind": "global"}},
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert service.report_missing_calls == 1
    assert isinstance(payload, list)
    assert payload[0]["table_name"] == "course_documents"


async def test_mcp_report_server_exposes_table_page_tool() -> None:
    service = StubReportService()
    server = create_report_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "db.report_table_page",
            {
                "scope": {"kind": "global"},
                "table_name": "documents",
                "cursor": None,
                "page_size": 50,
            },
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert service.report_table_calls == 1
    assert isinstance(payload, dict)
    assert payload["table_name"] == "documents"


async def test_mcp_action_server_exposes_prepare_delete_tool() -> None:
    service = StubActionService()
    server = create_action_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "ops.prepare_delete_document_process_runs",
            {
                "process_ids": [11, 12],
                "reason": "cleanup",
                "requested_by": "qa-user",
            },
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert service.prepare_calls == 1
    assert isinstance(payload, dict)
    assert payload["requested_ids"] == [11, 12]


async def test_mcp_action_server_exposes_execute_delete_tool() -> None:
    service = StubActionService()
    server = create_action_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "ops.execute_delete_document_process_runs",
            {
                "action_id": "a1",
                "requested_by": "qa-user",
            },
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert service.execute_calls == 1
    assert isinstance(payload, dict)
    assert payload["status"] == "applied"
    assert payload["deleted_process_ids"] == [7]


async def test_mcp_action_server_exposes_rollback_tool() -> None:
    service = StubActionService()
    server = create_action_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "ops.rollback_agent_action",
            {
                "action_id": "a1",
                "requested_by": "qa-user",
                "reason": "undo",
            },
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert service.rollback_calls == 1
    assert isinstance(payload, dict)
    assert payload["status"] == "rolled_back"
    assert payload["restored_row_count"] == 3


async def test_mcp_action_server_exposes_cancel_tool() -> None:
    service = StubActionService()
    server = create_action_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "ops.cancel_agent_action",
            {
                "action_id": "a1",
                "requested_by": "qa-user",
                "reason": "operator canceled",
            },
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert isinstance(payload, dict)
    assert payload["status"] == "canceled"


async def test_mcp_action_server_exposes_slice_document_pages_tool() -> None:
    action_service = StubActionService()
    docs_service = StubManagedDocsService()
    server = create_action_mcp_server(action_service, docs_service)

    async with Client(server) as client:
        result = await client.call_tool(
            "ops.slice_document_pages",
            {
                "mode": "path",
                "start_page": 2,
                "end_page": 3,
                "source_path": "/tmp/source.pdf",
            },
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert isinstance(payload, dict)
    assert payload["mode"] == "path"
    assert payload["start_page"] == 2
    assert payload["end_page"] == 3


async def test_mcp_action_server_exposes_list_managed_documents_tool() -> None:
    action_service = StubActionService()
    docs_service = StubManagedDocsService()
    server = create_action_mcp_server(action_service, docs_service)

    async with Client(server) as client:
        result = await client.call_tool(
            "ops.list_managed_documents",
            {},
        )

    payload = unwrap_tool_payload(parse_tool_result_payload(result))
    assert isinstance(payload, list)
    assert payload[0]["doc_id"] == "doc-1"
