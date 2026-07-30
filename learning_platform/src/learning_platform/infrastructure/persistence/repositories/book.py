"""Repository for persisting and loading CanonicalBook structures."""

from __future__ import annotations

import logging
from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.book import (
    BookChapterRow,
    BookItemRow,
    BookLessonRow,
    BookPageRow,
)
from learning_platform.models.book import (
    BookChapter,
    BookLesson,
    BookPage,
    CanonicalBook,
    CodeItem,
    ContentItem,
    EquationItem,
    HeadingItem,
    ImageItem,
    ListItem,
    TableItem,
    TextItem,
)

_LOG = logging.getLogger(__name__)


class BookRepository:
    """Persist and retrieve CanonicalBook objects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save_book(self, book: CanonicalBook) -> None:
        """Persist a full CanonicalBook, replacing any existing book for
        the same document_id."""
        # Delete existing book for this document (cascade deletes children)
        existing = await self._find_chapter_rows(book.document_id)
        for row in existing:
            await self._session.delete(row)
        await self._session.flush()

        for chapter in book.chapters:
            chapter_row = BookChapterRow(
                id=chapter.id,
                document_id=book.document_id,
                unit_id=chapter.unit_id,
                title=chapter.title,
                order=chapter.order,
                metadata_json=chapter.metadata or None,
            )
            self._session.add(chapter_row)
            await self._session.flush()

            for lesson in chapter.lessons:
                lesson_row = BookLessonRow(
                    id=lesson.id,
                    chapter_id=chapter_row.id,
                    unit_id=lesson.unit_id,
                    title=lesson.title,
                    order=lesson.order,
                    metadata_json=lesson.metadata or None,
                )
                self._session.add(lesson_row)
                await self._session.flush()

                for page in lesson.pages:
                    page_row = BookPageRow(
                        id=page.id,
                        lesson_id=lesson_row.id,
                        page_number=page.page_number,
                        order=page.order,
                        metadata_json=page.metadata or None,
                    )
                    self._session.add(page_row)
                    await self._session.flush()

                    for item in page.items:
                        item_row = self._item_to_row(item, page_row.id)
                        self._session.add(item_row)

        await self._session.flush()
        _LOG.info(
            "Saved book for document %s: %d chapters",
            book.document_id,
            len(book.chapters),
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def find_by_document(self, document_id: UUID) -> CanonicalBook | None:
        """Load the full CanonicalBook for a document."""
        chapter_rows = await self._find_chapter_rows(document_id)
        if not chapter_rows:
            return None

        chapter_ids = [chapter.id for chapter in chapter_rows]
        lessons_by_chapter = await self._find_lessons_by_chapter_ids(chapter_ids)
        lesson_ids = [lesson.id for lessons in lessons_by_chapter.values() for lesson in lessons]
        pages_by_lesson = await self._find_pages_by_lesson_ids(lesson_ids)
        page_ids = [page.id for pages in pages_by_lesson.values() for page in pages]
        items_by_page = await self._find_items_by_page_ids(page_ids)

        chapters: list[BookChapter] = []
        for chapter_row in sorted(chapter_rows, key=lambda r: r.order):
            lesson_rows = sorted(lessons_by_chapter.get(chapter_row.id, []), key=lambda r: r.order)
            lessons: list[BookLesson] = []
            for lesson_row in lesson_rows:
                page_rows = sorted(pages_by_lesson.get(lesson_row.id, []), key=lambda r: r.order)
                pages: list[BookPage] = []
                for page_row in page_rows:
                    item_rows = sorted(items_by_page.get(page_row.id, []), key=lambda r: r.order)
                    items: list[ContentItem] = []
                    for item_row in item_rows:
                        item = self._row_to_item(item_row)
                        if item is not None:
                            items.append(item)
                    pages.append(
                        BookPage(
                            id=page_row.id,
                            page_number=page_row.page_number,
                            order=page_row.order,
                            items=items,
                            metadata=page_row.metadata_json or {},
                        )
                    )
                lessons.append(
                    BookLesson(
                        id=lesson_row.id,
                        unit_id=lesson_row.unit_id,
                        title=lesson_row.title,
                        order=lesson_row.order,
                        pages=pages,
                        metadata=lesson_row.metadata_json or {},
                    )
                )
            chapters.append(
                BookChapter(
                    id=chapter_row.id,
                    unit_id=chapter_row.unit_id,
                    title=chapter_row.title,
                    order=chapter_row.order,
                    lessons=lessons,
                    metadata=chapter_row.metadata_json or {},
                )
            )

        return CanonicalBook(document_id=document_id, chapters=chapters)

    async def find_chapters_by_document(self, document_id: UUID) -> list[BookChapter]:
        """Load chapters (without pages/items) for a document."""
        chapter_rows = await self._find_chapter_rows(document_id)
        result: list[BookChapter] = []
        for row in sorted(chapter_rows, key=lambda r: r.order):
            lesson_rows = await self._find_lesson_rows(row.id)
            lessons = [
                BookLesson(
                    id=lr.id,
                    unit_id=lr.unit_id,
                    title=lr.title,
                    order=lr.order,
                )
                for lr in sorted(lesson_rows, key=lambda r: r.order)
            ]
            result.append(
                BookChapter(
                    id=row.id,
                    unit_id=row.unit_id,
                    title=row.title,
                    order=row.order,
                    lessons=lessons,
                )
            )
        return result

    async def find_pages_by_lesson(self, lesson_id: UUID) -> list[BookPage]:
        """Load all pages (with items) for a lesson."""
        stmt = select(BookPageRow).where(BookPageRow.lesson_id == lesson_id)
        result = await self._session.execute(stmt)
        page_rows = result.scalars().all()

        pages: list[BookPage] = []
        for page_row in sorted(page_rows, key=lambda r: r.order):
            items = await self._load_items(page_row.id)
            pages.append(
                BookPage(
                    id=page_row.id,
                    page_number=page_row.page_number,
                    order=page_row.order,
                    items=items,
                    metadata=page_row.metadata_json or {},
                )
            )
        return pages

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _find_chapter_rows(self, document_id: UUID) -> list[BookChapterRow]:
        stmt = select(BookChapterRow).where(BookChapterRow.document_id == document_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _find_lesson_rows(self, chapter_id: UUID) -> list[BookLessonRow]:
        stmt = select(BookLessonRow).where(BookLessonRow.chapter_id == chapter_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _find_lessons_by_chapter_ids(
        self,
        chapter_ids: list[UUID],
    ) -> dict[UUID, list[BookLessonRow]]:
        if not chapter_ids:
            return {}
        stmt = select(BookLessonRow).where(BookLessonRow.chapter_id.in_(chapter_ids))
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        grouped: dict[UUID, list[BookLessonRow]] = defaultdict(list)
        for row in rows:
            grouped[row.chapter_id].append(row)
        return dict(grouped)

    async def _find_pages_by_lesson_ids(
        self,
        lesson_ids: list[UUID],
    ) -> dict[UUID, list[BookPageRow]]:
        if not lesson_ids:
            return {}
        stmt = select(BookPageRow).where(BookPageRow.lesson_id.in_(lesson_ids))
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        grouped: dict[UUID, list[BookPageRow]] = defaultdict(list)
        for row in rows:
            grouped[row.lesson_id].append(row)
        return dict(grouped)

    async def _find_items_by_page_ids(
        self,
        page_ids: list[UUID],
    ) -> dict[UUID, list[BookItemRow]]:
        if not page_ids:
            return {}
        stmt = select(BookItemRow).where(BookItemRow.page_id.in_(page_ids))
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        grouped: dict[UUID, list[BookItemRow]] = defaultdict(list)
        for row in rows:
            grouped[row.page_id].append(row)
        return dict(grouped)

    async def _load_lessons(self, chapter_id: UUID) -> list[BookLesson]:
        lesson_rows = await self._find_lesson_rows(chapter_id)
        lessons: list[BookLesson] = []
        for lesson_row in sorted(lesson_rows, key=lambda r: r.order):
            pages = await self.find_pages_by_lesson(lesson_row.id)
            lessons.append(
                BookLesson(
                    id=lesson_row.id,
                    unit_id=lesson_row.unit_id,
                    title=lesson_row.title,
                    order=lesson_row.order,
                    pages=pages,
                    metadata=lesson_row.metadata_json or {},
                )
            )
        return lessons

    async def _load_items(self, page_id: UUID) -> list[ContentItem]:
        stmt = select(BookItemRow).where(BookItemRow.page_id == page_id)
        result = await self._session.execute(stmt)
        item_rows = result.scalars().all()
        items: list[ContentItem] = []
        for row in sorted(item_rows, key=lambda r: r.order):
            item = self._row_to_item(row)
            if item is not None:
                items.append(item)
        return items

    @staticmethod
    def _item_to_row(item: ContentItem, page_id: UUID) -> BookItemRow:
        """Serialize a ContentItem to a BookItemRow."""
        bbox: dict[str, object] | None = None
        style: dict[str, object] | None = None
        content: dict[str, object] = {}

        if item.type == "text" or item.type == "heading":
            content = {"text": item.content}
            bbox = dict(item.bbox) if item.bbox else None
            style = dict(item.style) if item.style else None
        elif item.type == "image":
            content = {"data": item.data, "caption": item.caption}
            bbox = dict(item.bbox) if item.bbox else None
        elif item.type == "table":
            content = {
                "caption": item.caption,
                "headers": item.headers,
                "rows": item.rows,
            }
            bbox = dict(item.bbox) if item.bbox else None
            style = dict(item.style) if item.style else None
        elif item.type == "equation":
            content = {"latex": item.latex, "label": item.label}
            bbox = dict(item.bbox) if item.bbox else None
        elif item.type == "code":
            content = {"code": item.content, "language": item.language}
            bbox = dict(item.bbox) if item.bbox else None
        elif item.type == "list":
            content = {"items": item.items, "ordered": item.ordered}
            bbox = dict(item.bbox) if item.bbox else None
            style = dict(item.style) if item.style else None

        level = getattr(item, "level", 0)

        return BookItemRow(
            id=item.id,
            page_id=page_id,
            item_type=item.type,
            order=item.order,
            level=level,
            content_json=content or None,
            bbox_json=bbox,
            style_json=style,
        )

    @staticmethod
    def _row_to_item(row: BookItemRow) -> ContentItem | None:
        """Deserialize a BookItemRow back to a ContentItem."""
        c = row.content_json or {}
        b = row.bbox_json
        s = row.style_json

        if row.item_type == "text":
            return TextItem(
                id=row.id,
                order=row.order,
                content=c.get("text", ""),
                level=row.level,
                bbox=b,
                style=s,
            )
        if row.item_type == "heading":
            return HeadingItem(
                id=row.id,
                order=row.order,
                content=c.get("text", ""),
                level=row.level,
                bbox=b,
                style=s,
            )
        if row.item_type == "image":
            return ImageItem(
                id=row.id,
                order=row.order,
                data=c.get("data", ""),
                caption=c.get("caption"),
                bbox=b,
            )
        if row.item_type == "table":
            return TableItem(
                id=row.id,
                order=row.order,
                caption=c.get("caption"),
                headers=c.get("headers", []),
                rows=c.get("rows", []),
                bbox=b,
                style=s,
            )
        if row.item_type == "equation":
            return EquationItem(
                id=row.id,
                order=row.order,
                latex=c.get("latex", ""),
                label=c.get("label"),
                bbox=b,
            )
        if row.item_type == "code":
            return CodeItem(
                id=row.id,
                order=row.order,
                content=c.get("code", ""),
                language=c.get("language"),
                bbox=b,
            )
        if row.item_type == "list":
            return ListItem(
                id=row.id,
                order=row.order,
                ordered=c.get("ordered", False),
                items=c.get("items", []),
                bbox=b,
                style=s,
            )
        _LOG.warning("Unknown item_type %r — skipping", row.item_type)
        return None
