"""ORM model for concepts and concept relationships."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class ConceptRow(Base):
    """A persisted concept."""

    __tablename__ = "lp_concepts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(256), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    importance: Mapped[float] = mapped_column(Float, default=0.0)
    mention_count: Mapped[int] = mapped_column(default=0)

    aliases_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="aliases", nullable=True
    )
    source_node_ids_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="source_node_ids", nullable=True
    )
    source_unit_ids_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="source_unit_ids", nullable=True
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class ConceptRelationshipRow(Base):
    """A persisted concept-to-concept relationship."""

    __tablename__ = "lp_concept_relationships"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"), index=True
    )
    source_concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_concepts.id", ondelete="CASCADE"),
        index=True,
    )
    target_concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_concepts.id", ondelete="CASCADE"),
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(64), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )
