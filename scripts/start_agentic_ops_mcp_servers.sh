#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

HOST="${MCP_HOST:-127.0.0.1}"
REPORT_PORT="${MCP_REPORT_PORT:-8765}"
ACTION_PORT="${MCP_ACTION_PORT:-8766}"
REPORT_PATH="${MCP_REPORT_PATH:-/mcp/lp/reporting}"
ACTION_PATH="${MCP_ACTION_PATH:-/mcp/lp/actions}"

echo "Starting Agentic Ops MCP servers"
echo "- Host: ${HOST}"
echo "- Report: http://${HOST}:${REPORT_PORT}${REPORT_PATH}"
echo "- Action: http://${HOST}:${ACTION_PORT}${ACTION_PATH}"

cleanup() {
  echo "Stopping MCP servers..."
  if [[ -n "${REPORT_PID:-}" ]] && kill -0 "${REPORT_PID}" 2>/dev/null; then
    kill "${REPORT_PID}" || true
  fi
  if [[ -n "${ACTION_PID:-}" ]] && kill -0 "${ACTION_PID}" 2>/dev/null; then
    kill "${ACTION_PID}" || true
  fi
}

trap cleanup EXIT INT TERM

uv run python -m learning_platform.agentic_ops.mcp_server \
  --mode report \
  --transport streamable-http \
  --host "${HOST}" \
  --port "${REPORT_PORT}" \
  --path "${REPORT_PATH}" &
REPORT_PID=$!

uv run python -m learning_platform.agentic_ops.mcp_server \
  --mode action \
  --transport streamable-http \
  --host "${HOST}" \
  --port "${ACTION_PORT}" \
  --path "${ACTION_PATH}" &
ACTION_PID=$!

echo "MCP servers running (report PID=${REPORT_PID}, action PID=${ACTION_PID})"
echo "Press Ctrl+C to stop both servers."

wait "${REPORT_PID}" "${ACTION_PID}"
