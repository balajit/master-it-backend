from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from learning_platform.infrastructure.persistence.models.agent_process import AgentProcessRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository

_LOG = logging.getLogger(__name__)

MAX_RETRIES: int = 3


class AgentProcessRepository(BaseRepository[AgentProcessRow]):
    model_class = AgentProcessRow

    async def find_by_document_id(self, document_id: str) -> AgentProcessRow | None:
        stmt = select(AgentProcessRow).where(AgentProcessRow.document_id == document_id)
        return (await self._session.execute(stmt)).scalars().first()

    async def find_pending(self, limit: int = 10) -> list[AgentProcessRow]:
        stmt = (
            select(AgentProcessRow)
            .where(AgentProcessRow.status == "pending")
            .order_by(AgentProcessRow.id.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_entry(self, document_id: str) -> AgentProcessRow:
        row = AgentProcessRow(
            document_id=document_id,
            status="pending",
            retry_count=0,
            max_retries=MAX_RETRIES,
        )
        row = await self._session.merge(row)
        await self._session.flush()
        _LOG.info("Created agent_process entry: document_id=%s id=%d", document_id, row.id)
        return row

    async def reset_entry(self, row: AgentProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "pending"
        row.retry_count = 0
        row.error_message = None
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()
        _LOG.info("Reset agent_process entry: document_id=%s id=%d", row.document_id, row.id)

    async def mark_processing(self, row: AgentProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "processing"
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_completed(self, row: AgentProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "completed"
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_failed(self, row: AgentProcessRow, error_message: str) -> None:
        row = await self._session.merge(row)
        row.status = "failed"
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_retry(self, row: AgentProcessRow, error_message: str) -> None:
        row = await self._session.merge(row)
        row.status = "pending"
        row.retry_count += 1
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_cancelled(self, row: AgentProcessRow, reason: str) -> None:
        """Mark a row as cancelled (superseded by a newer run for the same document)."""
        row = await self._session.merge(row)
        row.status = "cancelled"
        row.error_message = reason
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def find_latest_id_by_document_id(self, document_id: str) -> int | None:
        """Return the highest id (latest enqueued) for any row with this document_id."""
        stmt = select(func.max(AgentProcessRow.id)).where(
            AgentProcessRow.document_id == document_id
        )
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(result) if result is not None else None

    async def cancel_superseded(self, document_id: str, keep_id: int) -> int:
        """Cancel all pending rows for document_id with id < keep_id.

        Returns the number of rows cancelled.
        """
        stmt = (
            update(AgentProcessRow)
            .where(
                AgentProcessRow.document_id == document_id,
                AgentProcessRow.id < keep_id,
                AgentProcessRow.status == "pending",
            )
            .values(
                status="cancelled",
                error_message="Superseded by a newer run for the same document",
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        count: int = result.rowcount  # type: ignore[assignment]
        if count:
            _LOG.info(
                "Cancelled %d superseded agent_process row(s) for document %s",
                count,
                document_id,
            )
        return count
