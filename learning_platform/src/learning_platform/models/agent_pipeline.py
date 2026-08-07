"""Domain models for the Agent Pipeline (Pipeline 3).

These Pydantic models represent the structured output produced by the
CuratorAgent orchestrator and its sub-agents after book assembly completes.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class KeywordItem(BaseModel):
    """A key term with definition extracted from a lesson."""

    lesson_id: UUID
    term: str
    definition: str


class SummaryItem(BaseModel):
    """A concise summary of a lesson."""

    lesson_id: UUID
    content: str


class QuizQuestion(BaseModel):
    """A multiple-choice quiz question generated from a lesson.

    ``choices`` is an ordered list of answer strings.
    ``correct_index`` is the 0-based index of the correct choice.
    """

    lesson_id: UUID
    question: str
    choices: list[str] = Field(default_factory=list)
    correct_index: int = 0
    explanation: str | None = None


class PracticeQuestion(BaseModel):
    """A multiple-choice practice question generated from a lesson.

    Structurally identical to QuizQuestion but framed as an applied
    problem-solving exercise rather than a recall question.
    """

    lesson_id: UUID
    question: str
    choices: list[str] = Field(default_factory=list)
    correct_index: int = 0
    explanation: str | None = None


class AgentFlashcard(BaseModel):
    """An AI-generated flashcard seed from a lesson.

    Stored in ``lp_agent_flashcards``, distinct from the user-facing
    FSRS-tracked flashcards in ``lp_flashcards``.
    """

    lesson_id: UUID
    front: str
    back: str
    source_type: str = "agent"


class AgentPipelineResult(BaseModel):
    """Aggregated output from one full agent pipeline run for a document."""

    document_id: UUID
    keywords: list[KeywordItem] = Field(default_factory=list)
    summaries: list[SummaryItem] = Field(default_factory=list)
    quiz_questions: list[QuizQuestion] = Field(default_factory=list)
    practice_questions: list[PracticeQuestion] = Field(default_factory=list)
    flashcards: list[AgentFlashcard] = Field(default_factory=list)
