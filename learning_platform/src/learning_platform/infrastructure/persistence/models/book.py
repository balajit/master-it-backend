"""ORM models for the canonical book structure.

Tables (all singular names):
    lp_book_chapter  — one row per chapter in a document
    lp_book_lesson   — one row per lesson, FK to chapter
    lp_book_page     — one row per page slice, FK to lesson
    lp_book_item     — one row per content block, FK to page
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class BookChapterRow(Base):
    __tablename__ = "lp_book_chapter"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class BookLessonRow(Base):
    __tablename__ = "lp_book_lesson"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_book_chapter.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class BookPageRow(Base):
    __tablename__ = "lp_book_page"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_book_lesson.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, default=0)
    order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class BookItemRow(Base):
    __tablename__ = "lp_book_item"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_book_page.id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[str] = mapped_column(String(32), default="text", name="type")
    order: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=0)
    content_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="content", nullable=True
    )
    bbox_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="bbox", nullable=True
    )
    style_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="style", nullable=True
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )
