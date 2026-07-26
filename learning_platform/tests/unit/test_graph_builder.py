"""Unit tests for KnowledgeGraphBuilder and visualization utilities."""

from __future__ import annotations

from uuid import uuid4

import pytest

from learning_platform.models.concept import (
    Concept,
    ConceptCategory,
    ConceptMap,
    ConceptRelationship,
    RelationType,
)
from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)
from learning_platform.models.learning_unit import (
    Difficulty,
    LearningUnit,
    NodeRef,
    UnitType,
)
from learning_platform.stages.graph_builder.graph import NetworkxGraphBuilder
from learning_platform.stages.graph_builder.visualization import (
    graph_summary,
    to_adjacency_list,
    to_dot,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _unit(
    title: str = "Unit",
    *,
    parent_id: uuid4 | None = None,
    prerequisite_ids: list | None = None,
    content_references: list[NodeRef] | None = None,
) -> LearningUnit:
    return LearningUnit(
        id=uuid4(),
        unit_type=UnitType.LESSON,
        title=title,
        description=f"{title} description",
        parent_id=parent_id,
        prerequisite_ids=prerequisite_ids or [],
        content_references=content_references or [],
        content_node_refs=[NodeRef(node_id=uuid4(), node_type="paragraph")],
        difficulty=Difficulty.BASIC,
        estimated_study_time_minutes=10,
    )


def _concept(
    name: str = "concept",
    *,
    category: ConceptCategory = ConceptCategory.CONCEPT,
    importance: float = 0.5,
) -> Concept:
    return Concept(
        id=uuid4(),
        name=name,
        category=category,
        importance=importance,
        mention_count=3,
    )


def _concept_map(
    concepts: list[Concept] | None = None,
    relationships: list[ConceptRelationship] | None = None,
) -> ConceptMap:
    return ConceptMap(
        concepts=concepts or [],
        relationships=relationships or [],
    )


# ══════════════════════════════════════════════════════════════════════════════
# KnowledgeGraph model tests
# ══════════════════════════════════════════════════════════════════════════════


class TestKnowledgeGraphModel:
    def test_node_ids(self) -> None:
        n1, n2, n3 = uuid4(), uuid4(), uuid4()
        g = KnowledgeGraph(
            nodes=[
                GraphNode(id=n1, node_type=NodeType.UNIT, label="A"),
                GraphNode(id=n2, node_type=NodeType.CONCEPT, label="B"),
                GraphNode(id=n3, node_type=NodeType.UNIT, label="C"),
            ],
            edges=[],
        )
        assert g.node_ids() == {n1, n2, n3}

    def test_nodes_by_type(self) -> None:
        u1 = GraphNode(id=uuid4(), node_type=NodeType.UNIT, label="U1")
        c1 = GraphNode(id=uuid4(), node_type=NodeType.CONCEPT, label="C1")
        g = KnowledgeGraph(nodes=[u1, c1], edges=[])
        assert g.nodes_by_type(NodeType.UNIT) == [u1]
        assert g.nodes_by_type(NodeType.CONCEPT) == [c1]

    def test_edges_by_type(self) -> None:
        e1 = GraphEdge(source_id=uuid4(), target_id=uuid4(), edge_type=EdgeType.CONTAINS)
        e2 = GraphEdge(source_id=uuid4(), target_id=uuid4(), edge_type=EdgeType.REFERENCES)
        g = KnowledgeGraph(
            nodes=[GraphNode(id=uuid4(), node_type=NodeType.UNIT, label="X")],
            edges=[e1, e2],
        )
        assert g.edges_by_type(EdgeType.CONTAINS) == [e1]
        assert g.edges_by_type(EdgeType.REFERENCES) == [e2]

    def test_adjacency_list(self) -> None:
        a, b, c = uuid4(), uuid4(), uuid4()
        g = KnowledgeGraph(
            nodes=[
                GraphNode(id=a, node_type=NodeType.UNIT, label="A"),
                GraphNode(id=b, node_type=NodeType.UNIT, label="B"),
                GraphNode(id=c, node_type=NodeType.CONCEPT, label="C"),
            ],
            edges=[
                GraphEdge(source_id=a, target_id=b, edge_type=EdgeType.CONTAINS),
                GraphEdge(source_id=a, target_id=c, edge_type=EdgeType.REFERENCES),
            ],
        )
        adj = g.adjacency_list()
        assert a in adj
        assert b in adj[a]
        assert c in adj[a]
        assert adj[b] == []

    def test_empty_graph(self) -> None:
        g = KnowledgeGraph()
        assert g.node_ids() == set()
        assert g.adjacency_list() == {}

    def test_all_edge_types_exist(self) -> None:
        expected = {
            "contains",
            "depends_on",
            "prerequisite",
            "references",
            "extends",
            "explains",
            "illustrates",
        }
        actual = {e.value for e in EdgeType}
        assert expected == actual


# ══════════════════════════════════════════════════════════════════════════════
# NetworkxGraphBuilder tests
# ══════════════════════════════════════════════════════════════════════════════


class TestNetworkxGraphBuilder:
    def setup_method(self) -> None:
        self.builder = NetworkxGraphBuilder()

    def test_empty_inputs(self) -> None:
        graph = self.builder.build([], _concept_map())
        assert graph.nodes == []
        assert graph.edges == []

    def test_unit_nodes_created(self) -> None:
        u1 = _unit("Algebra")
        u2 = _unit("Geometry")
        graph = self.builder.build([u1, u2], _concept_map())

        unit_nodes = graph.nodes_by_type(NodeType.UNIT)
        assert len(unit_nodes) == 2
        labels = {n.label for n in unit_nodes}
        assert labels == {"Algebra", "Geometry"}

    def test_concept_nodes_created(self) -> None:
        c1 = _concept("vector")
        c2 = _concept("matrix")
        graph = self.builder.build([], _concept_map([c1, c2]))

        concept_nodes = graph.nodes_by_type(NodeType.CONCEPT)
        assert len(concept_nodes) == 2
        labels = {n.label for n in concept_nodes}
        assert labels == {"vector", "matrix"}

    def test_unit_metadata(self) -> None:
        u = _unit("Test")
        graph = self.builder.build([u], _concept_map())
        node = graph.nodes_by_type(NodeType.UNIT)[0]
        assert node.metadata["unit_type"] == "lesson"
        assert node.metadata["difficulty"] == "basic"

    def test_concept_metadata(self) -> None:
        c = _concept("foo", importance=0.9)
        graph = self.builder.build([], _concept_map([c]))
        node = graph.nodes_by_type(NodeType.CONCEPT)[0]
        assert node.metadata["category"] == "concept"
        assert node.metadata["importance"] == 0.9

    def test_contains_edge(self) -> None:
        parent = _unit("Parent")
        child = _unit("Child", parent_id=parent.id)
        graph = self.builder.build([parent, child], _concept_map())

        contains = graph.edges_by_type(EdgeType.CONTAINS)
        assert len(contains) == 1
        assert contains[0].source_id == parent.id
        assert contains[0].target_id == child.id
        assert contains[0].metadata["source"] == "NetworkxGraphBuilder"

    def test_depends_on_edge(self) -> None:
        prereq = _unit("Prereq")
        main = _unit("Main", prerequisite_ids=[prereq.id])
        graph = self.builder.build([prereq, main], _concept_map())

        deps = graph.edges_by_type(EdgeType.DEPENDS_ON)
        assert len(deps) == 1
        assert deps[0].source_id == prereq.id
        assert deps[0].target_id == main.id

    def test_references_edge(self) -> None:
        concept = _concept("topic")
        unit = _unit("Lesson")
        concept_with_unit = Concept(
            id=concept.id,
            name=concept.name,
            category=concept.category,
            source_unit_ids=[unit.id],
        )
        graph = self.builder.build([unit], _concept_map([concept_with_unit]))

        refs = graph.edges_by_type(EdgeType.REFERENCES)
        assert len(refs) == 1
        assert refs[0].source_id == unit.id
        assert refs[0].target_id == concept.id

    def test_concept_prerequisite_relationship(self) -> None:
        c1 = _concept("basics")
        c2 = _concept("advanced")
        rel = ConceptRelationship(
            source_id=c1.id,
            target_id=c2.id,
            relation_type=RelationType.PREREQUISITE,
        )
        graph = self.builder.build([], _concept_map([c1, c2], [rel]))

        prereqs = graph.edges_by_type(EdgeType.PREREQUISITE)
        assert len(prereqs) == 1
        assert prereqs[0].source_id == c1.id
        assert prereqs[0].target_id == c2.id

    def test_concept_derived_from_relationship(self) -> None:
        c1 = _concept("base")
        c2 = _concept("extended")
        rel = ConceptRelationship(
            source_id=c2.id,
            target_id=c1.id,
            relation_type=RelationType.DERIVED_FROM,
        )
        graph = self.builder.build([], _concept_map([c1, c2], [rel]))

        extends = graph.edges_by_type(EdgeType.EXTENDS)
        assert len(extends) == 1
        assert extends[0].source_id == c2.id
        assert extends[0].target_id == c1.id

    def test_concept_example_of_relationship(self) -> None:
        c1 = _concept("example")
        c2 = _concept("principle")
        rel = ConceptRelationship(
            source_id=c1.id,
            target_id=c2.id,
            relation_type=RelationType.EXAMPLE_OF,
        )
        graph = self.builder.build([], _concept_map([c1, c2], [rel]))

        illustrates = graph.edges_by_type(EdgeType.ILLUSTRATES)
        assert len(illustrates) == 1
        assert illustrates[0].source_id == c1.id
        assert illustrates[0].target_id == c2.id

    def test_concept_used_in_maps_to_references(self) -> None:
        c1 = _concept("used")
        c2 = _concept("context")
        rel = ConceptRelationship(
            source_id=c1.id,
            target_id=c2.id,
            relation_type=RelationType.USED_IN,
        )
        graph = self.builder.build([], _concept_map([c1, c2], [rel]))

        refs = graph.edges_by_type(EdgeType.REFERENCES)
        assert len(refs) == 1

    def test_concept_relates_to_maps_to_references(self) -> None:
        c1 = _concept("a")
        c2 = _concept("b")
        rel = ConceptRelationship(
            source_id=c1.id,
            target_id=c2.id,
            relation_type=RelationType.RELATES_TO,
        )
        graph = self.builder.build([], _concept_map([c1, c2], [rel]))

        refs = graph.edges_by_type(EdgeType.REFERENCES)
        assert len(refs) == 1

    def test_skips_dangling_prerequisite(self) -> None:
        """A prerequisite ID not present in units is silently skipped."""
        main = _unit("Main", prerequisite_ids=[uuid4()])
        graph = self.builder.build([main], _concept_map())
        assert graph.edges == []

    def test_skips_dangling_concept_reference(self) -> None:
        """A concept whose source_unit_ids references a missing unit is skipped."""
        concept = _concept("orphan")
        concept_with_dangling = Concept(
            id=concept.id,
            name=concept.name,
            category=concept.category,
            source_unit_ids=[uuid4()],  # ID not present in units
        )
        unit = _unit("Lesson")
        graph = self.builder.build([unit], _concept_map([concept_with_dangling]))
        refs = graph.edges_by_type(EdgeType.REFERENCES)
        assert refs == []

    def test_skips_dangling_concept_relationship(self) -> None:
        """A relationship referencing missing concepts is silently skipped."""
        rel = ConceptRelationship(
            source_id=uuid4(),
            target_id=uuid4(),
            relation_type=RelationType.PREREQUISITE,
        )
        graph = self.builder.build([], _concept_map([], [rel]))
        assert graph.edges == []

    def test_edge_weight_preserved(self) -> None:
        c1 = _concept("a")
        c2 = _concept("b")
        rel = ConceptRelationship(
            source_id=c1.id,
            target_id=c2.id,
            relation_type=RelationType.PREREQUISITE,
            weight=0.75,
        )
        graph = self.builder.build([], _concept_map([c1, c2], [rel]))
        assert graph.edges[0].weight == 0.75

    def test_metadata_source_field(self) -> None:
        u1 = _unit("A")
        u2 = _unit("B")
        graph = self.builder.build([u1, u2], _concept_map())
        for edge in graph.edges:
            assert "source" in edge.metadata

    def test_full_graph_structure(self) -> None:
        """Integration-style: units + concepts + all edge types."""
        parent = _unit("Course")
        child1 = _unit("Lesson1", parent_id=parent.id)
        lesson2 = _unit("Lesson2", parent_id=parent.id, prerequisite_ids=[child1.id])

        c1 = _concept("concept_a")
        c2 = _concept("concept_b")
        c3 = _concept("concept_c")

        # child1 references c1
        c1_with_unit = Concept(
            id=c1.id,
            name=c1.name,
            category=c1.category,
            source_unit_ids=[child1.id],
        )

        rel = ConceptRelationship(
            source_id=c1.id,
            target_id=c2.id,
            relation_type=RelationType.PREREQUISITE,
        )

        graph = self.builder.build(
            [parent, child1, lesson2],
            _concept_map([c1_with_unit, c2, c3], [rel]),
        )

        # 6 nodes: 3 units + 3 concepts
        assert len(graph.nodes) == 6
        assert len(graph.nodes_by_type(NodeType.UNIT)) == 3
        assert len(graph.nodes_by_type(NodeType.CONCEPT)) == 3

        # Edges: 2 CONTAINS + 1 DEPENDS_ON + 1 REFERENCES + 1 PREREQUISITE
        assert len(graph.edges_by_type(EdgeType.CONTAINS)) == 2
        assert len(graph.edges_by_type(EdgeType.DEPENDS_ON)) == 1
        assert len(graph.edges_by_type(EdgeType.REFERENCES)) == 1
        assert len(graph.edges_by_type(EdgeType.PREREQUISITE)) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Visualization tests
# ══════════════════════════════════════════════════════════════════════════════


class TestVisualization:
    def _sample_graph(self) -> KnowledgeGraph:
        u1_id, u2_id, c1_id = uuid4(), uuid4(), uuid4()
        return KnowledgeGraph(
            nodes=[
                GraphNode(
                    id=u1_id,
                    node_type=NodeType.UNIT,
                    label="Unit A",
                    metadata={"unit_type": "lesson"},
                ),
                GraphNode(
                    id=u2_id,
                    node_type=NodeType.UNIT,
                    label="Unit B",
                    metadata={"unit_type": "topic"},
                ),
                GraphNode(
                    id=c1_id,
                    node_type=NodeType.CONCEPT,
                    label="Concept X",
                    metadata={"category": "skill"},
                ),
            ],
            edges=[
                GraphEdge(
                    source_id=u1_id,
                    target_id=u2_id,
                    edge_type=EdgeType.CONTAINS,
                    weight=1.0,
                    metadata={"source": "test"},
                ),
                GraphEdge(
                    source_id=u1_id,
                    target_id=c1_id,
                    edge_type=EdgeType.REFERENCES,
                    weight=0.8,
                    metadata={"source": "test"},
                ),
                GraphEdge(
                    source_id=c1_id,
                    target_id=u2_id,
                    edge_type=EdgeType.EXPLAINS,
                    weight=0.5,
                    metadata={"source": "test"},
                ),
            ],
        )

    def test_to_dot_returns_string(self) -> None:
        dot = to_dot(self._sample_graph(), title="Test Graph")
        assert isinstance(dot, str)
        assert 'digraph "Test Graph"' in dot

    def test_to_dot_contains_all_nodes(self) -> None:
        dot = to_dot(self._sample_graph())
        assert "Unit A" in dot
        assert "Unit B" in dot
        assert "Concept X" in dot

    def test_to_dot_contains_all_edges(self) -> None:
        dot = to_dot(self._sample_graph())
        assert "contains" in dot
        assert "references" in dot
        assert "explains" in dot

    def test_to_dot_empty_graph(self) -> None:
        dot = to_dot(KnowledgeGraph(), title="Empty")
        assert "digraph" in dot
        assert "}" in dot

    def test_to_adjacency_list(self) -> None:
        adj = to_adjacency_list(self._sample_graph())
        assert len(adj) == 3
        # Unit A has 2 outgoing edges
        unit_a_key = [k for k in adj if "Unit A" in k][0]
        assert len(adj[unit_a_key]) == 2

    def test_to_adjacency_list_empty(self) -> None:
        adj = to_adjacency_list(KnowledgeGraph())
        assert adj == {}

    def test_graph_summary(self) -> None:
        summary = graph_summary(self._sample_graph())
        assert summary["total_nodes"] == 3
        assert summary["total_edges"] == 3
        assert summary["node_types"]["unit"] == 2
        assert summary["node_types"]["concept"] == 1
        assert summary["edge_types"]["contains"] == 1
        assert summary["edge_types"]["references"] == 1
        assert summary["edge_types"]["explains"] == 1
        assert summary["isolated_node_count"] == 0
        assert summary["avg_out_degree"] == pytest.approx(1.0)

    def test_graph_summary_empty(self) -> None:
        summary = graph_summary(KnowledgeGraph())
        assert summary["total_nodes"] == 0
        assert summary["total_edges"] == 0
        assert summary["avg_out_degree"] == 0.0

    def test_graph_summary_isolated_nodes(self) -> None:
        a, b = uuid4(), uuid4()
        g = KnowledgeGraph(
            nodes=[
                GraphNode(id=a, node_type=NodeType.UNIT, label="A"),
                GraphNode(id=b, node_type=NodeType.CONCEPT, label="B"),
            ],
            edges=[],
        )
        summary = graph_summary(g)
        assert summary["isolated_node_count"] == 2
        assert len(summary["isolated_node_ids"]) == 2

    def test_dot_special_characters_escaped(self) -> None:
        g = KnowledgeGraph(
            nodes=[
                GraphNode(
                    id=uuid4(),
                    node_type=NodeType.CONCEPT,
                    label='Quote "test" newline\n',
                ),
            ],
            edges=[],
        )
        dot = to_dot(g)
        assert '\\"test\\"' in dot
        assert "\\n" in dot
