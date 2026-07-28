"""Shared pytest configuration for src/tests/.

Maintains a single event loop for the entire test session.  Tests that call
asyncio.run() create and destroy their own inner loops, which can orphan
SQLAlchemy asyncpg connection-pool callbacks.  We work around this by
patching asyncio.run() in this module to use loop.run_until_complete() on
the session-level loop instead.

Also provides an autouse fixture that clears FastAPI dependency_overrides
between tests so auth mocks from one test cannot contaminate another.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Coroutine, Generator, TypeVar

import pytest

T = TypeVar("T")

# Ensure src/ is importable from all test files
_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# ── Single session-level event loop ──────────────────────────────────────────

_SESSION_LOOP: asyncio.AbstractEventLoop = asyncio.new_event_loop()
asyncio.set_event_loop(_SESSION_LOOP)

# Patch asyncio.run so that test helpers using asyncio.run() reuse the same
# loop, preventing "Future attached to a different loop" errors from the
# SQLAlchemy asyncpg connection pool.
_original_asyncio_run = asyncio.run


def _patched_asyncio_run(coro: Coroutine[Any, Any, T], **kwargs: Any) -> T:  # type: ignore[override]
    return _SESSION_LOOP.run_until_complete(coro)


asyncio.run = _patched_asyncio_run  # type: ignore[assignment]


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Expose the session loop for pytest-asyncio fixtures."""
    yield _SESSION_LOOP


# ── Dependency override cleanup ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Generator[None, None, None]:
    """Clear FastAPI dependency_overrides after every test.

    Prevents auth mocks set in one test from leaking into subsequent tests
    (e.g. a test that mocks get_current_user should not affect an auth test
    that expects a 401).
    """
    yield
    try:
        from main import app

        app.dependency_overrides.clear()
    except Exception:
        pass
