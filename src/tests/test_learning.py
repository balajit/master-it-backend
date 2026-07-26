"""Tests for the Learning domain API endpoints."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)


@pytest.fixture()
def app():
    from main import app as _app

    return _app


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


def _mock_deps(app, mock_user):
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: mock_user


MOCK_COURSE = {
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

MOCK_UNIT = {
    "id": 1,
    "course_id": 1,
    "title": "Unit 1",
    "description": "Intro",
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_SECTION = {
    "id": 1,
    "unit_id": 1,
    "title": "Section 1",
    "estimated_minutes": 30,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_LESSON = {
    "id": 1,
    "section_id": 1,
    "title": "Lesson 1",
    "description": "Content here",
    "duration_minutes": 15,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_PRACTICE = {
    "id": 1,
    "section_id": 1,
    "title": "Practice 1",
    "required_correct": 8,
    "total_questions": 10,
    "display_order": 0,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}

MOCK_QUIZ = {
    "id": 1,
    "section_id": 1,
    "title": "Quiz 1",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}


class TestUnits:
    def test_create_unit(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.post(
                        "/api/courses/1/units",
                        json={"title": "Unit 1", "description": "Intro"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 201
        assert resp.json()["title"] == "Unit 1"

    def test_create_unit_course_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.learning.get_course", new_callable=AsyncMock, return_value=None
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post("/api/courses/999/units", json={"title": "X"})

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_list_units(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.get("/api/courses/1/units")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_unit_with_sections(self, app, mock_user):
        _mock_deps(app, mock_user)

        from schemas import UnitCrudResponse

        mock_result = UnitCrudResponse(
            id=1,
            course_id=1,
            title="Unit 1",
            description="Intro",
            display_order=0,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )

        async def _run():
            with patch(
                "routers.learning.get_unit",
                new_callable=AsyncMock,
                return_value=mock_result.model_dump(),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/units/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Unit 1"
        assert data["description"] == "Intro"

    def test_update_unit(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.put("/api/units/1", json={"title": "Updated"})

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    def test_delete_unit(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.learning.delete_unit",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch(
                    "routers.learning.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.delete("/api/units/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 204


class TestSections:
    def test_create_section(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.post(
                        "/api/units/1/sections", json={"title": "Section 1"}
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 201

    def test_list_sections(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.get("/api/units/1/sections")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get_section_with_children(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.get("/api/sections/1")

        resp = asyncio.run(_run())
        data = resp.json()
        assert len(data["lessons"]) == 1
        assert len(data["practices"]) == 1
        assert len(data["quizzes"]) == 1

    def test_delete_section(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.learning.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.delete("/api/sections/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 204


class TestLessons:
    def test_create_lesson(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/sections/1/lessons",
                        json={"title": "Lesson 1", "description": "Content"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 201

    def test_get_lesson(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.learning.get_lesson",
                new_callable=AsyncMock,
                return_value=MOCK_LESSON,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/lessons/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert resp.json()["title"] == "Lesson 1"

    def test_delete_lesson(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.learning.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.delete("/api/lessons/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 204


class TestPractices:
    def test_create_practice(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.post(
                        "/api/sections/1/practices",
                        json={"title": "Practice 1"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 201

    def test_delete_practice(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.learning.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.delete("/api/practices/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 204


class TestQuizzes:
    def test_create_quiz(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.post(
                        "/api/sections/1/quizzes", json={"title": "Quiz 1"}
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 201

    def test_get_quiz(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.learning.get_quiz",
                new_callable=AsyncMock,
                return_value=MOCK_QUIZ,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/quizzes/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert resp.json()["title"] == "Quiz 1"

    def test_delete_quiz(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.learning.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.delete("/api/quizzes/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 204
