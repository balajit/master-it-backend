from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base


class PipelineLogRow(Base):
    __tablename__ = "lp_pipeline_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(512), default="")
    stage: Mapped[str] = mapped_column(String(128), default="")
    output: Mapped[str] = mapped_column(String(1024), default="")
    result: Mapped[str] = mapped_column(String(16), default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document_process_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("lp_document_process.id"), nullable=True, index=True
    )
