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
from typing import Any
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
