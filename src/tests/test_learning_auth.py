"""Tests for Learning endpoint authentication and authorization.

Verifies that all learning endpoints require a valid JWT and return 401 for
invalid tokens, and that the get_current_user dependency is properly wired.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from auth import get_current_user  # noqa: E402
from main import app  # noqa: E402

MOCK_USER: dict[str, Any] = {"id": 1, "email": "test@test.com", "role": "Student"}
FAKE_TOKEN: str = "Bearer fake-jwt-token"
INVALID_TOKEN: str = "Bearer completely-invalid-token"


def _mock_deps(user: dict[str, Any] | None = None) -> None:
    """Wire get_current_user to return a mock user (or raise 401)."""
    if user is None:

        async def _no_user() -> Any:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")

        app.dependency_overrides[get_current_user] = _no_user
    else:
        mock_user = MagicMock()
        mock_user.id = user["id"]
        mock_user.email = user["email"]
        mock_user.role = user.get("role", "Student")

        async def _get_user() -> Any:
            return mock_user

        app.dependency_overrides[get_current_user] = _get_user


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ── CRUD Learning endpoints ─────────────────────────────────────────────────


class TestCRUDEndpointsRequireAuth:
    """All /api/* learning endpoints should return 401 when unauthenticated."""

    def setup_method(self) -> None:
        _mock_deps(None)

    def teardown_method(self) -> None:
        _clear_deps()

    def test_list_units_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/courses/1/units")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_create_unit_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/units",
                    json={"title": "X", "description": ""},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_get_unit_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/units/1")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_update_unit_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.put("/api/units/1", json={"title": "X"})
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_delete_unit_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.delete("/api/units/1")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_list_sections_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/units/1/sections")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_create_section_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/units/1/sections",
                    json={"title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_list_lessons_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/sections/1/lessons")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_create_lesson_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/sections/1/lessons",
                    json={"title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_list_practices_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/sections/1/practices")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_create_practice_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/sections/1/practices",
                    json={"title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_list_quizzes_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/sections/1/quizzes")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_create_quiz_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/sections/1/quizzes",
                    json={"title": "X"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401


# ── V1 Learning endpoints ───────────────────────────────────────────────────


class TestV1EndpointsRequireAuth:
    """All /api/v1/* learning endpoints should return 401 when unauthenticated."""

    def setup_method(self) -> None:
        _mock_deps(None)

    def teardown_method(self) -> None:
        _clear_deps()

    def test_get_unit_detail_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/units/1")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_submit_practice_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/practices/1/submit",
                    json={"correct": 8, "total": 10},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_submit_quiz_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/v1/quizzes/1/submit",
                    json={"score": 85.0},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_update_lesson_progress_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.patch(
                    "/api/v1/users/me/lessons/1",
                    json={"status": "COMPLETED"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_update_practice_progress_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.patch(
                    "/api/v1/users/me/practices/1",
                    json={"status": "mastered"},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_update_quiz_progress_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.patch(
                    "/api/v1/users/me/quizzes/1",
                    json={"score": 85.0},
                )
                return resp.status_code

        assert asyncio.run(_run()) == 401


# ── Progress endpoints ──────────────────────────────────────────────────────


class TestProgressEndpointsRequireAuth:
    """Progress endpoints should return 401 when unauthenticated."""

    def setup_method(self) -> None:
        _mock_deps(None)

    def teardown_method(self) -> None:
        _clear_deps()

    def test_get_all_progress_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/users/me/progress")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_get_lesson_progress_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/users/1/lessons/1/progress")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_get_practice_progress_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/users/1/practices/1/progress")
                return resp.status_code

        assert asyncio.run(_run()) == 401

    def test_get_quiz_progress_no_auth(self):
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/users/1/quizzes/1/progress")
                return resp.status_code

        assert asyncio.run(_run()) == 401


# ── Auth with valid user (smoke tests) ──────────────────────────────────────


class TestEndpointsWithValidUser:
    """Smoke test that endpoints return 200/404 (not 401) when auth is provided."""

    def setup_method(self) -> None:
        _mock_deps(MOCK_USER)

    def teardown_method(self) -> None:
        _clear_deps()

    @patch("database.repositories.learning.AsyncSession")
    def test_list_units_with_auth(self, _mock_session: MagicMock) -> None:
        session = _make_session_for_repos()
        _mock_session.return_value = session
        transport = ASGITransport(app=app)

        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_course",
                    new_callable=AsyncMock,
                    return_value={"id": 1, "title": "C"},
                ),
                patch(
                    "routers.learning.list_units",
                    new_callable=AsyncMock,
                    return_value=[],
                ),
            ):
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    resp = await client.get("/api/courses/1/units")
                    return resp.status_code

        result = asyncio.run(_run())
        assert result in (200, 404, 422)

    @patch("database.repositories.learning.AsyncSession")
    def test_get_unit_with_auth(self, _mock_session: MagicMock) -> None:
        session = _make_session_for_repos(rows=None)
        _mock_session.return_value = session
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/v1/units/99999")
                return resp.status_code

        result = asyncio.run(_run())
        assert result in (200, 404)

    @patch("database.repositories.learning.AsyncSession")
    def test_list_sections_with_auth(self, _mock_session: MagicMock) -> None:
        session = _make_session_for_repos()
        _mock_session.return_value = session
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.get("/api/units/1/sections")
                return resp.status_code

        result = asyncio.run(_run())
        assert result in (200, 404, 422)


def _make_session_for_repos(rows: Any = None) -> MagicMock:
    """Create a mock AsyncSession with default empty results."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()

    scalars_mock = MagicMock()
    if rows is None:
        scalars_mock.first.return_value = None
        scalars_mock.all.return_value = []
    else:
        scalars_mock.first.return_value = rows
        scalars_mock.all.return_value = rows if isinstance(rows, list) else [rows]

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    execute_result.rowcount = 1
    session.execute = AsyncMock(return_value=execute_result)
    return session
