"""Repository for lp_agent_lesson_progress — orchestrator's lesson-level tracking."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select

from learning_platform.infrastructure.persistence.models.agent_lesson_progress import (
    AgentLessonProgressRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_LOG = logging.getLogger(__name__)

ALL_AGENT_TYPES: frozenset[str] = frozenset(
    {"keywords", "summaries", "flashcards", "quizzes", "practice"}
)


class AgentLessonProgressRepository:
    """Manages lesson-level progress rows for one agent pipeline run."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def find(self, agent_process_id: int, lesson_id: str) -> AgentLessonProgressRow | None:
        stmt = select(AgentLessonProgressRow).where(
            AgentLessonProgressRow.agent_process_id == agent_process_id,
            AgentLessonProgressRow.lesson_id == lesson_id,
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def find_all_for_run(self, agent_process_id: int) -> list[AgentLessonProgressRow]:
        stmt = select(AgentLessonProgressRow).where(
            AgentLessonProgressRow.agent_process_id == agent_process_id
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create(
        self, agent_process_id: int, document_id: str, lesson_id: str
    ) -> AgentLessonProgressRow:
        """Create a pending progress row. Idempotent — returns existing row if present."""
        existing = await self.find(agent_process_id, lesson_id)
        if existing is not None:
            return existing
        row = AgentLessonProgressRow(
            agent_process_id=agent_process_id,
            document_id=document_id,
            lesson_id=lesson_id,
            status="pending",
        )
        self._session.add(row)
        await self._session.flush()
        _LOG.debug(
            "Created lesson progress row: agent_process_id=%d lesson_id=%s",
            agent_process_id,
            lesson_id,
        )
        return row

    async def mark_completed(self, row: AgentLessonProgressRow) -> None:
        row = await self._session.merge(row)
        row.status = "completed"
        row.missing_agents = None
        row.error_message = None
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_failed(
        self,
        row: AgentLessonProgressRow,
        missing_agents: list[str],
        error_message: str | None = None,
    ) -> None:
        row = await self._session.merge(row)
        row.status = "failed"
        row.missing_agents = json.dumps(missing_agents)
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    def count_failed(self, rows: list[AgentLessonProgressRow]) -> int:
        return sum(1 for r in rows if r.status == "failed")
