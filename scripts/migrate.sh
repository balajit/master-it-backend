#!/usr/bin/env bash
# migrate.sh — Run Alembic migrations against one or more databases.
#
# Usage:
#   ./scripts/migrate.sh              # migrate both testing and production
#   ./scripts/migrate.sh testing      # migrate only testing
#   ./scripts/migrate.sh production   # migrate only production
#
# Each environment sources its own .env file to pick up the correct DATABASE_URL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE_PREFIX="$ROOT/.env"

run_migrations_for_env() {
  local env_name="$1"
  local env_file="${ENV_FILE_PREFIX}.${env_name}"

  if [[ ! -f "$env_file" ]]; then
    echo "Error: $env_file not found"
    return 1
  fi

  echo "========================================"
  echo "  Environment: $env_name"
  echo "  Env file   : $env_file"
  echo "========================================"

  # Export only DATABASE_URL (ignore other vars that might confuse Alembic)
  local database_url
  database_url="$(grep -E '^DATABASE_URL=' "$env_file" | tail -1 | cut -d= -f2-)"

  if [[ -z "$database_url" ]]; then
    echo "Error: DATABASE_URL not set in $env_file"
    return 1
  fi

  echo "  Database   : ${database_url##*@}"
  echo ""

  DATABASE_URL="$database_url" uv run alembic upgrade head

  echo ""
  echo "  Done — $env_name migrations applied."
  echo ""
}

case "${1:-all}" in
  all)
    run_migrations_for_env testing
    run_migrations_for_env production
    ;;
  testing|production)
    run_migrations_for_env "$1"
    ;;
  *)
    echo "Usage: $0 [testing|production|all]"
    exit 1
    ;;
esac
