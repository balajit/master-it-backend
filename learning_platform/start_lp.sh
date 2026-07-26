#!/usr/bin/env bash
set -euo pipefail

PORT=5555
ENV="testing"

usage() {
    echo "Usage: $0 [--testing|--production]"
    echo "  --testing     Use testing environment (default)"
    echo "  --production  Use production environment"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --testing)
            ENV="testing"
            shift
            ;;
        --production)
            ENV="production"
            shift
            ;;
        *)
            usage
            ;;
    esac
done

if lsof -ti :"$PORT" >/dev/null 2>&1; then
    echo "Stopping existing server on port $PORT..."
    lsof -ti :"$PORT" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

ENV_FILE=".env.$ENV"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: $ENV_FILE not found"
    exit 1
fi

echo "Starting server in $ENV mode on http://localhost:$PORT ..."
export $(grep -v '^#' "$ENV_FILE" | xargs)
if [[ "$ENV" == "production" ]]; then
    exec uv run uvicorn main:app --app-dir src --host 0.0.0.0 --port "$PORT" --workers 4
else
    exec uv run fastapi dev src/learning_platform/api/app.py --port "$PORT"
fi
