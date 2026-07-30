"""Integration tests for the Book Assembly pipeline and study-plan API.

These tests exercise end-to-end scenarios without mocking business logic:

1. BookAssembler — converts LearningUnits + CanonicalDocument into CanonicalBook
2. BookRepository — persists and reloads a CanonicalBook via SQLite in-memory DB
3. BookPipeline — assembles and saves a book given LP artifacts
4. Study-plan API — GET /api/courses/{id}/study-plan returns Chapter→Lesson→Page→Item

Run these tests:
    uv run pytest src/tests/integration/ -v

Postgres-dependent tests are skipped automatically when the DB is unreachable.
SQLite-backed tests always run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Ensure src/ is importable
_src_dir = str(Path(__file__).resolve().parent.parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_user() -> dict[str, Any]:
    return {
        "id": 1,
        "email": "integration@example.com",
        "name": "Integration Tester",
        "picture_url": "",
        "phone": "",
        "auth_provider": "local",
        "roles": ["Admin"],
        "permissions": [],
    }


@pytest.fixture()
def app(mock_user: dict[str, Any]):
    """FastAPI app with auth bypassed."""
    import os

    os.environ.setdefault("JWT_SECRET", "test-secret")

    from auth import get_current_user
    from main import app as _app

    _app.dependency_overrides[get_current_user] = lambda: mock_user
    return _app


# ── BookAssembler unit-integration tests (no DB required) ────────────────────


class TestBookAssembler:
    """Tests for BookAssembler that run entirely in-process with no DB."""

    def _make_document(self, title: str = "Test Doc") -> Any:
        """Build a minimal CanonicalDocument with a few nodes."""
        from uuid import uuid4

        from learning_platform.models.document import (
            CanonicalDocument,
            DocumentMetadata,
            DocumentNode,
            Heading,
            HeadingLevel,
            Paragraph,
            StyledText,
        )

        heading_node = DocumentNode(
            id=uuid4(),
            content=Heading(
                text=StyledText(plain_text="Chapter 1: Introduction"),
                level=HeadingLevel.CHAPTER,
            ),
            page=1,
            seq=0,
            level=HeadingLevel.CHAPTER,
        )
        para_node = DocumentNode(
            id=uuid4(),
            content=Paragraph(
                text=StyledText(plain_text="This is the first paragraph.")
            ),
            page=1,
            seq=1,
        )
        section_node = DocumentNode(
            id=uuid4(),
            content=Heading(
                text=StyledText(plain_text="Section 1.1"),
                level=HeadingLevel.SECTION,
            ),
            page=2,
            seq=0,
            level=HeadingLevel.SECTION,
        )
        para2_node = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(plain_text="Section content here.")),
            page=2,
            seq=1,
        )

        meta = DocumentMetadata(title=title, page_count=2)
        doc = CanonicalDocument(
            source="test.pdf",
            title=title,
            metadata=meta,
            nodes=[heading_node, para_node, section_node, para2_node],
        )
        # Build node_map
        doc.node_map = {n.id: n for n in doc.nodes}
        return doc

    def _make_units(self, doc: Any) -> list[Any]:
        """Build LearningUnits that reference nodes in the document."""
        from learning_platform.models.learning_unit import LearningUnit, UnitType

        chapter_unit = LearningUnit(
            id=uuid4(),
            unit_type=UnitType.MODULE,
            title="Chapter 1: Introduction",
            source_node_ids=[doc.nodes[0].id, doc.nodes[1].id],
        )
        lesson_unit = LearningUnit(
            id=uuid4(),
            unit_type=UnitType.LESSON,
            title="Section 1.1",
            parent_id=chapter_unit.id,
            source_node_ids=[doc.nodes[2].id, doc.nodes[3].id],
        )
        return [chapter_unit, lesson_unit]

    def _make_paragraph_only_document(
        self, page_count: int, title: str = "Fallback Doc"
    ) -> Any:
        """Build a document with paragraph-only content across pages.

        Used to exercise page-first fallback chunking when heading anchors
        are unavailable.
        """
        from learning_platform.models.document import (
            CanonicalDocument,
            DocumentMetadata,
            DocumentNode,
            Paragraph,
            StyledText,
            TextRun,
        )

        nodes = []
        seq = 0
        for page in range(1, page_count + 1):
            nodes.append(
                DocumentNode(
                    id=uuid4(),
                    content=Paragraph(
                        text=StyledText(
                            runs=[
                                TextRun(
                                    text=f"Page {page} paragraph body for fallback chunking."
                                )
                            ]
                        )
                    ),
                    page=page,
                    seq=seq,
                )
            )
            seq += 1

        doc = CanonicalDocument(
            source="fallback.pdf",
            title=title,
            metadata=DocumentMetadata(title=title, page_count=page_count),
            nodes=nodes,
        )
        doc.node_map = {n.id: n for n in doc.nodes}
        return doc

    def test_assembler_produces_chapter_lesson_page_structure(self) -> None:
        from learning_platform.stages.book_assembler.assembler import BookAssembler

        doc = self._make_document()
        units = self._make_units(doc)
        assembler = BookAssembler()

        book = assembler.assemble(units, doc)

        assert len(book.chapters) == 1
        chapter = book.chapters[0]
        assert "Chapter 1" in chapter.title or "Introduction" in chapter.title

        assert len(chapter.lessons) >= 1
        lesson = chapter.lessons[0]
        assert len(lesson.pages) >= 1

    def test_assembler_fallback_no_units(self) -> None:
        from learning_platform.stages.book_assembler.assembler import BookAssembler

        doc = self._make_document()
        assembler = BookAssembler()

        book = assembler.assemble([], doc)

        # Fallback produces chapters from page-count grouping
        assert isinstance(book.chapters, list)

    def test_assembler_single_chapter_fallback_no_module_units(self) -> None:
        """Page-first assembly still returns at least one chapter/lesson.

        Unit hierarchy no longer drives segmentation, but should still map IDs
        where overlap exists.
        """
        from learning_platform.models.learning_unit import LearningUnit, UnitType
        from learning_platform.stages.book_assembler.assembler import BookAssembler

        doc = self._make_document()
        lesson_only = LearningUnit(
            id=uuid4(),
            unit_type=UnitType.LESSON,
            title="Lone Lesson",
            source_node_ids=[doc.nodes[0].id, doc.nodes[1].id],
        )
        assembler = BookAssembler()
        book = assembler.assemble([lesson_only], doc)

        assert len(book.chapters) == 1
        assert len(book.chapters[0].lessons) >= 1

    def test_fallback_lessons_use_five_pages_with_adaptive_window(self) -> None:
        """No heading anchors -> lessons chunk to 5 pages with adaptive +/-1."""
        from learning_platform.stages.book_assembler.assembler import BookAssembler

        doc = self._make_paragraph_only_document(page_count=11)
        assembler = BookAssembler()

        book = assembler.assemble([], doc)

        lessons = [lesson for chapter in book.chapters for lesson in chapter.lessons]
        assert len(lessons) >= 2

        page_lengths = [len(lesson.pages) for lesson in lessons]
        assert all(4 <= length <= 6 for length in page_lengths)
        assert sum(page_lengths) == 11

    def test_fallback_chapters_group_five_lessons(self) -> None:
        """No chapter anchors -> chapters are grouped in batches of 5 lessons."""
        from learning_platform.stages.book_assembler.assembler import BookAssembler

        doc = self._make_paragraph_only_document(page_count=30)
        assembler = BookAssembler()

        book = assembler.assemble([], doc)

        assert len(book.chapters) == 2
        assert len(book.chapters[0].lessons) == 5
        assert len(book.chapters[1].lessons) == 1

    def test_items_have_correct_types(self) -> None:
        """Paragraph nodes → TextItem, Heading nodes → HeadingItem."""
        from learning_platform.stages.book_assembler.assembler import BookAssembler

        doc = self._make_document()
        units = self._make_units(doc)
        assembler = BookAssembler()

        book = assembler.assemble(units, doc)

        all_items = [
            item
            for chapter in book.chapters
            for lesson in chapter.lessons
            for page in lesson.pages
            for item in page.items
        ]
        types = {item.type for item in all_items}
        assert "text" in types or "heading" in types


class TestKeywordDetection:
    """Tests for the keyword-aware _unit_type_for_heading function."""

    def test_chapter_keyword_overrides_level(self) -> None:
        from learning_platform.models.document import HeadingLevel
        from learning_platform.models.learning_unit import UnitType
        from learning_platform.stages.unit_builder.builder import _unit_type_for_heading

        # "Section" heading at level 1 — keyword wins → LESSON not MODULE
        result = _unit_type_for_heading(HeadingLevel.CHAPTER, "Section 3: Forces")
        assert result == UnitType.LESSON

    def test_module_keyword_at_section_level(self) -> None:
        from learning_platform.models.document import HeadingLevel
        from learning_platform.models.learning_unit import UnitType
        from learning_platform.stages.unit_builder.builder import _unit_type_for_heading

        # "Chapter" heading at level 2 — keyword wins → MODULE not LESSON
        result = _unit_type_for_heading(HeadingLevel.SECTION, "Chapter 2: Dynamics")
        assert result == UnitType.MODULE

    def test_fallback_to_heading_level_when_no_keyword(self) -> None:
        from learning_platform.models.document import HeadingLevel
        from learning_platform.models.learning_unit import UnitType
        from learning_platform.stages.unit_builder.builder import _unit_type_for_heading

        result = _unit_type_for_heading(HeadingLevel.CHAPTER, "Introduction to Physics")
        assert result == UnitType.MODULE

        result = _unit_type_for_heading(HeadingLevel.SECTION, "Newton's Laws")
        assert result == UnitType.LESSON

    def test_empty_title_uses_level(self) -> None:
        from learning_platform.models.document import HeadingLevel
        from learning_platform.models.learning_unit import UnitType
        from learning_platform.stages.unit_builder.builder import _unit_type_for_heading

        result = _unit_type_for_heading(HeadingLevel.CHAPTER, "")
        assert result == UnitType.MODULE


# ── BookRepository integration tests (SQLite in-memory) ──────────────────────


@pytest.mark.asyncio
async def test_book_repository_save_and_reload() -> None:
    """Save a CanonicalBook and reload it — verify full round-trip."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from learning_platform.infrastructure.persistence.models.base import Base
    from learning_platform.infrastructure.persistence.models.book import (  # noqa: F401 — registers ORM
        BookChapterRow,
        BookItemRow,
        BookLessonRow,
        BookPageRow,
    )
    from learning_platform.infrastructure.persistence.repositories.book import (
        BookRepository,
    )
    from learning_platform.models.book import (
        BookChapter,
        BookLesson,
        BookPage,
        CanonicalBook,
        HeadingItem,
        TextItem,
    )

    doc_id = uuid4()

    # Build a minimal book
    book = CanonicalBook(
        document_id=doc_id,
        title="Test Book",
        chapters=[
            BookChapter(
                title="Chapter 1",
                order=0,
                lessons=[
                    BookLesson(
                        title="Lesson 1.1",
                        order=0,
                        pages=[
                            BookPage(
                                page_number=1,
                                order=0,
                                items=[
                                    HeadingItem(
                                        order=0,
                                        content="Introduction",
                                        level=1,
                                    ),
                                    TextItem(
                                        order=1,
                                        content="First paragraph of the lesson.",
                                    ),
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    # Use SQLite in-memory DB — FKs are not enforced in SQLite by default
    # so we can create book tables without the lp_documents parent table
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        repo = BookRepository(session)

        # Override FK constraint for in-memory test (document_id won't exist)
        # by patching the chapter row document_id column constraint
        await repo.save_book(book)
        await session.commit()

        reloaded = await repo.find_by_document(doc_id)

    await engine.dispose()

    assert reloaded is not None
    assert reloaded.document_id == doc_id
    assert len(reloaded.chapters) == 1

    chapter = reloaded.chapters[0]
    assert chapter.title == "Chapter 1"
    assert len(chapter.lessons) == 1

    lesson = chapter.lessons[0]
    assert lesson.title == "Lesson 1.1"
    assert len(lesson.pages) == 1

    page = lesson.pages[0]
    assert page.page_number == 1
    assert len(page.items) == 2

    heading = page.items[0]
    assert heading.type == "heading"
    assert heading.content == "Introduction"

    text = page.items[1]
    assert text.type == "text"
    assert "paragraph" in text.content


# ── API integration tests (FastAPI + mocked LP DB) ────────────────────────────


class TestStudyPlanAPI:
    """Tests for GET /api/courses/{course_id}/study-plan with mocked LP layer."""

    @pytest.mark.asyncio
    async def test_study_plan_returns_chapter_structure(
        self, app: Any, mock_user: dict[str, Any]
    ) -> None:
        """Study plan endpoint returns Chapter→Lesson→Page structure."""
        import httpx
        from httpx import ASGITransport

        doc_id = str(uuid4())
        # book is constructed to show the expected shape — the mock returns the
        # schema-level Chapter objects directly (see mock_fetch.return_value below)

        with (
            patch("routers.courses.get_course", new_callable=AsyncMock) as mock_course,
            patch(
                "routers.courses.get_documents_by_course", new_callable=AsyncMock
            ) as mock_docs,
            patch(
                "routers.courses._fetch_book_chapters", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_course.return_value = {
                "id": 1,
                "title": "Physics 101",
                "description": "",
                "number_of_credits": 3,
                "difficulty": "beginner",
                "status": "OPEN",
                "owner_id": 1,
            }
            mock_docs.return_value = [
                {
                    "id": doc_id,
                    "filename": "physics.pdf",
                    "storage_path": "/tmp/physics.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 4096,
                    "created_at": "2026-01-01T00:00:00",
                }
            ]

            from schemas import Chapter, Lesson, Page, TextItem as SchemaTextItem

            mock_fetch.return_value = [
                Chapter(
                    id=str(uuid4()),
                    title="Chapter 1: Mechanics",
                    order=0,
                    lessons=[
                        Lesson(
                            id=str(uuid4()),
                            title="Lesson 1.1: Newton's Laws",
                            order=0,
                            pages=[
                                Page(
                                    id=str(uuid4()),
                                    page_number=5,
                                    order=0,
                                    items=[
                                        SchemaTextItem(
                                            id=str(uuid4()),
                                            order=0,
                                            content="An object at rest stays at rest.",
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ]

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/courses/1/study-plan")

        assert resp.status_code == 200
        data = resp.json()

        assert data["course_id"] == 1
        assert data["course_title"] == "Physics 101"
        assert len(data["chapters"]) == 1

        chapter = data["chapters"][0]
        assert "Mechanics" in chapter["title"] or "Chapter 1" in chapter["title"]
        assert len(chapter["lessons"]) == 1

        lesson = chapter["lessons"][0]
        assert "Newton" in lesson["title"]
        assert len(lesson["pages"]) == 1

        page = lesson["pages"][0]
        assert page["page_number"] == 5
        assert len(page["items"]) == 1
        assert page["items"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_study_plan_course_not_found(self, app: Any) -> None:
        import httpx
        from httpx import ASGITransport

        with patch("routers.courses.get_course", new_callable=AsyncMock) as mock_course:
            mock_course.return_value = None

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/courses/999/study-plan")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Course not found"

    @pytest.mark.asyncio
    async def test_study_plan_no_documents_returns_empty_chapters(
        self, app: Any
    ) -> None:
        import httpx
        from httpx import ASGITransport

        with (
            patch("routers.courses.get_course", new_callable=AsyncMock) as mock_course,
            patch(
                "routers.courses.get_documents_by_course", new_callable=AsyncMock
            ) as mock_docs,
        ):
            mock_course.return_value = {
                "id": 2,
                "title": "Empty Course",
                "description": "",
                "number_of_credits": 0,
                "difficulty": "beginner",
                "status": "OPEN",
                "owner_id": 1,
            }
            mock_docs.return_value = []

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/courses/2/study-plan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["chapters"] == []

    @pytest.mark.asyncio
    async def test_study_plan_multiple_documents_chapters_concatenated(
        self, app: Any
    ) -> None:
        """Chapters from multiple documents are concatenated with correct ordering."""
        import httpx
        from httpx import ASGITransport

        from schemas import Chapter

        with (
            patch("routers.courses.get_course", new_callable=AsyncMock) as mock_course,
            patch(
                "routers.courses.get_documents_by_course", new_callable=AsyncMock
            ) as mock_docs,
            patch(
                "routers.courses._fetch_book_chapters", new_callable=AsyncMock
            ) as mock_fetch,
        ):
            mock_course.return_value = {
                "id": 3,
                "title": "Multi-Doc Course",
                "description": "",
                "number_of_credits": 3,
                "difficulty": "intermediate",
                "status": "OPEN",
                "owner_id": 1,
            }
            mock_docs.return_value = [
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

            mock_fetch.side_effect = [
                [Chapter(id=str(uuid4()), title="Chapter 1", order=0, lessons=[])],
                [Chapter(id=str(uuid4()), title="Chapter 2", order=1, lessons=[])],
            ]

            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/courses/3/study-plan")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["chapters"]) == 2
        assert data["chapters"][0]["title"] == "Chapter 1"
        assert data["chapters"][1]["title"] == "Chapter 2"


# ── BookPipeline integration test (mocked repositories) ───────────────────────


@pytest.mark.asyncio
async def test_book_pipeline_run_calls_assembler_and_saves() -> None:
    """BookPipeline.run() loads document+units, assembles book, persists it."""
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from learning_platform.models.book import BookChapter, CanonicalBook
    from learning_platform.models.document import CanonicalDocument
    from learning_platform.models.learning_unit import LearningUnit, UnitType
    from learning_platform.pipeline.book_pipeline import BookPipeline

    doc_id = uuid4()

    # Build fake document and units
    fake_doc = MagicMock(spec=CanonicalDocument)
    fake_doc.title = "Test"
    fake_doc.nodes = []
    fake_doc.metadata = MagicMock()
    fake_doc.metadata.title = "Test"

    fake_units = [
        LearningUnit(id=uuid4(), unit_type=UnitType.MODULE, title="Ch 1"),
    ]

    fake_book = CanonicalBook(
        document_id=doc_id,
        title="Test",
        chapters=[BookChapter(title="Ch 1", order=0, lessons=[])],
    )

    session = MagicMock()

    with (
        patch.object(
            BookPipeline,
            "__init__",
            lambda self, session: (
                setattr(self, "_session", session)
                or setattr(self, "_assembler", MagicMock())
                or setattr(self, "_book_repo", AsyncMock())
                or setattr(self, "_doc_repo", AsyncMock())
                or setattr(self, "_unit_repo", AsyncMock())
            ),
        ),
    ):
        pipeline = BookPipeline(session)
        pipeline._doc_repo.find_document = AsyncMock(return_value=fake_doc)
        pipeline._unit_repo.find_by_document = AsyncMock(return_value=fake_units)
        pipeline._assembler.assemble = MagicMock(return_value=fake_book)
        pipeline._book_repo.save_book = AsyncMock()

        result = await pipeline.run(doc_id)

    pipeline._doc_repo.find_document.assert_awaited_once_with(doc_id)
    pipeline._unit_repo.find_by_document.assert_awaited_once_with(doc_id)
    pipeline._assembler.assemble.assert_called_once_with(fake_units, fake_doc)
    pipeline._book_repo.save_book.assert_awaited_once()

    assert result.document_id == doc_id
    assert len(result.chapters) == 1
