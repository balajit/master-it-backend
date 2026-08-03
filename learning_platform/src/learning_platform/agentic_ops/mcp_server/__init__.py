"""MCP server runtimes for triage report and action tools."""

from __future__ import annotations

from learning_platform.agentic_ops.mcp_server.action_server import (
    MCP_ACTION_SERVER_NAME,
    STREAMABLE_HTTP_ACTION_PATH,
    create_action_mcp_server,
    run_stdio_action_server,
    run_streamable_http_action_server,
)
from learning_platform.agentic_ops.mcp_server.reporting_server import (
    MCP_REPORT_SERVER_NAME,
    MCP_SERVER_NAME,
    STREAMABLE_HTTP_PATH,
    STREAMABLE_HTTP_REPORT_PATH,
    create_mcp_server,
    create_report_mcp_server,
    run_stdio_report_server,
    run_stdio_server,
    run_streamable_http_report_server,
    run_streamable_http_server,
)

__all__ = [
    "MCP_ACTION_SERVER_NAME",
    "MCP_SERVER_NAME",
    "MCP_REPORT_SERVER_NAME",
    "STREAMABLE_HTTP_PATH",
    "STREAMABLE_HTTP_ACTION_PATH",
    "STREAMABLE_HTTP_REPORT_PATH",
    "create_mcp_server",
    "create_action_mcp_server",
    "create_report_mcp_server",
    "run_stdio_server",
    "run_stdio_action_server",
    "run_stdio_report_server",
    "run_streamable_http_server",
    "run_streamable_http_action_server",
    "run_streamable_http_report_server",
]
