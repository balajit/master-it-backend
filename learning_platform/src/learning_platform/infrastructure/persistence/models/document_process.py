from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class DocumentProcessRow(Base):
    __tablename__ = "lp_document_process"
    __table_args__ = (
        Index(
            "uq_lp_document_process_active_abs_path",
            "abs_path",
            unique=True,
            postgresql_where=text("status IN ('pending','processing')"),
            sqlite_where=text("status IN ('pending','processing')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    abs_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    run_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="process")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_completed_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resume_state_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="resume_state", nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
