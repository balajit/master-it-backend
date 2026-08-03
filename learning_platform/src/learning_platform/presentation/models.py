"""Presentation models — immutable view models for the study screen.

These models represent the learning experience as shown to students,
rather than the internal processing pipeline.  They reference existing
pipeline objects by ID wherever possible to avoid data duplication.

Design Principles
-----------------
- **Immutable**: Models use ``model_config = {"frozen": True}`` where practical.
- **No persistence logic**: Pure data transfer objects, no DB operations.
- **ID references**: Reference pipeline objects (``LearningUnit``, ``Lesson``,
  ``Quiz``, etc.) by UUID rather than embedding duplicate data.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field

from learning_platform.models.learning_unit import NodeRef

# ──────────────────────────────────────────────────────────────────────────────
# Type Aliases — thin wrappers for clarity
# ──────────────────────────────────────────────────────────────────────────────

UnitId = UUID
"""A UUID referencing a pipeline ``LearningUnit``."""

SectionId = UUID
"""A UUID referencing a section within a ``LearningUnit``."""

MilestoneId = UUID
"""A UUID referencing a pipeline ``Milestone``."""


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class CardStatus(StrEnum):
    """Status of a learning card as shown in the UI."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MASTERED = "mastered"
    LOCKED = "locked"
    PRACTICED = "practiced"
    ATTEMPTED = "attempted"


class CardType(StrEnum):
    """Type of learning card."""

    LESSON = "lesson"
    PRACTICE = "practice"
    QUIZ = "quiz"
    MILESTONE = "milestone"


class DifficultyLevel(StrEnum):
    """Difficulty level for display purposes."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class NavigationNodeType(StrEnum):
    """Type of navigation node in the learning tree."""

    COURSE = "course"
    MODULE = "module"
    LESSON = "lesson"
    TOPIC = "topic"


# ──────────────────────────────────────────────────────────────────────────────
# Value Objects
# ──────────────────────────────────────────────────────────────────────────────


class LearningObjective(BaseModel):
    """A single learning objective displayed to the student.

    References a pipeline ``ObjectiveAnnotation`` by ``annotation_id``.
    """

    model_config = {"frozen": True}

    text: str
    annotation_id: UUID | None = None
    order: int = 0


class Metadata(BaseModel):
    """Flexible key-value metadata for presentation models.

    Used for extensible properties that don't warrant their own field.
    """

    model_config = {"frozen": True}

    key: str
    value: Any = None


# ──────────────────────────────────────────────────────────────────────────────
# Card Models
# ──────────────────────────────────────────────────────────────────────────────


class UnitCard(BaseModel):
    """Top-level card representing a learning unit in the study screen.

    References the pipeline ``LearningUnit`` by ``unit_id``.
    """

    model_config = {"frozen": True}

    unit_id: UnitId
    title: str
    description: str = ""
    difficulty: DifficultyLevel = DifficultyLevel.BEGINNER
    estimated_minutes: int = 0
    total_sections: int = 0
    total_lessons: int = 0
    course_id: int | None = None
    progress_pct: float = 0.0


class Section(BaseModel):
    """A section within a unit, grouping related learning cards.

    References the section within a pipeline ``LearningUnit``.
    """

    model_config = {"frozen": True}

    section_id: SectionId
    unit_id: UnitId
    title: str
    order: int = 0
    estimated_minutes: int = 0
    lesson_count: int = 0
    practice_count: int = 0
    quiz_count: int = 0
    completed_count: int = 0
    start_page: int = 0
    end_page: int = 0


class LessonCard(BaseModel):
    """A lesson card shown in the study screen.

    References the pipeline ``Lesson`` by ``lesson_id``.
    Carries content references so the UI can render lesson content
    directly without additional out-of-band queries.
    """

    model_config = {"frozen": True}

    lesson_id: UUID
    unit_id: UnitId
    section_id: SectionId
    title: str
    description: str = ""
    order: int = 0
    duration_minutes: int = 0
    difficulty: DifficultyLevel = DifficultyLevel.BEGINNER
    status: CardStatus = CardStatus.NOT_STARTED
    learning_objectives: list[LearningObjective] = Field(default_factory=list)
    start_page: int = 0
    end_page: int = 0
    completed_at: str | None = None

    content_references: list[NodeRef] = Field(default_factory=list)
    definitions: list[NodeRef] = Field(default_factory=list)
    examples: list[NodeRef] = Field(default_factory=list)
    figures: list[NodeRef] = Field(default_factory=list)
    tables: list[NodeRef] = Field(default_factory=list)
    equations: list[NodeRef] = Field(default_factory=list)
    content: list[ContentNode] = Field(
        default_factory=list,
        description="Ordered array of typed content nodes for this lesson. "
        "Empty list when content has not yet been extracted.",
    )


class ExerciseOption(BaseModel):
    """A single answer choice for a practice exercise."""

    model_config = {"frozen": True}

    label: str = ""
    text: str = ""
    is_correct: bool = False
    explanation: str = ""


class PracticeCard(BaseModel):
    """A practice activity card shown in the study screen.

    References the pipeline ``LearningUnit`` exercises by ``practice_id``.
    Exercise content (question, options, solution) is resolved from the
    canonical document's ``Exercise`` content block.
    """

    model_config = {"frozen": True}

    practice_id: UUID
    unit_id: UnitId
    section_id: SectionId
    title: str
    order: int = 0
    required_correct: int = 0
    total_questions: int = 0
    status: CardStatus = CardStatus.NOT_STARTED
    attempts: int = 0
    best_score: float = 0.0
    question_text: str = ""
    exercise_type: str = ""
    options: list[ExerciseOption] = Field(default_factory=list)
    solution: str = ""
    explanation: str = ""


class QuizCard(BaseModel):
    """A quiz card shown in the study screen.

    References the pipeline ``Quiz`` by ``quiz_id``.
    """

    model_config = {"frozen": True}

    quiz_id: UUID
    unit_id: UnitId
    section_id: SectionId
    title: str
    order: int = 0
    total_points: int = 0
    passing_points: int = 0
    time_limit_minutes: int | None = None
    status: CardStatus = CardStatus.NOT_STARTED
    score: float | None = None
    completed_at: str | None = None


class MilestoneCard(BaseModel):
    """A milestone card grouping lessons at natural breakpoints.

    References the pipeline ``Milestone`` by ``milestone_id``.
    """

    model_config = {"frozen": True}

    milestone_id: MilestoneId
    unit_id: UnitId
    title: str
    description: str = ""
    order: int = 0
    estimated_minutes: int = 0
    lesson_count: int = 0
    completed_lesson_count: int = 0
    status: CardStatus = CardStatus.NOT_STARTED


# ──────────────────────────────────────────────────────────────────────────────
# Progress & Status
# ──────────────────────────────────────────────────────────────────────────────


class ProgressSummary(BaseModel):
    """Aggregated progress for a unit or section.

    Provides high-level metrics for the progress bar and stats display.
    """

    model_config = {"frozen": True}

    total_items: int = 0
    completed_items: int = 0
    mastery_pct: float = 0.0
    total_minutes_studied: int = 0
    estimated_remaining_minutes: int = 0


class StatusLegend(BaseModel):
    """Legend explaining card status colors/icons in the UI."""

    model_config = {"frozen": True}

    status: CardStatus
    label: str
    description: str
    icon_name: str = ""
    color_hex: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Navigation
# ──────────────────────────────────────────────────────────────────────────────


class PageView(BaseModel):
    """A single page view shown in the study screen.

    Derived from the pipeline ``PageContext``.  Contains a text preview
    for quick summary display, full_text for complete page rendering,
    and references to the content units, annotations, and concepts
    originating from that page.
    """

    model_config = {"frozen": True}

    page_number: int
    title: str = ""
    text_preview: str = ""
    full_text: str = ""
    unit_ids: list[UnitId] = Field(default_factory=list)
    annotation_ids: list[UUID] = Field(default_factory=list)
    concept_ids: list[UUID] = Field(default_factory=list)


class NavigationNode(BaseModel):
    """A node in the course navigation tree.

    Represents the hierarchical structure: Course → Module → Lesson → Topic.
    References pipeline objects by ID.
    """

    model_config = {"frozen": True}

    node_id: UUID
    node_type: NavigationNodeType
    title: str
    parent_id: UUID | None = None
    children_ids: list[UUID] = Field(default_factory=list)
    unit_id: UnitId | None = None
    order: int = 0
    is_current: bool = False
    is_accessible: bool = True
    status: CardStatus = CardStatus.NOT_STARTED


# ──────────────────────────────────────────────────────────────────────────────
# Content Node Types — typed, ordered lesson body content
# ──────────────────────────────────────────────────────────────────────────────


class TextRunType(StrEnum):
    """Discriminator for inline run types within a paragraph."""

    TEXT = "text"
    EQ = "eq"
    BOLD = "bold"
    ITALIC = "italic"
    CODE = "code"
    LINK = "link"


class PlainRun(BaseModel):
    """A plain text span within a paragraph."""

    run_type: Literal[TextRunType.TEXT] = TextRunType.TEXT
    text: str


class EqRun(BaseModel):
    """An inline LaTeX equation embedded in a paragraph."""

    run_type: Literal[TextRunType.EQ] = TextRunType.EQ
    latex: str


class BoldRun(BaseModel):
    """Bold text span."""

    run_type: Literal[TextRunType.BOLD] = TextRunType.BOLD
    text: str


class ItalicRun(BaseModel):
    """Italic text span."""

    run_type: Literal[TextRunType.ITALIC] = TextRunType.ITALIC
    text: str


class CodeRun(BaseModel):
    """Inline code span."""

    run_type: Literal[TextRunType.CODE] = TextRunType.CODE
    text: str


class LinkRun(BaseModel):
    """Hyperlink span."""

    run_type: Literal[TextRunType.LINK] = TextRunType.LINK
    text: str
    href: str


InlineRun = Annotated[
    Union[PlainRun, EqRun, BoldRun, ItalicRun, CodeRun, LinkRun],  # noqa: UP007
    Field(discriminator="run_type"),
]


class HeadingNode(BaseModel):
    """A section heading."""

    type: Literal["heading"] = "heading"
    level: int = Field(
        ge=1, le=4, description="1=chapter, 2=section, 3=subsection, 4=sub-subsection"
    )
    number: str = ""
    text: str


class ParagraphNode(BaseModel):
    """A paragraph of inline content, possibly with mixed styling and inline math."""

    type: Literal["paragraph"] = "paragraph"
    runs: list[InlineRun] = Field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> ParagraphNode:
        """Convenience constructor for a plain-text paragraph."""
        return cls(runs=[PlainRun(text=text)])


class TextItemNode(BaseModel):
    """A discrete text element, typically within a form area.

    Unlike ``ParagraphNode`` (flowing prose), ``TextItemNode`` represents
    individual text fragments like word-bank choices, form field labels,
    or answer options.
    """

    type: Literal["text_item"] = "text_item"
    runs: list[InlineRun] = Field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> TextItemNode:
        """Convenience constructor for a plain-text item."""
        return cls(runs=[PlainRun(text=text)])


class ListItemNode(BaseModel):
    """A single item in a list — may itself contain inline runs."""

    runs: list[InlineRun] = Field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> ListItemNode:
        return cls(runs=[PlainRun(text=text)])


class ListNode(BaseModel):
    """An ordered or unordered list."""

    type: Literal["list"] = "list"
    style: Literal["bullet", "numbered", "alpha", "roman", "checkbox"] = "bullet"
    items: list[ListItemNode] = Field(default_factory=list)


class FormAreaNode(BaseModel):
    """A form area containing interactive content like word banks or answer boxes.

    Children are ``TextItemNode`` elements representing individual selectable
    or fillable items within the form area.

    The ``display_hint`` field provides rendering guidance:
    - ``"word_bank"``: horizontal layout of selectable items
    - ``"answer_box"``: bordered input region
    - ``None``: default form area rendering
    """

    type: Literal["form_area"] = "form_area"
    items: list[TextItemNode] = Field(default_factory=list)
    display_hint: Literal["word_bank", "answer_box"] | None = None


class EquationNode(BaseModel):
    """A block (display) LaTeX equation.

    For inline equations within paragraph text, use EqRun inside ParagraphNode.
    """

    type: Literal["equation"] = "equation"
    latex: str
    label: str = ""


class CodeBlockNode(BaseModel):
    """A verbatim code listing."""

    type: Literal["code_block"] = "code_block"
    language: str = ""
    code: str


class TableCellNode(BaseModel):
    """A single cell in a content table."""

    header: bool = False
    text: str
    col_span: int = 1
    row_span: int = 1


class TableRowNode(BaseModel):
    """A row in a content table."""

    cells: list[TableCellNode] = Field(default_factory=list)
    is_header: bool = False


class TableNode(BaseModel):
    """A data table."""

    type: Literal["table"] = "table"
    caption: str = ""
    rows: list[TableRowNode] = Field(default_factory=list)


class NoteNode(BaseModel):
    """A margin note, tip, warning, or danger block."""

    type: Literal["note"] = "note"
    variant: Literal["info", "tip", "warning", "danger"] = "info"
    runs: list[InlineRun] = Field(default_factory=list)

    @classmethod
    def from_text(cls, text: str, variant: str = "info") -> NoteNode:
        return cls(variant=variant, runs=[PlainRun(text=text)])  # type: ignore[arg-type]


class CalloutNode(BaseModel):
    """A highlighted callout block — example, non-example, or reminder."""

    type: Literal["callout"] = "callout"
    variant: Literal["example", "non_example", "reminder"] = "example"
    title: str = ""
    runs: list[InlineRun] = Field(default_factory=list)

    @classmethod
    def from_text(cls, text: str, title: str = "", variant: str = "example") -> CalloutNode:
        return cls(title=title, variant=variant, runs=[PlainRun(text=text)])  # type: ignore[arg-type]


class DefinitionNode(BaseModel):
    """A term-definition pair."""

    type: Literal["definition"] = "definition"
    term: str
    definition: str


class FigureNode(BaseModel):
    """An image or diagram."""

    type: Literal["figure"] = "figure"
    image_url: str = ""
    alt_text: str = ""
    caption: str = ""


ContentNode = Annotated[
    Union[  # noqa: UP007
        HeadingNode,
        ParagraphNode,
        TextItemNode,
        ListNode,
        FormAreaNode,
        EquationNode,
        CodeBlockNode,
        TableNode,
        NoteNode,
        CalloutNode,
        DefinitionNode,
        FigureNode,
    ],
    Field(discriminator="type"),
]
"""Typed, ordered array element for lesson body content."""


# ──────────────────────────────────────────────────────────────────────────────
# Root Presentation Model
# ──────────────────────────────────────────────────────────────────────────────


class StudyExperience(BaseModel):
    """The complete learning experience shown on the study screen.

    This is the root presentation model that aggregates all cards,
    progress, and navigation for a unit.  It references pipeline
    objects by ID and contains no persistence logic.
    """

    model_config = {"frozen": True}

    unit: UnitCard
    sections: list[Section] = Field(default_factory=list)
    lessons: list[LessonCard] = Field(default_factory=list)
    practices: list[PracticeCard] = Field(default_factory=list)
    quizzes: list[QuizCard] = Field(default_factory=list)
    milestones: list[MilestoneCard] = Field(default_factory=list)
    pages: list[PageView] = Field(default_factory=list)
    progress: ProgressSummary = Field(default_factory=ProgressSummary)
    navigation: list[NavigationNode] = Field(default_factory=list)
    status_legend: list[StatusLegend] = Field(default_factory=list)
