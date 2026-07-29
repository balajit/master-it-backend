#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env.production"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found"
  exit 1
fi

if [[ -n "${1:-}" ]]; then
  NEW_PASSWORD="$1"
else
  read -rsp "Enter new production DB password: " NEW_PASSWORD
  echo
fi

if [[ -z "$NEW_PASSWORD" ]]; then
  echo "Error: password cannot be empty"
  exit 1
fi

python3 - "$ENV_FILE" "$NEW_PASSWORD" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit


def build_netloc(
    username: str,
    password: str,
    host: str,
    port: int | None,
) -> str:
    encoded_user = quote(username, safe="")
    encoded_password = quote(password, safe="")

    host_part = host
    if ":" in host and not host.startswith("["):
        host_part = f"[{host}]"

    port_part = f":{port}" if port is not None else ""
    return f"{encoded_user}:{encoded_password}@{host_part}{port_part}"


env_path = Path(sys.argv[1])
new_password_raw = sys.argv[2]

content = env_path.read_text(encoding="utf-8")
match = re.search(r"^DATABASE_URL=(.+)$", content, flags=re.MULTILINE)
if match is None:
    raise SystemExit("Error: DATABASE_URL not found in .env.production")

old_url = match.group(1).strip()
parts = urlsplit(old_url)

if not parts.scheme or not parts.username or not parts.hostname:
    raise SystemExit(
        "Error: DATABASE_URL must include scheme, username, and host"
    )

new_netloc = build_netloc(
    username=parts.username,
    password=new_password_raw,
    host=parts.hostname,
    port=parts.port,
)
new_url = urlunsplit(
    (parts.scheme, new_netloc, parts.path, parts.query, parts.fragment)
)

updated = re.sub(
    r"^DATABASE_URL=.*$",
    f"DATABASE_URL={new_url}",
    content,
    flags=re.MULTILINE,
)

env_path.write_text(updated, encoding="utf-8")
print("Updated DATABASE_URL password in .env.production")
PY
