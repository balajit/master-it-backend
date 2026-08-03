"""Tests for the V1 API versioned endpoints."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
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

MOCK_SECTION: dict[str, Any] = {
    "id": 1,
    "unit_id": 1,
    "title": "Section A",
    "estimated_minutes": 30,
    "display_order": 0,
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


class TestV1Courses:
    def test_list_courses(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.list_courses",
                new_callable=AsyncMock,
                return_value=[MOCK_COURSE],
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/courses")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "ML Course"

    def test_list_courses_empty(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.list_courses",
                new_callable=AsyncMock,
                return_value=[],
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/courses")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_course(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_course",
                new_callable=AsyncMock,
                return_value=MOCK_COURSE,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/courses/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert resp.json()["title"] == "ML Course"

    def test_get_course_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_course",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/courses/999")

        resp = asyncio.run(_run())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Course not found"

    def test_enroll_passes_source_document_id(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.v1.get_course",
                    new_callable=AsyncMock,
                    return_value=MOCK_COURSE,
                ),
                patch(
                    "routers.v1.provision_enrollment",
                    new_callable=AsyncMock,
                    return_value={
                        "course_id": 1,
                        "user_id": 1,
                        "enrolled_at": "2026-01-01T00:00:00Z",
                        "status": "enrolled",
                        "lessons_initialized": 3,
                        "practices_initialized": 2,
                        "quizzes_initialized": 1,
                    },
                ) as mock_provision,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post(
                        "/api/v1/courses/1/enroll",
                        json={"source_document_id": "122e720903b24930af4f8485c8f8f25b"},
                    )
                assert resp.status_code == 200
                mock_provision.assert_awaited_once_with(
                    user_id=1,
                    course_id=1,
                    source_document_id="122e720903b24930af4f8485c8f8f25b",
                )
                return resp

        resp = asyncio.run(_run())
        body = resp.json()
        assert body["status"] == "enrolled"
        assert body["lessons_initialized"] == 3

    def test_enroll_propagates_strict_provisioning_errors(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.v1.get_course",
                    new_callable=AsyncMock,
                    return_value=MOCK_COURSE,
                ),
                patch(
                    "routers.v1.provision_enrollment",
                    new_callable=AsyncMock,
                    side_effect=HTTPException(
                        status_code=409,
                        detail="Study plan is not ready for the provided source document.",
                    ),
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/courses/1/enroll",
                        json={"source_document_id": "abc123"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 409
        assert "Study plan is not ready" in resp.json()["detail"]


class TestV1Units:
    def test_get_unit(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_unit_details",
                new_callable=AsyncMock,
                return_value=MOCK_UNIT_RESPONSE,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/units/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert resp.json()["title"] == "Unit 1"

    def test_get_unit_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_unit_details",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/units/999")

        resp = asyncio.run(_run())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Unit not found"


class TestV1Lessons:
    def test_get_lesson(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.get("/api/v1/lessons/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Lesson 1"
        assert data["status"] == "not_started"

    def test_get_lesson_with_progress(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.v1.get_lesson",
                    new_callable=AsyncMock,
                    return_value=MOCK_LESSON,
                ),
                patch(
                    "routers.v1.get_user_lesson_progress",
                    new_callable=AsyncMock,
                    return_value={
                        "user_id": 1,
                        "lesson_id": 1,
                        "status": "COMPLETED",
                        "completed_at": "2026-01-15T10:00:00",
                    },
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/lessons/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "mastered"
        assert data["completed_at"] == "2026-01-15T10:00:00"

    def test_get_lesson_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_lesson",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/lessons/999")

        resp = asyncio.run(_run())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Lesson not found"


class TestV1Practices:
    def test_get_practice(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.v1.get_practice",
                    new_callable=AsyncMock,
                    return_value=MOCK_PRACTICE,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/practices/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Practice 1"
        assert data["status"] == "not_started"

    def test_get_practice_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_practice",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/practices/999")

        resp = asyncio.run(_run())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Practice not found"

    def test_submit_practice(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    "routers.v1.upsert_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/practices/1/submit",
                        json={"answers": [1, 2, 3], "score": 9.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["practice_id"] == 1
        assert data["score"] == 9.0
        assert data["passed"] is True
        assert data["attempts"] == 1
        assert data["best_score"] == 9.0
        assert data["status"] == "mastered"

    def test_submit_practice_not_mastered(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    "routers.v1.upsert_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/practices/1/submit",
                        json={"answers": [1], "score": 5.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert data["status"] == "attempted"

    def test_submit_practice_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_practice",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/practices/999/submit",
                        json={"score": 10.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_submit_practice_increments_attempts(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    "routers.v1.upsert_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/practices/1/submit",
                        json={"score": 6.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["attempts"] == 3
        assert data["best_score"] == 7.0


class TestV1Quizzes:
    def test_get_quiz(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    return await c.get("/api/v1/quizzes/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Quiz 1"
        assert data["score"] is None

    def test_get_quiz_with_score(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.v1.get_quiz",
                    new_callable=AsyncMock,
                    return_value=MOCK_QUIZ,
                ),
                patch(
                    "routers.v1.get_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value={
                        "user_id": 1,
                        "quiz_id": 1,
                        "score": 85.0,
                        "completed_at": "2026-01-15T10:00:00",
                    },
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/quizzes/1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 85.0
        assert data["completed_at"] == "2026-01-15T10:00:00"

    def test_get_quiz_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_quiz",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/quizzes/999")

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_submit_quiz(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.v1.upsert_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/quizzes/1/submit",
                        json={"answers": [1, 2, 3], "score": 85.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["quiz_id"] == 1
        assert data["score"] == 85.0
        assert data["passed"] is True
        assert "completed_at" in data

    def test_submit_quiz_failed(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.v1.upsert_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/quizzes/1/submit",
                        json={"score": 50.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False

    def test_submit_quiz_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_quiz",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/quizzes/999/submit",
                        json={"score": 100.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 404


class TestV1UserProgress:
    def test_get_user_progress(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_all_user_progress",
                new_callable=AsyncMock,
                return_value={
                    "lessons": [
                        {
                            "user_id": 1,
                            "lesson_id": 1,
                            "status": "COMPLETED",
                            "completed_at": "2026-01-15T10:00:00",
                        }
                    ],
                    "practices": [],
                    "quizzes": [],
                },
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/users/me/progress")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == 1
        assert len(data["lessons"]) == 1
        assert data["lessons"][0]["lesson_id"] == 1
        assert len(data["practices"]) == 0
        assert len(data["quizzes"]) == 0

    def test_get_user_progress_empty(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_all_user_progress",
                new_callable=AsyncMock,
                return_value={"lessons": [], "practices": [], "quizzes": []},
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/users/me/progress")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["lessons"] == []
        assert data["practices"] == []
        assert data["quizzes"] == []


class TestV1UserProgressUpdate:
    def test_update_lesson_progress(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.v1.upsert_user_lesson_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.get_user_lesson_progress",
                    new_callable=AsyncMock,
                    return_value={
                        "user_id": 1,
                        "lesson_id": 1,
                        "status": "COMPLETED",
                        "completed_at": "2026-01-15T10:00:00",
                    },
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.patch(
                        "/api/v1/users/me/lessons/1",
                        json={
                            "status": "COMPLETED",
                            "completed_at": "2026-01-15T10:00:00",
                        },
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert (
            data["status"] == "COMPLETED"
        )  # passthrough from mock, not a ProgressStatus enum

    def test_update_lesson_progress_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_lesson",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.patch(
                        "/api/v1/users/me/lessons/999",
                        json={"status": "IN_PROGRESS"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_update_practice_progress(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                    "routers.v1.upsert_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.get_user_practice_progress",
                    new_callable=AsyncMock,
                    return_value={
                        "user_id": 1,
                        "practice_id": 1,
                        "attempts": 1,
                        "best_score": 8.0,
                        "status": "mastered",
                    },
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.patch(
                        "/api/v1/users/me/practices/1",
                        json={
                            "attempts": 1,
                            "best_score": 8.0,
                            "status": "MASTERED",
                        },
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "mastered"
        assert data["best_score"] == 8.0

    def test_update_practice_progress_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_practice",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.patch(
                        "/api/v1/users/me/practices/999",
                        json={"attempts": 1, "best_score": 5.0, "status": "ATTEMPTED"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_update_quiz_progress(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
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
                patch(
                    "routers.v1.upsert_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value=None,
                ),
                patch(
                    "routers.v1.get_user_quiz_progress",
                    new_callable=AsyncMock,
                    return_value={
                        "user_id": 1,
                        "quiz_id": 1,
                        "score": 90.0,
                        "completed_at": "2026-01-15T10:00:00",
                    },
                ),
                patch(
                    "routers.v1.invalidate_study_page_cache",
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.patch(
                        "/api/v1/users/me/quizzes/1",
                        json={"score": 90.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 90.0

    def test_update_quiz_progress_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.v1.get_quiz",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.patch(
                        "/api/v1/users/me/quizzes/999",
                        json={"score": 100.0},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 404


class TestV1Auth:
    def test_unauthenticated_returns_403(self, app, mock_user):
        app.dependency_overrides.clear()

        async def _run():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                return await c.get("/api/v1/courses")

        resp = asyncio.run(_run())
        assert resp.status_code in (401, 403)


class TestV1Triage:
    def test_post_diagnosis(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.triage.run_diagnosis",
                new_callable=AsyncMock,
                return_value={
                    "diagnosis_id": 11,
                    "document_id": "doc-1",
                    "status": "completed",
                    "verdict": "warn",
                    "report_id": "report-1",
                    "created_at": "2026-08-02T00:00:00Z",
                    "completed_at": "2026-08-02T00:01:00Z",
                    "summary": {"stats": {"finding_count": 1}},
                    "missing_entry_tables": [],
                    "findings": [],
                },
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/triage/diagnoses",
                        json={"document_id": "doc-1"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["diagnosis_id"] == 11
        assert body["verdict"] == "warn"

    def test_get_diagnosis_not_found(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with patch(
                "routers.triage.get_diagnosis_view",
                new_callable=AsyncMock,
                return_value=None,
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/triage/diagnoses/999")

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_get_diagnosis_findings(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.triage.get_diagnosis_view",
                    new_callable=AsyncMock,
                    return_value={
                        "diagnosis_id": 12,
                        "document_id": "doc-2",
                        "status": "completed",
                        "verdict": "pass",
                        "report_id": "report-2",
                        "created_at": "2026-08-02T00:00:00Z",
                        "completed_at": "2026-08-02T00:00:30Z",
                        "summary": {},
                        "missing_entry_tables": [],
                        "findings": [],
                    },
                ),
                patch(
                    "routers.triage.get_diagnosis_findings_view",
                    new_callable=AsyncMock,
                    return_value=[
                        {
                            "id": 1,
                            "diagnosis_id": 12,
                            "rule_id": "table.documents.non_empty",
                            "severity": "warning",
                            "table_name": "documents",
                            "message": "documents low count",
                            "affected_count": 2,
                            "sample": {"rows": ["a", "b"]},
                        }
                    ],
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.get("/api/v1/triage/diagnoses/12/findings")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["table_name"] == "documents"

    def test_post_diagnosis_requires_document_id(self, app, mock_user):
        _mock_deps(app, mock_user)

        async def _run():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                return await c.post(
                    "/api/v1/triage/diagnoses",
                    json={"document_id": ""},
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 422

    def test_post_delete_document_process_runs_prepare(self, app, mock_user):
        _mock_deps(app, mock_user)
        mock_user["permissions"] = ["course:manage"]

        async def _run():
            with (
                patch(
                    "routers.triage.get_diagnosis_view",
                    new_callable=AsyncMock,
                    return_value={
                        "diagnosis_id": 12,
                        "document_id": "doc-2",
                        "status": "completed",
                        "verdict": "pass",
                        "report_id": "report-2",
                        "created_at": "2026-08-02T00:00:00Z",
                        "completed_at": "2026-08-02T00:00:30Z",
                        "summary": {},
                        "missing_entry_tables": [],
                        "findings": [],
                    },
                ),
                patch(
                    "routers.triage.delete_document_process_runs",
                    new_callable=AsyncMock,
                    return_value={
                        "diagnosis_id": 12,
                        "status": "confirmation_required",
                        "action_id": "a1",
                        "action_type": "delete_document_process_runs",
                        "precheck_passed": True,
                        "preview": {
                            "requested_ids": [11, 12],
                            "target_process_ids": [11],
                            "missing_process_ids": [12],
                            "affected_row_count": 3,
                            "affected_file_count": 1,
                            "integrity_hash": "abc123",
                        },
                        "expires_at": None,
                        "message": "Preparation complete. Submit confirm=true to execute delete.",
                    },
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/triage/diagnoses/12/actions/delete-document-process-runs",
                        json={
                            "process_ids": [11, 12],
                            "reason": "cleanup",
                            "confirm": False,
                        },
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "confirmation_required"
        assert body["action_id"] == "a1"

    def test_post_delete_document_process_runs_execute(self, app, mock_user):
        _mock_deps(app, mock_user)
        mock_user["permissions"] = ["course:manage"]

        async def _run():
            with (
                patch(
                    "routers.triage.get_diagnosis_view",
                    new_callable=AsyncMock,
                    return_value={
                        "diagnosis_id": 12,
                        "document_id": "doc-2",
                        "status": "completed",
                        "verdict": "pass",
                        "report_id": "report-2",
                        "created_at": "2026-08-02T00:00:00Z",
                        "completed_at": "2026-08-02T00:00:30Z",
                        "summary": {},
                        "missing_entry_tables": [],
                        "findings": [],
                    },
                ),
                patch(
                    "routers.triage.delete_document_process_runs",
                    new_callable=AsyncMock,
                    return_value={
                        "diagnosis_id": 12,
                        "status": "applied",
                        "action_id": "a1",
                        "action_type": "delete_document_process_runs",
                        "deleted_process_ids": [11],
                        "missing_process_ids": [12],
                        "deleted_pipeline_log_count": 2,
                        "affected_row_count": 3,
                        "affected_file_count": 1,
                        "applied_at": None,
                    },
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/triage/diagnoses/12/actions/delete-document-process-runs",
                        json={
                            "reason": "cleanup",
                            "confirm": True,
                            "action_id": "a1",
                        },
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "applied"
        assert body["deleted_process_ids"] == [11]

    def test_cancel_delete_action(self, app, mock_user):
        _mock_deps(app, mock_user)
        mock_user["permissions"] = ["course:manage"]

        async def _run():
            with (
                patch(
                    "routers.triage.get_diagnosis_view",
                    new_callable=AsyncMock,
                    return_value={
                        "diagnosis_id": 12,
                        "document_id": "doc-2",
                        "status": "completed",
                        "verdict": "pass",
                        "report_id": "report-2",
                        "created_at": "2026-08-02T00:00:00Z",
                        "completed_at": "2026-08-02T00:00:30Z",
                        "summary": {},
                        "missing_entry_tables": [],
                        "findings": [],
                    },
                ),
                patch(
                    "routers.triage.cancel_delete_action",
                    new_callable=AsyncMock,
                    return_value={
                        "diagnosis_id": 12,
                        "status": "canceled",
                        "action_id": "a1",
                        "action_type": "delete_document_process_runs",
                        "canceled_at": None,
                    },
                ),
            ):
                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    return await c.post(
                        "/api/v1/triage/diagnoses/12/actions/a1/cancel",
                        json={"reason": "cancel"},
                    )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "canceled"
