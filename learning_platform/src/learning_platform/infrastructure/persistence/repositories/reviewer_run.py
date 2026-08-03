from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from learning_platform.infrastructure.persistence.models.reviewer_run import (
    ReviewerPageResultRow,
    ReviewerRunRow,
)
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository

_LOG = logging.getLogger(__name__)


class ReviewerRunRepository(BaseRepository[ReviewerRunRow]):
    model_class = ReviewerRunRow

    async def create_processing_run(
        self,
        *,
        requested_lp_documents_id: UUID,
        resolved_lp_documents_id: UUID,
        resolved_document_name: str,
        metadata: dict[str, object] | None = None,
    ) -> ReviewerRunRow:
        row = ReviewerRunRow(
            requested_lp_documents_id=requested_lp_documents_id,
            resolved_lp_documents_id=resolved_lp_documents_id,
            resolved_document_name=resolved_document_name,
            status="processing",
            aggregate_summary="",
            metadata_json=metadata,
        )
        self._session.add(row)
        await self._session.flush()
        _LOG.debug(
            "Created reviewer run row: id=%s requested_lp_documents_id=%s "
            "resolved_lp_documents_id=%s status=%s",
            row.id,
            row.requested_lp_documents_id,
            row.resolved_lp_documents_id,
            row.status,
        )
        return row

    async def mark_completed(
        self,
        row: ReviewerRunRow,
        *,
        aggregate_verdict: str,
        aggregate_summary: str,
        metadata: dict[str, object],
    ) -> None:
        attached = await self._session.merge(row)
        attached.status = "completed"
        attached.aggregate_verdict = aggregate_verdict
        attached.aggregate_summary = aggregate_summary
        attached.metadata_json = metadata
        attached.error_message = None
        attached.updated_at = datetime.now(UTC)
        await self._session.flush()
        _LOG.debug(
            "Completed reviewer run row: id=%s aggregate_verdict=%s",
            attached.id,
            attached.aggregate_verdict,
        )

    async def mark_failed(
        self,
        row: ReviewerRunRow,
        *,
        error_message: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        attached = await self._session.merge(row)
        attached.status = "failed"
        attached.error_message = error_message
        if metadata is not None:
            attached.metadata_json = metadata
        attached.updated_at = datetime.now(UTC)
        await self._session.flush()
        _LOG.debug(
            "Failed reviewer run row: id=%s error_message=%s",
            attached.id,
            attached.error_message,
        )


class ReviewerPageResultRepository(BaseRepository[ReviewerPageResultRow]):
    model_class = ReviewerPageResultRow

    async def create_page_result(
        self,
        *,
        reviewer_run_id: UUID,
        lp_documents_id: UUID,
        page_number: int,
        review_status: str,
        review_error: str | None,
        extracted_text_char_count: int,
        summary: str,
        strengths: list[str],
        issues: list[dict[str, object]],
        recommendations: list[str],
        verdict: str | None,
        confidence: float | None,
        metadata: dict[str, object],
    ) -> ReviewerPageResultRow:
        row = ReviewerPageResultRow(
            reviewer_run_id=reviewer_run_id,
            lp_documents_id=lp_documents_id,
            page_number=page_number,
            review_status=review_status,
            review_error=review_error,
            extracted_text_char_count=extracted_text_char_count,
            summary=summary,
            strengths_json=strengths,
            issues_json=issues,
            recommendations_json=recommendations,
            verdict=verdict,
            confidence=confidence,
            metadata_json=metadata,
        )
        self._session.add(row)
        await self._session.flush()
        _LOG.debug(
            "Created reviewer page row: id=%s run_id=%s page_number=%s status=%s",
            row.id,
            row.reviewer_run_id,
            row.page_number,
            row.review_status,
        )
        return row

    async def list_by_run_id(self, reviewer_run_id: UUID) -> list[ReviewerPageResultRow]:
        stmt = (
            select(ReviewerPageResultRow)
            .where(ReviewerPageResultRow.reviewer_run_id == reviewer_run_id)
            .order_by(ReviewerPageResultRow.page_number.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())
