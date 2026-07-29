"""ORM model for knowledge graphs, graph nodes, and graph edges."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class KnowledgeGraphRow(Base):
    """A persisted knowledge graph container."""

    __tablename__ = "lp_knowledge_graphs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class GraphNodeRow(Base):
    """A persisted knowledge graph node."""

    __tablename__ = "lp_graph_nodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_knowledge_graphs.id", ondelete="CASCADE"), index=True
    )
    node_type: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(512), default="")
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lp_learning_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lp_concepts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class GraphEdgeRow(Base):
    """A persisted knowledge graph edge."""

    __tablename__ = "lp_graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_knowledge_graphs.id", ondelete="CASCADE"), index=True
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_graph_nodes.id", ondelete="CASCADE"),
        index=True,
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_graph_nodes.id", ondelete="CASCADE"),
        index=True,
    )
    edge_type: Mapped[str] = mapped_column(String(64), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )
