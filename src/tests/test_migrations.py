"""Regression test for scripts/migrate.sh / `alembic upgrade head`.

The reported issue: `alembic upgrade head` fails when the database schema has
drifted from its `alembic_version` stamp (e.g. the schema was rebuilt via
SQLAlchemy ``create_all`` while the stamp was left at an older revision).
This leaves index/column operations assuming schema states that no longer
exist, e.g. ``DROP INDEX ix_lp_concept_relationships_source``.

The test runs the exact command used by scripts/migrate.sh against the test
database and asserts it completes successfully with the database at head.

Skipped automatically when the database is unreachable.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

ROOT: Path = Path(__file__).resolve().parent.parent.parent

_DEFAULT_TEST_DB_URL: str = (
    "postgresql+asyncpg://postgres_user:secure_password_here"
    "@localhost:5433/learning_platform_testing"
)

TEST_DATABASE_URL: str = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DB_URL)


def _run_alembic(args: list[str]) -> subprocess.CompletedProcess[str]:
    env: dict[str, str] = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def _parse_head(output: str) -> str | None:
    for line in output.splitlines():
        match = re.search(r"\b([0-9a-f]{12,})\b.*\(head\)", line)
        if match:
            return match.group(1)
    return None


def _parse_current(output: str) -> str | None:
    for line in output.splitlines():
        match = re.search(r"\b([0-9a-f]{12,})\b", line)
        if match:
            return match.group(1)
    return None


async def _database_reachable() -> bool:
    try:
        import asyncpg

        dsn: str = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn=dsn, timeout=3)
        await conn.close()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(loop_scope="session")
async def _db_reachable() -> bool:
    return await _database_reachable()


@pytest.mark.asyncio
async def test_alembic_upgrade_head_succeeds(_db_reachable: bool) -> None:
    if not _db_reachable:
        pytest.skip(f"PostgreSQL not reachable at {TEST_DATABASE_URL}")

    heads_proc = _run_alembic(["heads"])
    assert heads_proc.returncode == 0, heads_proc.stderr
    head: str | None = _parse_head(heads_proc.stdout)
    assert head is not None, heads_proc.stdout

    upgrade_proc = _run_alembic(["upgrade", "head"])
    assert upgrade_proc.returncode == 0, (
        f"`alembic upgrade head` failed against {TEST_DATABASE_URL}\n"
        f"stdout:\n{upgrade_proc.stdout}\n"
        f"stderr:\n{upgrade_proc.stderr}"
    )

    current_proc = _run_alembic(["current"])
    assert current_proc.returncode == 0, current_proc.stderr
    current: str | None = _parse_current(current_proc.stdout)
    assert current == head, (
        f"database not at head after upgrade: current={current}, head={head}"
    )
