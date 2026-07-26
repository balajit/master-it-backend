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

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from learning_platform.models.page_context import PageContext, build_page_contexts
from learning_platform.pipeline.event_bus import EventBus, SimpleEventBus
from learning_platform.pipeline.events import EventType, PipelineEvent
from learning_platform.pipeline.plugins import PluginRegistry
from learning_platform.pipeline.retry import RetryPolicy, RetryResult, with_retry

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
        self._pipeline_id = uuid4()
        self._events: list[PipelineEvent] = []
        self._retry_results: dict[str, RetryResult] = {}
        self._event_bus.subscribe(self._capture_event)

    def run(self, source: str) -> PipelineResult:
        """Execute the full pipeline from source file to study plan.

        Uses page-based processing: after normalization, nodes are grouped
        by page into ``PageContext`` objects.  The enricher, unit builder,
        and concept extractor all operate on page-level groupings.
        """
        self._emit(EventType.PIPELINE_STARTED, "pipeline", {"source": source})
        _LOG.info("Pipeline started: %s", source)
        pipeline_start = time.monotonic()

        try:
            document = self._run_stage("parser", self._parser.parse, source)

            document = self._run_stage("normalizer", self._normalizer.normalize, document)

            # Build page contexts from normalized document
            pages = self._run_stage("page_grouping", build_page_contexts, document)

            # Page-aware enrichment
            pages = self._run_stage("enricher", self._enricher.enrich_pages, pages)

            # Page-aware unit building
            units = self._run_stage("unit_builder", self._unit_builder.build_pages, pages)

            # Page-aware concept extraction
            concepts = self._run_stage(
                "concept_extractor",
                self._concept_extractor.extract_pages,
                pages,
                units,
            )

            graph = self._run_stage("graph_builder", self._graph_builder.build, units, concepts)

            study_plan = self._run_stage("sequence_builder", self._sequence_builder.build, graph)

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
                events=list(self._events),
                retry_results=dict(self._retry_results),
            )

        except Exception as exc:
            self._emit(
                EventType.PIPELINE_FAILED,
                "pipeline",
                {"error": str(exc)},
            )
            raise

    def _run_stage(self, stage_name: str, fn: Any, *args: Any) -> Any:
        """Run a single stage with logging, events, and optional retry."""
        self._emit(
            EventType.STAGE_STARTED,
            stage_name,
            {"stage": stage_name},
        )
        _LOG.info("Stage: %s — started", stage_name)
        stage_start = time.monotonic()

        if self._retry_policy is not None and self._retry_policy.max_retries > 0:
            retrier = with_retry(
                fn,
                policy=self._retry_policy,
                stage_name=stage_name,
                event_fn=self._event_bus.publish,
            )
            result: RetryResult = retrier(*args)
            self._retry_results[stage_name] = result

            if result.error is not None:
                self._emit(
                    EventType.STAGE_FAILED,
                    stage_name,
                    {
                        "error": str(result.error),
                        "attempts": result.attempts,
                        "elapsed_seconds": result.total_seconds,
                    },
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
        )
        _LOG.info("Stage: %s — completed in %.3fs", stage_name, elapsed)

        return value

    def _emit(self, event_type: EventType, stage: str, data: dict[str, Any]) -> None:
        """Create and publish a pipeline event."""
        event = PipelineEvent(
            event_type=event_type,
            stage=stage,
            data=data,
            pipeline_id=self._pipeline_id,
        )
        self._event_bus.publish(event)
        self._plugin_registry.dispatch(event)

    def _capture_event(self, event: PipelineEvent) -> None:
        """Bus listener that records all events (including those from retries)."""
        if event not in self._events:
            self._events.append(event)
