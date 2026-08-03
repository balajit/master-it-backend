"""MCP server exposing DB report tools for triage."""

from __future__ import annotations

from typing import Any, Protocol

from mcp.server import MCPServer

from learning_platform.agentic_ops.contracts.mcp import ReportScope
from learning_platform.agentic_ops.reporting import TriageReportService

MCP_REPORT_SERVER_NAME = "master-it-triage-report-service"
STREAMABLE_HTTP_REPORT_PATH = "/mcp/lp/reporting"


class ReportService(Protocol):
    async def report_all_entries(
        self,
        *,
        scope: ReportScope,
        cursor: str | None,
        page_size: int,
        include_rows: bool,
    ) -> Any: ...

    async def report_missing_entries(
        self,
        *,
        scope: ReportScope,
    ) -> Any: ...

    async def report_table_page(
        self,
        *,
        scope: ReportScope,
        table_name: str,
        cursor: str | None,
        page_size: int,
    ) -> Any: ...


def create_report_mcp_server(report_service: ReportService | None = None) -> MCPServer:
    service = report_service or TriageReportService()
    server = MCPServer(MCP_REPORT_SERVER_NAME)

    @server.tool(name="db.report_all_entries", structured_output=True)
    async def report_all_entries(
        scope: dict[str, Any],
        cursor: str | None = None,
        page_size: int = 500,
        include_rows: bool = False,
    ) -> dict[str, Any]:
        parsed_scope = ReportScope.model_validate(scope)
        result = await service.report_all_entries(
            scope=parsed_scope,
            cursor=cursor,
            page_size=page_size,
            include_rows=include_rows,
        )
        return result.model_dump(mode="json")

    @server.tool(name="db.report_missing_entries", structured_output=True)
    async def report_missing_entries(scope: dict[str, Any]) -> list[dict[str, Any]]:
        parsed_scope = ReportScope.model_validate(scope)
        result = await service.report_missing_entries(scope=parsed_scope)
        return [row.model_dump(mode="json") for row in result]

    @server.tool(name="db.report_table_page", structured_output=True)
    async def report_table_page(
        scope: dict[str, Any],
        table_name: str,
        cursor: str | None = None,
        page_size: int = 200,
    ) -> dict[str, Any]:
        parsed_scope = ReportScope.model_validate(scope)
        return await service.report_table_page(
            scope=parsed_scope,
            table_name=table_name,
            cursor=cursor,
            page_size=page_size,
        )

    return server


async def run_streamable_http_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    streamable_http_path: str = STREAMABLE_HTTP_REPORT_PATH,
) -> None:
    server = create_report_mcp_server()
    await server.run_streamable_http_async(
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )


async def run_stdio_server() -> None:
    server = create_report_mcp_server()
    await server.run_stdio_async()


# Backward-compatible aliases.
MCP_SERVER_NAME = MCP_REPORT_SERVER_NAME
STREAMABLE_HTTP_PATH = STREAMABLE_HTTP_REPORT_PATH
create_mcp_server = create_report_mcp_server
run_streamable_http_report_server = run_streamable_http_server
run_stdio_report_server = run_stdio_server
