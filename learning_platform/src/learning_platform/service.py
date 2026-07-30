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
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.api.deps import get_pipeline_orchestrator, get_session_factory
from learning_platform.cache import pipeline_cache
from learning_platform.pipeline.events import EventType, PipelineEvent
from learning_platform.pipeline.orchestrator import PipelineOrchestrator, PipelineResult

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
        *,
        orchestrator: PipelineOrchestrator | None = None,
        doc_id: UUID | None = None,
        owner_sub: str | None = None,
        dedupe_by_source: bool = True,
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
        orchestrator:
            Optional orchestrator override, used by API tests and DI paths.
        doc_id:
            Optional document ID to use as the cache and persistence key.
        owner_sub:
            Optional owner subject to persist on the canonical document row.
        dedupe_by_source:
            When ``True``, allow source-name dedupe based on pipeline logs.

        Returns
        -------
        PipelineResult
            The complete pipeline output (document, units, concepts, graph,
            study plan, pages, events).
        """
        from learning_platform.infrastructure.persistence.repositories.annotation import (
            AnnotationRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.concept import (
            ConceptRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.document import (
            DocumentRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
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

        orchestrator = orchestrator or get_pipeline_orchestrator()
        doc_id_uuid: UUID = doc_id or UUID(stable_doc_id(file_path)[:32])

        # ── Duplicate check ──────────────────────────────────────────────
        if session is not None and dedupe_by_source:
            source_name = Path(file_path).name
            log_repo = PipelineLogRepository(session)
            already_done = await log_repo.has_success_by_source(source_name)
            if already_done:
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

        event_bus = getattr(orchestrator, "_event_bus", None)
        subscribed = False
        if event_bus is not None and hasattr(event_bus, "subscribe"):
            event_bus.subscribe(collector)
            subscribed = True
        try:
            run_async = getattr(orchestrator, "run_async", None)
            resume_row: Any | None = None
            proc_repo_for_run = None
            if session is not None and document_process_id is not None:
                proc_repo_for_run = DocumentProcessRepository(session)
                resume_row = await proc_repo_for_run.find_by_id(document_process_id)

            resume_start_stage = "parser"
            resume_document = None
            resume_units = None
            resume_annotations = None
            resume_concepts = None
            resume_graph = None

            if (
                proc_repo_for_run is not None
                and resume_row is not None
                and resume_row.run_mode in {"retry", "reprocess"}
            ):
                resume_start_stage, resume_payload = proc_repo_for_run.resolve_resume_from_row(
                    resume_row
                )
                (
                    resume_document,
                    resume_units,
                    resume_annotations,
                    resume_concepts,
                    resume_graph,
                ) = await self._restore_resume_payload(
                    resume_payload,
                    expected_stage=resume_start_stage,
                )
                if resume_start_stage != "parser" and resume_document is None:
                    _LOG.warning(
                        "Resume payload missing for process_id=%s; restarting from parser",
                        document_process_id,
                    )
                    resume_start_stage = "parser"

                    if proc_repo_for_run is not None and resume_row is not None:
                        await proc_repo_for_run.update_resume_state(resume_row, resume_state=None)

            if run_async is not None and asyncio.iscoroutinefunction(run_async):
                run_async_resumable = getattr(orchestrator, "run_async_resumable", None)
                if run_async_resumable is not None and asyncio.iscoroutinefunction(
                    run_async_resumable
                ):
                    maybe_result = run_async_resumable(
                        file_path,
                        start_stage=resume_start_stage,
                        resume_document=resume_document,
                        resume_units=resume_units,
                        resume_annotations=resume_annotations,
                        resume_concepts=resume_concepts,
                        resume_graph=resume_graph,
                        checkpoint_hook=(
                            self._make_checkpoint_hook(document_process_id)
                            if document_process_id is not None
                            else None
                        ),
                    )
                else:
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
            if session is not None and document_process_id is not None:
                await self._capture_resume_failure(
                    session,
                    document_process_id=document_process_id,
                    events=collected,
                )
            if session is not None and (collected or document_process_id is not None):
                await session.commit()
            raise
        finally:
            if subscribed and event_bus is not None and hasattr(event_bus, "unsubscribe"):
                event_bus.unsubscribe(collector)

        if session is not None:
            doc_repo = DocumentRepository(session)
            unit_repo = LearningUnitRepository(session)
            ann_repo = AnnotationRepository(session)
            concept_repo = ConceptRepository(session)
            graph_repo = KnowledgeGraphRepository(session)
            plan_repo = StudyPlanRepository(session)

            await self._delete_existing_artifacts(doc_id_uuid, session)

            await doc_repo.save_document(result.document, doc_id=doc_id_uuid, owner_sub=owner_sub)
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

            if document_process_id is not None:
                proc_repo = DocumentProcessRepository(session)
                proc_row = await proc_repo.find_by_id(document_process_id)
                if proc_row is not None:
                    await proc_repo.record_stage_completed(proc_row, "pipeline")
                    await proc_repo.update_resume_state(proc_row, resume_state=None)

            await session.commit()
            _LOG.info("Pipeline result persisted for doc_id=%s", doc_id_uuid)

            pipeline_cache.set(str(doc_id_uuid), result)
            _LOG.info("Pipeline result cached for doc_id=%s (file=%s)", doc_id_uuid, file_path)

            # ── Pipeline 2: Book Assembly entry ──────────────────────────
            from learning_platform.infrastructure.persistence.repositories.book_process import (
                BookProcessRepository,
            )

            book_proc_repo = BookProcessRepository(session)
            existing = await book_proc_repo.find_by_document_id(str(doc_id_uuid))
            if existing is not None:
                await book_proc_repo.reset_entry(existing)
            else:
                await book_proc_repo.create_entry(str(doc_id_uuid))
            await session.commit()
        else:
            pipeline_cache.set(str(doc_id_uuid), result)
            _LOG.info("Pipeline result cached for doc_id=%s (file=%s)", doc_id_uuid, file_path)

        return result

    @staticmethod
    async def _delete_existing_artifacts(doc_id: UUID, session: AsyncSession) -> None:
        from sqlalchemy import delete, select

        from learning_platform.infrastructure.persistence.models.annotation import AnnotationRow
        from learning_platform.infrastructure.persistence.models.concept import (
            ConceptRelationshipRow,
            ConceptRow,
        )
        from learning_platform.infrastructure.persistence.models.knowledge_graph import (
            GraphEdgeRow,
            GraphNodeRow,
            KnowledgeGraphRow,
        )
        from learning_platform.infrastructure.persistence.models.learning_unit import (
            LearningUnitRow,
        )
        from learning_platform.infrastructure.persistence.models.sequence import (
            CheckpointRow,
            LessonRow,
            MilestoneRow,
            StudyPlanRow,
        )

        graph_ids = select(KnowledgeGraphRow.id).where(KnowledgeGraphRow.document_id == doc_id)
        study_plan_ids = select(StudyPlanRow.id).where(StudyPlanRow.document_id == doc_id)

        await session.execute(delete(GraphEdgeRow).where(GraphEdgeRow.graph_id.in_(graph_ids)))
        await session.execute(delete(GraphNodeRow).where(GraphNodeRow.graph_id.in_(graph_ids)))
        await session.execute(
            delete(KnowledgeGraphRow).where(KnowledgeGraphRow.document_id == doc_id)
        )

        await session.execute(
            delete(CheckpointRow).where(CheckpointRow.study_plan_id.in_(study_plan_ids))
        )
        await session.execute(delete(LessonRow).where(LessonRow.study_plan_id.in_(study_plan_ids)))
        await session.execute(
            delete(MilestoneRow).where(MilestoneRow.study_plan_id.in_(study_plan_ids))
        )
        await session.execute(delete(StudyPlanRow).where(StudyPlanRow.document_id == doc_id))

        await session.execute(
            delete(ConceptRelationshipRow).where(ConceptRelationshipRow.document_id == doc_id)
        )
        await session.execute(delete(ConceptRow).where(ConceptRow.document_id == doc_id))
        await session.execute(delete(LearningUnitRow).where(LearningUnitRow.document_id == doc_id))
        await session.execute(delete(AnnotationRow).where(AnnotationRow.document_id == doc_id))

    async def _capture_resume_failure(
        self,
        session: AsyncSession,
        *,
        document_process_id: int,
        events: list[PipelineEvent],
    ) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        if not events:
            return

        proc_repo = DocumentProcessRepository(session)
        proc_row = await proc_repo.find_by_id(document_process_id)
        if proc_row is None:
            return

        failed_stage: str | None = None
        failed_error: str | None = None
        for event in events:
            if event.event_type == EventType.STAGE_FAILED:
                failed_stage = str(event.stage)
                failed_error = str(event.data.get("error", ""))
            elif event.event_type == EventType.STAGE_COMPLETED:
                await proc_repo.record_stage_completed(proc_row, str(event.stage))

        if failed_stage:
            await proc_repo.record_stage_failed(
                proc_row,
                failed_stage,
                failed_error or proc_row.error_message or "Pipeline error, will retry",
            )

    def _make_checkpoint_hook(
        self,
        document_process_id: int,
    ):
        async def _hook(stage_name: str, payload: dict[str, Any]) -> None:
            from learning_platform.infrastructure.persistence.repositories.document_process import (
                DocumentProcessRepository,
            )

            session_factory = get_session_factory()
            async with session_factory() as session:
                proc_repo = DocumentProcessRepository(session)
                proc_row = await proc_repo.find_by_id(document_process_id)
                if proc_row is None:
                    return

                now_iso = datetime.utcnow().isoformat()
                if stage_name == "normalizer":
                    document = payload.get("document")
                    if document is None:
                        return
                    resume_state = {
                        "normalized_document": document.model_dump(mode="json"),
                        "saved_at": now_iso,
                    }
                    await proc_repo.record_stage_completed(proc_row, "normalizer")
                    await proc_repo.update_resume_state(proc_row, resume_state=resume_state)
                elif stage_name == "concept_extractor":
                    document = payload.get("document")
                    units = payload.get("units")
                    annotations = payload.get("annotations")
                    concepts = payload.get("concepts")
                    if (
                        document is None
                        or units is None
                        or annotations is None
                        or concepts is None
                    ):
                        return
                    resume_state = {
                        "normalized_document": document.model_dump(mode="json"),
                        "units": [u.model_dump(mode="json") for u in units],
                        "annotations": [a.model_dump(mode="json") for a in annotations],
                        "concepts": concepts.model_dump(mode="json"),
                        "saved_at": now_iso,
                    }
                    await proc_repo.record_stage_completed(proc_row, "concept_extractor")
                    await proc_repo.update_resume_state(proc_row, resume_state=resume_state)
                elif stage_name == "graph_builder":
                    document = payload.get("document")
                    units = payload.get("units")
                    annotations = payload.get("annotations")
                    concepts = payload.get("concepts")
                    graph = payload.get("graph")
                    if (
                        document is None
                        or units is None
                        or annotations is None
                        or concepts is None
                        or graph is None
                    ):
                        return
                    resume_state = {
                        "normalized_document": document.model_dump(mode="json"),
                        "units": [u.model_dump(mode="json") for u in units],
                        "annotations": [a.model_dump(mode="json") for a in annotations],
                        "concepts": concepts.model_dump(mode="json"),
                        "graph": graph.model_dump(mode="json"),
                        "saved_at": now_iso,
                    }
                    await proc_repo.record_stage_completed(proc_row, "graph_builder")
                    await proc_repo.update_resume_state(proc_row, resume_state=resume_state)

                await session.commit()

        return _hook

    async def _restore_resume_payload(
        self,
        resume_payload: dict[str, Any],
        *,
        expected_stage: str,
    ) -> tuple[
        Any,
        list[Any] | None,
        list[Any] | None,
        Any,
        Any,
    ]:
        from pydantic import TypeAdapter

        from learning_platform.models.annotation import Annotation
        from learning_platform.models.concept import ConceptMap
        from learning_platform.models.document import CanonicalDocument
        from learning_platform.models.knowledge_graph import KnowledgeGraph
        from learning_platform.models.learning_unit import LearningUnit

        document_data = resume_payload.get("normalized_document")
        if document_data is None:
            return None, None, None, None, None

        document = CanonicalDocument.model_validate(document_data)
        document.rebuild_index()

        if expected_stage == "page_grouping":
            return document, None, None, None, None

        units_data = resume_payload.get("units")
        concepts_data = resume_payload.get("concepts")
        if units_data is None or concepts_data is None:
            return None, None, None, None, None

        units = TypeAdapter(list[LearningUnit]).validate_python(units_data)
        annotations = TypeAdapter(list[Annotation]).validate_python(
            resume_payload.get("annotations") or []
        )
        concepts = ConceptMap.model_validate(concepts_data)

        if expected_stage == "graph_builder":
            return document, units, annotations, concepts, None

        graph_data = resume_payload.get("graph")
        if graph_data is None:
            return None, None, None, None, None
        graph = KnowledgeGraph.model_validate(graph_data)
        return document, units, annotations, concepts, graph

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
