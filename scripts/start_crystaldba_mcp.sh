  echo "========================================"

  # Export only DATABASE_URL (ignore other vars that might confuse Alembic)
  database_url="$(grep -E '^DATABASE_URL=' ".env.testing" | tail -1 | cut -d= -f2-)"

  if [[ -z "$database_url" ]]; then
    echo "Error: DATABASE_URL not set in $env_file"
    return 1
  fi

  echo "  Database   : ${database_url##*@}"
  echo ""

CLEAN_DB_URL=$(echo "$database_url" | sed 's/+asyncpg//')
docker run -i --rm \
  --network master-it-backend_default  \
  -e DATABASE_URI=${CLEAN_DB_URL} \
  crystaldba/postgres-mcp:latest \
  --access-mode=restricted
