"""ORM model for persisted document node images."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base


class DocumentImageRow(Base):
    """Binary image data for a single Figure node in a canonical document.

    ``document_id`` references ``lp_documents.id`` logically (no FK
    constraint — documents are the parent, but we avoid a hard constraint
    so image rows can be inserted/deleted independently).

    ``node_id`` is the UUID of the ``DocumentNode`` whose content is a
    ``Figure``.  It is not a FK because document nodes are stored as JSON
    inside ``lp_documents.nodes``, not as a relational table.
    """

    __tablename__ = "lp_document_images"
    __table_args__ = (
        Index("ix_lp_document_images_document_id", "document_id"),
        Index("ix_lp_document_images_node_id", "node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    node_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    image_format: Mapped[str] = mapped_column(String(16), nullable=False, default="PNG")
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
