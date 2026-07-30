"""Pipeline orchestrator — composes stages into a sequential processing chain.

The orchestrator accepts all stage dependencies via constructor injection
(Dependency Inversion).  Each stage execution is wrapped with:

* **Logging** — progress is logged at INFO level.
* **Events** — ``PipelineEvent`` instances are published before and after
  every stage call via the ``EventBus``.
* **Retries** — each stage call can be wrapped with a ``RetryPolicy``.
  Failures trigger automatic retry with exponential backoff.
* **Plugins** — registered ``PipelinePlugin`` instances receive every
  event and can react (metrics, validation, side-effects).

Page-based pipeline:
    Parser → CanonicalDocument
    Normalizer → CanonicalDocument
    build_page_contexts → list[PageContext]
    Enricher.enrich_pages → pages (annotations populated)
    UnitBuilder.build_pages → units (from page-level headings)
    ConceptExtractor.extract_pages → ConceptMap (from page-level text)
    GraphBuilder → KnowledgeGraph
    SequenceBuilder → StudyPlan
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from learning_platform.models.page_context import PageContext, build_page_contexts
from learning_platform.pipeline.event_bus import EventBus, SimpleEventBus
from learning_platform.pipeline.events import EventType, PipelineEvent
from learning_platform.pipeline.plugins import PluginRegistry
from learning_platform.pipeline.retry import (
    RetryPolicy,
    RetryResult,
    with_retry,
    with_retry_async,
)

if TYPE_CHECKING:
    from learning_platform.models.annotation import Annotation
    from learning_platform.models.concept import ConceptMap
    from learning_platform.models.document import CanonicalDocument
    from learning_platform.models.knowledge_graph import KnowledgeGraph
    from learning_platform.models.learning_unit import LearningUnit
    from learning_platform.models.sequence import StudyPlan
    from learning_platform.pipeline.base import (
        AbstractParser,
        ConceptExtractor,
        KnowledgeGraphBuilder,
        LearningSequenceBuilder,
        LearningUnitBuilder,
        SemanticEnricher,
        StructuralNormalizer,
    )

_LOG = logging.getLogger(__name__)

_RESUME_START_STAGES: tuple[str, ...] = (
    "parser",
    "page_grouping",
    "graph_builder",
    "sequence_builder",
)


@dataclass(frozen=True)
class PipelineResult:
    """Complete output of the processing pipeline."""

    document: CanonicalDocument
    annotations: list[Annotation]
    units: list[LearningUnit]
    concepts: ConceptMap
    graph: KnowledgeGraph
    study_plan: StudyPlan
    pages: list[PageContext] = field(default_factory=list)
    events: list[PipelineEvent] = field(default_factory=list)
    retry_results: dict[str, RetryResult] = field(default_factory=dict)


@dataclass
class _RunState:
    """Mutable state scoped to a single pipeline execution."""

    pipeline_id: UUID
    events: list[PipelineEvent] = field(default_factory=list)
    retry_results: dict[str, RetryResult] = field(default_factory=dict)


class PipelineOrchestrator:
    """Composes pipeline stages and executes them in order.

    All stage dependencies are injected via the constructor.
    No concrete implementations are imported here — only Protocols.
    """

    def __init__(
        self,
        parser: AbstractParser,
        normalizer: StructuralNormalizer,
        enricher: SemanticEnricher,
        unit_builder: LearningUnitBuilder,
        concept_extractor: ConceptExtractor,
        graph_builder: KnowledgeGraphBuilder,
        sequence_builder: LearningSequenceBuilder,
        event_bus: EventBus | None = None,
        plugin_registry: PluginRegistry | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._parser = parser
        self._normalizer = normalizer
        self._enricher = enricher
        self._unit_builder = unit_builder
        self._concept_extractor = concept_extractor
        self._graph_builder = graph_builder
        self._sequence_builder = sequence_builder
        self._event_bus = event_bus or SimpleEventBus()
        self._plugin_registry = plugin_registry or PluginRegistry()
        self._retry_policy = retry_policy

    def run(self, source: str) -> PipelineResult:
        """Execute the full pipeline from source file to study plan.

        Uses page-based processing: after normalization, nodes are grouped
        by page into ``PageContext`` objects.  The enricher, unit builder,
        and concept extractor all operate on page-level groupings.
        """
        run_state = _RunState(pipeline_id=uuid4())
        collector = self._make_event_collector(run_state)
        self._event_bus.subscribe(collector)

        self._emit(
            EventType.PIPELINE_STARTED, "pipeline", {"source": source}, run_state.pipeline_id
        )
        _LOG.info("Pipeline started: %s", source)
        pipeline_start = time.monotonic()

        try:
            document = self._run_stage("parser", self._parser.parse, run_state, source)

            document = self._run_stage(
                "normalizer", self._normalizer.normalize, run_state, document
            )

            # Build page contexts from normalized document
            pages = self._run_stage("page_grouping", build_page_contexts, run_state, document)

            # Page-aware enrichment
            pages = self._run_stage("enricher", self._enricher.enrich_pages, run_state, pages)

            # Page-aware unit building
            units = self._run_stage(
                "unit_builder", self._unit_builder.build_pages, run_state, pages
            )

            # Page-aware concept extraction
            concepts = self._run_stage(
                "concept_extractor",
                self._concept_extractor.extract_pages,
                run_state,
                pages,
                units,
            )

            graph = self._run_stage(
                "graph_builder", self._graph_builder.build, run_state, units, concepts
            )

            study_plan = self._run_stage(
                "sequence_builder", self._sequence_builder.build, run_state, graph
            )

            # Aggregate annotations from all pages
            annotations: list[Annotation] = [ann for p in pages for ann in p.annotations]

            elapsed = time.monotonic() - pipeline_start
            self._emit(
                EventType.PIPELINE_COMPLETED,
                "pipeline",
                {
                    "pages": len(pages),
                    "units": len(units),
                    "concepts": len(concepts.concepts),
                    "graph_nodes": len(graph.nodes),
                    "lessons": study_plan.total_lessons,
                    "elapsed_seconds": elapsed,
                },
                run_state.pipeline_id,
            )

            _LOG.info(
                "Pipeline complete: %d pages, %d units, %d concepts, %d graph nodes, %d lessons",
                len(pages),
                len(units),
                len(concepts.concepts),
                len(graph.nodes),
                study_plan.total_lessons,
            )

            return PipelineResult(
                document=document,
                annotations=annotations,
                units=units,
                concepts=concepts,
                graph=graph,
                study_plan=study_plan,
                pages=pages,
                events=list(run_state.events),
                retry_results=dict(run_state.retry_results),
            )

        except Exception as exc:
            self._emit(
                EventType.PIPELINE_FAILED,
                "pipeline",
                {"error": str(exc)},
                run_state.pipeline_id,
            )
            raise
        finally:
            self._event_bus.unsubscribe(collector)

    async def run_async(self, source: str) -> PipelineResult:
        """Async variant of ``run`` using non-blocking retries and stage execution.

        Parameters
        ----------
        source:
            Input file path.
        start_stage:
            Resume entry stage. Supported values are
            ``parser``, ``page_grouping``, ``graph_builder``, and
            ``sequence_builder``.
        resume_document:
            Normalized document checkpoint for resume runs.
        resume_units:
            Unit checkpoint for graph/sequence resume runs.
        resume_annotations:
            Annotation checkpoint for graph/sequence resume runs.
        resume_concepts:
            Concept checkpoint for graph/sequence resume runs.
        resume_graph:
            Graph checkpoint for sequence-only resume runs.
        checkpoint_hook:
            Optional callback invoked after key checkpoints are produced.
        """
        return await self._run_async_internal(source)

    async def run_async_resumable(
        self,
        source: str,
        *,
        start_stage: str = "parser",
        resume_document: CanonicalDocument | None = None,
        resume_units: list[LearningUnit] | None = None,
        resume_annotations: list[Annotation] | None = None,
        resume_concepts: ConceptMap | None = None,
        resume_graph: KnowledgeGraph | None = None,
        checkpoint_hook: (Callable[[str, dict[str, Any]], Awaitable[None] | None] | None) = None,
    ) -> PipelineResult:
        """Run asynchronously with optional stateful resume checkpoints."""
        return await self._run_async_internal(
            source,
            start_stage=start_stage,
            resume_document=resume_document,
            resume_units=resume_units,
            resume_annotations=resume_annotations,
            resume_concepts=resume_concepts,
            resume_graph=resume_graph,
            checkpoint_hook=checkpoint_hook,
        )

    async def _run_async_internal(
        self,
        source: str,
        *,
        start_stage: str = "parser",
        resume_document: CanonicalDocument | None = None,
        resume_units: list[LearningUnit] | None = None,
        resume_annotations: list[Annotation] | None = None,
        resume_concepts: ConceptMap | None = None,
        resume_graph: KnowledgeGraph | None = None,
        checkpoint_hook: (Callable[[str, dict[str, Any]], Awaitable[None] | None] | None) = None,
    ) -> PipelineResult:
        """Internal async runner shared by fresh and resumable paths."""
        if start_stage not in _RESUME_START_STAGES:
            allowed = ", ".join(_RESUME_START_STAGES)
            raise ValueError(f"Unsupported start_stage '{start_stage}'. Allowed: {allowed}")

        run_state = _RunState(pipeline_id=uuid4())
        collector = self._make_event_collector(run_state)
        self._event_bus.subscribe(collector)

        self._emit(
            EventType.PIPELINE_STARTED, "pipeline", {"source": source}, run_state.pipeline_id
        )
        _LOG.info("Pipeline started: %s", source)
        pipeline_start = time.monotonic()

        try:
            pages: list[PageContext] = []

            if start_stage == "parser":
                document = await self._run_stage_async(
                    "parser", self._parser.parse, run_state, source
                )

                document = await self._run_stage_async(
                    "normalizer",
                    self._normalizer.normalize,
                    run_state,
                    document,
                )
                await self._invoke_checkpoint_hook(
                    checkpoint_hook,
                    "normalizer",
                    {"document": document},
                )

                pages = await self._run_stage_async(
                    "page_grouping", build_page_contexts, run_state, document
                )

                pages = await self._run_stage_async(
                    "enricher", self._enricher.enrich_pages, run_state, pages
                )

                units = await self._run_stage_async(
                    "unit_builder", self._unit_builder.build_pages, run_state, pages
                )

                concepts = await self._run_stage_async(
                    "concept_extractor",
                    self._concept_extractor.extract_pages,
                    run_state,
                    pages,
                    units,
                )

                annotations = [ann for p in pages for ann in p.annotations]
                await self._invoke_checkpoint_hook(
                    checkpoint_hook,
                    "concept_extractor",
                    {
                        "document": document,
                        "units": units,
                        "annotations": annotations,
                        "concepts": concepts,
                    },
                )
            elif start_stage == "page_grouping":
                if resume_document is None:
                    raise ValueError("resume_document is required when start_stage=page_grouping")

                document = resume_document
                pages = await self._run_stage_async(
                    "page_grouping", build_page_contexts, run_state, document
                )

                pages = await self._run_stage_async(
                    "enricher", self._enricher.enrich_pages, run_state, pages
                )

                units = await self._run_stage_async(
                    "unit_builder", self._unit_builder.build_pages, run_state, pages
                )

                concepts = await self._run_stage_async(
                    "concept_extractor",
                    self._concept_extractor.extract_pages,
                    run_state,
                    pages,
                    units,
                )

                annotations = [ann for p in pages for ann in p.annotations]
                await self._invoke_checkpoint_hook(
                    checkpoint_hook,
                    "concept_extractor",
                    {
                        "document": document,
                        "units": units,
                        "annotations": annotations,
                        "concepts": concepts,
                    },
                )
            elif start_stage == "graph_builder":
                if resume_document is None:
                    raise ValueError("resume_document is required when start_stage=graph_builder")
                if resume_units is None or resume_concepts is None:
                    raise ValueError(
                        "resume_units and resume_concepts are required when start_stage=graph_builder"
                    )

                document = resume_document
                units = list(resume_units)
                concepts = resume_concepts
                annotations = list(resume_annotations or [])
            else:
                if resume_document is None:
                    raise ValueError(
                        "resume_document is required when start_stage=sequence_builder"
                    )
                if resume_units is None or resume_concepts is None or resume_graph is None:
                    raise ValueError(
                        "resume_units, resume_concepts, and resume_graph are required when start_stage=sequence_builder"
                    )

                document = resume_document
                units = list(resume_units)
                concepts = resume_concepts
                annotations = list(resume_annotations or [])

            if start_stage != "sequence_builder":
                graph = await self._run_stage_async(
                    "graph_builder",
                    self._graph_builder.build,
                    run_state,
                    units,
                    concepts,
                )
                await self._invoke_checkpoint_hook(
                    checkpoint_hook,
                    "graph_builder",
                    {
                        "document": document,
                        "units": units,
                        "annotations": annotations,
                        "concepts": concepts,
                        "graph": graph,
                    },
                )
            else:
                graph = resume_graph
                assert graph is not None

            study_plan = await self._run_stage_async(
                "sequence_builder",
                self._sequence_builder.build,
                run_state,
                graph,
            )

            elapsed = time.monotonic() - pipeline_start
            self._emit(
                EventType.PIPELINE_COMPLETED,
                "pipeline",
                {
                    "pages": len(pages),
                    "units": len(units),
                    "concepts": len(concepts.concepts),
                    "graph_nodes": len(graph.nodes),
                    "lessons": study_plan.total_lessons,
                    "elapsed_seconds": elapsed,
                },
                run_state.pipeline_id,
            )

            _LOG.info(
                "Pipeline complete: %d pages, %d units, %d concepts, %d graph nodes, %d lessons",
                len(pages),
                len(units),
                len(concepts.concepts),
                len(graph.nodes),
                study_plan.total_lessons,
            )

            return PipelineResult(
                document=document,
                annotations=annotations,
                units=units,
                concepts=concepts,
                graph=graph,
                study_plan=study_plan,
                pages=pages,
                events=list(run_state.events),
                retry_results=dict(run_state.retry_results),
            )

        except Exception as exc:
            self._emit(
                EventType.PIPELINE_FAILED,
                "pipeline",
                {"error": str(exc)},
                run_state.pipeline_id,
            )
            raise
        finally:
            self._event_bus.unsubscribe(collector)

    @staticmethod
    async def _invoke_checkpoint_hook(
        checkpoint_hook: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None,
        stage_name: str,
        payload: dict[str, Any],
    ) -> None:
        if checkpoint_hook is None:
            return
        maybe_awaitable = checkpoint_hook(stage_name, payload)
        if asyncio.iscoroutine(maybe_awaitable):
            await maybe_awaitable

    def _run_stage(self, stage_name: str, fn: Any, run_state: _RunState, *args: Any) -> Any:
        """Run a single stage with logging, events, and optional retry."""
        self._emit(
            EventType.STAGE_STARTED,
            stage_name,
            {"stage": stage_name},
            run_state.pipeline_id,
        )
        _LOG.info("Stage: %s — started", stage_name)
        stage_start = time.monotonic()

        if self._retry_policy is not None and self._retry_policy.max_retries > 0:
            retrier = with_retry(
                fn,
                policy=self._retry_policy,
                stage_name=stage_name,
                event_fn=self._event_bus.publish,
                pipeline_id=run_state.pipeline_id,
            )
            result: RetryResult = retrier(*args)
            run_state.retry_results[stage_name] = result

            if result.error is not None:
                self._emit(
                    EventType.STAGE_FAILED,
                    stage_name,
                    {
                        "error": str(result.error),
                        "attempts": result.attempts,
                        "elapsed_seconds": result.total_seconds,
                    },
                    run_state.pipeline_id,
                )
                raise result.error

            value = result.value
        else:
            value = fn(*args)

        elapsed = time.monotonic() - stage_start
        self._emit(
            EventType.STAGE_COMPLETED,
            stage_name,
            {"elapsed_seconds": elapsed},
            run_state.pipeline_id,
        )
        _LOG.info("Stage: %s — completed in %.3fs", stage_name, elapsed)

        return value

    async def _run_stage_async(
        self,
        stage_name: str,
        fn: Any,
        run_state: _RunState,
        *args: Any,
    ) -> Any:
        """Run a single stage asynchronously with non-blocking retries."""
        self._emit(
            EventType.STAGE_STARTED,
            stage_name,
            {"stage": stage_name},
            run_state.pipeline_id,
        )
        _LOG.info("Stage: %s — started", stage_name)
        stage_start = time.monotonic()

        if self._retry_policy is not None and self._retry_policy.max_retries > 0:
            retrier = with_retry_async(
                fn,
                policy=self._retry_policy,
                stage_name=stage_name,
                event_fn=self._event_bus.publish,
                pipeline_id=run_state.pipeline_id,
            )
            result: RetryResult = await retrier(*args)
            run_state.retry_results[stage_name] = result

            if result.error is not None:
                self._emit(
                    EventType.STAGE_FAILED,
                    stage_name,
                    {
                        "error": str(result.error),
                        "attempts": result.attempts,
                        "elapsed_seconds": result.total_seconds,
                    },
                    run_state.pipeline_id,
                )
                raise result.error

            value = result.value
        else:
            value = await asyncio.to_thread(fn, *args)

        elapsed = time.monotonic() - stage_start
        self._emit(
            EventType.STAGE_COMPLETED,
            stage_name,
            {"elapsed_seconds": elapsed},
            run_state.pipeline_id,
        )
        _LOG.info("Stage: %s — completed in %.3fs", stage_name, elapsed)

        return value

    def _emit(
        self,
        event_type: EventType,
        stage: str,
        data: dict[str, Any],
        pipeline_id: UUID,
    ) -> None:
        """Create and publish a pipeline event."""
        event = PipelineEvent(
            event_type=event_type,
            stage=stage,
            data=data,
            pipeline_id=pipeline_id,
        )
        self._event_bus.publish(event)
        self._plugin_registry.dispatch(event)

    def _make_event_collector(self, run_state: _RunState) -> Any:
        """Return a run-scoped collector that captures only matching pipeline events."""

        def _capture_event(event: PipelineEvent) -> None:
            if event.pipeline_id != run_state.pipeline_id:
                return
            if event not in run_state.events:
                run_state.events.append(event)

        return _capture_event
