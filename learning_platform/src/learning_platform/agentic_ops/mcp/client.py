"""MCP clients for triage report and action tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.client import Client as McpSdkClient
from mcp_types import CallToolResult, TextContent

from learning_platform.agentic_ops.contracts.mcp import (
    CancelAgentActionRequest,
    CanceledAgentActionResult,
    DatabaseEntriesReportPage,
    ExecutedAgentActionResult,
    ExecuteDeleteDocumentProcessRunsRequest,
    ManagedDocumentEntry,
    MissingEntryTable,
    PreparedAgentActionResult,
    PrepareDeleteDocumentProcessRunsRequest,
    ReportScope,
    RollBackAgentActionRequest,
    RolledBackAgentActionResult,
    SliceDocumentPagesRequest,
    SliceDocumentPagesResult,
)


class McpClientError(RuntimeError):
    """Raised when MCP transport/protocol interactions fail."""


def unwrap_tool_payload(raw_payload: Any) -> Any:
    """Extract nested payload wrappers used by some MCP transports."""
    if not isinstance(raw_payload, dict):
        return raw_payload
    for candidate_key in ("result", "data", "content", "payload"):
        candidate = raw_payload.get(candidate_key)
        if isinstance(candidate, dict | list):
            return candidate
    return raw_payload


def extract_mcp_payload(raw_payload: Any) -> Any:
    """Backward-compatible alias for payload unwrapping."""
    return unwrap_tool_payload(raw_payload)


def parse_tool_result_payload(result: CallToolResult) -> Any:
    """Return structured payload from an MCP ``tools/call`` result."""
    if result.is_error:
        error_text = _collect_text_content(result)
        if not error_text and result.structured_content is not None:
            error_text = json.dumps(result.structured_content)
        message = error_text or "Tool returned is_error=true"
        raise McpClientError(f"MCP tool call failed: {message}")

    if result.structured_content is not None:
        return result.structured_content

    text_payload = _collect_text_content(result)
    if not text_payload:
        raise McpClientError("MCP tool result missing structured_content and text content")

    try:
        return json.loads(text_payload)
    except json.JSONDecodeError as exc:
        raise McpClientError("MCP text content was not valid JSON") from exc


def _collect_text_content(result: CallToolResult) -> str:
    text_parts: list[str] = []
    for content_part in result.content:
        if isinstance(content_part, TextContent):
            stripped = content_part.text.strip()
            if stripped:
                text_parts.append(stripped)
    return "\n".join(text_parts)


class _McpBaseClient:
    """Shared MCP tool invocation plumbing."""

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: float,
        api_key: str | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._api_key = api_key

    async def _invoke_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        try:
            if self._api_key:
                import httpx2
                from mcp.client.streamable_http import streamable_http_client

                headers = {"authorization": f"Bearer {self._api_key}"}
                async with httpx2.AsyncClient(
                    timeout=self._timeout_seconds,
                    headers=headers,
                ) as http_client:
                    transport = streamable_http_client(
                        self._endpoint,
                        http_client=http_client,
                    )
                    async with McpSdkClient(
                        transport,
                        read_timeout_seconds=self._timeout_seconds,
                    ) as client:
                        result = await client.call_tool(tool_name, arguments)
            else:
                async with McpSdkClient(
                    self._endpoint,
                    read_timeout_seconds=self._timeout_seconds,
                ) as client:
                    result = await client.call_tool(tool_name, arguments)
        except Exception as exc:
            raise McpClientError(f"MCP request failed for {tool_name}: {exc}") from exc

        extracted = parse_tool_result_payload(result)
        return unwrap_tool_payload(extracted)


class McpReportClient(_McpBaseClient):
    """Thin client around read-only MCP reporting tool contract."""

    async def report_all_entries(
        self,
        *,
        scope: ReportScope,
        page_size: int,
        include_rows: bool,
        cursor: str | None,
    ) -> DatabaseEntriesReportPage:
        payload = await self._invoke_tool(
            tool_name="db.report_all_entries",
            arguments={
                "scope": scope.model_dump(mode="json"),
                "page_size": page_size,
                "include_rows": include_rows,
                "cursor": cursor,
            },
        )
        if not isinstance(payload, dict):
            raise McpClientError("Invalid all-entries payload shape from MCP")
        return DatabaseEntriesReportPage.model_validate(payload)

    async def report_missing_entries(
        self,
        *,
        scope: ReportScope,
    ) -> list[MissingEntryTable]:
        payload = await self._invoke_tool(
            tool_name="db.report_missing_entries",
            arguments={"scope": scope.model_dump(mode="json")},
        )
        if isinstance(payload, dict) and isinstance(payload.get("missing_entry_tables"), list):
            source = payload["missing_entry_tables"]
        elif isinstance(payload, list):
            source = payload
        else:
            raise McpClientError("Invalid missing-entry payload shape from MCP")
        return [MissingEntryTable.model_validate(item) for item in source]


class McpActionClient(_McpBaseClient):
    """Thin client around destructive MCP action tools."""

    async def prepare_delete_document_process_runs(
        self,
        *,
        process_ids: list[int],
        reason: str,
        requested_by: str,
    ) -> PreparedAgentActionResult:
        request = PrepareDeleteDocumentProcessRunsRequest(
            process_ids=process_ids,
            reason=reason,
            requested_by=requested_by,
        )
        payload = await self._invoke_tool(
            tool_name="ops.prepare_delete_document_process_runs",
            arguments=request.model_dump(mode="json"),
        )
        if not isinstance(payload, dict):
            raise McpClientError("Invalid prepare-delete payload shape from MCP")
        return PreparedAgentActionResult.model_validate(payload)

    async def execute_delete_document_process_runs(
        self,
        *,
        action_id: str,
        requested_by: str,
    ) -> ExecutedAgentActionResult:
        request = ExecuteDeleteDocumentProcessRunsRequest(
            action_id=action_id,
            requested_by=requested_by,
        )
        payload = await self._invoke_tool(
            tool_name="ops.execute_delete_document_process_runs",
            arguments=request.model_dump(mode="json"),
        )
        if not isinstance(payload, dict):
            raise McpClientError("Invalid execute-delete payload shape from MCP")
        return ExecutedAgentActionResult.model_validate(payload)

    async def rollback_agent_action(
        self,
        *,
        action_id: str,
        requested_by: str,
        reason: str,
    ) -> RolledBackAgentActionResult:
        request = RollBackAgentActionRequest(
            action_id=action_id,
            requested_by=requested_by,
            reason=reason,
        )
        payload = await self._invoke_tool(
            tool_name="ops.rollback_agent_action",
            arguments=request.model_dump(mode="json"),
        )
        if not isinstance(payload, dict):
            raise McpClientError("Invalid rollback payload shape from MCP")
        return RolledBackAgentActionResult.model_validate(payload)

    async def cancel_agent_action(
        self,
        *,
        action_id: str,
        requested_by: str,
        reason: str,
    ) -> CanceledAgentActionResult:
        request = CancelAgentActionRequest(
            action_id=action_id,
            requested_by=requested_by,
            reason=reason,
        )
        payload = await self._invoke_tool(
            tool_name="ops.cancel_agent_action",
            arguments=request.model_dump(mode="json"),
        )
        if not isinstance(payload, dict):
            raise McpClientError("Invalid cancel payload shape from MCP")
        return CanceledAgentActionResult.model_validate(payload)

    async def slice_document_pages(
        self,
        *,
        mode: str,
        start_page: int,
        end_page: int,
        source_path: str | None = None,
        source_pdf_base64: str | None = None,
        filename: str | None = None,
    ) -> SliceDocumentPagesResult:
        request = SliceDocumentPagesRequest(
            mode=mode,
            start_page=start_page,
            end_page=end_page,
            source_path=source_path,
            source_pdf_base64=source_pdf_base64,
            filename=filename,
        )
        payload = await self._invoke_tool(
            tool_name="ops.slice_document_pages",
            arguments=request.model_dump(mode="json"),
        )
        if not isinstance(payload, dict):
            raise McpClientError("Invalid slice-document payload shape from MCP")
        return SliceDocumentPagesResult.model_validate(payload)

    async def list_managed_documents(self) -> list[ManagedDocumentEntry]:
        payload = await self._invoke_tool(
            tool_name="ops.list_managed_documents",
            arguments={},
        )
        if not isinstance(payload, list):
            raise McpClientError("Invalid managed-documents payload shape from MCP")
        return [ManagedDocumentEntry.model_validate(item) for item in payload]
