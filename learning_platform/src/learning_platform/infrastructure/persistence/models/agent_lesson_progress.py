from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base


class AgentLessonProgressRow(Base):
    """Orchestrator-level lesson progress for one agent pipeline run.

    One row per (agent_process_id, lesson_id). A lesson is ``completed``
    when all sub-agents have written their completion marker to
    ``lp_agent_lesson_completions``.
    """

    __tablename__ = "lp_agent_lesson_progress"
    __table_args__ = (
        UniqueConstraint("agent_process_id", "lesson_id", name="uq_agent_lesson_progress"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lesson_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # pending | completed | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    missing_agents: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
