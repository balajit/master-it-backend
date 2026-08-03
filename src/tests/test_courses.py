"""Tests for course endpoints including the study plan API."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

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
            with patch(
                "routers.courses.get_course", new_callable=AsyncMock, return_value=None
            ):
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
        assert data["documents"] == []
        assert data["chapters"] == []

    def test_study_plan_course_with_documents_no_book_returns_empty_chapters(
        self, app, mock_user
    ):
        """Documents without assembled books are skipped from response."""
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
                    "routers.courses._fetch_book_chapters", new_callable=AsyncMock
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
                        "storage_path": "/tmp/a.pdf",
                        "content_type": "",
                        "size_bytes": 0,
                        "created_at": "",
                    },
                    {
                        "id": "doc-2",
                        "filename": "b.pdf",
                        "storage_path": "/tmp/b.pdf",
                        "content_type": "",
                        "size_bytes": 0,
                        "created_at": "",
                    },
                ]
                # _fetch_book_chapters returns [] when no book exists
                mock_fetch.return_value = []

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/courses/2/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == 2
        assert data["course_title"] == "Physics"
        assert len(data["documents"]) == 2
        assert data["documents"][0]["document_id"] == "doc-1"
        assert data["documents"][0]["document_name"] == "a.pdf"
        assert data["documents"][0]["chapters"] == []
        assert data["documents"][1]["document_id"] == "doc-2"
        assert data["documents"][1]["document_name"] == "b.pdf"
        assert data["documents"][1]["chapters"] == []
        assert data["chapters"] == []

    def test_study_plan_course_with_chapters(self, app, mock_user):
        """Documents processed into chapters — verify chapter structure is returned."""
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
                    "routers.courses._fetch_book_chapters", new_callable=AsyncMock
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
                        "storage_path": "/tmp/notes.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 1024,
                        "created_at": "2026-01-01T00:00:00",
                    }
                ]

                from schemas import Chapter, Lesson, Page

                with patch(
                    "routers.courses.lp_doc_uuid_from_storage_path",
                    return_value=UUID("7f3cf7e4-1126-f240-09dc-afb0fd3eafed"),
                ):
                    chapter = Chapter(
                        id="ch-001",
                        title="Chapter 1: Intro",
                        order=0,
                        unit_id=10,
                        lessons=[
                            Lesson(
                                id="l-001",
                                title="What is ML?",
                                order=0,
                                lesson_id=42,
                                unit_id=10,
                                pages=[
                                    Page(id="p-001", page_number=1, order=0, items=[])
                                ],
                            )
                        ],
                    )
                    mock_fetch.return_value = [chapter]

                    async with httpx.AsyncClient(
                        transport=ASGITransport(app=app), base_url="http://test"
                    ) as client:
                        return await client.get("/api/courses/1/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert data["course_id"] == 1
        assert data["course_title"] == "ML Course"
        assert len(data["documents"]) == 1
        assert data["documents"][0]["document_id"] == "doc-abc"
        assert data["documents"][0]["document_name"] == "notes.pdf"
        assert len(data["documents"][0]["chapters"]) == 1
        assert len(data["chapters"]) == 1
        ch = data["chapters"][0]
        assert ch["id"] == "ch-001"
        assert ch["title"] == "Chapter 1: Intro"
        assert ch["unit_id"] == 10
        assert len(ch["lessons"]) == 1
        lesson = ch["lessons"][0]
        assert lesson["id"] == "l-001"
        assert lesson["lesson_id"] == 42
        assert len(lesson["pages"]) == 1

    def test_study_plan_uses_course_scoped_plan_lesson_mapping(self, app, mock_user):
        self._mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.courses.get_course", new_callable=AsyncMock
                ) as mock_get_course,
                patch(
                    "routers.courses.get_documents_by_course", new_callable=AsyncMock
                ) as mock_get_docs,
                patch("routers.courses.lp_doc_uuid_from_storage_path") as mock_lp_uuid,
                patch(
                    "routers.courses.get_lessons_by_plan_ids_for_course",
                    new_callable=AsyncMock,
                ) as mock_get_by_course,
                patch(
                    "routers.courses.get_sections_by_ids", new_callable=AsyncMock
                ) as mock_sections,
                patch(
                    "learning_platform.infrastructure.persistence.repositories.book.BookRepository.find_by_document",
                    new_callable=AsyncMock,
                ) as mock_find_book,
            ):
                mock_get_course.return_value = {
                    "id": 9,
                    "title": "Scoped Course",
                    "description": "",
                    "number_of_credits": 3,
                    "difficulty": "beginner",
                    "status": "OPEN",
                    "owner_id": 1,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
                mock_get_docs.return_value = [
                    {
                        "id": "doc-scope",
                        "filename": "scope.pdf",
                        "storage_path": "/tmp/scope.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 1024,
                        "created_at": "2026-01-01T00:00:00",
                    }
                ]
                mock_lp_uuid.return_value = UUID("7f3cf7e4-1126-f240-09dc-afb0fd3eafed")

                from learning_platform.models.book import (
                    BookChapter,
                    BookLesson,
                    CanonicalBook,
                )

                lp_lesson_uuid = UUID("11111111-2222-3333-4444-555555555555")
                book = CanonicalBook(
                    document_id=UUID("7f3cf7e4-1126-f240-09dc-afb0fd3eafed"),
                    chapters=[
                        BookChapter(
                            title="Scoped Chapter",
                            lessons=[
                                BookLesson(
                                    title="Scoped Lesson", unit_id=lp_lesson_uuid
                                )
                            ],
                        )
                    ],
                )
                mock_find_book.return_value = book

                mock_get_by_course.return_value = [
                    {"id": 123, "plan_lesson_id": str(lp_lesson_uuid), "section_id": 77}
                ]
                mock_sections.return_value = [{"id": 77, "unit_id": 5}]

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get(
                        "/api/courses/9/study-plan"
                    ), mock_get_by_course

        resp, mock_get_by_course = asyncio.run(_run())
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["chapters"][0]["lessons"][0]["lesson_id"] == 123
        mock_get_by_course.assert_awaited_once()
        assert len(mock_get_by_course.await_args_list) == 1
        assert mock_get_by_course.await_args_list[0].args[0] == 9

    def test_study_plan_incomplete_documents_are_skipped(self, app, mock_user):
        self._mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.courses.get_course", new_callable=AsyncMock
                ) as mock_get_course,
                patch(
                    "routers.courses.get_documents_by_course", new_callable=AsyncMock
                ) as mock_get_docs,
                patch("routers.courses.lp_doc_uuid_from_storage_path") as mock_lp_uuid,
                patch(
                    "routers.courses._fetch_book_chapters", new_callable=AsyncMock
                ) as mock_fetch,
            ):
                mock_get_course.return_value = {
                    "id": 2,
                    "title": "Chemistry",
                    "description": "",
                    "number_of_credits": 4,
                    "difficulty": "intermediate",
                    "status": "OPEN",
                    "owner_id": 1,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
                mock_get_docs.return_value = [
                    {
                        "id": "doc-1",
                        "filename": "chem.pdf",
                        "storage_path": "/tmp/chem.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 1024,
                        "created_at": "2026-01-01T00:00:00",
                    }
                ]
                mock_lp_uuid.return_value = UUID("7f3cf7e4-1126-f240-09dc-afb0fd3eafed")
                mock_fetch.return_value = []

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/courses/2/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["course_id"] == 2
        assert body["course_title"] == "Chemistry"
        assert len(body["documents"]) == 1
        assert body["documents"][0]["document_id"] == "doc-1"
        assert body["documents"][0]["document_name"] == "chem.pdf"
        assert body["documents"][0]["chapters"] == []
        assert body["chapters"] == []

    def test_study_plan_mixed_docs_returns_available_chapters(self, app, mock_user):
        self._mock_deps(app, mock_user)

        async def _run():
            with (
                patch(
                    "routers.courses.get_course", new_callable=AsyncMock
                ) as mock_get_course,
                patch(
                    "routers.courses.get_documents_by_course", new_callable=AsyncMock
                ) as mock_get_docs,
                patch("routers.courses.lp_doc_uuid_from_storage_path") as mock_lp_uuid,
                patch(
                    "routers.courses._fetch_book_chapters", new_callable=AsyncMock
                ) as mock_fetch,
            ):
                mock_get_course.return_value = {
                    "id": 4,
                    "title": "Biology",
                    "description": "",
                    "number_of_credits": 4,
                    "difficulty": "intermediate",
                    "status": "OPEN",
                    "owner_id": 1,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                }
                mock_get_docs.return_value = [
                    {
                        "id": "doc-1",
                        "filename": "bio-main.pdf",
                        "storage_path": "/tmp/bio-main.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 1024,
                        "created_at": "2026-01-01T00:00:00",
                    },
                    {
                        "id": "doc-2",
                        "filename": "bio-handout.docx",
                        "storage_path": "/tmp/bio-handout.docx",
                        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "size_bytes": 2048,
                        "created_at": "2026-01-02T00:00:00",
                    },
                ]
                mock_lp_uuid.side_effect = [UUID(int=1), UUID(int=2)]

                from schemas import Chapter

                mock_fetch.side_effect = [
                    [Chapter(id="ch-1", title="Cell Biology", order=0, lessons=[])],
                    [],
                ]

                async with httpx.AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.get("/api/courses/4/study-plan")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["course_id"] == 4
        assert body["course_title"] == "Biology"
        assert len(body["documents"]) == 2
        assert body["documents"][0]["document_id"] == "doc-1"
        assert body["documents"][0]["document_name"] == "bio-main.pdf"
        assert len(body["documents"][0]["chapters"]) == 1
        assert body["documents"][1]["document_id"] == "doc-2"
        assert body["documents"][1]["document_name"] == "bio-handout.docx"
        assert body["documents"][1]["chapters"] == []
        assert len(body["chapters"]) == 1
        assert body["chapters"][0]["title"] == "Cell Biology"

    def test_form_area_item_schema_accepts_display_hint(self) -> None:
        from schemas import FormAreaItem

        item = FormAreaItem(
            id="item-1",
            items=["bank", "words"],
            metadata={"display_hint": "word_bank", "semantic_node_type": "form_area"},
        )

        payload = item.model_dump(mode="json")
        assert payload["type"] == "form_area"
        assert payload["items"] == ["bank", "words"]
        assert payload["metadata"]["display_hint"] == "word_bank"

    def test_content_item_union_accepts_form_area(self) -> None:
        from schemas import ContentItem
        from pydantic import TypeAdapter

        adapter = TypeAdapter(ContentItem)
        parsed = adapter.validate_python(
            {
                "type": "form_area",
                "id": "item-2",
                "order": 1,
                "items": ["A", "B", "C"],
                "metadata": {"display_hint": "answer_box"},
            }
        )

        assert parsed.type == "form_area"
        assert parsed.items == ["A", "B", "C"]
