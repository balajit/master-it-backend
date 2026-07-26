"""Study Plan models — the structured learning output for a student.

A ``StudyPlan`` is the final output of the pipeline.  It contains an
ordered list of ``Lesson`` items grouped into ``Milestone`` blocks, with
``Checkpoint`` assessment points after each milestone.

The builder uses topological sort on the knowledge graph, balances
difficulty across lessons, and inserts milestones at natural breakpoints
(e.g., when difficulty level changes or after a fixed batch size).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class LessonType(StrEnum):
    """What kind of lesson this is in the study plan."""

    INTRODUCTION = "introduction"
    CORE = "core"
    ADVANCED = "advanced"
    REVIEW = "review"


class CheckpointType(StrEnum):
    """What kind of assessment a checkpoint represents."""

    QUIZ = "quiz"
    PRACTICE = "practice"
    PROJECT = "project"
    SELF_TEST = "self_test"


# ──────────────────────────────────────────────────────────────────────────────
# Lesson
# ──────────────────────────────────────────────────────────────────────────────


class Lesson(BaseModel):
    """An ordered lesson in the study plan.

    Each lesson maps to a single ``LearningUnit`` in the knowledge graph
    and carries a subset of its metadata needed for the student-facing
    study plan.

    Attributes
    ----------
    id : UUID
        Globally unique identifier.
    unit_id : UUID
        Reference to the ``LearningUnit`` this lesson is derived from.
    order : int
        0-based position in the overall study plan.
    title : str
        Human-readable title from the learning unit.
    description : str
        Short summary from the learning unit.
    learning_objectives : list[str]
        Objectives extracted from the learning unit.
    lesson_type : LessonType
        Classification based on difficulty and position.
    difficulty : str
        Difficulty string from the learning unit (basic / intermediate / advanced).
    estimated_minutes : int
        Estimated study time from the learning unit.
    milestone_id : UUID | None
        The milestone this lesson belongs to.
    prerequisites : list[UUID]
        Unit IDs that must be completed before this lesson.
    metadata : dict[str, Any]
        Open key-value store.
    """

    id: UUID = Field(default_factory=uuid4)
    unit_id: UUID
    order: int = 0
    title: str = ""
    description: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    lesson_type: LessonType = LessonType.CORE
    difficulty: str = "basic"
    estimated_minutes: int = 0
    milestone_id: UUID | None = None
    prerequisites: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Milestone
# ──────────────────────────────────────────────────────────────────────────────


class Milestone(BaseModel):
    """A grouping of lessons into a study milestone.

    Milestones are created at natural breakpoints — typically when
    difficulty level shifts or after a configurable batch of lessons.

    Attributes
    ----------
    id : UUID
        Globally unique identifier.
    order : int
        0-based position in the study plan.
    title : str
        Human-readable title (e.g., "Milestone 1: Basics").
    description : str
        Summary of what this milestone covers.
    lesson_ids : list[UUID]
        Ordered lesson IDs in this milestone.
    estimated_minutes : int
        Total estimated study time for all lessons in this milestone.
    metadata : dict[str, Any]
        Open key-value store.
    """

    id: UUID = Field(default_factory=uuid4)
    order: int = 0
    title: str = ""
    description: str = ""
    lesson_ids: list[UUID] = Field(default_factory=list)
    estimated_minutes: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Checkpoint
# ──────────────────────────────────────────────��──────────────────────────────


class Checkpoint(BaseModel):
    """An assessment point inserted after each milestone.

    Checkpoints are placeholders for quizzes, practice exercises, or
    self-tests that a student completes at the end of a milestone.

    Attributes
    ----------
    id : UUID
        Globally unique identifier.
    milestone_id : UUID
        The milestone this checkpoint follows.
    order : int
        0-based position in the study plan.
    title : str
        Human-readable title (e.g., "Checkpoint 1: Basics Review").
    checkpoint_type : CheckpointType
        What kind of assessment this represents.
    estimated_minutes : int
        Estimated time to complete.
    lesson_ids : list[UUID]
        Lesson IDs this checkpoint assesses (the lessons in the milestone).
    metadata : dict[str, Any]
        Open key-value store.
    """

    id: UUID = Field(default_factory=uuid4)
    milestone_id: UUID
    order: int = 0
    title: str = ""
    checkpoint_type: CheckpointType = CheckpointType.SELF_TEST
    estimated_minutes: int = 0
    lesson_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Study Plan (root output)
# ──────────────────────────────────────────────────────────────────────────────


class StudyPlan(BaseModel):
    """The complete structured study plan for a student.

    This is the final output of the learning sequence builder.  It
    contains an ordered list of lessons grouped into milestones, with
    checkpoints at natural breakpoints.

    Attributes
    ----------
    title : str
        Overall title for the study plan.
    description : str
        Summary of the study plan.
    lessons : list[Lesson]
        Ordered lessons in the study plan.
    milestones : list[Milestone]
        Milestone groupings of lessons.
    checkpoints : list[Checkpoint]
        Assessment points after each milestone.
    total_estimated_minutes : int
        Sum of all lesson estimated study times.
    total_lessons : int
        Number of lessons in the plan.
    metadata : dict[str, Any]
        Open key-value store.
    """

    title: str = ""
    description: str = ""
    lessons: list[Lesson] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    total_estimated_minutes: int = 0
    total_lessons: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Legacy compatibility — keep LearningSequence as an alias
# ──────────────────────────────────────────────────────────────────────────────


class LearningSequence(BaseModel):
    """Legacy ordered sequence — wraps a ``StudyPlan`` for backward compat."""

    steps: list[Lesson] = Field(default_factory=list)
    study_plan: StudyPlan | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
