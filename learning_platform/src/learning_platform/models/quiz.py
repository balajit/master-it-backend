"""Quiz models — questions, answers, and generated quizzes.

A ``Quiz`` is produced by a ``QuizGenerator`` plugin after the pipeline
has generated a ``StudyPlan``, learning units, and concepts.  Each quiz
is scoped to a lesson or milestone and contains typed questions with
answer keys.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class QuestionType(StrEnum):
    """Kinds of quiz questions."""

    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    FILL_IN_BLANK = "fill_in_blank"
    MATCHING = "matching"
    ORDERING = "ordering"


class Answer(BaseModel):
    """A single answer option or the correct answer text."""

    id: UUID = Field(default_factory=uuid4)
    text: str
    is_correct: bool = False
    explanation: str = ""


class Question(BaseModel):
    """A single quiz question."""

    id: UUID = Field(default_factory=uuid4)
    question_type: QuestionType
    text: str
    answers: list[Answer] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    points: int = 1
    source_unit_id: UUID | None = None
    source_concept_names: list[str] = Field(default_factory=list)


class Quiz(BaseModel):
    """A generated quiz scoped to a lesson or milestone."""

    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str = ""
    lesson_id: UUID | None = None
    milestone_id: UUID | None = None
    questions: list[Question] = Field(default_factory=list)
    total_points: int = 0
    passing_points: int = 0
    time_limit_minutes: int | None = None
    question_types: list[QuestionType] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        """Compute total_points from questions if not set."""
        if self.total_points == 0 and self.questions:
            object.__setattr__(self, "total_points", sum(q.points for q in self.questions))
