#!/usr/bin/env bash
# scripts/start_url_pdf_service.sh
#
# Start the url-pdf-service microservice.
#
# Usage:
#   ./scripts/start_url_pdf_service.sh              # local dev (uvicorn, hot-reload)
#   ./scripts/start_url_pdf_service.sh --production # local production-mode (no reload)
#   ./scripts/start_url_pdf_service.sh --docker     # via docker compose
#
# The service runs on port 8001 by default.
# Set PORT env var to override: PORT=9001 ./scripts/start_url_pdf_service.sh

set -euo pipefail

PORT="${PORT:-8001}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVICE_DIR="${REPO_ROOT}/url-pdf-service"
MODE="dev"

usage() {
    echo "Usage: $0 [--dev|--production|--docker]"
    echo ""
    echo "  --dev          Hot-reload dev mode via uvicorn (default)"
    echo "  --production   Production mode (4 workers, no reload)"
    echo "  --docker       Build and start via docker compose"
    echo ""
    echo "Environment:"
    echo "  PORT           Override the default port (default: 8001)"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            MODE="dev"
            shift
            ;;
        --production)
            MODE="production"
            shift
            ;;
        --docker)
            MODE="docker"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# ── Docker mode ───────────────────────────────────────────────────────────────
if [[ "$MODE" == "docker" ]]; then
    echo "Building and starting url-pdf-service via docker compose..."
    cd "${REPO_ROOT}"
    docker compose build url-pdf-service
    docker compose up -d url-pdf-service
    echo ""
    echo "url-pdf-service is running at http://localhost:${PORT}"
    echo "  Logs:   make logs-url-pdf"
    echo "  Stop:   docker compose stop url-pdf-service"
    exit 0
fi

# ── Local mode (dev or production) ───────────────────────────────────────────
if [[ ! -d "${SERVICE_DIR}" ]]; then
    echo "Error: url-pdf-service directory not found at ${SERVICE_DIR}"
    exit 1
fi

# Kill any existing process on the port
if lsof -ti :"${PORT}" >/dev/null 2>&1; then
    echo "Stopping existing process on port ${PORT}..."
    lsof -ti :"${PORT}" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

cd "${SERVICE_DIR}"

# Ensure dependencies are installed (fast no-op if already up to date)
echo "Syncing url-pdf-service dependencies..."
uv sync --quiet

# Warn if Chromium is not installed
if ! uv run playwright install --dry-run chromium 2>/dev/null | grep -q "already installed" 2>/dev/null; then
    if ! uv run python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.chromium; p.stop()" 2>/dev/null; then
        echo "Warning: Playwright Chromium may not be installed."
        echo "Run: cd url-pdf-service && uv run playwright install chromium --with-deps"
        echo "Continuing anyway..."
    fi
fi

echo ""
if [[ "$MODE" == "production" ]]; then
    echo "Starting url-pdf-service in production mode on http://localhost:${PORT} ..."
    exec uv run uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "${PORT}" \
        --workers 4
else
    echo "Starting url-pdf-service in dev mode on http://localhost:${PORT} ..."
    echo "  Health: http://localhost:${PORT}/health"
    echo "  Docs:   http://localhost:${PORT}/docs"
    echo ""
    exec uv run uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "${PORT}" \
        --reload
fi
