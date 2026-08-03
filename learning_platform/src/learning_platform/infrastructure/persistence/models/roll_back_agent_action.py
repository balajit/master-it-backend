from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class RollBackAgentActionRow(Base):
    __tablename__ = "lp_roll_back_agent_action"
    __table_args__ = (
        Index("idx_lp_roll_back_agent_action_status", "status"),
        Index("idx_lp_roll_back_agent_action_created_at", "created_at"),
        Index("idx_lp_roll_back_agent_action_action_type", "action_type"),
        Index(
            "uq_lp_roll_back_agent_action_prepared_target_key",
            "target_key",
            unique=True,
            postgresql_where=text("status = 'prepared'"),
            sqlite_where=text("status = 'prepared'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    target_key: Mapped[str] = mapped_column(String(64), nullable=False)
    precheck_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    target_summary_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType,
        name="target_summary",
        nullable=True,
    )
    undo_steps_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JsonType,
        name="undo_steps",
        nullable=True,
    )
    integrity_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    affected_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    affected_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
