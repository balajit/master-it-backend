from __future__ import annotations

import json

import pytest
from mcp_types import CallToolResult, TextContent

from learning_platform.agentic_ops.mcp.client import (
    McpActionClient,
    McpClientError,
    parse_tool_result_payload,
    unwrap_tool_payload,
)


def _tool_result(
    *,
    structured_content: object | None,
    text_content: str | None,
    is_error: bool = False,
) -> CallToolResult:
    content: list[TextContent] = []
    if text_content is not None:
        content.append(TextContent(type="text", text=text_content))
    return CallToolResult(
        content=content,
        structured_content=structured_content,
        is_error=is_error,
    )


def test_parse_tool_result_payload_prefers_structured_content() -> None:
    result = _tool_result(
        structured_content={"report_id": "r1", "tables": []},
        text_content='{"report_id":"r2"}',
    )

    payload = parse_tool_result_payload(result)

    assert payload == {"report_id": "r1", "tables": []}


def test_parse_tool_result_payload_reads_text_json_when_needed() -> None:
    result = _tool_result(
        structured_content=None,
        text_content=json.dumps({"missing_entry_tables": []}),
    )

    payload = parse_tool_result_payload(result)

    assert payload == {"missing_entry_tables": []}


def test_parse_tool_result_payload_raises_on_invalid_text_json() -> None:
    result = _tool_result(
        structured_content=None,
        text_content="not-json",
    )

    with pytest.raises(McpClientError, match="valid JSON"):
        _ = parse_tool_result_payload(result)


def test_parse_tool_result_payload_raises_on_is_error() -> None:
    result = _tool_result(
        structured_content=None,
        text_content="database unavailable",
        is_error=True,
    )

    with pytest.raises(McpClientError, match="database unavailable"):
        _ = parse_tool_result_payload(result)


def test_unwrap_tool_payload_returns_nested_result_wrapper() -> None:
    payload = unwrap_tool_payload({"result": {"tables": []}})

    assert payload == {"tables": []}


def test_unwrap_tool_payload_returns_input_when_not_wrapped() -> None:
    payload = unwrap_tool_payload([{"table_name": "documents"}])

    assert payload == [{"table_name": "documents"}]


async def test_prepare_delete_document_process_runs_uses_mcp_tool_call() -> None:
    expected_payload = {
        "action_id": "a1",
        "action_type": "delete_document_process_runs",
        "status": "prepared",
        "precheck_passed": True,
        "requested_ids": [7, 8],
        "target_process_ids": [7],
        "missing_process_ids": [8],
        "affected_row_count": 3,
        "affected_file_count": 1,
        "integrity_hash": "abc123",
        "expires_at": None,
    }
    client = McpActionClient(endpoint="http://localhost:8766/mcp/lp/actions", timeout_seconds=5.0)

    async def _invoke_tool_stub(
        *, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert tool_name == "ops.prepare_delete_document_process_runs"
        assert arguments == {
            "process_ids": [7, 8],
            "reason": "cleanup stale runs",
            "requested_by": "qa-user",
        }
        return expected_payload

    client._invoke_tool = _invoke_tool_stub  # type: ignore[method-assign]

    result = await client.prepare_delete_document_process_runs(
        process_ids=[7, 8],
        reason="cleanup stale runs",
        requested_by="qa-user",
    )

    assert result.action_id == "a1"
    assert result.requested_ids == [7, 8]
    assert result.target_process_ids == [7]
    assert result.missing_process_ids == [8]


async def test_execute_delete_document_process_runs_uses_mcp_tool_call() -> None:
    expected_payload = {
        "action_id": "a1",
        "action_type": "delete_document_process_runs",
        "status": "applied",
        "deleted_process_ids": [7],
        "missing_process_ids": [8],
        "deleted_pipeline_log_count": 2,
        "affected_row_count": 3,
        "affected_file_count": 1,
        "applied_at": None,
    }
    client = McpActionClient(endpoint="http://localhost:8766/mcp/lp/actions", timeout_seconds=5.0)

    async def _invoke_tool_stub(
        *, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert tool_name == "ops.execute_delete_document_process_runs"
        assert arguments == {
            "action_id": "a1",
            "requested_by": "qa-user",
        }
        return expected_payload

    client._invoke_tool = _invoke_tool_stub  # type: ignore[method-assign]

    result = await client.execute_delete_document_process_runs(
        action_id="a1",
        requested_by="qa-user",
    )

    assert result.status == "applied"
    assert result.deleted_process_ids == [7]
    assert result.missing_process_ids == [8]
    assert result.deleted_pipeline_log_count == 2


async def test_rollback_agent_action_uses_mcp_tool_call() -> None:
    expected_payload = {
        "action_id": "a1",
        "action_type": "delete_document_process_runs",
        "status": "rolled_back",
        "restored_row_count": 3,
        "rolled_back_at": None,
    }
    client = McpActionClient(endpoint="http://localhost:8766/mcp/lp/actions", timeout_seconds=5.0)

    async def _invoke_tool_stub(
        *, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert tool_name == "ops.rollback_agent_action"
        assert arguments == {
            "action_id": "a1",
            "requested_by": "qa-user",
            "reason": "undo accidental delete",
        }
        return expected_payload

    client._invoke_tool = _invoke_tool_stub  # type: ignore[method-assign]

    result = await client.rollback_agent_action(
        action_id="a1",
        requested_by="qa-user",
        reason="undo accidental delete",
    )

    assert result.status == "rolled_back"
    assert result.restored_row_count == 3


async def test_cancel_agent_action_uses_mcp_tool_call() -> None:
    expected_payload = {
        "action_id": "a1",
        "action_type": "delete_document_process_runs",
        "status": "canceled",
        "canceled_at": None,
    }
    client = McpActionClient(endpoint="http://localhost:8766/mcp/lp/actions", timeout_seconds=5.0)

    async def _invoke_tool_stub(
        *, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert tool_name == "ops.cancel_agent_action"
        assert arguments == {
            "action_id": "a1",
            "requested_by": "qa-user",
            "reason": "operator canceled",
        }
        return expected_payload

    client._invoke_tool = _invoke_tool_stub  # type: ignore[method-assign]

    result = await client.cancel_agent_action(
        action_id="a1",
        requested_by="qa-user",
        reason="operator canceled",
    )

    assert result.status == "canceled"


async def test_slice_document_pages_uses_mcp_tool_call() -> None:
    expected_payload = {
        "doc_id": "doc-1",
        "mode": "path",
        "orig_filename": "orig.pdf",
        "orig_path": "/tmp/mcp/orig/orig.pdf",
        "sliced_filename": "slice.pdf",
        "sliced_path": "/tmp/mcp/sliced/slice.pdf",
        "start_page": 2,
        "end_page": 4,
        "total_pages": 12,
        "sliced_page_count": 3,
        "sliced_size_bytes": 4096,
        "sliced_sha256": "abc123",
        "sliced_pdf_base64": None,
    }
    client = McpActionClient(endpoint="http://localhost:8766/mcp/lp/actions", timeout_seconds=5.0)

    async def _invoke_tool_stub(
        *, tool_name: str, arguments: dict[str, object]
    ) -> dict[str, object]:
        assert tool_name == "ops.slice_document_pages"
        assert arguments == {
            "mode": "path",
            "start_page": 2,
            "end_page": 4,
            "source_path": "/tmp/source.pdf",
            "source_pdf_base64": None,
            "filename": "source.pdf",
        }
        return expected_payload

    client._invoke_tool = _invoke_tool_stub  # type: ignore[method-assign]

    result = await client.slice_document_pages(
        mode="path",
        start_page=2,
        end_page=4,
        source_path="/tmp/source.pdf",
        filename="source.pdf",
    )

    assert result.doc_id == "doc-1"
    assert result.mode == "path"
    assert result.sliced_path is not None
    assert result.sliced_path.endswith("slice.pdf")


async def test_list_managed_documents_uses_mcp_tool_call() -> None:
    expected_payload = [
        {
            "doc_id": "doc-1",
            "filename": "orig.pdf",
            "path": "/tmp/mcp/orig/orig.pdf",
            "size_bytes": 100,
            "sha256": "abc123",
            "page_count": 5,
            "created_at": "2026-01-01T00:00:00Z",
            "source_mode": "path",
            "source_path": "/tmp/source.pdf",
        }
    ]
    client = McpActionClient(endpoint="http://localhost:8766/mcp/lp/actions", timeout_seconds=5.0)

    async def _invoke_tool_stub(
        *, tool_name: str, arguments: dict[str, object]
    ) -> list[dict[str, object]]:
        assert tool_name == "ops.list_managed_documents"
        assert arguments == {}
        return expected_payload

    client._invoke_tool = _invoke_tool_stub  # type: ignore[method-assign]

    rows = await client.list_managed_documents()
    assert len(rows) == 1
    assert rows[0].doc_id == "doc-1"
    assert rows[0].source_mode == "path"
