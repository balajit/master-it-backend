from __future__ import annotations

from sqlalchemy import select

from learning_platform.infrastructure.persistence.models.pipeline_log import PipelineLogRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository


class PipelineLogRepository(BaseRepository[PipelineLogRow]):
    model_class = PipelineLogRow

    async def has_success_by_source(self, source: str) -> bool:
        """Return ``True`` if a pipeline-level success log exists for *source*."""
        stmt = (
            select(PipelineLogRow.id)
            .where(PipelineLogRow.source == source)
            .where(PipelineLogRow.stage == "pipeline")
            .where(PipelineLogRow.result == "success")
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None
