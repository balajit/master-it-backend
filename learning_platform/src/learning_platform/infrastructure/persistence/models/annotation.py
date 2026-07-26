"""ORM model for annotations."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class AnnotationRow(Base):
    """A persisted annotation."""

    __tablename__ = "lp_annotations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[uuid.UUID] = mapped_column(index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    detector: Mapped[str] = mapped_column(String(128), default="")

    payload: Mapped[dict[str, object] | None] = mapped_column(JsonType, nullable=True)
