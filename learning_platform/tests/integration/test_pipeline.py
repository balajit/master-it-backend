"""Integration tests for the complete pipeline.

Tests run the full pipeline from parsing through study-plan generation
using lightweight stub implementations of each stage.  No external
services (DB, LLM, file system) are required.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from learning_platform.models.annotation import (
    Annotation,
    DefinitionAnnotation,
    ObjectiveAnnotation,
)
from learning_platform.models.concept import Concept, ConceptCategory, ConceptMap
from learning_platform.models.document import (
    BlockStyle,
    BoundingBox,
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Heading,
    HeadingLevel,
    NodeType,
    Paragraph,
    SourceLocation,
    StyledText,
    TextRun,
)
from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
)
from learning_platform.models.knowledge_graph import (
    NodeType as GraphNodeType,
)
from learning_platform.models.learning_unit import Difficulty, LearningUnit, UnitType
from learning_platform.models.sequence import StudyPlan
from learning_platform.pipeline.event_bus import SimpleEventBus
from learning_platform.pipeline.events import EventType, PipelineEvent
from learning_platform.pipeline.orchestrator import PipelineOrchestrator, PipelineResult
from learning_platform.pipeline.plugins import PluginRegistry
from learning_platform.pipeline.retry import RetryPolicy

# ── Stub implementations ─────────────────────────────────────────────────────


class StubParser:
    """Minimal parser that returns a canned document."""

    def __init__(self, document: CanonicalDocument | None = None) -> None:
        self._document = document or _make_document()

    def parse(self, source: str) -> CanonicalDocument:
        return self._document

    def supports(self, source: str) -> bool:
        return True

    def confidence(self, source: str) -> float:
        return 0.9


class StubNormalizer:
    """Pass-through normalizer."""

    def normalize(self, document: CanonicalDocument) -> CanonicalDocument:
        return document


class StubEnricher:
    """Returns the document with a couple of annotations."""

    def __init__(self, annotations: list[Annotation] | None = None) -> None:
        self._annotations = annotations or _make_annotations()

    def enrich(self, document: CanonicalDocument) -> tuple[CanonicalDocument, list[Annotation]]:
        return document, self._annotations

    def enrich_pages(self, pages: list[Any]) -> list[Any]:
        for page in pages:
            page.annotations = list(self._annotations)
        return pages


class StubUnitBuilder:
    """Returns a fixed set of learning units."""

    def __init__(self, units: list[LearningUnit] | None = None) -> None:
        self._units = units or _make_units()

    def build(
        self, document: CanonicalDocument, annotations: list[Annotation]
    ) -> list[LearningUnit]:
        return self._units

    def build_pages(self, pages: list[Any]) -> list[LearningUnit]:
        return self._units


class StubConceptExtractor:
    """Returns a fixed concept map."""

    def __init__(self, concepts: ConceptMap | None = None) -> None:
        self._concepts = concepts or _make_concepts()

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> ConceptMap:
        return self._concepts

    def extract_pages(
        self,
        pages: list[Any],
        units: list[LearningUnit],
    ) -> ConceptMap:
        return self._concepts


class StubGraphBuilder:
    """Returns a fixed knowledge graph."""

    def __init__(self, graph: KnowledgeGraph | None = None) -> None:
        self._graph = graph or _make_graph()

    def build(self, units: list[LearningUnit], concepts: ConceptMap) -> KnowledgeGraph:
        return self._graph


class StubSequenceBuilder:
    """Returns a fixed study plan."""

    def __init__(self, plan: StudyPlan | None = None) -> None:
        self._plan = plan or _make_study_plan()

    def build(self, graph: KnowledgeGraph) -> StudyPlan:
        return self._plan


class FailingParser:
    """Parser that always raises."""

    def parse(self, source: str) -> CanonicalDocument:
        raise RuntimeError("Parse failure")

    def supports(self, source: str) -> bool:
        return True

    def confidence(self, source: str) -> float:
        return 1.0


class FlakyParser:
    """Parser that fails the first N calls then succeeds."""

    def __init__(self, fail_count: int = 1) -> None:
        self._fail_count = fail_count
        self._call_count = 0
        self._document = _make_document()

    def parse(self, source: str) -> CanonicalDocument:
        self._call_count += 1
        if self._call_count <= self._fail_count:
            raise RuntimeError(f"Transient failure #{self._call_count}")
        return self._document

    def supports(self, source: str) -> bool:
        return True

    def confidence(self, source: str) -> float:
        return 1.0


# ── Data factories ───────────────────────────────────────────────────────────


def _text(text: str) -> StyledText:
    return StyledText(runs=[TextRun(text=text)])


def _make_document() -> CanonicalDocument:
    """Create a minimal 3-node document."""
    meta = DocumentMetadata(title="Test Document", author="Test")
    root_id = uuid4()

    h1_node = DocumentNode(
        id=uuid4(),
        node_type=NodeType.HEADING,
        content=Heading(level=HeadingLevel.SECTION, text=_text("Section 1.1")),
        page=1,
        source=SourceLocation(),
        bbox=BoundingBox(x0=0, y0=25, x1=100, y1=45),
        style=BlockStyle(),
        parent_id=root_id,
    )

    p1_node = DocumentNode(
        id=uuid4(),
        node_type=NodeType.PARAGRAPH,
        content=Paragraph(text=_text("Introduction paragraph.")),
        page=1,
        source=SourceLocation(),
        bbox=BoundingBox(x0=0, y0=50, x1=100, y1=70),
        style=BlockStyle(),
        parent_id=root_id,
    )

    root_node = DocumentNode(
        id=root_id,
        node_type=NodeType.HEADING,
        content=Heading(level=HeadingLevel.CHAPTER, text=_text("Chapter 1")),
        page=1,
        source=SourceLocation(),
        bbox=BoundingBox(x0=0, y0=0, x1=100, y1=20),
        style=BlockStyle(),
        children=[h1_node, p1_node],
    )

    nodes = [root_node, h1_node, p1_node]

    return CanonicalDocument(
        metadata=meta,
        nodes=nodes,
        root_id=root_id,
    )


def _make_annotations() -> list[Annotation]:
    """Create two stub annotations."""
    node_id = uuid4()
    return [
        DefinitionAnnotation(
            node_id=node_id,
            term="algorithm",
            definition_text="A step-by-step procedure.",
        ),
        ObjectiveAnnotation(
            node_id=node_id,
            objective="Understand basic algorithms.",
        ),
    ]


def _make_units() -> list[LearningUnit]:
    """Create two stub learning units."""
    u1 = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.LESSON,
        title="Introduction",
        description="First lesson.",
        learning_objectives=["Understand X"],
        difficulty=Difficulty.BASIC,
        estimated_study_time_minutes=10,
    )
    u2 = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.LESSON,
        title="Core Concepts",
        description="Second lesson.",
        learning_objectives=["Apply Y"],
        difficulty=Difficulty.INTERMEDIATE,
        estimated_study_time_minutes=15,
        prerequisite_ids=[u1.id],
    )
    return [u1, u2]


def _make_concepts() -> ConceptMap:
    """Create a stub concept map."""
    c1 = Concept(
        id=uuid4(),
        name="algorithm",
        category=ConceptCategory.CONCEPT,
        importance=0.8,
        mention_count=5,
    )
    c2 = Concept(
        id=uuid4(),
        name="sorting",
        category=ConceptCategory.SKILL,
        importance=0.6,
        mention_count=3,
    )
    return ConceptMap(concepts=[c1, c2])


def _make_graph() -> KnowledgeGraph:
    """Create a stub knowledge graph."""
    u1_id = uuid4()
    u2_id = uuid4()
    c1_id = uuid4()
    return KnowledgeGraph(
        nodes=[
            GraphNode(id=u1_id, node_type=GraphNodeType.UNIT, label="Introduction"),
            GraphNode(id=u2_id, node_type=GraphNodeType.UNIT, label="Core Concepts"),
            GraphNode(id=c1_id, node_type=GraphNodeType.CONCEPT, label="algorithm"),
        ],
        edges=[
            GraphEdge(
                source_id=u1_id,
                target_id=u2_id,
                edge_type=EdgeType.DEPENDS_ON,
            ),
        ],
    )


def _make_study_plan() -> StudyPlan:
    """Create a stub study plan."""
    from learning_platform.models.sequence import Checkpoint, Lesson, Milestone

    l1 = Lesson(
        unit_id=uuid4(),
        order=0,
        title="Introduction",
        difficulty="basic",
        estimated_minutes=10,
    )
    l2 = Lesson(
        unit_id=uuid4(),
        order=1,
        title="Core Concepts",
        difficulty="intermediate",
        estimated_minutes=15,
    )
    m1 = Milestone(
        order=0,
        title="Milestone 1",
        lesson_ids=[l1.id, l2.id],
        estimated_minutes=25,
    )
    cp1 = Checkpoint(
        milestone_id=m1.id,
        order=0,
        title="Checkpoint 1",
        estimated_minutes=5,
        lesson_ids=[l1.id, l2.id],
    )
    return StudyPlan(
        title="Test Plan",
        lessons=[l1, l2],
        milestones=[m1],
        checkpoints=[cp1],
        total_estimated_minutes=25,
        total_lessons=2,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_orchestrator(**kwargs: Any) -> PipelineOrchestrator:
    """Build an orchestrator with default stubs, overriding as needed."""
    return PipelineOrchestrator(
        parser=kwargs.get("parser", StubParser()),
        normalizer=kwargs.get("normalizer", StubNormalizer()),
        enricher=kwargs.get("enricher", StubEnricher()),
        unit_builder=kwargs.get("unit_builder", StubUnitBuilder()),
        concept_extractor=kwargs.get("concept_extractor", StubConceptExtractor()),
        graph_builder=kwargs.get("graph_builder", StubGraphBuilder()),
        sequence_builder=kwargs.get("sequence_builder", StubSequenceBuilder()),
        event_bus=kwargs.get("event_bus", SimpleEventBus()),
        plugin_registry=kwargs.get("plugin_registry", PluginRegistry()),
        retry_policy=kwargs.get("retry_policy"),
    )


# ── Test classes ─────────────────────────────────────────────────────────────


class TestPipelineEndToEnd:
    """Full pipeline execution with stub stages."""

    def test_returns_pipeline_result(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("test.pdf")
        assert isinstance(result, PipelineResult)

    def test_document_flows_through(self) -> None:
        doc = _make_document()
        orch = _build_orchestrator(parser=StubParser(doc))
        result = orch.run("input.pdf")
        assert result.document is doc

    def test_annotations_flows_through(self) -> None:
        annotations = _make_annotations()
        orch = _build_orchestrator(enricher=StubEnricher(annotations))
        result = orch.run("input.pdf")
        assert result.annotations == annotations

    def test_units_flows_through(self) -> None:
        units = _make_units()
        orch = _build_orchestrator(unit_builder=StubUnitBuilder(units))
        result = orch.run("input.pdf")
        assert result.units == units

    def test_concepts_flows_through(self) -> None:
        concepts = _make_concepts()
        orch = _build_orchestrator(concept_extractor=StubConceptExtractor(concepts))
        result = orch.run("input.pdf")
        assert result.concepts is concepts

    def test_graph_flows_through(self) -> None:
        graph = _make_graph()
        orch = _build_orchestrator(graph_builder=StubGraphBuilder(graph))
        result = orch.run("input.pdf")
        assert result.graph is graph

    def test_study_plan_flows_through(self) -> None:
        plan = _make_study_plan()
        orch = _build_orchestrator(sequence_builder=StubSequenceBuilder(plan))
        result = orch.run("input.pdf")
        assert result.study_plan is plan

    def test_study_plan_has_lessons(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        assert result.study_plan.total_lessons == 2
        assert len(result.study_plan.milestones) == 1
        assert len(result.study_plan.checkpoints) == 1


class TestPipelineEvents:
    """Event emission during pipeline execution."""

    def test_events_collected(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        assert len(result.events) > 0

    def test_pipeline_started_event(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        types = [e.event_type for e in result.events]
        assert EventType.PIPELINE_STARTED in types

    def test_pipeline_completed_event(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        types = [e.event_type for e in result.events]
        assert EventType.PIPELINE_COMPLETED in types

    def test_all_stages_emit_events(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        stage_names = {e.stage for e in result.events if e.stage != "pipeline"}
        expected = {
            "parser",
            "normalizer",
            "enricher",
            "unit_builder",
            "concept_extractor",
            "graph_builder",
            "sequence_builder",
        }
        assert expected.issubset(stage_names)

    def test_each_stage_has_started_and_completed(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        stages = [
            "parser",
            "normalizer",
            "enricher",
            "unit_builder",
            "concept_extractor",
            "graph_builder",
            "sequence_builder",
        ]
        for stage in stages:
            started = any(
                e.event_type == EventType.STAGE_STARTED and e.stage == stage for e in result.events
            )
            completed = any(
                e.event_type == EventType.STAGE_COMPLETED and e.stage == stage
                for e in result.events
            )
            assert started, f"{stage} missing STAGE_STARTED"
            assert completed, f"{stage} missing STAGE_COMPLETED"

    def test_events_have_pipeline_id(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        ids = {e.pipeline_id for e in result.events}
        assert len(ids) == 1, "All events should share the same pipeline_id"

    def test_event_bus_receives_events(self) -> None:
        bus = SimpleEventBus()
        received: list[PipelineEvent] = []
        bus.subscribe(received.append)
        orch = _build_orchestrator(event_bus=bus)
        orch.run("input.pdf")
        assert len(received) > 0

    def test_completed_event_has_elapsed(self) -> None:
        orch = _build_orchestrator()
        result = orch.run("input.pdf")
        completed = [e for e in result.events if e.event_type == EventType.PIPELINE_COMPLETED]
        assert len(completed) == 1
        assert "elapsed_seconds" in completed[0].data
        assert completed[0].data["elapsed_seconds"] >= 0


class TestPipelinePlugins:
    """Plugin dispatch during pipeline execution."""

    def test_plugin_receives_events(self) -> None:
        received: list[PipelineEvent] = []

        class Collector:
            def on_event(self, event: PipelineEvent) -> None:
                received.append(event)

        reg = PluginRegistry()
        reg.register(Collector())
        orch = _build_orchestrator(plugin_registry=reg)
        orch.run("input.pdf")
        assert len(received) > 0

    def test_multiple_plugins_receive_events(self) -> None:
        counts = [0, 0]

        class Counter1:
            def on_event(self, event: PipelineEvent) -> None:
                counts[0] += 1

        class Counter2:
            def on_event(self, event: PipelineEvent) -> None:
                counts[1] += 1

        reg = PluginRegistry()
        reg.register(Counter1())
        reg.register(Counter2())
        orch = _build_orchestrator(plugin_registry=reg)
        orch.run("input.pdf")
        assert counts[0] > 0
        assert counts[1] > 0
        assert counts[0] == counts[1]

    def test_plugin_error_does_not_break_pipeline(self) -> None:
        class BrokenPlugin:
            def on_event(self, event: PipelineEvent) -> None:
                raise RuntimeError("plugin broke")

        reg = PluginRegistry()
        reg.register(BrokenPlugin())
        orch = _build_orchestrator(plugin_registry=reg)
        result = orch.run("input.pdf")
        assert result.study_plan.total_lessons == 2

    def test_unregister_plugin(self) -> None:
        received: list[PipelineEvent] = []

        class Collector:
            def on_event(self, event: PipelineEvent) -> None:
                received.append(event)

        reg = PluginRegistry()
        collector = Collector()
        reg.register(collector)
        reg.unregister(collector)
        orch = _build_orchestrator(plugin_registry=reg)
        orch.run("input.pdf")
        assert len(received) == 0


class TestPipelineRetries:
    """Retry behaviour on transient failures."""

    def test_retry_succeeds_after_failure(self) -> None:
        flaky = FlakyParser(fail_count=1)
        policy = RetryPolicy(max_retries=2, base_delay=0.0, backoff_factor=1.0)
        orch = _build_orchestrator(parser=flaky, retry_policy=policy)
        result = orch.run("input.pdf")
        assert result.study_plan.total_lessons == 2
        assert flaky._call_count == 2

    def test_retry_exhausted_raises(self) -> None:
        policy = RetryPolicy(max_retries=1, base_delay=0.0, backoff_factor=1.0)
        orch = _build_orchestrator(parser=FailingParser(), retry_policy=policy)
        with pytest.raises(RuntimeError, match="Parse failure"):
            orch.run("input.pdf")

    def test_retry_result_recorded(self) -> None:
        policy = RetryPolicy(max_retries=2, base_delay=0.0, backoff_factor=1.0)
        orch = _build_orchestrator(parser=FailingParser(), retry_policy=policy)
        with pytest.raises(RuntimeError):
            orch.run("input.pdf")
        assert "parser" in orch._retry_results
        rr = orch._retry_results["parser"]
        assert rr.attempts == 3  # 1 initial + 2 retries
        assert rr.error is not None

    def test_retry_events_emitted(self) -> None:
        policy = RetryPolicy(max_retries=2, base_delay=0.0, backoff_factor=1.0)
        bus = SimpleEventBus()
        orch = _build_orchestrator(parser=FailingParser(), retry_policy=policy, event_bus=bus)
        with pytest.raises(RuntimeError):
            orch.run("input.pdf")
        retry_events = [e for e in orch._events if e.event_type == EventType.STAGE_RETRYING]
        assert len(retry_events) == 2

    def test_no_retry_when_policy_is_none(self) -> None:
        orch = _build_orchestrator(parser=FailingParser(), retry_policy=None)
        with pytest.raises(RuntimeError, match="Parse failure"):
            orch.run("input.pdf")

    def test_no_retry_when_max_retries_is_zero(self) -> None:
        policy = RetryPolicy(max_retries=0)
        orch = _build_orchestrator(parser=FailingParser(), retry_policy=policy)
        with pytest.raises(RuntimeError, match="Parse failure"):
            orch.run("input.pdf")


class TestPipelineFailure:
    """Pipeline-level failure handling."""

    def test_pipeline_failed_event_on_exception(self) -> None:
        orch = _build_orchestrator(parser=FailingParser())
        with pytest.raises(RuntimeError):
            orch.run("bad.pdf")
        failed = [e for e in orch._events if e.event_type == EventType.PIPELINE_FAILED]
        assert len(failed) == 1
        assert "error" in failed[0].data

    def test_pipeline_started_event_emitted_before_failure(self) -> None:
        orch = _build_orchestrator(parser=FailingParser())
        with pytest.raises(RuntimeError):
            orch.run("bad.pdf")
        started = [e for e in orch._events if e.event_type == EventType.PIPELINE_STARTED]
        assert len(started) == 1

    def test_partial_stages_not_completed(self) -> None:
        orch = _build_orchestrator(parser=FailingParser())
        with pytest.raises(RuntimeError):
            orch.run("bad.pdf")
        completed = [e for e in orch._events if e.event_type == EventType.STAGE_COMPLETED]
        assert len(completed) == 0


class TestPipelineDependencyInjection:
    """Verify that all stages are injected, not hardcoded."""

    def test_custom_parser_called(self) -> None:
        called = False

        class TrackingParser:
            def parse(self, source: str) -> CanonicalDocument:
                nonlocal called
                called = True
                return _make_document()

            def supports(self, source: str) -> bool:
                return True

            def confidence(self, source: str) -> float:
                return 1.0

        orch = _build_orchestrator(parser=TrackingParser())
        orch.run("test.pdf")
        assert called

    def test_custom_enricher_called(self) -> None:
        called = False

        class TrackingEnricher:
            def enrich(
                self, document: CanonicalDocument
            ) -> tuple[CanonicalDocument, list[Annotation]]:
                nonlocal called
                called = True
                return document, []

            def enrich_pages(self, pages: list[Any]) -> list[Any]:
                nonlocal called
                called = True
                return pages

        orch = _build_orchestrator(enricher=TrackingEnricher())
        orch.run("test.pdf")
        assert called

    def test_custom_unit_builder_called(self) -> None:
        called = False

        class TrackingUnitBuilder:
            def build(
                self, document: CanonicalDocument, annotations: list[Annotation]
            ) -> list[LearningUnit]:
                nonlocal called
                called = True
                return []

            def build_pages(self, pages: list[Any]) -> list[LearningUnit]:
                nonlocal called
                called = True
                return []

        orch = _build_orchestrator(unit_builder=TrackingUnitBuilder())
        orch.run("test.pdf")
        assert called

    def test_custom_concept_extractor_called(self) -> None:
        called = False

        class TrackingConceptExtractor:
            def extract(
                self,
                document: CanonicalDocument,
                annotations: list[Annotation],
                units: list[LearningUnit],
            ) -> ConceptMap:
                nonlocal called
                called = True
                return ConceptMap()

            def extract_pages(
                self,
                pages: list[Any],
                units: list[LearningUnit],
            ) -> ConceptMap:
                nonlocal called
                called = True
                return ConceptMap()

        orch = _build_orchestrator(concept_extractor=TrackingConceptExtractor())
        orch.run("test.pdf")
        assert called

    def test_custom_graph_builder_called(self) -> None:
        called = False

        class TrackingGraphBuilder:
            def build(self, units: list[LearningUnit], concepts: ConceptMap) -> KnowledgeGraph:
                nonlocal called
                called = True
                return KnowledgeGraph()

        orch = _build_orchestrator(graph_builder=TrackingGraphBuilder())
        orch.run("test.pdf")
        assert called

    def test_custom_sequence_builder_called(self) -> None:
        called = False

        class TrackingSequenceBuilder:
            def build(self, graph: KnowledgeGraph) -> StudyPlan:
                nonlocal called
                called = True
                return StudyPlan()

        orch = _build_orchestrator(sequence_builder=TrackingSequenceBuilder())
        orch.run("test.pdf")
        assert called
