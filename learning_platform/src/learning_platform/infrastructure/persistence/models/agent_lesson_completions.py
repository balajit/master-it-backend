from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base


class AgentLessonCompletionRow(Base):
    """Sub-agent completion marker for one (agent_process_id, lesson_id, agent_type).

    Each sub-agent writes one row here after finishing a lesson — regardless
    of whether it produced output. The orchestrator uses these markers to
    determine if a lesson is fully complete (all 5 agent_types present).
    """

    __tablename__ = "lp_agent_lesson_completions"
    __table_args__ = (
        UniqueConstraint(
            "agent_process_id",
            "lesson_id",
            "agent_type",
            name="uq_agent_lesson_completion",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lesson_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # keywords | summaries | flashcards | quizzes | practice
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
