"""Repository for Agent Pipeline (Pipeline 3) output tables.

Provides bulk-insert and per-lesson cleanup helpers for each sub-agent's output type.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import delete

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.agent_pipeline_outputs import (
    AgentFlashcardRow,
    KeywordRow,
    PracticeQuestionRow,
    QuizQuestionRow,
    SummaryRow,
)
from learning_platform.models.agent_pipeline import (
    AgentFlashcard,
    KeywordItem,
    PracticeQuestion,
    QuizQuestion,
    SummaryItem,
)

_LOG = logging.getLogger(__name__)


class AgentPipelineOutputRepository:
    """Bulk-insert helpers for all agent pipeline output tables."""

    def __init__(self, session: "AsyncSession") -> None:
        self._session: "AsyncSession" = session

    async def save_keywords(self, document_id: str, items: list[KeywordItem]) -> None:
        if not items:
            return
        rows = [
            KeywordRow(
                document_id=document_id,
                lesson_id=str(item.lesson_id),
                term=item.term,
                definition=item.definition,
            )
            for item in items
        ]
        self._session.add_all(rows)
        await self._session.flush()
        _LOG.info("Saved %d keyword(s) for document %s", len(rows), document_id)

    async def save_summaries(self, document_id: str, items: list[SummaryItem]) -> None:
        if not items:
            return
        rows = [
            SummaryRow(
                document_id=document_id,
                lesson_id=str(item.lesson_id),
                content=item.content,
            )
            for item in items
        ]
        self._session.add_all(rows)
        await self._session.flush()
        _LOG.info("Saved %d summary(ies) for document %s", len(rows), document_id)

    async def save_quiz_questions(self, document_id: str, items: list[QuizQuestion]) -> None:
        if not items:
            return
        rows = [
            QuizQuestionRow(
                document_id=document_id,
                lesson_id=str(item.lesson_id),
                question=item.question,
                choices=json.dumps(item.choices),
                correct_index=item.correct_index,
                explanation=item.explanation,
            )
            for item in items
        ]
        self._session.add_all(rows)
        await self._session.flush()
        _LOG.info("Saved %d quiz question(s) for document %s", len(rows), document_id)

    async def save_practice_questions(
        self, document_id: str, items: list[PracticeQuestion]
    ) -> None:
        if not items:
            return
        rows = [
            PracticeQuestionRow(
                document_id=document_id,
                lesson_id=str(item.lesson_id),
                question=item.question,
                choices=json.dumps(item.choices),
                correct_index=item.correct_index,
                explanation=item.explanation,
            )
            for item in items
        ]
        self._session.add_all(rows)
        await self._session.flush()
        _LOG.info("Saved %d practice question(s) for document %s", len(rows), document_id)

    async def save_flashcards(self, document_id: str, items: list[AgentFlashcard]) -> None:
        if not items:
            return
        rows = [
            AgentFlashcardRow(
                document_id=document_id,
                lesson_id=str(item.lesson_id),
                front=item.front,
                back=item.back,
                source_type=item.source_type,
            )
            for item in items
        ]
        self._session.add_all(rows)
        await self._session.flush()
        _LOG.info("Saved %d agent flashcard(s) for document %s", len(rows), document_id)

    # ── Per-lesson cleanup (called by sub-agents before retry insert) ─────────

    async def delete_keywords_for_lesson(self, document_id: str, lesson_id: str) -> None:
        await self._session.execute(
            delete(KeywordRow).where(
                KeywordRow.document_id == document_id,
                KeywordRow.lesson_id == lesson_id,
            )
        )
        await self._session.flush()

    async def delete_summaries_for_lesson(self, document_id: str, lesson_id: str) -> None:
        await self._session.execute(
            delete(SummaryRow).where(
                SummaryRow.document_id == document_id,
                SummaryRow.lesson_id == lesson_id,
            )
        )
        await self._session.flush()

    async def delete_quiz_questions_for_lesson(self, document_id: str, lesson_id: str) -> None:
        await self._session.execute(
            delete(QuizQuestionRow).where(
                QuizQuestionRow.document_id == document_id,
                QuizQuestionRow.lesson_id == lesson_id,
            )
        )
        await self._session.flush()

    async def delete_practice_questions_for_lesson(self, document_id: str, lesson_id: str) -> None:
        await self._session.execute(
            delete(PracticeQuestionRow).where(
                PracticeQuestionRow.document_id == document_id,
                PracticeQuestionRow.lesson_id == lesson_id,
            )
        )
        await self._session.flush()

    async def delete_flashcards_for_lesson(self, document_id: str, lesson_id: str) -> None:
        await self._session.execute(
            delete(AgentFlashcardRow).where(
                AgentFlashcardRow.document_id == document_id,
                AgentFlashcardRow.lesson_id == lesson_id,
            )
        )
        await self._session.flush()
