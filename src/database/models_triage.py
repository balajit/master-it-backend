from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TriageRunModel(Base):
    __tablename__ = "triage_runs"
    __table_args__ = (
        Index("idx_triage_runs_created_at", "created_at"),
        Index("idx_triage_runs_scope", "scope_kind"),
        Index("idx_triage_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    course_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TriageFindingModel(Base):
    __tablename__ = "triage_findings"
    __table_args__ = (
        Index("idx_triage_findings_run_id", "run_id"),
        Index("idx_triage_findings_table", "table_name"),
        Index("idx_triage_findings_severity", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("triage_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
