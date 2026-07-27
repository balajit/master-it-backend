from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from learning_platform.infrastructure.persistence.models.document_process import DocumentProcessRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository

_LOG = logging.getLogger(__name__)

MAX_RETRIES: int = 3


class DocumentProcessRepository(BaseRepository[DocumentProcessRow]):
    model_class = DocumentProcessRow

    async def find_by_source(self, source: str) -> DocumentProcessRow | None:
        stmt = select(DocumentProcessRow).where(DocumentProcessRow.source == source)
        return (await self._session.execute(stmt)).scalars().first()

    async def find_pending(self, limit: int = 10) -> list[DocumentProcessRow]:
        stmt = (
            select(DocumentProcessRow)
            .where(DocumentProcessRow.status == "pending")
            .order_by(DocumentProcessRow.id.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_processing(self, limit: int = 10) -> list[DocumentProcessRow]:
        stmt = (
            select(DocumentProcessRow)
            .where(DocumentProcessRow.status == "processing")
            .order_by(DocumentProcessRow.id.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_entry(self, source: str, abs_path: str) -> DocumentProcessRow:
        row = DocumentProcessRow(
            source=source,
            abs_path=abs_path,
            status="pending",
            retry_count=0,
            max_retries=MAX_RETRIES,
        )
        self._session.add(row)
        await self._session.flush()
        _LOG.info("Created document_process entry: source=%s id=%d", source, row.id)
        return row

    async def mark_processing(self, row: DocumentProcessRow) -> None:
        row.status = "processing"
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_completed(self, row: DocumentProcessRow) -> None:
        row.status = "completed"
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_failed(self, row: DocumentProcessRow, error_message: str) -> None:
        row.status = "failed"
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_retry(self, row: DocumentProcessRow, error_message: str) -> None:
        row.status = "pending"
        row.retry_count += 1
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()
