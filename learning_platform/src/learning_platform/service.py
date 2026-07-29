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
from learning_platform.pipeline.events import EventType, PipelineEvent
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
        document_process_id: int | None = None,
    ) -> PipelineResult:
        """Run the full pipeline on *file_path* and cache the result.

        Parameters
        ----------
        file_path:
            Absolute (or UPLOAD_PATH-relative) path to the document.
        session:
            Optional async DB session.  When provided, the pipeline result is
            persisted immediately.  When ``None``, only the cache is populated.
        document_process_id:
            Optional ``lp_document_process`` ID to link pipeline logs to.

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
        from learning_platform.infrastructure.persistence.repositories.pipeline_log import (
            PipelineLogRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.sequence import (
            StudyPlanRepository,
        )

        orchestrator = get_pipeline_orchestrator()

        # ── Duplicate check ──────────────────────────────────────────────
        if session is not None:
            source_name = Path(file_path).name
            log_repo = PipelineLogRepository(session)
            already_done = await log_repo.has_success_by_source(source_name)
            if already_done:
                doc_id_str = stable_doc_id(file_path)
                doc_id_uuid = UUID(doc_id_str[:32])
                cached = pipeline_cache.get(str(doc_id_uuid))
                if cached is not None:
                    _LOG.info("Skipping already-processed file (cache hit): %s", file_path)
                    return cached
                _LOG.info("Skipping already-processed file, re-caching: %s", file_path)
                run_async = getattr(orchestrator, "run_async", None)
                if run_async is not None and asyncio.iscoroutinefunction(run_async):
                    maybe_result = run_async(file_path)
                    result = (
                        await maybe_result if asyncio.iscoroutine(maybe_result) else maybe_result
                    )
                else:
                    result = await asyncio.to_thread(orchestrator.run, file_path)
                pipeline_cache.set(str(doc_id_uuid), result)
                return result

        collected: list[PipelineEvent] = []
        active_pipeline_id: str | None = None

        def collector(event: PipelineEvent) -> None:
            nonlocal active_pipeline_id
            if (
                event.event_type == EventType.PIPELINE_STARTED
                and event.data.get("source") == file_path
            ):
                active_pipeline_id = str(event.pipeline_id)
            if active_pipeline_id is None:
                return
            if str(event.pipeline_id) != active_pipeline_id:
                return
            collected.append(event)

        orchestrator._event_bus.subscribe(collector)
        try:
            run_async = getattr(orchestrator, "run_async", None)
            if run_async is not None and asyncio.iscoroutinefunction(run_async):
                maybe_result = run_async(file_path)
                result = await maybe_result if asyncio.iscoroutine(maybe_result) else maybe_result
            else:
                result = await asyncio.to_thread(orchestrator.run, file_path)
        except Exception:
            if session is not None and collected:
                await self._persist_pipeline_logs(
                    collected,
                    session,
                    file_path,
                    document_process_id=document_process_id,
                )
                await session.commit()
            raise
        finally:
            orchestrator._event_bus.unsubscribe(collector)

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

            await doc_repo.save_document(result.document, doc_id=doc_id_uuid)
            await unit_repo.save_all_units(result.units, doc_id_uuid)
            await ann_repo.save_all_annotations(result.annotations, doc_id_uuid)
            await concept_repo.save_concept_map(result.concepts, doc_id_uuid)
            await graph_repo.save_graph(result.graph, doc_id_uuid)
            await plan_repo.save_plan(result.study_plan, doc_id_uuid)

            if collected:
                await self._persist_pipeline_logs(
                    collected,
                    session,
                    file_path,
                    document_process_id=document_process_id,
                )

            await session.commit()
            _LOG.info("Pipeline result persisted for doc_id=%s", doc_id_str)

        return result

    async def _persist_pipeline_logs(
        self,
        events: list[PipelineEvent],
        session: AsyncSession,
        file_path: str,
        document_process_id: int | None = None,
    ) -> None:
        from learning_platform.infrastructure.persistence.models.pipeline_log import (
            PipelineLogRow,
        )
        from learning_platform.infrastructure.persistence.repositories.pipeline_log import (
            PipelineLogRepository,
        )

        repo = PipelineLogRepository(session)
        source: str = Path(file_path).name
        rows: list[PipelineLogRow] = []

        for event in events:
            if event.event_type == EventType.STAGE_COMPLETED:
                rows.append(
                    PipelineLogRow(
                        source=source,
                        stage=event.stage,
                        output=str(event.data.get("elapsed_seconds", "")),
                        result="success",
                        document_process_id=document_process_id,
                    )
                )
            elif event.event_type == EventType.STAGE_FAILED:
                rows.append(
                    PipelineLogRow(
                        source=source,
                        stage=event.stage,
                        output=str(event.data.get("error", "")),
                        result="error",
                        document_process_id=document_process_id,
                    )
                )
            elif event.event_type == EventType.PIPELINE_COMPLETED:
                rows.append(
                    PipelineLogRow(
                        source=source,
                        stage="pipeline",
                        output=str(event.data.get("elapsed_seconds", "")),
                        result="success",
                        document_process_id=document_process_id,
                    )
                )
            elif event.event_type == EventType.PIPELINE_FAILED:
                rows.append(
                    PipelineLogRow(
                        source=source,
                        stage="pipeline",
                        output=str(event.data.get("error", "")),
                        result="error",
                        document_process_id=document_process_id,
                    )
                )

        if rows:
            await repo.save_all(rows)
            _LOG.info("Persisted %d pipeline log rows for source=%s", len(rows), source)

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
