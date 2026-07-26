"""LearningPlatformService — a callable Python service for the host application.

Instead of proxying HTTP requests through ASGI transport (which creates a
duplicate app instance with a separate cache), the host app imports and calls
this service directly.  Both apps share the same ``pipeline_cache`` singleton
because they run in the same process.

Usage (in ``src/routers/documents.py``)::

    from learning_platform.service import LearningPlatformService, get_service

    # Trigger pipeline processing
    result = await get_service().process(file_path)

    # Read cached results
    result = get_service().get_cached(doc_id)
    units  = get_service().get_units(doc_id)
    ...
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.api.deps import get_pipeline_orchestrator
from learning_platform.cache import pipeline_cache
from learning_platform.pipeline.orchestrator import PipelineResult

_LOG = logging.getLogger(__name__)


def stable_doc_id(file_path: str) -> str:
    """Derive a stable, deterministic document ID from the resolved file path.

    Uses a SHA-256 hex digest of the absolute path so the same file always
    produces the same ID regardless of how the caller supplied the path.
    The host app should use this function to compute the LP doc ID that
    corresponds to a given uploaded file — no more ID mismatch between
    ``src/`` and ``learning_platform``.
    """
    resolved = str(Path(file_path).resolve())
    return hashlib.sha256(resolved.encode()).hexdigest()


class LearningPlatformService:
    """Thin service facade over the pipeline orchestrator and cache.

    Instantiated once per process (see ``get_service()``).  The host app
    calls methods here rather than proxying HTTP requests to the LP sub-app.
    """

    async def process(
        self,
        file_path: str,
        session: AsyncSession | None = None,
    ) -> PipelineResult:
        """Run the full pipeline on *file_path* and cache the result.

        Parameters
        ----------
        file_path:
            Absolute (or UPLOAD_PATH-relative) path to the document.
        session:
            Optional async DB session.  When provided, the pipeline result is
            persisted immediately.  When ``None``, only the cache is populated.

        Returns
        -------
        PipelineResult
            The complete pipeline output (document, units, concepts, graph,
            study plan, pages, events).
        """
        from uuid import UUID

        from learning_platform.infrastructure.persistence.repositories.annotation import (
            AnnotationRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.concept import (
            ConceptRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.document import (
            DocumentRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.knowledge_graph import (
            KnowledgeGraphRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.learning_unit import (
            LearningUnitRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.sequence import (
            StudyPlanRepository,
        )

        orchestrator = get_pipeline_orchestrator()
        result: PipelineResult = await asyncio.to_thread(orchestrator.run, file_path)

        doc_id_str = stable_doc_id(file_path)
        doc_id_uuid = UUID(doc_id_str[:32])

        pipeline_cache.set(str(doc_id_uuid), result)
        _LOG.info("Pipeline result cached for doc_id=%s (file=%s)", doc_id_uuid, file_path)

        if session is not None:
            doc_repo = DocumentRepository(session)
            unit_repo = LearningUnitRepository(session)
            ann_repo = AnnotationRepository(session)
            concept_repo = ConceptRepository(session)
            graph_repo = KnowledgeGraphRepository(session)
            plan_repo = StudyPlanRepository(session)

            await doc_repo.save_document(result.document)
            await unit_repo.save_all_units(result.units, doc_id_uuid)
            await ann_repo.save_all_annotations(result.annotations, doc_id_uuid)
            await concept_repo.save_concept_map(result.concepts, doc_id_uuid)
            await graph_repo.save_graph(result.graph, doc_id_uuid)
            await plan_repo.save_plan(result.study_plan, doc_id_uuid)
            await session.commit()
            _LOG.info("Pipeline result persisted for doc_id=%s", doc_id_str)

        return result

    def get_cached(self, doc_id: str) -> PipelineResult | None:
        """Return the cached ``PipelineResult`` for *doc_id*, or ``None``."""
        return pipeline_cache.get(doc_id)

    def is_processed(self, doc_id: str) -> bool:
        """Return ``True`` if the document has a cached pipeline result."""
        return pipeline_cache.get(doc_id) is not None

    def list_processed(self) -> list[str]:
        """Return all document IDs with cached pipeline results."""
        return pipeline_cache.keys()


# ── Module-level singleton ───────────────────────────────────────────────────

_service: LearningPlatformService | None = None


def get_service() -> LearningPlatformService:
    """Return the singleton ``LearningPlatformService`` instance."""
    global _service
    if _service is None:
        _service = LearningPlatformService()
    return _service
