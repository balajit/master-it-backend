"""ORM model for learning units."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class LearningUnitRow(Base):
    """A persisted learning unit."""

    __tablename__ = "lp_learning_units"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"), index=True
    )
    unit_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(32), default="basic")
    estimated_study_time_minutes: Mapped[int] = mapped_column(default=0)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lp_learning_units.id", ondelete="SET NULL"), nullable=True, index=True
    )

    learning_objectives_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="learning_objectives", nullable=True
    )
    content_references_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="content_references", nullable=True
    )
    definitions_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="definitions", nullable=True
    )
    examples_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="examples", nullable=True
    )
    figures_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="figures", nullable=True
    )
    tables_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="tables", nullable=True
    )
    equations_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="equations", nullable=True
    )
    exercises_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="exercises", nullable=True
    )
    source_node_ids_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="source_node_ids", nullable=True
    )
    children_ids_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="children_ids", nullable=True
    )
    prerequisite_ids_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="prerequisite_ids", nullable=True
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )
