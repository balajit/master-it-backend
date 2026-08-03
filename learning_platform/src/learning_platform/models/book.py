"""Canonical Book model — structured representation of a processed document.

A CanonicalBook is produced by the Book Assembler pipeline (Pipeline 2).
It organises LearningUnit nodes into a hierarchy:

    Chapter  (≈ LearningUnit MODULE/COURSE)
      └─ Lesson  (≈ LearningUnit LESSON/TOPIC)
           └─ Page  (a page-number slice of the lesson's DocumentNodes)
                └─ Item  (a single typed content block on that page)
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Content item types — one discriminated-union member per content block kind
# ---------------------------------------------------------------------------


class TextItem(BaseModel):
    type: Literal["text"] = "text"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    content: str = ""
    level: int = 0  # 0 for non-headings
    bbox: dict[str, float] | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HeadingItem(BaseModel):
    type: Literal["heading"] = "heading"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    content: str = ""
    level: int = 1
    bbox: dict[str, float] | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageItem(BaseModel):
    type: Literal["image"] = "image"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    data: str = ""  # base64-encoded image bytes
    caption: str | None = None
    bbox: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableItem(BaseModel):
    type: Literal["table"] = "table"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    caption: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    bbox: dict[str, float] | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EquationItem(BaseModel):
    type: Literal["equation"] = "equation"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    latex: str = ""
    label: str | None = None
    bbox: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeItem(BaseModel):
    type: Literal["code"] = "code"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    content: str = ""
    language: str | None = None
    bbox: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListItem(BaseModel):
    type: Literal["list"] = "list"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    ordered: bool = False
    items: list[str] = Field(default_factory=list)
    bbox: dict[str, float] | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormAreaItem(BaseModel):
    type: Literal["form_area"] = "form_area"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    items: list[str] = Field(default_factory=list)
    bbox: dict[str, float] | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionOption(BaseModel):
    label: str = ""
    text: str = ""
    is_correct: bool | None = None
    explanation: str = ""


class QuestionBlank(BaseModel):
    blank_id: int
    placeholder: str = ""
    answer: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionStatement(BaseModel):
    number: int | None = None
    text: str = ""
    expected_answer: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionItem(BaseModel):
    type: Literal["question"] = "question"
    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    question_type: str = "unknown"
    content: str = ""
    options: list[QuestionOption] = Field(default_factory=list)
    blanks: list[QuestionBlank] = Field(default_factory=list)
    statements: list[QuestionStatement] = Field(default_factory=list)
    solution: str = ""
    explanation: str = ""
    points: float = 0.0
    bbox: dict[str, float] | None = None
    style: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


ContentItem = (
    TextItem
    | HeadingItem
    | ImageItem
    | TableItem
    | EquationItem
    | CodeItem
    | ListItem
    | FormAreaItem
    | QuestionItem
)

# ---------------------------------------------------------------------------
# Book structural models
# ---------------------------------------------------------------------------


class BookPage(BaseModel):
    """A page-number slice of a lesson, containing ordered content items."""

    id: UUID = Field(default_factory=uuid4)
    page_number: int = 0
    order: int = 0
    items: list[ContentItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BookLesson(BaseModel):
    """A lesson within a chapter, spanning one or more pages."""

    id: UUID = Field(default_factory=uuid4)
    unit_id: UUID | None = None  # → lp_learning_unit.id
    title: str = ""
    order: int = 0
    pages: list[BookPage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BookChapter(BaseModel):
    """A chapter within a book, containing ordered lessons."""

    id: UUID = Field(default_factory=uuid4)
    unit_id: UUID | None = None  # → lp_learning_unit.id
    title: str = ""
    order: int = 0
    lessons: list[BookLesson] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalBook(BaseModel):
    """The complete structured book assembled from a processed document."""

    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    title: str = ""
    chapters: list[BookChapter] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
