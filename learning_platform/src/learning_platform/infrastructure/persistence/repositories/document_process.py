from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select

from learning_platform.infrastructure.persistence.models.document import CanonicalDocumentRow
from learning_platform.infrastructure.persistence.models.document_process import DocumentProcessRow
from learning_platform.infrastructure.persistence.models.pipeline_log import PipelineLogRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository

_LOG = logging.getLogger(__name__)

MAX_RETRIES: int = 3
ACTIVE_STATUSES: tuple[str, str] = ("pending", "processing")


class DocumentProcessRepository(BaseRepository[DocumentProcessRow]):
    model_class = DocumentProcessRow

    async def find_by_source(self, source: str) -> DocumentProcessRow | None:
        stmt = select(DocumentProcessRow).where(DocumentProcessRow.source == source)
        return (await self._session.execute(stmt)).scalars().first()

    async def find_by_abs_path(self, abs_path: str) -> DocumentProcessRow | None:
        stmt = select(DocumentProcessRow).where(DocumentProcessRow.abs_path == abs_path)
        return (await self._session.execute(stmt)).scalars().first()

    async def find_latest_by_abs_path(self, abs_path: str) -> DocumentProcessRow | None:
        stmt = (
            select(DocumentProcessRow)
            .where(DocumentProcessRow.abs_path == abs_path)
            .order_by(DocumentProcessRow.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def find_latest_by_document_id(self, doc_id: UUID) -> DocumentProcessRow | None:
        stmt = (
            select(DocumentProcessRow)
            .join(
                CanonicalDocumentRow,
                CanonicalDocumentRow.source == DocumentProcessRow.abs_path,
            )
            .where(CanonicalDocumentRow.id == doc_id)
            .order_by(DocumentProcessRow.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def find_active_by_abs_path(self, abs_path: str) -> DocumentProcessRow | None:
        stmt = (
            select(DocumentProcessRow)
            .where(DocumentProcessRow.abs_path == abs_path)
            .where(DocumentProcessRow.status.in_(ACTIVE_STATUSES))
            .order_by(DocumentProcessRow.id.desc())
            .limit(1)
        )
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

    async def create_entry(
        self,
        source: str,
        abs_path: str,
        *,
        run_mode: str = "process",
    ) -> DocumentProcessRow:
        row = DocumentProcessRow(
            source=source,
            abs_path=abs_path,
            status="pending",
            run_mode=run_mode,
            retry_count=0,
            max_retries=MAX_RETRIES,
        )
        # Use merge so the row is always attached to the current session,
        # even if callers pass detached instances in future refactors.
        row = await self._session.merge(row)
        await self._session.flush()
        _LOG.info("Created document_process entry: source=%s id=%d", source, row.id)
        return row

    async def mark_processing(self, row: DocumentProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "processing"
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_completed(self, row: DocumentProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "completed"
        row.last_completed_stage = "pipeline"
        row.failed_stage = None
        row.error_message = None
        row.resume_state_json = None
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_failed(self, row: DocumentProcessRow, error_message: str) -> None:
        row = await self._session.merge(row)
        row.status = "failed"
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_retry(self, row: DocumentProcessRow, error_message: str) -> None:
        row = await self._session.merge(row)
        row.status = "pending"
        row.run_mode = "retry"
        row.retry_count += 1
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def mark_book_pending(self, row: DocumentProcessRow, error_message: str) -> None:
        row = await self._session.merge(row)
        row.status = "processing"
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def reset_entry(self, row: DocumentProcessRow) -> None:
        row = await self._session.merge(row)
        row.status = "pending"
        row.run_mode = "reprocess"
        row.retry_count = 0
        row.last_completed_stage = None
        row.failed_stage = None
        row.resume_state_json = None
        row.error_message = None
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def record_stage_completed(self, row: DocumentProcessRow, stage: str) -> None:
        row = await self._session.merge(row)
        row.last_completed_stage = stage
        row.failed_stage = None
        row.error_message = None
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def record_stage_failed(
        self,
        row: DocumentProcessRow,
        stage: str,
        error_message: str,
    ) -> None:
        row = await self._session.merge(row)
        row.failed_stage = stage
        row.error_message = error_message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def update_resume_state(
        self,
        row: DocumentProcessRow,
        *,
        resume_state: dict[str, object] | None,
    ) -> None:
        row = await self._session.merge(row)
        row.resume_state_json = resume_state
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    async def requeue_processing_after_restart(
        self,
        row: DocumentProcessRow,
        message: str,
    ) -> None:
        row = await self._session.merge(row)
        row.status = "pending"
        row.run_mode = "retry"
        row.error_message = message
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self._session.flush()

    @staticmethod
    def stage_order() -> list[str]:
        return [
            "parser",
            "normalizer",
            "page_grouping",
            "enricher",
            "unit_builder",
            "concept_extractor",
            "graph_builder",
            "sequence_builder",
            "pipeline",
        ]

    @classmethod
    def next_stage_after(cls, stage: str | None) -> str:
        stages = cls.stage_order()
        if not stage or stage not in stages:
            return "parser"
        idx = stages.index(stage)
        if idx + 1 >= len(stages):
            return "sequence_builder"
        return cls._resume_stage_for_pipeline_stage(stages[idx + 1])

    @staticmethod
    def _resume_stage_for_pipeline_stage(stage: str) -> str:
        if stage in {"parser", "normalizer"}:
            return "parser"
        if stage in {"page_grouping", "enricher", "unit_builder", "concept_extractor"}:
            return "page_grouping"
        if stage == "graph_builder":
            return "graph_builder"
        if stage in {"sequence_builder", "pipeline"}:
            return "sequence_builder"
        return "parser"

    @classmethod
    def resolve_resume_from_row(cls, row: DocumentProcessRow) -> tuple[str, dict[str, Any]]:
        state = dict(row.resume_state_json or {})
        if row.run_mode == "reprocess":
            return "parser", {}

        if row.run_mode == "retry":
            failed_stage = row.failed_stage
            if failed_stage:
                return cls._resume_stage_for_pipeline_stage(failed_stage), state

            next_stage = cls.next_stage_after(row.last_completed_stage)
            return next_stage, state

        return "parser", {}

    async def create_retry_entry(self, row: DocumentProcessRow) -> DocumentProcessRow:
        retry_row = await self.create_entry(
            source=row.source,
            abs_path=row.abs_path,
            run_mode="retry",
        )
        retry_row.last_completed_stage = row.last_completed_stage
        retry_row.failed_stage = row.failed_stage
        retry_row.resume_state_json = row.resume_state_json
        retry_row.retry_count = row.retry_count
        await self._session.flush()
        return retry_row

    async def create_reprocess_entry(self, row: DocumentProcessRow) -> DocumentProcessRow:
        return await self.create_entry(
            source=row.source,
            abs_path=row.abs_path,
            run_mode="reprocess",
        )

    async def list_entries_by_ids(self, process_ids: list[int]) -> list[DocumentProcessRow]:
        if not process_ids:
            return []

        unique_ids = sorted(set(process_ids))
        stmt = (
            select(DocumentProcessRow)
            .where(DocumentProcessRow.id.in_(unique_ids))
            .order_by(DocumentProcessRow.id.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_pipeline_logs_by_process_ids(
        self, process_ids: list[int]
    ) -> list[PipelineLogRow]:
        if not process_ids:
            return []

        unique_ids = sorted(set(process_ids))
        stmt = (
            select(PipelineLogRow)
            .where(PipelineLogRow.document_process_id.in_(unique_ids))
            .order_by(PipelineLogRow.id.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete_entries_by_ids(
        self,
        process_ids: list[int],
    ) -> tuple[list[int], list[int], int]:
        if not process_ids:
            return [], [], 0

        unique_ids = sorted(set(process_ids))
        existing_stmt = (
            select(DocumentProcessRow.id)
            .where(DocumentProcessRow.id.in_(unique_ids))
            .order_by(DocumentProcessRow.id.asc())
        )
        existing_rows = await self._session.execute(existing_stmt)
        deleted_ids = [int(row_id) for row_id in existing_rows.scalars().all()]
        existing_set = set(deleted_ids)
        not_found_ids = [row_id for row_id in unique_ids if row_id not in existing_set]

        deleted_pipeline_logs = 0
        if deleted_ids:
            pipeline_log_delete = delete(PipelineLogRow).where(
                PipelineLogRow.document_process_id.in_(deleted_ids)
            )
            pipeline_log_result = await self._session.execute(pipeline_log_delete)
            deleted_pipeline_logs = int(pipeline_log_result.rowcount or 0)

            process_delete = delete(DocumentProcessRow).where(
                DocumentProcessRow.id.in_(deleted_ids)
            )
            await self._session.execute(process_delete)

        await self._session.flush()
        return deleted_ids, not_found_ids, deleted_pipeline_logs
