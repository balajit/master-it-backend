from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from learning_platform.infrastructure.persistence.models.book_process import BookProcessRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository

_LOG = logging.getLogger(__name__)

MAX_RETRIES: int = 3


class BookProcessRepository(BaseRepository[BookProcessRow]):
    model_class = BookProcessRow

    async def find_by_document_id(self, document_id: str) -> BookProcessRow | None:
        stmt = select(BookProcessRow).where(BookProcessRow.document_id == document_id)
        return (await self._session.execute(stmt)).scalars().first()

    async def find_pending(self, limit: int = 10) -> list[BookProcessRow]:
        stmt = (
            select(BookProcessRow)
            .where(BookProcessRow.status == "pending")
            .order_by(BookProcessRow.id.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_entry(self, document_id: str) -> BookProcessRow:
        row = BookProcessRow(
            document_id=document_id,
            status="pending",
            retry_count=0,
            max_retries=MAX_RETRIES,
        )
        row = await self._session.merge(row)
        await self._session.flush()
        _LOG.info("Created book_process entry: document_id=%s id=%d", document_id, row.id)
        return row

    async def reset_entry(self, row: BookProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "pending"
        row.retry_count = 0
        row.error_message = None
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()
        _LOG.info("Reset book_process entry: document_id=%s id=%d", row.document_id, row.id)

    async def mark_processing(self, row: BookProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "processing"
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_completed(self, row: BookProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "completed"
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_failed(self, row: BookProcessRow, error_message: str) -> None:
        row = await self._session.merge(row)
        row.status = "failed"
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_retry(self, row: BookProcessRow, error_message: str) -> None:
        row = await self._session.merge(row)
        row.status = "pending"
        row.retry_count += 1
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()
