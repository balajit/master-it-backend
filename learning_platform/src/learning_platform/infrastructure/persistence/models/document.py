"""ORM model for canonical documents."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class CanonicalDocumentRow(Base):
    """A persisted canonical document (from the processing pipeline)."""

    __tablename__ = "lp_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(default="")
    title: Mapped[str] = mapped_column(default="")
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )
    nodes_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="nodes", nullable=True
    )
    created_at: Mapped[str] = mapped_column(default="")
