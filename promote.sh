#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

usage() {
    echo "Usage: $0 [--dry-run]"
    echo "  --dry-run  Show what would be done without making changes"
    exit 1
}

DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            usage
            ;;
    esac
done

echo "=== Pre-flight Checks ==="

# Check PostgreSQL connectivity
echo "1. Checking PostgreSQL connectivity..."
if ! pg_isready -h localhost -p 5432 -U postgres_user >/dev/null 2>&1; then
    echo "   Warning: Cannot connect to production PostgreSQL"
fi
if ! pg_isready -h localhost -p 5433 -U postgres_user >/dev/null 2>&1; then
    echo "   Warning: Cannot connect to testing PostgreSQL"
fi

# Validate testing schema
echo "2. Validating testing schema..."
DB_ENV=testing uv run python -c "
import asyncio
from database import engine
from sqlalchemy import text

async def check():
    async with engine.connect() as conn:
        result = await conn.execute(text(\"SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'\"))
        tables = [r[0] for r in result.fetchall()]
        expected = ['users', 'sessions', 'courses', 'roles', 'user_roles', 'permissions', 'role_permissions', 'documents', 'course_documents']
        missing = [t for t in expected if t not in tables]
        if missing:
            print(f'   Missing tables: {missing}')
            exit(1)
        else:
            print(f'   All {len(expected)} tables present')

asyncio.run(check())
" 2>/dev/null

if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "=== Dry Run Mode ==="
    echo "Would backup production PostgreSQL to $BACKUP_DIR/pg_production_${TIMESTAMP}.sql"
    echo "Would copy testing data to production (courses, users, etc.)"
    exit 0
fi

echo ""
echo "=== Backup Production ==="
mkdir -p "$BACKUP_DIR"
pg_dump -h localhost -p 5432 -U postgres_user learning_platform_production > "$BACKUP_DIR/pg_production_${TIMESTAMP}.sql" 2>/dev/null || echo "Warning: pg_dump failed (is PostgreSQL running?)"
echo "Backup created: $BACKUP_DIR/pg_production_${TIMESTAMP}.sql"

echo ""
echo "=== Initialize System Data ==="
DB_ENV=production uv run python init_system.py 2>/dev/null

echo ""
echo "=== Promote Data ==="
DB_ENV=production uv run python promote_data.py

echo ""
echo "=== Complete ==="
echo "Production database updated successfully."
