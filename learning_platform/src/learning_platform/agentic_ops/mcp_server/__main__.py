"""CLI entrypoint for triage MCP report/action servers."""

from __future__ import annotations

import argparse
import asyncio

from learning_platform.agentic_ops.mcp_server.action_server import (
    STREAMABLE_HTTP_ACTION_PATH,
    run_stdio_action_server,
    run_streamable_http_action_server,
)
from learning_platform.agentic_ops.mcp_server.reporting_server import (
    STREAMABLE_HTTP_REPORT_PATH,
    run_stdio_server,
    run_streamable_http_server,
)

REPORT_DEFAULT_PORT = 8765
ACTION_DEFAULT_PORT = 8766


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run triage MCP report/action server")
    parser.add_argument(
        "--mode",
        choices=("report", "action"),
        default="report",
        help="Server mode (default: report)",
    )
    parser.add_argument(
        "--transport",
        choices=("streamable-http", "stdio"),
        default="streamable-http",
        help="Transport type (default: streamable-http)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (streamable-http transport)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP bind port (streamable-http transport)",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="HTTP MCP path (streamable-http transport)",
    )
    return parser


async def _run(args: argparse.Namespace) -> None:
    if args.mode == "action":
        port = int(args.port) if args.port is not None else ACTION_DEFAULT_PORT
        path = str(args.path) if args.path is not None else STREAMABLE_HTTP_ACTION_PATH
        if args.transport == "stdio":
            await run_stdio_action_server()
            return
        await run_streamable_http_action_server(
            host=args.host,
            port=port,
            streamable_http_path=path,
        )
        return

    port = int(args.port) if args.port is not None else REPORT_DEFAULT_PORT
    path = str(args.path) if args.path is not None else STREAMABLE_HTTP_REPORT_PATH
    if args.transport == "stdio":
        await run_stdio_server()
        return

    await run_streamable_http_server(
        host=args.host,
        port=port,
        streamable_http_path=path,
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
