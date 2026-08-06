"""Integration test configuration and shared fixtures.

These tests require a running PostgreSQL instance. Set the environment variable:

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5433/test_db

If the database is unreachable, all tests in this package are automatically
skipped via the `db_engine` fixture.

Run integration tests only:
    uv run pytest src/tests/integration/ -v

Run with a custom DB URL:
    TEST_DATABASE_URL=... uv run pytest src/tests/integration/ -v
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# Ensure src/ is importable when running pytest from the project root.
_src_dir: str = str(Path(__file__).resolve().parent.parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TEST_DB_URL: str = (
    "postgresql+asyncpg://postgres_user:secure_password_here"
    "@localhost:5433/learning_platform_testing"
)

TEST_DATABASE_URL: str = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DB_URL)

# ---------------------------------------------------------------------------
# Session-scoped engine — created once per pytest session
# ---------------------------------------------------------------------------


def _run_alembic_upgrade() -> subprocess.CompletedProcess[str]:
    """Apply migrations (alembic upgrade head) against the test DB.

    Keeps alembic as the single source of truth for the schema and prevents
    drift between ``create_all``-built test schemas and migrations.
    """
    env: dict[str, str] = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL
    return subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an async engine connected to the test Postgres DB.

    Skips the entire session if the database is unreachable.
    The schema is rebuilt from migrations (alembic upgrade head) before the
    session starts and dropped after.
    """
    engine: AsyncEngine = create_async_engine(
        TEST_DATABASE_URL, echo=False, poolclass=NullPool
    )

    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        proc: subprocess.CompletedProcess[str] = await asyncio.to_thread(
            _run_alembic_upgrade
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"`alembic upgrade head` failed\nstdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO users (id, email, name, picture_url, phone)
                    VALUES (1000000, 'integration@example.com', 'Integration User', '', '')
                    ON CONFLICT (id) DO NOTHING
                    """
                )
            )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable at {TEST_DATABASE_URL}: {exc}")

    yield engine

    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    await engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped session — each test gets a rolled-back transaction
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession that is rolled back after each test.

    This keeps tests fully isolated without truncating tables.
    """
    async_session_factory = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# FastAPI test app — auth bypassed, engine pointed at test DB
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mock_user() -> dict[str, Any]:
    """Fake authenticated user injected via dependency_overrides."""
    return {
        "id": 1000000,
        "email": "integration@example.com",
        "name": "Integration User",
        "picture_url": "",
        "phone": "",
        "auth_provider": "local",
        "roles": ["Admin"],
        "permissions": ["course:browse", "course:manage"],
    }


@pytest.fixture(scope="session")
def app(mock_user: dict[str, Any]):
    """FastAPI app with auth overridden and engine pointed at test DB.

    The DATABASE_URL env var is set before importing main so the module-level
    engine singleton picks up the test URL.
    """
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ.setdefault("JWT_SECRET", "test-integration-secret")

    from auth import get_current_user
    from main import app as _app

    _app.dependency_overrides[get_current_user] = lambda: mock_user
    return _app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(
    app, mock_user: dict[str, Any], db_engine: AsyncEngine
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client wired to the integration app.

    Session-scoped so the FastAPI lifespan (startup/shutdown) only runs once.
    Auth override is re-applied by the ``_reapply_auth`` autouse fixture so
    the parent conftest's ``clear_dependency_overrides`` wipe is harmless.
    """
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: mock_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reapply_auth(app, mock_user: dict[str, Any]) -> Generator[None, None, None]:
    """Re-apply the auth override before each test.

    The parent conftest (src/tests/conftest.py) has an autouse fixture that
    clears ``dependency_overrides`` after every test.  This fixture re-sets
    the integration auth override before each test so the client stays
    authenticated throughout the session.

    We do NOT re-apply after yield (teardown) so the clear from the parent
    conftest is effective for non-integration tests that run afterward.
    """
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield
