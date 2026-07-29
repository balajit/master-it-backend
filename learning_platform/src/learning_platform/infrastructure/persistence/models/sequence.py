"""ORM model for study plans, lessons, milestones, and checkpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.persistence.models.base import Base, JsonType


class StudyPlanRow(Base):
    """A persisted study plan."""

    __tablename__ = "lp_study_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_documents.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(String(2048), default="")
    total_estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)
    total_lessons: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class LessonRow(Base):
    """A persisted lesson within a study plan."""

    __tablename__ = "lp_lessons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_study_plans.id", ondelete="CASCADE"), index=True
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lp_milestones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_learning_units.id", ondelete="CASCADE"),
        index=True,
    )
    order: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(String(2048), default="")
    lesson_type: Mapped[str] = mapped_column(String(32), default="core")
    difficulty: Mapped[str] = mapped_column(String(32), default="basic")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)

    learning_objectives_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="learning_objectives", nullable=True
    )
    prerequisites_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="prerequisites", nullable=True
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class MilestoneRow(Base):
    """A persisted milestone within a study plan."""

    __tablename__ = "lp_milestones"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_study_plans.id", ondelete="CASCADE"), index=True
    )
    order: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(String(2048), default="")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)

    lesson_ids_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="lesson_ids", nullable=True
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )


class CheckpointRow(Base):
    """A persisted checkpoint within a study plan."""

    __tablename__ = "lp_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_study_plans.id", ondelete="CASCADE"), index=True
    )
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lp_milestones.id", ondelete="CASCADE"),
        index=True,
    )
    order: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512), default="")
    checkpoint_type: Mapped[str] = mapped_column(String(32), default="self_test")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)

    lesson_ids_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="lesson_ids", nullable=True
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(
        JsonType, name="metadata", nullable=True
    )
