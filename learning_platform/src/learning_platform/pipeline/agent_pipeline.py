"""Pipeline 3 — Agent Pipeline.

Reads the persisted CanonicalBook for a given document_id, runs the
CuratorAgent orchestrator over all lessons, and delegates all DB writes
to the sub-agents (output rows) and repositories (lesson progress/completion).

This pipeline is independent of Pipeline 2 (BookPipeline) and can be
re-run without re-assembling the book.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.agents.curator.orchestrator import CuratorAgent
from learning_platform.infrastructure.persistence.repositories.book import (
    BookRepository,
)
from learning_platform.models.agent_pipeline import AgentPipelineResult
from learning_platform.models.book import CanonicalBook

_LOG = logging.getLogger(__name__)


class AgentPipelinePartialFailureError(Exception):
    """Raised when one or more lessons failed during the agent pipeline.

    The poller catches this and marks lp_agent_process as failed, scheduling
    a retry. On retry, only lessons without a ``completed`` progress row are
    reprocessed; within each lesson, only agents without a completion marker
    rerun.
    """


class AgentPipeline:
    """Runs the CuratorAgent orchestrator over a CanonicalBook.

    Sub-agents own all DB writes for their output tables. This class only
    orchestrates the top-level flow: load book → run orchestrator → handle
    partial failure signal.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._book_repo = BookRepository(session)
        self._curator = CuratorAgent()

    async def run(self, document_id: UUID, agent_process_id: int) -> AgentPipelineResult:
        """Run the agent pipeline for a document.

        Args:
            document_id: UUID of the document whose book to process.
            agent_process_id: The lp_agent_process row id for this run.
                Passed through to sub-agents for completion tracking.

        Returns:
            AgentPipelineResult with all sub-agent outputs.

        Raises:
            ValueError: if no book is found for the document.
            AgentPipelinePartialFailureError: if one or more lessons failed.
        """
        _LOG.info(
            "AgentPipeline: starting for document %s (agent_process_id=%d)",
            document_id,
            agent_process_id,
        )

        book: CanonicalBook | None = await self._book_repo.find_by_document(document_id)
        if book is None:
            raise ValueError(
                f"No CanonicalBook found for document {document_id}. "
                "BookPipeline must complete before AgentPipeline can run."
            )

        _LOG.info(
            "AgentPipeline: loaded book with %d chapter(s) for document %s",
            len(book.chapters),
            document_id,
        )

        # Orchestrator manages lesson-level progress; sub-agents manage their
        # own output and completion markers. The session is shared for the
        # duration of this run so all writes are in one transaction.
        result: AgentPipelineResult = await self._curator.run_pipeline(
            book=book,
            document_id=document_id,
            agent_process_id=agent_process_id,
            session=self._session,
        )

        _LOG.info(
            "AgentPipeline: completed for document %s — "
            "%d keywords, %d summaries, %d flashcards, %d quizzes, %d practice",
            document_id,
            len(result.keywords),
            len(result.summaries),
            len(result.flashcards),
            len(result.quiz_questions),
            len(result.practice_questions),
        )
        return result
