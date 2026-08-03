"""MCP server exposing destructive action tools for triage operations."""

from __future__ import annotations

from typing import Any, Protocol

from mcp.server import MCPServer

from learning_platform.agentic_ops.actions import AgenticActionService
from learning_platform.agentic_ops.contracts.mcp import (
    CancelAgentActionRequest,
    ExecuteDeleteDocumentProcessRunsRequest,
    PrepareDeleteDocumentProcessRunsRequest,
    RollBackAgentActionRequest,
    SliceDocumentPagesRequest,
)
from learning_platform.agentic_ops.settings import AgenticOpsSettings
from learning_platform.capabilities.managed_docs import ManagedDocsService

MCP_ACTION_SERVER_NAME = "master-it-triage-action-service"
STREAMABLE_HTTP_ACTION_PATH = "/mcp/lp/actions"


class ActionService(Protocol):
    async def prepare_delete_document_process_runs(
        self,
        *,
        request: PrepareDeleteDocumentProcessRunsRequest,
    ) -> Any: ...

    async def execute_delete_document_process_runs(
        self,
        *,
        request: ExecuteDeleteDocumentProcessRunsRequest,
    ) -> Any: ...

    async def rollback_agent_action(
        self,
        *,
        request: RollBackAgentActionRequest,
    ) -> Any: ...

    async def cancel_agent_action(
        self,
        *,
        request: CancelAgentActionRequest,
    ) -> Any: ...


class ManagedDocsToolService(Protocol):
    def slice_document_pages(
        self,
        *,
        mode: str,
        start_page: int,
        end_page: int,
        source_path: str | None,
        source_pdf_base64: str | None,
        filename: str | None,
    ) -> Any: ...

    def list_managed_documents(self) -> Any: ...


def create_action_mcp_server(
    action_service: ActionService | None = None,
    managed_docs_service: ManagedDocsToolService | None = None,
) -> MCPServer:
    settings = AgenticOpsSettings()
    service = action_service or AgenticActionService(
        action_ttl_minutes=settings.action_ttl_minutes
    )
    docs_service = managed_docs_service or ManagedDocsService(
        managed_docs_root=settings.mcp_managed_docs,
        max_input_size_bytes=settings.mcp_max_input_size_bytes,
        max_pages_per_slice=settings.mcp_max_pages_per_slice,
        max_base64_return_bytes=settings.mcp_max_base64_return_bytes,
    )
    server = MCPServer(MCP_ACTION_SERVER_NAME)

    @server.tool(name="ops.prepare_delete_document_process_runs", structured_output=True)
    async def prepare_delete_document_process_runs(
        process_ids: list[int],
        reason: str,
        requested_by: str,
    ) -> dict[str, Any]:
        request = PrepareDeleteDocumentProcessRunsRequest(
            process_ids=process_ids,
            reason=reason,
            requested_by=requested_by,
        )
        result = await service.prepare_delete_document_process_runs(request=request)
        if isinstance(result, dict):
            return result
        return result.model_dump(mode="json")

    @server.tool(name="ops.execute_delete_document_process_runs", structured_output=True)
    async def execute_delete_document_process_runs(
        action_id: str,
        requested_by: str,
    ) -> dict[str, Any]:
        request = ExecuteDeleteDocumentProcessRunsRequest(
            action_id=action_id,
            requested_by=requested_by,
        )
        result = await service.execute_delete_document_process_runs(request=request)
        if isinstance(result, dict):
            return result
        return result.model_dump(mode="json")

    @server.tool(name="ops.rollback_agent_action", structured_output=True)
    async def rollback_agent_action(
        action_id: str,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        request = RollBackAgentActionRequest(
            action_id=action_id,
            requested_by=requested_by,
            reason=reason,
        )
        result = await service.rollback_agent_action(request=request)
        if isinstance(result, dict):
            return result
        return result.model_dump(mode="json")

    @server.tool(name="ops.cancel_agent_action", structured_output=True)
    async def cancel_agent_action(
        action_id: str,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        request = CancelAgentActionRequest(
            action_id=action_id,
            requested_by=requested_by,
            reason=reason,
        )
        result = await service.cancel_agent_action(request=request)
        if isinstance(result, dict):
            return result
        return result.model_dump(mode="json")

    @server.tool(name="ops.slice_document_pages", structured_output=True)
    async def slice_document_pages(
        mode: str,
        start_page: int,
        end_page: int,
        source_path: str | None = None,
        source_pdf_base64: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        request = SliceDocumentPagesRequest(
            mode=mode,
            start_page=start_page,
            end_page=end_page,
            source_path=source_path,
            source_pdf_base64=source_pdf_base64,
            filename=filename,
        )
        result = docs_service.slice_document_pages(
            mode=request.mode,
            start_page=request.start_page,
            end_page=request.end_page,
            source_path=request.source_path,
            source_pdf_base64=request.source_pdf_base64,
            filename=request.filename,
        )
        if isinstance(result, dict):
            return result
        return {
            "doc_id": result.doc_id,
            "mode": result.source_mode,
            "orig_filename": result.orig_filename,
            "orig_path": result.orig_path,
            "sliced_filename": result.sliced_filename,
            "sliced_path": result.sliced_path,
            "start_page": result.start_page,
            "end_page": result.end_page,
            "total_pages": result.total_pages,
            "sliced_page_count": result.sliced_page_count,
            "sliced_size_bytes": result.sliced_size_bytes,
            "sliced_sha256": result.sliced_sha256,
            "sliced_pdf_base64": result.sliced_pdf_base64,
        }

    @server.tool(name="ops.list_managed_documents", structured_output=True)
    async def list_managed_documents() -> list[dict[str, Any]]:
        result = docs_service.list_managed_documents()
        rows: list[dict[str, Any]] = []
        for row in result:
            if isinstance(row, dict):
                rows.append(row)
            else:
                rows.append(
                    {
                        "doc_id": row.doc_id,
                        "filename": row.filename,
                        "path": row.path,
                        "size_bytes": row.size_bytes,
                        "sha256": row.sha256,
                        "page_count": row.page_count,
                        "created_at": row.created_at,
                        "source_mode": row.source_mode,
                        "source_path": row.source_path,
                    }
                )
        return rows

    return server


async def run_streamable_http_action_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    streamable_http_path: str = STREAMABLE_HTTP_ACTION_PATH,
) -> None:
    server = create_action_mcp_server()
    await server.run_streamable_http_async(
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )


async def run_stdio_action_server() -> None:
    server = create_action_mcp_server()
    await server.run_stdio_async()
