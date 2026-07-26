"""Tests for JSON and GraphML exporters."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from learning_platform.infrastructure.persistence.exporters.graphml_exporter import GraphMLExporter
from learning_platform.infrastructure.persistence.exporters.json_exporter import JsonExporter
from learning_platform.models.annotation import DefinitionAnnotation
from learning_platform.models.concept import (
    Concept,
    ConceptCategory,
    ConceptMap,
    ConceptRelationship,
    RelationType,
)
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Heading,
    HeadingLevel,
    StyledText,
    TextRun,
)
from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)
from learning_platform.models.learning_unit import Difficulty, LearningUnit, UnitType
from learning_platform.models.sequence import (
    Checkpoint,
    CheckpointType,
    Lesson,
    Milestone,
    StudyPlan,
)


def _make_full_output() -> tuple[
    CanonicalDocument,
    list[LearningUnit],
    list[DefinitionAnnotation],
    ConceptMap,
    KnowledgeGraph,
    StudyPlan,
]:
    doc_id = uuid.uuid4()
    root = DocumentNode(
        id=doc_id,
        content=Heading(level=HeadingLevel.CHAPTER, text=StyledText(runs=[TextRun(text="Ch1")])),
    )
    doc = CanonicalDocument(
        source="test.pdf",
        title="Test",
        metadata=DocumentMetadata(title="Test"),
        nodes=[root],
    )
    unit = LearningUnit(
        unit_type=UnitType.LESSON,
        title="U1",
        difficulty=Difficulty.BASIC,
    )
    ann = DefinitionAnnotation(node_id=uuid.uuid4(), term="X", definition_text="Y")
    c1 = Concept(name="C1", category=ConceptCategory.CONCEPT)
    c2 = Concept(name="C2", category=ConceptCategory.SKILL)
    rel = ConceptRelationship(
        source_id=c1.id,
        target_id=c2.id,
        relation_type=RelationType.RELATES_TO,
    )
    cmap = ConceptMap(concepts=[c1, c2], relationships=[rel])
    n1 = GraphNode(node_type=NodeType.UNIT, label="U1")
    n2 = GraphNode(node_type=NodeType.CONCEPT, label="C1")
    edge = GraphEdge(source_id=n1.id, target_id=n2.id, edge_type=EdgeType.REFERENCES)
    graph = KnowledgeGraph(nodes=[n1, n2], edges=[edge])
    lesson = Lesson(unit_id=unit.id, order=0, title="L1")
    milestone = Milestone(order=0, title="M1", lesson_ids=[lesson.id])
    cp = Checkpoint(
        milestone_id=milestone.id,
        order=0,
        title="CP1",
        checkpoint_type=CheckpointType.QUIZ,
    )
    plan = StudyPlan(
        title="Plan",
        lessons=[lesson],
        milestones=[milestone],
        checkpoints=[cp],
        total_lessons=1,
    )

    return doc, [unit], [ann], cmap, graph, plan


class TestJsonExporter:
    def test_export_all(self, tmp_path: Path) -> None:
        doc, units, anns, cmap, graph, plan = _make_full_output()
        exporter = JsonExporter(tmp_path)

        paths = exporter.export_all(doc, units, anns, cmap, graph, plan)

        assert len(paths) == 6
        for p in paths:
            assert p.exists()
            assert p.stat().st_size > 0

    def test_document_roundtrip(self, tmp_path: Path) -> None:
        doc, _, _, _, _, _ = _make_full_output()
        exporter = JsonExporter(tmp_path)
        path = exporter.export_document(doc)

        data = json.loads(path.read_text())
        assert data["source"] == "test.pdf"
        assert data["title"] == "Test"

    def test_units_roundtrip(self, tmp_path: Path) -> None:
        _, units, _, _, _, _ = _make_full_output()
        exporter = JsonExporter(tmp_path)
        path = exporter.export_units(units)

        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["title"] == "U1"

    def test_annotations_roundtrip(self, tmp_path: Path) -> None:
        _, _, anns, _, _, _ = _make_full_output()
        exporter = JsonExporter(tmp_path)
        path = exporter.export_annotations(anns)

        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["type"] == "definition"

    def test_concepts_roundtrip(self, tmp_path: Path) -> None:
        _, _, _, cmap, _, _ = _make_full_output()
        exporter = JsonExporter(tmp_path)
        path = exporter.export_concepts(cmap)

        data = json.loads(path.read_text())
        assert len(data["concepts"]) == 2
        assert len(data["relationships"]) == 1

    def test_graph_roundtrip(self, tmp_path: Path) -> None:
        _, _, _, _, graph, _ = _make_full_output()
        exporter = JsonExporter(tmp_path)
        path = exporter.export_graph(graph)

        data = json.loads(path.read_text())
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

    def test_study_plan_roundtrip(self, tmp_path: Path) -> None:
        _, _, _, _, _, plan = _make_full_output()
        exporter = JsonExporter(tmp_path)
        path = exporter.export_study_plan(plan)

        data = json.loads(path.read_text())
        assert data["title"] == "Plan"
        assert len(data["lessons"]) == 1


class TestGraphMLExporter:
    def test_export_creates_file(self, tmp_path: Path) -> None:
        _, _, _, _, graph, _ = _make_full_output()
        exporter = GraphMLExporter(tmp_path)
        path = exporter.export(graph)

        assert path.exists()
        assert path.suffix == ".graphml"

    def test_graphml_content(self, tmp_path: Path) -> None:
        _, _, _, _, graph, _ = _make_full_output()
        exporter = GraphMLExporter(tmp_path)
        path = exporter.export(graph)

        content = path.read_text()
        assert "node" in content
        assert "edge" in content

    def test_empty_graph(self, tmp_path: Path) -> None:
        graph = KnowledgeGraph()
        exporter = GraphMLExporter(tmp_path)
        path = exporter.export(graph)

        assert path.exists()
        content = path.read_text()
        assert "graphml" in content
