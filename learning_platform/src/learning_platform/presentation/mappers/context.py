"""External context for presentation mapping.

This module defines the data structures that carry information NOT available
in the pipeline models: user progress, course ownership, and session state.

The mapper uses this context to enrich pipeline output with user-specific
data when transforming to presentation models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ProgressStatus(StrEnum):
    """User progress status for a learning item."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MASTERED = "mastered"
    PRACTICED = "practiced"
    ATTEMPTED = "attempted"


@dataclass(frozen=True)
class LessonProgress:
    """User progress for a single lesson."""

    lesson_id: UUID
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    completed_at: datetime | None = None
    time_spent_minutes: int = 0


@dataclass(frozen=True)
class PracticeProgress:
    """User progress for a single practice activity."""

    practice_id: UUID
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    attempts: int = 0
    best_score: float = 0.0
    time_spent_minutes: int = 0


@dataclass(frozen=True)
class QuizProgress:
    """User progress for a single quiz."""

    quiz_id: UUID
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    score: float | None = None
    completed_at: datetime | None = None
    time_spent_minutes: int = 0


@dataclass(frozen=True)
class UnitProgress:
    """Aggregated progress for a unit."""

    total_items: int = 0
    completed_items: int = 0
    total_minutes_studied: int = 0


@dataclass(frozen=True)
class ProgressContext:
    """External context carrying user progress data.

    This context is passed to mappers to enrich pipeline models with
    user-specific progress information. It contains data that exists
    outside the pipeline (in the database/user session).

    Attributes
    ----------
    user_id : int
        The authenticated user's ID.
    course_id : int
        The course this user is studying.
    lesson_progress : dict[UUID, LessonProgress]
        Map of lesson_id → user progress for that lesson.
    practice_progress : dict[UUID, PracticeProgress]
        Map of practice_id → user progress for that practice.
    quiz_progress : dict[UUID, QuizProgress]
        Map of quiz_id → user progress for that quiz.
    unit_progress : dict[UUID, UnitProgress]
        Map of unit_id → aggregated progress for that unit.
    current_node_id : UUID | None
        The node the user is currently viewing (for navigation highlighting).
    """

    user_id: int
    course_id: int
    lesson_progress: dict[UUID, LessonProgress] = field(default_factory=dict)
    practice_progress: dict[UUID, PracticeProgress] = field(default_factory=dict)
    quiz_progress: dict[UUID, QuizProgress] = field(default_factory=dict)
    unit_progress: dict[UUID, UnitProgress] = field(default_factory=dict)
    current_node_id: UUID | None = None

    def get_lesson_status(self, lesson_id: UUID) -> ProgressStatus:
        """Get the progress status for a lesson."""
        progress = self.lesson_progress.get(lesson_id)
        return progress.status if progress else ProgressStatus.NOT_STARTED

    def get_practice_status(self, practice_id: UUID) -> ProgressStatus:
        """Get the progress status for a practice activity."""
        progress = self.practice_progress.get(practice_id)
        return progress.status if progress else ProgressStatus.NOT_STARTED

    def get_quiz_status(self, quiz_id: UUID) -> ProgressStatus:
        """Get the progress status for a quiz."""
        progress = self.quiz_progress.get(quiz_id)
        return progress.status if progress else ProgressStatus.NOT_STARTED

    def get_unit_progress(self, unit_id: UUID) -> UnitProgress:
        """Get aggregated progress for a unit."""
        return self.unit_progress.get(unit_id, UnitProgress())
