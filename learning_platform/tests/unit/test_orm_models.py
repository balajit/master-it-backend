"""Tests for ORM model construction and table metadata."""

from __future__ import annotations

import uuid

from learning_platform.infrastructure.persistence.models.annotation import AnnotationRow
from learning_platform.infrastructure.persistence.models.base import Base
from learning_platform.infrastructure.persistence.models.concept import (
    ConceptRelationshipRow,
    ConceptRow,
)
from learning_platform.infrastructure.persistence.models.document import CanonicalDocumentRow
from learning_platform.infrastructure.persistence.models.knowledge_graph import (
    GraphEdgeRow,
    GraphNodeRow,
    KnowledgeGraphRow,
)
from learning_platform.infrastructure.persistence.models.learning_unit import LearningUnitRow
from learning_platform.infrastructure.persistence.models.sequence import (
    CheckpointRow,
    LessonRow,
    MilestoneRow,
    StudyPlanRow,
)


class TestBase:
    def test_base_is_declarative(self) -> None:
        assert hasattr(Base, "metadata")

    def test_all_tables_registered(self) -> None:
        table_names = sorted(Base.metadata.tables.keys())
        expected = [
            "lp_annotations",
            "lp_checkpoints",
            "lp_concept_relationships",
            "lp_concepts",
            "lp_documents",
            "lp_graph_edges",
            "lp_graph_nodes",
            "lp_knowledge_graphs",
            "lp_learning_units",
            "lp_lessons",
            "lp_milestones",
            "lp_study_plans",
        ]
        assert table_names == expected

    def test_total_table_count(self) -> None:
        assert len(Base.metadata.tables) == 12


class TestCanonicalDocumentRow:
    def test_table_name(self) -> None:
        assert CanonicalDocumentRow.__tablename__ == "lp_documents"

    def test_construction(self) -> None:
        row = CanonicalDocumentRow(
            id=uuid.uuid4(),
            source="test.pdf",
            title="Test Doc",
            metadata_json={"key": "val"},
            nodes_json=[{"id": "abc"}],
            created_at="2025-01-01T00:00:00Z",
        )
        assert row.source == "test.pdf"
        assert row.title == "Test Doc"
        assert row.metadata_json == {"key": "val"}


class TestLearningUnitRow:
    def test_table_name(self) -> None:
        assert LearningUnitRow.__tablename__ == "lp_learning_units"

    def test_construction(self) -> None:
        row = LearningUnitRow(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            unit_type="lesson",
            title="Unit 1",
            difficulty="basic",
        )
        assert row.unit_type == "lesson"
        assert row.title == "Unit 1"


class TestAnnotationRow:
    def test_table_name(self) -> None:
        assert AnnotationRow.__tablename__ == "lp_annotations"

    def test_construction(self) -> None:
        row = AnnotationRow(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            type="definition",
            node_id=uuid.uuid4(),
            confidence=0.95,
            detector="test_detector",
            payload={"term": "foo"},
        )
        assert row.type == "definition"
        assert row.confidence == 0.95


class TestConceptRows:
    def test_concept_table_name(self) -> None:
        assert ConceptRow.__tablename__ == "lp_concepts"

    def test_relationship_table_name(self) -> None:
        assert ConceptRelationshipRow.__tablename__ == "lp_concept_relationships"

    def test_concept_construction(self) -> None:
        row = ConceptRow(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            name="derivative",
            category="concept",
            importance=0.8,
            mention_count=5,
        )
        assert row.name == "derivative"
        assert row.importance == 0.8

    def test_relationship_construction(self) -> None:
        row = ConceptRelationshipRow(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            source_concept_id=uuid.uuid4(),
            target_concept_id=uuid.uuid4(),
            relation_type="prerequisite",
            weight=0.9,
        )
        assert row.relation_type == "prerequisite"


class TestKnowledgeGraphRows:
    def test_graph_table_name(self) -> None:
        assert KnowledgeGraphRow.__tablename__ == "lp_knowledge_graphs"

    def test_node_table_name(self) -> None:
        assert GraphNodeRow.__tablename__ == "lp_graph_nodes"

    def test_edge_table_name(self) -> None:
        assert GraphEdgeRow.__tablename__ == "lp_graph_edges"

    def test_graph_construction(self) -> None:
        row = KnowledgeGraphRow(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            created_at="2025-01-01T00:00:00Z",
        )
        assert row.document_id is not None

    def test_node_construction(self) -> None:
        row = GraphNodeRow(
            id=uuid.uuid4(),
            graph_id=uuid.uuid4(),
            node_type="unit",
            label="Chapter 1",
        )
        assert row.node_type == "unit"

    def test_edge_construction(self) -> None:
        row = GraphEdgeRow(
            id=uuid.uuid4(),
            graph_id=uuid.uuid4(),
            source_node_id=uuid.uuid4(),
            target_node_id=uuid.uuid4(),
            edge_type="contains",
        )
        assert row.edge_type == "contains"


class TestSequenceRows:
    def test_study_plan_table_name(self) -> None:
        assert StudyPlanRow.__tablename__ == "lp_study_plans"

    def test_lesson_table_name(self) -> None:
        assert LessonRow.__tablename__ == "lp_lessons"

    def test_milestone_table_name(self) -> None:
        assert MilestoneRow.__tablename__ == "lp_milestones"

    def test_checkpoint_table_name(self) -> None:
        assert CheckpointRow.__tablename__ == "lp_checkpoints"

    def test_study_plan_construction(self) -> None:
        row = StudyPlanRow(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            title="My Plan",
            total_lessons=5,
        )
        assert row.title == "My Plan"

    def test_lesson_construction(self) -> None:
        row = LessonRow(
            id=uuid.uuid4(),
            study_plan_id=uuid.uuid4(),
            unit_id=uuid.uuid4(),
            order=0,
            lesson_type="core",
        )
        assert row.lesson_type == "core"

    def test_milestone_construction(self) -> None:
        row = MilestoneRow(
            id=uuid.uuid4(),
            study_plan_id=uuid.uuid4(),
            order=0,
            title="Milestone 1",
        )
        assert row.title == "Milestone 1"

    def test_checkpoint_construction(self) -> None:
        row = CheckpointRow(
            id=uuid.uuid4(),
            study_plan_id=uuid.uuid4(),
            milestone_id=uuid.uuid4(),
            checkpoint_type="quiz",
        )
        assert row.checkpoint_type == "quiz"
