"""Tests for agent process dedup, lesson progress, and lesson completion repos."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from learning_platform.infrastructure.persistence.models.agent_process import AgentProcessRow


class TestAgentProcessDedup:
    @pytest.mark.asyncio
    async def test_find_latest_id_returns_max(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_process import (
            AgentProcessRepository,
        )

        session = MagicMock()
        # Simulate scalar_one_or_none returning 42
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = 42
        session.execute = AsyncMock(return_value=execute_result)

        repo = AgentProcessRepository(session)
        result = await repo.find_latest_id_by_document_id("doc-1")
        assert result == 42

    @pytest.mark.asyncio
    async def test_find_latest_id_returns_none_when_no_rows(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_process import (
            AgentProcessRepository,
        )

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        repo = AgentProcessRepository(session)
        result = await repo.find_latest_id_by_document_id("doc-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_mark_cancelled_sets_status(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_process import (
            AgentProcessRepository,
        )

        session = MagicMock()
        row = AgentProcessRow(document_id="doc-1", status="pending")
        session.merge = AsyncMock(return_value=row)
        session.flush = AsyncMock()

        repo = AgentProcessRepository(session)
        await repo.mark_cancelled(row, "Superseded")

        assert row.status == "cancelled"
        assert row.error_message == "Superseded"


class TestAgentLessonProgressRepository:
    @pytest.mark.asyncio
    async def test_create_returns_new_row(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
        )

        session = MagicMock()
        # find returns None (no existing row)
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=execute_result)
        session.add = MagicMock()
        session.flush = AsyncMock()

        repo = AgentLessonProgressRepository(session)
        lesson_id = str(uuid4())
        row = await repo.create(1, "doc-1", lesson_id)

        assert row.agent_process_id == 1
        assert row.document_id == "doc-1"
        assert row.lesson_id == lesson_id
        assert row.status == "pending"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_idempotent_returns_existing(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_lesson_progress import (
            AgentLessonProgressRow,
        )

        session = MagicMock()
        existing = AgentLessonProgressRow(
            agent_process_id=1, document_id="doc-1", lesson_id="les-1", status="completed"
        )
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = existing
        session.execute = AsyncMock(return_value=execute_result)

        repo = AgentLessonProgressRepository(session)
        row = await repo.create(1, "doc-1", "les-1")
        assert row is existing
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_mark_completed(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_lesson_progress import (
            AgentLessonProgressRow,
        )

        session = MagicMock()
        row = AgentLessonProgressRow(status="pending")
        session.merge = AsyncMock(return_value=row)
        session.flush = AsyncMock()

        repo = AgentLessonProgressRepository(session)
        await repo.mark_completed(row)
        assert row.status == "completed"
        assert row.missing_agents is None

    @pytest.mark.asyncio
    async def test_mark_failed_records_missing_agents(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_lesson_progress import (
            AgentLessonProgressRow,
        )
        import json

        session = MagicMock()
        row = AgentLessonProgressRow(status="pending")
        session.merge = AsyncMock(return_value=row)
        session.flush = AsyncMock()

        repo = AgentLessonProgressRepository(session)
        await repo.mark_failed(row, ["quizzes", "practice"], "LLM timeout")
        assert row.status == "failed"
        assert json.loads(row.missing_agents) == ["quizzes", "practice"]
        assert row.error_message == "LLM timeout"

    def test_count_failed(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_lesson_progress import (
            AgentLessonProgressRow,
        )

        repo = AgentLessonProgressRepository(MagicMock())
        rows = [
            AgentLessonProgressRow(status="completed"),
            AgentLessonProgressRow(status="failed"),
            AgentLessonProgressRow(status="failed"),
        ]
        assert repo.count_failed(rows) == 2


class TestAgentLessonCompletionRepository:
    @pytest.mark.asyncio
    async def test_has_completed_true_when_row_exists(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = 7  # some id
        session.execute = AsyncMock(return_value=execute_result)

        repo = AgentLessonCompletionRepository(session)
        result = await repo.has_completed(1, "les-1", "keywords")
        assert result is True

    @pytest.mark.asyncio
    async def test_has_completed_false_when_no_row(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        repo = AgentLessonCompletionRepository(session)
        result = await repo.has_completed(1, "les-1", "keywords")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_done_inserts_row(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )

        session = MagicMock()
        # has_completed returns False → insert
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=execute_result)
        session.add = MagicMock()
        session.flush = AsyncMock()

        repo = AgentLessonCompletionRepository(session)
        await repo.mark_done(1, "doc-1", "les-1", "keywords")
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_done_idempotent_skips_if_exists(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )

        session = MagicMock()
        # has_completed returns True → skip
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = 5
        session.execute = AsyncMock(return_value=execute_result)
        session.add = MagicMock()

        repo = AgentLessonCompletionRepository(session)
        await repo.mark_done(1, "doc-1", "les-1", "keywords")
        session.add.assert_not_called()
