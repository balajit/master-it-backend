from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class ReviewerRunRow(Base):
    __tablename__ = "lp_reviewer_run"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    requested_lp_documents_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    resolved_lp_documents_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resolved_document_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="processing", index=True
    )
    aggregate_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aggregate_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType,
        name="metadata",
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ReviewerPageResultRow(Base):
    __tablename__ = "lp_reviewer_page_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reviewer_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_reviewer_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lp_documents_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    review_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strengths_json: Mapped[list[str] | None] = mapped_column(
        JsonType,
        name="strengths",
        nullable=True,
    )
    issues_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JsonType,
        name="issues",
        nullable=True,
    )
    recommendations_json: Mapped[list[str] | None] = mapped_column(
        JsonType,
        name="recommendations",
        nullable=True,
    )
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType,
        name="metadata",
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
