"""Tests for course endpoints including the study plan API."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport

# Ensure src/ is on sys.path
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


class TestCourseStudyPlan:
    """Tests for GET /api/courses/{course_id}/study-plan."""

    def _mock_deps(self, app, mock_user):
        """Override auth dependency to return a fake user."""
        from auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: mock_user

    def test_study_plan_course_not_found(self, app, mock_user):
        self._mock_deps(app, mock_user)

        async def _run():
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.get("/api/courses/999/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Course not found"

    def test_study_plan_course_with_no_documents(self, app, mock_user):
        self._mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.courses.get_course", new_callable=AsyncMock
                ) as mock_get_course,
                patch(
                    "routers.courses.get_documents_by_course", new_callable=AsyncMock
                ) as mock_get_docs,
            ):
                mock_get_course.return_value = {
                    "id": 1,
                    "title": "Test Course",
                    "description": "A test course",
                    "number_of_credits": 3,
                    "difficulty": "beginner",
                    "status": "OPEN",
                    "owner_id": 1,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
                mock_get_docs.return_value = []

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/courses/1/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == 1
        assert data["course_title"] == "Test Course"
        assert data["documents_processed"] == 0
        assert data["study_plans"] == []

    def test_study_plan_course_with_documents(self, app, mock_user):
        self._mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.courses.get_course", new_callable=AsyncMock
                ) as mock_get_course,
                patch(
                    "routers.courses.get_documents_by_course", new_callable=AsyncMock
                ) as mock_get_docs,
                patch(
                    "routers.courses._fetch_study_plan", new_callable=AsyncMock
                ) as mock_fetch,
            ):
                mock_get_course.return_value = {
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
                mock_get_docs.return_value = [
                    {
                        "id": "doc-abc",
                        "filename": "notes.pdf",
                        "storage_path": "/tmp/doc-abc/notes.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 1024,
                        "created_at": "2026-01-01T00:00:00",
                    },
                    {
                        "id": "doc-def",
                        "filename": "slides.pdf",
                        "storage_path": "/tmp/doc-def/slides.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 2048,
                        "created_at": "2026-01-02T00:00:00",
                    },
                ]

                from schemas import (
                    StudyPlanCheckpoint,
                    StudyPlanDetail,
                    StudyPlanLesson,
                    StudyPlanMilestone,
                )

                plan1 = StudyPlanDetail(
                    doc_id="doc-abc",
                    title="ML Notes Study Plan",
                    description="Study plan for ML notes",
                    total_estimated_minutes=120,
                    total_lessons=5,
                    lessons=[
                        StudyPlanLesson(
                            id="l-001",
                            unit_id="u-001",
                            order=0,
                            title="Intro to ML",
                            description="What is ML?",
                            lesson_type="introduction",
                            difficulty="basic",
                            estimated_minutes=30,
                        ),
                    ],
                    milestones=[
                        StudyPlanMilestone(
                            id="m-001",
                            order=0,
                            title="Milestone 1",
                            description="Basics",
                            estimated_minutes=60,
                            lesson_count=3,
                        ),
                    ],
                    checkpoints=[
                        StudyPlanCheckpoint(
                            id="cp-001",
                            milestone_id="m-001",
                            order=0,
                            title="Quiz 1",
                            checkpoint_type="quiz",
                            estimated_minutes=15,
                        ),
                    ],
                )
                plan2 = StudyPlanDetail(
                    doc_id="doc-def",
                    title="ML Slides Study Plan",
                    total_estimated_minutes=90,
                    total_lessons=3,
                )
                mock_fetch.side_effect = [plan1, plan2]

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/courses/1/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == 1
        assert data["course_title"] == "ML Course"
        assert data["documents_processed"] == 2
        assert len(data["study_plans"]) == 2

        sp1 = data["study_plans"][0]
        assert sp1["doc_id"] == "doc-abc"
        assert sp1["title"] == "ML Notes Study Plan"
        assert sp1["total_lessons"] == 5
        assert len(sp1["lessons"]) == 1
        assert sp1["lessons"][0]["title"] == "Intro to ML"
        assert len(sp1["milestones"]) == 1
        assert len(sp1["checkpoints"]) == 1

        sp2 = data["study_plans"][1]
        assert sp2["doc_id"] == "doc-def"
        assert sp2["title"] == "ML Slides Study Plan"

    def test_study_plan_skips_docs_without_plans(self, app, mock_user):
        self._mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.courses.get_course", new_callable=AsyncMock
                ) as mock_get_course,
                patch(
                    "routers.courses.get_documents_by_course", new_callable=AsyncMock
                ) as mock_get_docs,
                patch(
                    "routers.courses._fetch_study_plan", new_callable=AsyncMock
                ) as mock_fetch,
            ):
                mock_get_course.return_value = {
                    "id": 2,
                    "title": "Physics",
                    "description": "",
                    "number_of_credits": 3,
                    "difficulty": "advanced",
                    "status": "OPEN",
                    "owner_id": 1,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
                mock_get_docs.return_value = [
                    {
                        "id": "doc-1",
                        "filename": "a.pdf",
                        "storage_path": "",
                        "content_type": "",
                        "size_bytes": 0,
                        "created_at": "",
                    },
                    {
                        "id": "doc-2",
                        "filename": "b.pdf",
                        "storage_path": "",
                        "content_type": "",
                        "size_bytes": 0,
                        "created_at": "",
                    },
                ]
                mock_fetch.side_effect = [None, None]

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/courses/2/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents_processed"] == 0
        assert data["study_plans"] == []


# Needed for the async helper
import asyncio  # noqa: E402
