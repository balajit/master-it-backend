"""Graph visualization utilities — export KnowledgeGraph to common formats.

Provides DOT (Graphviz) export, adjacency-list representation, and
summary statistics.  No external graph-rendering libraries are required
at runtime — the DOT output can be piped to ``dot`` / ``neato`` or
rendered via ``graphviz-python``.
"""

from __future__ import annotations

import io
from collections import Counter
from typing import TYPE_CHECKING, Any

from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)

if TYPE_CHECKING:
    from uuid import UUID

# ──────────────────────────────────────────────────────────────────────────────
# Colour palette
# ──────────────────────────────────────────────────────────────────────────────

_UNIT_COLOUR = "#4A90D9"
_CONCEPT_COLOUR = "#F5A623"
_EDGE_COLOURS: dict[EdgeType, str] = {
    EdgeType.CONTAINS: "#555555",
    EdgeType.DEPENDS_ON: "#D0021B",
    EdgeType.PREREQUISITE: "#D0021B",
    EdgeType.REFERENCES: "#7ED321",
    EdgeType.EXTENDS: "#BD10E0",
    EdgeType.EXPLAINS: "#F8E71C",
    EdgeType.ILLUSTRATES: "#50E3C2",
}


# ──────────────────────────────────────────────────────────────────────────────
# DOT export
# ──────────────────────────────────────────────────────────────────────────────


def to_dot(graph: KnowledgeGraph, *, title: str = "KnowledgeGraph") -> str:
    """Render *graph* as a Graphviz DOT string.

    Unit nodes are drawn as boxes, concept nodes as ellipses.  Edge
    colours follow ``_EDGE_COLOURS``.
    """
    buf = io.StringIO()
    buf.write(f'digraph "{title}" {{\n')
    buf.write("  rankdir=LR;\n")
    buf.write('  node [shape=box, style=filled, fontname="Helvetica"];\n\n')

    # ── nodes ──────────────────────────────────────────────────────────────
    for node in graph.nodes:
        attrs = _node_dot_attrs(node)
        buf.write(f'  "{node.id}" [{attrs}];\n')

    buf.write("\n")

    # ── edges ──────────────────────────────────────────────────────────────
    for edge in graph.edges:
        attrs = _edge_dot_attrs(edge)
        buf.write(f'  "{edge.source_id}" -> "{edge.target_id}" [{attrs}];\n')

    buf.write("}\n")
    return buf.getvalue()


def _node_dot_attrs(node: GraphNode) -> str:
    """Return comma-separated DOT attributes for *node*."""
    colour = _UNIT_COLOUR if node.node_type == NodeType.UNIT else _CONCEPT_COLOUR
    shape = "box" if node.node_type == NodeType.UNIT else "ellipse"
    parts = [
        f'label="{_escape_dot(node.label)}"',
        f'fillcolor="{colour}"',
        f"shape={shape}",
        "style=filled",
    ]
    if node.metadata:
        tooltip = _escape_dot(", ".join(f"{k}={v}" for k, v in node.metadata.items()))
        parts.append(f'tooltip="{tooltip}"')
    return ", ".join(parts)


def _edge_dot_attrs(edge: GraphEdge) -> str:
    """Return comma-separated DOT attributes for *edge*."""
    colour = _EDGE_COLOURS.get(edge.edge_type, "#999999")
    label = edge.edge_type.value
    parts = [
        f'label="{label}"',
        f'color="{colour}"',
        f"penwidth={max(0.5, edge.weight):.1f}",
    ]
    if edge.metadata:
        tooltip = _escape_dot(", ".join(f"{k}={v}" for k, v in edge.metadata.items()))
        parts.append(f'tooltip="{tooltip}"')
    return ", ".join(parts)


def _escape_dot(text: str) -> str:
    """Escape characters that break DOT labels."""
    return text.replace('"', '\\"').replace("\n", "\\n")


# ──────────────────────────────────────────────────────────────────────────────
# Adjacency list
# ──────────────────────────────────────────────────────────────────────────────


def to_adjacency_list(graph: KnowledgeGraph) -> dict[str, list[str]]:
    """Return a human-readable adjacency list.

    Keys are ``"<label> (<node_type>)"``; values are lists of
    ``"<label> (<edge_type>)"`` strings.
    """
    id_to_node: dict[UUID, GraphNode] = {n.id: n for n in graph.nodes}
    adj: dict[str, list[str]] = {_node_key(n): [] for n in graph.nodes}
    for edge in graph.edges:
        src = id_to_node.get(edge.source_id)
        tgt = id_to_node.get(edge.target_id)
        if src is not None and tgt is not None:
            adj[_node_key(src)].append(f"{tgt.label} ({edge.edge_type.value})")
    return adj


def _node_key(node: GraphNode) -> str:
    return f"{node.label} ({node.node_type.value})"


# ──────────────────────────────────────────────────────────────────────────────
# Summary statistics
# ──────────────────────────────────────────────────────────────────────────────


def graph_summary(graph: KnowledgeGraph) -> dict[str, Any]:
    """Return a dictionary of summary statistics for *graph*."""
    node_types = Counter(n.node_type.value for n in graph.nodes)
    edge_types = Counter(e.edge_type.value for e in graph.edges)

    in_degree: Counter[str] = Counter()
    out_degree: Counter[str] = Counter()
    for edge in graph.edges:
        out_degree[str(edge.source_id)] += 1
        in_degree[str(edge.target_id)] += 1

    all_ids = {str(n.id) for n in graph.nodes}
    isolated = [str(nid) for nid in all_ids if in_degree[nid] == 0 and out_degree[nid] == 0]

    return {
        "total_nodes": len(graph.nodes),
        "total_edges": len(graph.edges),
        "node_types": dict(node_types),
        "edge_types": dict(edge_types),
        "isolated_node_count": len(isolated),
        "isolated_node_ids": isolated,
        "avg_out_degree": (sum(out_degree.values()) / len(graph.nodes) if graph.nodes else 0.0),
    }
