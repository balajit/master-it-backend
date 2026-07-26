"""Knowledge Graph models — a directed graph of learning concepts and their relationships.

The graph mixes two kinds of nodes — **unit nodes** (representing
``LearningUnit`` instances) and **concept nodes** (representing
``Concept`` instances).  Edges carry typed metadata following the six
supported relationship types.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EdgeType(StrEnum):
    """Supported edge types in the knowledge graph.

    Attributes
    ----------
    CONTAINS:
        A parent unit contains child unit B.
    DEPENDS_ON:
        Unit A is a prerequisite for unit B (direct dependency).
    PREREQUISITE:
        Alias for DEPENDS_ON — kept for backward compatibility.
    REFERENCES:
        Unit A references concept B.
    EXTENDS:
        Concept A extends / generalises concept B.
    EXPLAINS:
        Concept A explains / defines concept B.
    ILLUSTRATES:
        Concept A illustrates / gives an example of concept B.
    """

    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    PREREQUISITE = "prerequisite"
    REFERENCES = "references"
    EXTENDS = "extends"
    EXPLAINS = "explains"
    ILLUSTRATES = "illustrates"


class NodeType(StrEnum):
    """Discriminator for graph node kinds."""

    UNIT = "unit"
    CONCEPT = "concept"


class GraphNode(BaseModel):
    """A node in the knowledge graph.

    Nodes can represent either a ``LearningUnit`` (``node_type=UNIT``) or
    a ``Concept`` (``node_type=CONCEPT``).  ``unit_id`` or ``concept_id``
    holds the foreign key respectively.
    """

    id: UUID = Field(default_factory=uuid4)
    node_type: NodeType
    label: str
    unit_id: UUID | None = None
    concept_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """A directed edge between two graph nodes.

    ``metadata`` MUST carry at least ``{"source": "<originator>"}``
    identifying the stage that created the edge.
    """

    source_id: UUID
    target_id: UUID
    edge_type: EdgeType
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraph(BaseModel):
    """A directed graph of learning units and their domain concepts.

    The graph is expected to be acyclic (DAG) but this is validated at
    the ``NetworkX`` level rather than enforced at the model level.
    """

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ── lookups ────────────────────────────────────────────────────────────
    def node_ids(self) -> set[UUID]:
        """Return all node IDs for quick membership tests."""
        return {n.id for n in self.nodes}

    def nodes_by_type(self, node_type: NodeType) -> list[GraphNode]:
        """Return nodes filtered by ``NodeType``."""
        return [n for n in self.nodes if n.node_type == node_type]

    def edges_by_type(self, edge_type: EdgeType) -> list[GraphEdge]:
        """Return edges filtered by ``EdgeType``."""
        return [e for e in self.edges if e.edge_type == edge_type]

    def adjacency_list(self) -> dict[UUID, list[UUID]]:
        """Return a mapping from each node ID to its outgoing neighbours."""
        adj: dict[UUID, list[UUID]] = {n.id: [] for n in self.nodes}
        for edge in self.edges:
            if edge.source_id in adj:
                adj[edge.source_id].append(edge.target_id)
        return adj
