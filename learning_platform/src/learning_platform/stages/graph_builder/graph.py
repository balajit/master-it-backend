"""Knowledge Graph Builder — constructs a directed graph from LearningUnits and Concepts.

The builder creates a mixed graph containing both unit-level nodes and
concept-level nodes.  Six edge types are supported:

* **CONTAINS** — parent unit → child unit
* **DEPENDS_ON** — unit A is a prerequisite for unit B
* **PREREQUISITE** — alias for DEPENDS_ON (backward compat)
* **REFERENCES** — unit → concept it references
* **EXTENDS** — concept A extends concept B
* **EXPLAINS** — concept A explains / defines concept B
* **ILLUSTRATES** — concept A illustrates concept B

Every edge carries ``metadata`` with at least ``{"source": "..."}``
identifying the originator.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from learning_platform.models.concept import ConceptMap, RelationType
from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)

if TYPE_CHECKING:
    from uuid import UUID

    from learning_platform.models.learning_unit import LearningUnit

_LOG = logging.getLogger(__name__)

_SOURCE = "NetworkxGraphBuilder"

# Mapping from Concept RelationshipType → EdgeType
_RELATION_TO_EDGE: dict[RelationType, EdgeType] = {
    RelationType.PREREQUISITE: EdgeType.PREREQUISITE,
    RelationType.CONTAINS: EdgeType.CONTAINS,
    RelationType.RELATES_TO: EdgeType.REFERENCES,
    RelationType.USED_IN: EdgeType.REFERENCES,
    RelationType.DERIVED_FROM: EdgeType.EXTENDS,
    RelationType.EXAMPLE_OF: EdgeType.ILLUSTRATES,
}


class NetworkxGraphBuilder:
    """Builds a KnowledgeGraph using NetworkX for DAG validation."""

    def build(
        self,
        units: list[LearningUnit],
        concepts: ConceptMap,
    ) -> KnowledgeGraph:
        """Convert LearningUnits and Concepts into a validated directed graph."""
        import networkx as nx

        _LOG.info(
            "Building knowledge graph from %d units, %d concepts",
            len(units),
            len(concepts.concepts),
        )

        id_to_unit: dict[UUID, LearningUnit] = {u.id: u for u in units}
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # ── Unit nodes ─────────────────────────────────────────────────────
        for unit in units:
            nodes.append(
                GraphNode(
                    id=unit.id,
                    node_type=NodeType.UNIT,
                    label=unit.title,
                    unit_id=unit.id,
                    metadata={
                        "unit_type": unit.unit_type.value,
                        "difficulty": unit.difficulty.value,
                        "estimated_minutes": unit.estimated_study_time_minutes,
                    },
                )
            )

        # ── Concept nodes ──────────────────────────────────────────────────
        for concept in concepts.concepts:
            nodes.append(
                GraphNode(
                    id=concept.id,
                    node_type=NodeType.CONCEPT,
                    label=concept.name,
                    concept_id=concept.id,
                    metadata={
                        "category": concept.category.value,
                        "importance": concept.importance,
                        "mention_count": concept.mention_count,
                        "aliases": concept.aliases,
                    },
                )
            )

        # ── Unit → Unit edges ──────────────────────────────────────────────
        for unit in units:
            # CONTAINS — parent / child
            if unit.parent_id is not None and unit.parent_id in id_to_unit:
                edges.append(
                    GraphEdge(
                        source_id=unit.parent_id,
                        target_id=unit.id,
                        edge_type=EdgeType.CONTAINS,
                        metadata={"source": _SOURCE, "relationship": "parent_child"},
                    )
                )

            # DEPENDS_ON — prerequisites
            for prereq_id in unit.prerequisite_ids:
                if prereq_id in id_to_unit:
                    edges.append(
                        GraphEdge(
                            source_id=prereq_id,
                            target_id=unit.id,
                            edge_type=EdgeType.DEPENDS_ON,
                            metadata={"source": _SOURCE, "relationship": "prerequisite"},
                        )
                    )

        # ── Unit → Concept edges (REFERENCES) ──────────────────────────────
        # Built by inverting Concept.source_unit_ids: each concept knows
        # which units it belongs to, so we create a REFERENCES edge from
        # each of those units to the concept.
        unit_ids: set[UUID] = {u.id for u in units}
        for concept in concepts.concepts:
            for uid in concept.source_unit_ids:
                if uid in unit_ids:
                    edges.append(
                        GraphEdge(
                            source_id=uid,
                            target_id=concept.id,
                            edge_type=EdgeType.REFERENCES,
                            metadata={
                                "source": _SOURCE,
                                "relationship": "unit_references_concept",
                            },
                        )
                    )

        # ── Concept → Concept edges ────────────────────────────────────────
        concept_ids: set[UUID] = {c.id for c in concepts.concepts}
        for rel in concepts.relationships:
            edge_type = _RELATION_TO_EDGE.get(rel.relation_type)
            if edge_type is None:
                _LOG.debug("Skipping unsupported relation type: %s", rel.relation_type)
                continue
            if rel.source_id not in concept_ids or rel.target_id not in concept_ids:
                continue
            edges.append(
                GraphEdge(
                    source_id=rel.source_id,
                    target_id=rel.target_id,
                    edge_type=edge_type,
                    weight=rel.weight,
                    metadata={
                        "source": _SOURCE,
                        "relationship": rel.relation_type.value,
                        **rel.metadata,
                    },
                )
            )

        # ── Cycle detection ────────────────────────────────────────────────
        digraph = nx.DiGraph()
        for node in nodes:
            digraph.add_node(str(node.id))
        for edge in edges:
            digraph.add_edge(str(edge.source_id), str(edge.target_id))

        if not nx.is_directed_acyclic_graph(digraph):
            _LOG.warning("Graph has cycles — topological sort may be incomplete")

        _LOG.info(
            "Graph built: %d nodes (%d unit, %d concept), %d edges",
            len(nodes),
            len(nodes_by_type(nodes, NodeType.UNIT)),
            len(nodes_by_type(nodes, NodeType.CONCEPT)),
            len(edges),
        )

        return KnowledgeGraph(nodes=nodes, edges=edges)


def nodes_by_type(nodes: list[GraphNode], node_type: NodeType) -> list[GraphNode]:
    """Filter nodes by their ``NodeType``."""
    return [n for n in nodes if n.node_type == node_type]
