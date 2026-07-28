"""Comprehensive tests for Learning API endpoints.

Covers: CRUD operations, authentication, authorization, 404 handling,
progress updates, quiz/practice submissions, and edge cases.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from main import app  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_user() -> dict[str, Any]:
    return {
        "id": 1,
        "email": "test@example.com",
        "name": "Test User",
        "picture_url": "",
        "phone": "",
        "auth_provider": "local",
        "roles": ["Student"],
        "permissions": ["course:browse"],
    }


MOCK_COURSE: dict[str, Any] = {
    "id": 1,
    "title": "ML Course",
    "description": "Machine Learning",
    "number_of_credits": 4,
    "difficulty": "intermediate",
    "status": "OPEN",
    "owner_id": 1,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_UNIT: dict[str, Any] = {
    "id": 1,
    "course_id": 1,
    "title": "Unit 1",
    "description": "Intro",
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_SECTION: dict[str, Any] = {
    "id": 1,
    "unit_id": 1,
    "title": "Section 1",
    "estimated_minutes": 30,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_LESSON: dict[str, Any] = {
    "id": 1,
    "section_id": 1,
    "title": "Lesson 1",
    "description": "Content here",
    "duration_minutes": 15,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_PRACTICE: dict[str, Any] = {
    "id": 1,
    "section_id": 1,
    "title": "Practice 1",
    "required_correct": 8,
    "total_questions": 10,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_QUIZ: dict[str, Any] = {
    "id": 1,
    "section_id": 1,
    "title": "Quiz 1",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_UNIT_RESPONSE: dict[str, Any] = {
    "id": 1,
    "title": "Unit 1",
    "description": "Intro",
    "course_id": 1,
    "about": "Intro",
    "progress": {"total": 0, "completed": 0, "mastered_pct": 0.0, "squares": []},
    "sections": [],
}

MOCK_LESSON_PROGRESS: dict[str, Any] = {
    "user_id": 1,
    "lesson_id": 1,
    "status": "COMPLETED",
    "completed_at": "2026-01-15T10:00:00",
}

MOCK_PRACTICE_PROGRESS: dict[str, Any] = {
    "user_id": 1,
    "practice_id": 1,
    "attempts": 3,
    "best_score": 9.0,
    "status": "MASTERED",
}

MOCK_QUIZ_PROGRESS: dict[str, Any] = {
    "user_id": 1,
    "quiz_id": 1,
    "score": 85.0,
    "completed_at": "2026-01-15T10:00:00",
}


def _mock_deps(user: dict[str, Any]) -> None:
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Authentication — All endpoints require valid user
# ═══════════════════════════════════════════════════════════════════════════


class TestAuthentication:
    """All learning endpoints must return 401 when unauthenticated."""

    def setup_method(self) -> None:
        app.dependency_overrides.clear()

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def _test_unauthenticated(
        self, method: str, url: str, json: dict | None = None
    ) -> int:
        transport = ASGITransport(app=app)

        async def _run() -> int:
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                resp = await client.request(method, url, json=json)
                return resp.status_code

        return asyncio.run(_run())

    def test_get_units_no_auth(self) -> None:
        assert self._test_unauthenticated("GET", "/api/courses/1/units") == 401

    def test_create_unit_no_auth(self) -> None:
        assert (
            self._test_unauthenticated("POST", "/api/courses/1/units", {"title": "X"})
            == 401
        )

    def test_get_unit_no_auth(self) -> None:
        assert self._test_unauthenticated("GET", "/api/units/1") == 401

    def test_update_unit_no_auth(self) -> None:
        assert self._test_unauthenticated("PUT", "/api/units/1", {"title": "X"}) == 401

    def test_delete_unit_no_auth(self) -> None:
        assert self._test_unauthenticated("DELETE", "/api/units/1") == 401

    def test_get_sections_no_auth(self) -> None:
        assert self._test_unauthenticated("GET", "/api/units/1/sections") == 401

    def test_create_section_no_auth(self) -> None:
        assert (
            self._test_unauthenticated("POST", "/api/units/1/sections", {"title": "X"})
            == 401
        )

    def test_get_section_no_auth(self) -> None:
        assert self._test_unauthenticated("GET", "/api/sections/1") == 401

    def test_create_lesson_no_auth(self) -> None:
        assert (
            self._test_unauthenticated(
                "POST", "/api/sections/1/lessons", {"title": "X"}
            )
            == 401
        )

    def test_get_lesson_no_auth(self) -> None:
        assert self._test_unauthenticated("GET", "/api/lessons/1") == 401

    def test_create_practice_no_auth(self) -> None:
        assert (
            self._test_unauthenticated(
                "POST", "/api/sections/1/practices", {"title": "X"}
            )
            == 401
        )

    def test_create_quiz_no_auth(self) -> None:
        assert (
            self._test_unauthenticated(
                "POST", "/api/sections/1/quizzes", {"title": "X"}
            )
            == 401
        )

    def test_v1_unit_no_auth(self) -> None:
        assert self._test_unauthenticated("GET", "/api/v1/units/1") == 401

    def test_v1_submit_practice_no_auth(self) -> None:
        assert (
            self._test_unauthenticated(
                "POST", "/api/v1/practices/1/submit", {"score": 8.0}
            )
            == 401
        )

    def test_v1_submit_quiz_no_auth(self) -> None:
        assert (
            self._test_unauthenticated(
                "POST", "/api/v1/quizzes/1/submit", {"score": 85.0}
            )
            == 401
        )

    def test_v1_update_lesson_progress_no_auth(self) -> None:
        assert (
            self._test_unauthenticated(
                "PATCH", "/api/v1/users/me/lessons/1", {"status": "COMPLETED"}
            )
            == 401
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2. Units CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestUnitsCRUD:
    """Test CRUD operations on Units endpoint."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_create_unit(self, mock_user: dict) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_course",
                    new_callable=AsyncMock,
                    return_value=MOCK_COURSE,
                ),
                patch(
                    "routers.learning.create_unit",
                    new_callable=AsyncMock,
                    return_value=1,
                ),
                patch(
                    "routers.learning.get_unit",
                    new_callable=AsyncMock,
                    return_value=MOCK_UNIT,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/courses/1/units",
                        json={"title": "Unit 1", "description": "Intro"},
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 201

    def test_create_unit_course_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_course", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post("/api/courses/999/units", json={"title": "X"})
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_create_unit_value_error_returns_400(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_course",
                    new_callable=AsyncMock,
                    return_value=MOCK_COURSE,
                ),
                patch(
                    "routers.learning.create_unit",
                    new_callable=AsyncMock,
                    side_effect=ValueError("Course 1 not found"),
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post("/api/courses/1/units", json={"title": "X"})
                    return resp.status_code

        assert asyncio.run(_run()) == 400

    def test_list_units(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.learning.get_course",
                    new_callable=AsyncMock,
                    return_value=MOCK_COURSE,
                ),
                patch(
                    "routers.learning.list_units",
                    new_callable=AsyncMock,
                    return_value=[MOCK_UNIT],
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/courses/1/units")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert len(data) == 1

    def test_list_units_course_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_course", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/courses/999/units")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_get_unit(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.learning.get_unit",
                new_callable=AsyncMock,
                return_value=MOCK_UNIT,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/units/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "Unit 1"

    def test_get_unit_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_unit", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/units/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_update_unit(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.learning.update_unit",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch(
                    "routers.learning.get_unit",
                    new_callable=AsyncMock,
                    return_value={**MOCK_UNIT, "title": "Updated"},
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.put("/api/units/1", json={"title": "Updated"})
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "Updated"

    def test_update_unit_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.update_unit",
                new_callable=AsyncMock,
                return_value=False,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.put("/api/units/999", json={"title": "X"})
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_delete_unit(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.delete_unit",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch("routers.learning.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/units/1")
                    return resp.status_code

        assert asyncio.run(_run()) == 204

    def test_delete_unit_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.delete_unit",
                new_callable=AsyncMock,
                return_value=False,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/units/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404


# ═══════════════════════════════════════════════════════════════════════════
# 3. Sections CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionsCRUD:
    """Test CRUD operations on Sections endpoint."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_create_section(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_unit",
                    new_callable=AsyncMock,
                    return_value=MOCK_UNIT,
                ),
                patch(
                    "routers.learning.create_section",
                    new_callable=AsyncMock,
                    return_value=1,
                ),
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/units/1/sections", json={"title": "Section 1"}
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 201

    def test_create_section_unit_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_unit", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post("/api/units/999/sections", json={"title": "X"})
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_list_sections(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.learning.get_unit",
                    new_callable=AsyncMock,
                    return_value=MOCK_UNIT,
                ),
                patch(
                    "routers.learning.list_sections",
                    new_callable=AsyncMock,
                    return_value=[MOCK_SECTION],
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/units/1/sections")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert len(data) == 1

    def test_get_section_with_children(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.list_lessons",
                    new_callable=AsyncMock,
                    return_value=[MOCK_LESSON],
                ),
                patch(
                    "routers.learning.list_practices",
                    new_callable=AsyncMock,
                    return_value=[MOCK_PRACTICE],
                ),
                patch(
                    "routers.learning.list_quizzes",
                    new_callable=AsyncMock,
                    return_value=[MOCK_QUIZ],
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/sections/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert len(data["lessons"]) == 1
        assert len(data["practices"]) == 1
        assert len(data["quizzes"]) == 1

    def test_get_section_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_section",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/sections/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_delete_section(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.delete_section",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch("routers.learning.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/sections/1")
                    return resp.status_code

        assert asyncio.run(_run()) == 204

    def test_delete_section_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_section",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/sections/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404


# ═══════════════════════════════════════════════════════════════════════════
# 4. Lessons, Practices, Quizzes CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestLessonsCRUD:
    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_create_lesson(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.create_lesson",
                    new_callable=AsyncMock,
                    return_value=1,
                ),
                patch(
                    "routers.learning.get_lesson",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON,
                ),
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/sections/1/lessons",
                        json={"title": "Lesson 1", "description": "Content"},
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 201

    def test_create_lesson_section_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_section",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/sections/999/lessons", json={"title": "X"}
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_get_lesson(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.learning.get_lesson",
                new_callable=AsyncMock,
                return_value=MOCK_LESSON,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/lessons/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "Lesson 1"

    def test_get_lesson_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_lesson", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/lessons/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_update_lesson(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.learning.update_lesson",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch(
                    "routers.learning.get_lesson",
                    new_callable=AsyncMock,
                    return_value={**MOCK_LESSON, "title": "Updated"},
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.put("/api/lessons/1", json={"title": "Updated"})
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "Updated"

    def test_update_lesson_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.update_lesson",
                new_callable=AsyncMock,
                return_value=False,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.put("/api/lessons/999", json={"title": "X"})
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_delete_lesson(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_lesson",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON,
                ),
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.delete_lesson",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch("routers.learning.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/lessons/1")
                    return resp.status_code

        assert asyncio.run(_run()) == 204

    def test_delete_lesson_not_found(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_lesson",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.delete_lesson",
                    new_callable=AsyncMock,
                    return_value=False,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/lessons/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404


class TestPracticesCRUD:
    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_create_practice(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.create_practice",
                    new_callable=AsyncMock,
                    return_value=1,
                ),
                patch(
                    "routers.learning.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/sections/1/practices", json={"title": "Practice 1"}
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 201

    def test_get_practice(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.learning.get_practice",
                new_callable=AsyncMock,
                return_value=MOCK_PRACTICE,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/practices/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "Practice 1"

    def test_get_practice_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_practice",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/practices/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_delete_practice(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.delete_practice",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch("routers.learning.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/practices/1")
                    return resp.status_code

        assert asyncio.run(_run()) == 204


class TestQuizzesCRUD:
    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_create_quiz(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.create_quiz",
                    new_callable=AsyncMock,
                    return_value=1,
                ),
                patch(
                    "routers.learning.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/sections/1/quizzes", json={"title": "Quiz 1"}
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 201

    def test_get_quiz(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.learning.get_quiz",
                new_callable=AsyncMock,
                return_value=MOCK_QUIZ,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/quizzes/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "Quiz 1"

    def test_get_quiz_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_quiz", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/quizzes/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_delete_quiz(self) -> None:
        async def _run() -> int:
            with (
                patch(
                    "routers.learning.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.learning.delete_quiz",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch("routers.learning.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.delete("/api/quizzes/1")
                    return resp.status_code

        assert asyncio.run(_run()) == 204


# ═══════════════════════════════════════════════════════════════════════════
# 5. V1 API — Study Page, Submissions, Progress Updates
# ═══════════════════════════════════════════════════════════════════════════


class TestV1StudyPage:
    """Test V1 unit study page endpoint."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_get_unit_details(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.v1.get_unit_details",
                new_callable=AsyncMock,
                return_value=MOCK_UNIT_RESPONSE,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/units/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "Unit 1"

    def test_get_unit_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.v1.get_unit_details", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/units/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404


class TestV1QuizSubmission:
    """Test quiz submission via V1 API."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_submit_quiz_passing(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.v1.upsert_user_quiz_progress", new_callable=AsyncMock),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/quizzes/1/submit",
                        json={"score": 85.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["quiz_id"] == 1
        assert data["score"] == 85.0
        assert data["passed"] is True

    def test_submit_quiz_failing(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.v1.upsert_user_quiz_progress", new_callable=AsyncMock),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/quizzes/1/submit",
                        json={"score": 50.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["passed"] is False

    def test_submit_quiz_exact_boundary(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.v1.upsert_user_quiz_progress", new_callable=AsyncMock),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/quizzes/1/submit",
                        json={"score": 70.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["passed"] is True

    def test_submit_quiz_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.v1.get_quiz", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/quizzes/999/submit",
                        json={"score": 85.0},
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_submit_quiz_score_zero(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.v1.upsert_user_quiz_progress", new_callable=AsyncMock),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/quizzes/1/submit",
                        json={"score": 0.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["passed"] is False

    def test_submit_quiz_score_100(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.v1.upsert_user_quiz_progress", new_callable=AsyncMock),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/quizzes/1/submit",
                        json={"score": 100.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["passed"] is True


class TestV1PracticeSubmission:
    """Test practice submission via V1 API."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_submit_practice_passing(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.upsert_user_practice_progress", new_callable=AsyncMock
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/practices/1/submit",
                        json={"score": 9.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["practice_id"] == 1
        assert data["score"] == 9.0
        assert data["passed"] is True
        assert data["attempts"] == 1
        assert data["best_score"] == 9.0
        assert data["status"] == "mastered"

    def test_submit_practice_not_passing(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.upsert_user_practice_progress", new_callable=AsyncMock
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/practices/1/submit",
                        json={"score": 5.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["passed"] is False
        assert data["status"] == "attempted"

    def test_submit_practice_increments_attempts(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value={
                        "user_id": 1,
                        "practice_id": 1,
                        "attempts": 2,
                        "best_score": 7.0,
                        "status": "ATTEMPTED",
                    },
                ),
                patch(
                    "routers.v1.upsert_user_practice_progress", new_callable=AsyncMock
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/practices/1/submit",
                        json={"score": 6.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["attempts"] == 3
        assert data["best_score"] == 7.0

    def test_submit_practice_best_score_preserved(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value={
                        "user_id": 1,
                        "practice_id": 1,
                        "attempts": 2,
                        "best_score": 9.0,
                        "status": "MASTERED",
                    },
                ),
                patch(
                    "routers.v1.upsert_user_practice_progress", new_callable=AsyncMock
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/practices/1/submit",
                        json={"score": 5.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["best_score"] == 9.0

    def test_submit_practice_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.v1.get_practice", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/practices/999/submit",
                        json={"score": 10.0},
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_submit_practice_zero_score(self) -> None:
        """Practice with required_correct=8 and score=0 should not pass."""

        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.upsert_user_practice_progress", new_callable=AsyncMock
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/practices/1/submit",
                        json={"score": 0.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["passed"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 6. V1 Progress Updates
# ═══════════════════════════════════════════════════════════════════════════


class TestV1ProgressUpdates:
    """Test V1 progress update endpoints."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_get_all_progress(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.v1.get_all_user_progress",
                new_callable=AsyncMock,
                return_value={
                    "lessons": [MOCK_LESSON_PROGRESS],
                    "practices": [],
                    "quizzes": [],
                },
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/users/me/progress")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["user_id"] == 1
        assert len(data["lessons"]) == 1

    def test_get_all_progress_empty(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.v1.get_all_user_progress",
                new_callable=AsyncMock,
                return_value={"lessons": [], "practices": [], "quizzes": []},
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/users/me/progress")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["lessons"] == []

    def test_update_lesson_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_lesson",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.v1.upsert_user_lesson_progress", new_callable=AsyncMock),
                patch(
                    "routers.v1.get_user_lesson_progress",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON_PROGRESS,
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.patch(
                        "/api/v1/users/me/lessons/1",
                        json={
                            "status": "COMPLETED",
                            "completed_at": "2026-01-15T10:00:00",
                        },
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["status"] == "COMPLETED"

    def test_update_lesson_progress_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.v1.get_lesson", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.patch(
                        "/api/v1/users/me/lessons/999",
                        json={"status": "IN_PROGRESS"},
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_update_practice_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch(
                    "routers.v1.upsert_user_practice_progress", new_callable=AsyncMock
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE_PROGRESS,
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.patch(
                        "/api/v1/users/me/practices/1",
                        json={"attempts": 1, "best_score": 8.0, "status": "MASTERED"},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["status"] == "MASTERED"

    def test_update_practice_progress_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.v1.get_practice", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.patch(
                        "/api/v1/users/me/practices/999",
                        json={"attempts": 1, "best_score": 5.0, "status": "ATTEMPTED"},
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_update_quiz_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.v1.upsert_user_quiz_progress", new_callable=AsyncMock),
                patch(
                    "routers.v1.get_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ_PROGRESS,
                ),
                patch("routers.v1.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.patch(
                        "/api/v1/users/me/quizzes/1",
                        json={"score": 90.0},
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["score"] == 85.0

    def test_update_quiz_progress_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.v1.get_quiz", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.patch(
                        "/api/v1/users/me/quizzes/999",
                        json={"score": 100.0},
                    )
                    return resp.status_code

        assert asyncio.run(_run()) == 404


# ═══════════════════════════════════════════════════════════════════════════
# 7. User Lesson/Practice/Quiz Progress CRUD (learning router)
# ═══════════════════════════════════════════════════════════════════════════


class TestUserProgressCRUD:
    """Test user progress endpoints on the learning router."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_get_lesson_progress(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.learning.get_user_lesson_progress",
                new_callable=AsyncMock,
                return_value=MOCK_LESSON_PROGRESS,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/users/1/lessons/1/progress")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["status"] == "COMPLETED"

    def test_get_lesson_progress_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_user_lesson_progress",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/users/1/lessons/999/progress")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_upsert_lesson_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.learning.upsert_user_lesson_progress",
                    new_callable=AsyncMock,
                ),
                patch(
                    "routers.learning.get_user_lesson_progress",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON_PROGRESS,
                ),
                patch(
                    "routers.learning.get_lesson",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON,
                ),
                patch(
                    "routers.learning.get_section",
                    new_callable=AsyncMock,
                    return_value=MOCK_SECTION,
                ),
                patch("routers.learning.invalidate_study_page_cache"),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.put(
                        "/api/users/1/lessons/1/progress",
                        json={
                            "status": "COMPLETED",
                            "completed_at": "2026-01-15T10:00:00",
                        },
                    )
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["status"] == "COMPLETED"

    def test_get_practice_progress(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.learning.get_user_practice_progress",
                new_callable=AsyncMock,
                return_value=MOCK_PRACTICE_PROGRESS,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/users/1/practices/1/progress")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["best_score"] == 9.0

    def test_get_practice_progress_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_user_practice_progress",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/users/1/practices/999/progress")
                    return resp.status_code

        assert asyncio.run(_run()) == 404

    def test_get_quiz_progress(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.learning.get_user_quiz_progress",
                new_callable=AsyncMock,
                return_value=MOCK_QUIZ_PROGRESS,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/users/1/quizzes/1/progress")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["score"] == 85.0

    def test_get_quiz_progress_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.learning.get_user_quiz_progress",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/users/1/quizzes/999/progress")
                    return resp.status_code

        assert asyncio.run(_run()) == 404


# ═══════════════════════════════════════════════════════════════════════════
# 8. V1 Get Lesson / Practice / Quiz with Progress
# ═══════════════════════════════════════════════════════════════════════════


class TestV1GetEntitiesWithProgress:
    """Test V1 GET endpoints that merge entity data with user progress."""

    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_get_lesson_with_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_lesson",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON,
                ),
                patch(
                    "routers.v1.get_user_lesson_progress",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON_PROGRESS,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/lessons/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["status"] == "mastered"
        assert data["completed_at"] == "2026-01-15T10:00:00"

    def test_get_lesson_no_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_lesson",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON,
                ),
                patch(
                    "routers.v1.get_user_lesson_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/lessons/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["status"] == "not_started"

    def test_get_practice_with_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE_PROGRESS,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/practices/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["attempts"] == 3
        assert data["best_score"] == 9.0

    def test_get_quiz_with_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ_PROGRESS,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/quizzes/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["score"] == 85.0

    def test_get_quiz_no_progress(self) -> None:
        async def _run() -> tuple:
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/quizzes/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["score"] is None


# ═══════════════════════════════════════════════════════════════════════════
# 9. V1 Courses
# ═══════════════════════════════════════════════════════════════════════════


class TestV1Courses:
    def setup_method(self) -> None:
        _mock_deps({"id": 1, "email": "test@test.com", "name": "T"})

    def teardown_method(self) -> None:
        _clear_deps()

    def test_list_courses(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.v1.list_courses",
                new_callable=AsyncMock,
                return_value=[MOCK_COURSE],
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/courses")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert len(data) == 1

    def test_get_course(self) -> None:
        async def _run() -> tuple:
            with patch(
                "routers.v1.get_course",
                new_callable=AsyncMock,
                return_value=MOCK_COURSE,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/courses/1")
                    return resp.status_code, resp.json()

        status, data = asyncio.run(_run())
        assert status == 200
        assert data["title"] == "ML Course"

    def test_get_course_not_found(self) -> None:
        async def _run() -> int:
            with patch(
                "routers.v1.get_course", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.get("/api/v1/courses/999")
                    return resp.status_code

        assert asyncio.run(_run()) == 404
