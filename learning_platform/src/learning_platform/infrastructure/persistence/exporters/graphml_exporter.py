"""GraphML exporter — exports knowledge graphs to GraphML via NetworkX."""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from learning_platform.models.knowledge_graph import KnowledgeGraph


class GraphMLExporter:
    """Exports a ``KnowledgeGraph`` to a GraphML file.

    Graph nodes carry ``label``, ``node_type``, and optional
    ``unit_id`` / ``concept_id`` attributes.  Graph edges carry
    ``edge_type`` and ``weight``.
    """

    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)

    def export(self, graph: KnowledgeGraph, filename: str = "knowledge_graph.graphml") -> Path:
        """Convert the ``KnowledgeGraph`` to a NetworkX DiGraph and write GraphML."""
        nx_graph = self._to_networkx(graph)
        path = self._output_dir / filename
        nx.write_graphml(nx_graph, str(path))
        return path

    def _to_networkx(self, graph: KnowledgeGraph) -> nx.DiGraph:
        """Build a ``networkx.DiGraph`` from a ``KnowledgeGraph``."""
        nx_graph = nx.DiGraph()

        for node in graph.nodes:
            attrs: dict[str, str | float] = {
                "label": node.label,
                "node_type": node.node_type.value,
            }
            if node.unit_id is not None:
                attrs["unit_id"] = str(node.unit_id)
            if node.concept_id is not None:
                attrs["concept_id"] = str(node.concept_id)
            nx_graph.add_node(str(node.id), **attrs)

        for edge in graph.edges:
            nx_graph.add_edge(
                str(edge.source_id),
                str(edge.target_id),
                edge_type=edge.edge_type.value,
                weight=edge.weight,
            )

        return nx_graph
