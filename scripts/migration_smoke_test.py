#!/usr/bin/env python3
"""Smoke-test Alembic upgrades against a temporary PostgreSQL database.

Requirements:
- Reachable PostgreSQL from DATABASE_URL
- Permission to create/drop databases on maintenance DB
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg


ROOT: Path = Path(__file__).resolve().parent.parent


def _admin_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/postgres"))


def _db_url_with_name(database_url: str, db_name: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path=f"/{db_name}"))


def _to_asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _create_database(admin_url: str, db_name: str) -> None:
    conn = await asyncpg.connect(dsn=_to_asyncpg_dsn(admin_url))
    try:
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def _drop_database(admin_url: str, db_name: str) -> None:
    conn = await asyncpg.connect(dsn=_to_asyncpg_dsn(admin_url))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        await conn.close()


def main() -> int:
    base_url = os.environ.get("DATABASE_URL", "").strip()
    if not base_url:
        print("[migrations] DATABASE_URL is required for smoke test")
        return 1

    if "+asyncpg" not in base_url:
        print("[migrations] DATABASE_URL must use postgresql+asyncpg")
        return 1

    db_name = f"lp_migration_smoke_{secrets.token_hex(4)}"
    admin_url = _admin_url(base_url)
    smoke_url = _db_url_with_name(base_url, db_name)

    try:
        asyncio.run(_create_database(admin_url, db_name))
    except Exception as exc:
        print(f"[migrations] Could not create temporary smoke-test database: {exc}")
        return 1

    env = os.environ.copy()
    env["DATABASE_URL"] = smoke_url

    try:
        upgrade = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        if upgrade.returncode != 0:
            print(upgrade.stdout)
            print(upgrade.stderr)
            print("[migrations] Smoke test failed")
            return 1

        print("[migrations] Smoke test passed (temporary postgres upgrade head)")
        return 0
    finally:
        try:
            asyncio.run(_drop_database(admin_url, db_name))
        except Exception as exc:
            print(f"[migrations] Warning: failed to drop temporary DB {db_name}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
