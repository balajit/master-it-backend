"""Repository for knowledge graphs, graph nodes, and graph edges."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.knowledge_graph import (
    GraphEdgeRow,
    GraphNodeRow,
    KnowledgeGraphRow,
)
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository
from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)


class KnowledgeGraphRepository(BaseRepository[KnowledgeGraphRow]):
    """Persists and retrieves ``KnowledgeGraph`` instances."""

    model_class = KnowledgeGraphRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._node_repo = GraphNodeRepository(session)
        self._edge_repo = GraphEdgeRepository(session)

    async def save_graph(self, graph: KnowledgeGraph, document_id: UUID) -> UUID:
        """Persist a full knowledge graph.  Returns the graph row ID."""
        graph_row = KnowledgeGraphRow(
            document_id=document_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata_json=graph.metadata,
        )
        await self.save(graph_row)

        for node in graph.nodes:
            await self._node_repo._save_node(node, graph_row.id)
        for edge in graph.edges:
            await self._edge_repo._save_edge(edge, graph_row.id)

        return graph_row.id

    async def find_by_document(self, document_id: UUID) -> KnowledgeGraph | None:
        """Load the knowledge graph for a document."""
        stmt = select(KnowledgeGraphRow).where(KnowledgeGraphRow.document_id == document_id)
        result = await self._session.execute(stmt)
        graph_row = result.scalars().first()
        if graph_row is None:
            return None

        nodes = await self._node_repo.find_by_graph(graph_row.id)
        edges = await self._edge_repo.find_by_graph(graph_row.id)
        return KnowledgeGraph(
            nodes=nodes,
            edges=edges,
            metadata=graph_row.metadata_json or {},
        )

    async def delete_by_document(self, document_id: UUID) -> int:
        """Delete graph and all child nodes/edges for a document."""
        stmt = select(KnowledgeGraphRow).where(KnowledgeGraphRow.document_id == document_id)
        result = await self._session.execute(stmt)
        graphs = result.scalars().all()
        count = 0
        for g in graphs:
            await self._edge_repo.delete_by_graph(g.id)
            await self._node_repo.delete_by_graph(g.id)
            await self._session.delete(g)
            count += 1
        await self._session.flush()
        return count


class GraphNodeRepository(BaseRepository[GraphNodeRow]):
    """Persists and retrieves ``GraphNode`` instances."""

    model_class = GraphNodeRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _save_node(self, node: GraphNode, graph_id: UUID) -> UUID:
        row = GraphNodeRow(
            id=node.id,
            graph_id=graph_id,
            node_type=node.node_type.value,
            label=node.label,
            unit_id=node.unit_id,
            concept_id=node.concept_id,
            metadata_json=node.metadata,
        )
        await self.save(row)
        return row.id

    async def find_by_graph(self, graph_id: UUID) -> list[GraphNode]:
        stmt = select(GraphNodeRow).where(GraphNodeRow.graph_id == graph_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_graph(self, graph_id: UUID) -> None:
        from sqlalchemy import delete

        stmt = delete(GraphNodeRow).where(GraphNodeRow.graph_id == graph_id)
        await self._session.execute(stmt)

    @staticmethod
    def _to_domain(row: GraphNodeRow) -> GraphNode:
        return GraphNode(
            id=row.id,
            node_type=NodeType(row.node_type),
            label=row.label,
            unit_id=row.unit_id,
            concept_id=row.concept_id,
            metadata=row.metadata_json or {},
        )


class GraphEdgeRepository(BaseRepository[GraphEdgeRow]):
    """Persists and retrieves ``GraphEdge`` instances."""

    model_class = GraphEdgeRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _save_edge(self, edge: GraphEdge, graph_id: UUID) -> UUID:
        row = GraphEdgeRow(
            graph_id=graph_id,
            source_node_id=edge.source_id,
            target_node_id=edge.target_id,
            edge_type=edge.edge_type.value,
            weight=edge.weight,
            metadata_json=edge.metadata,
        )
        await self.save(row)
        return row.id

    async def find_by_graph(self, graph_id: UUID) -> list[GraphEdge]:
        stmt = select(GraphEdgeRow).where(GraphEdgeRow.graph_id == graph_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_graph(self, graph_id: UUID) -> None:
        from sqlalchemy import delete

        stmt = delete(GraphEdgeRow).where(GraphEdgeRow.graph_id == graph_id)
        await self._session.execute(stmt)

    @staticmethod
    def _to_domain(row: GraphEdgeRow) -> GraphEdge:
        return GraphEdge(
            source_id=row.source_node_id,
            target_id=row.target_node_id,
            edge_type=EdgeType(row.edge_type),
            weight=row.weight,
            metadata=row.metadata_json or {},
        )
