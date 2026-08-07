"""Repository for lp_agent_lesson_completions — sub-agent completion markers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from learning_platform.infrastructure.persistence.models.agent_lesson_completions import (
    AgentLessonCompletionRow,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_LOG = logging.getLogger(__name__)


class AgentLessonCompletionRepository:
    """Read/write completion markers written by sub-agents after finishing a lesson."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def find_completed_agents(self, agent_process_id: int, lesson_id: str) -> set[str]:
        """Return the set of agent_types that have completed for this lesson."""
        stmt = select(AgentLessonCompletionRow.agent_type).where(
            AgentLessonCompletionRow.agent_process_id == agent_process_id,
            AgentLessonCompletionRow.lesson_id == lesson_id,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return set(rows)

    async def has_completed(self, agent_process_id: int, lesson_id: str, agent_type: str) -> bool:
        """Return True if this sub-agent already has a completion marker for this lesson."""
        stmt = select(AgentLessonCompletionRow.id).where(
            AgentLessonCompletionRow.agent_process_id == agent_process_id,
            AgentLessonCompletionRow.lesson_id == lesson_id,
            AgentLessonCompletionRow.agent_type == agent_type,
        )
        result = (await self._session.execute(stmt)).scalars().first()
        return result is not None

    async def mark_done(
        self, agent_process_id: int, document_id: str, lesson_id: str, agent_type: str
    ) -> None:
        """Write a completion marker. Idempotent — no-op if already present."""
        already = await self.has_completed(agent_process_id, lesson_id, agent_type)
        if already:
            return
        row = AgentLessonCompletionRow(
            agent_process_id=agent_process_id,
            document_id=document_id,
            lesson_id=lesson_id,
            agent_type=agent_type,
        )
        self._session.add(row)
        await self._session.flush()
        _LOG.debug(
            "Completion marker written: agent_process_id=%d lesson_id=%s agent_type=%s",
            agent_process_id,
            lesson_id,
            agent_type,
        )
