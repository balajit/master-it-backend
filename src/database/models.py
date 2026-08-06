from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    google_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    picture_url: Mapped[str] = mapped_column(String, nullable=False, default="")
    password_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    expires_at: Mapped[str] = mapped_column(String, nullable=False)


class CourseModel(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    number_of_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    difficulty: Mapped[str] = mapped_column(String, nullable=False, default="beginner")
    status: Mapped[str] = mapped_column(String, nullable=False, default="COMING_SOON")
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class RoleModel(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class UserRoleModel(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id"), primary_key=True
    )


class PermissionModel(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class RolePermissionModel(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("roles.id"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("permissions.id"), primary_key=True
    )


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class CourseDocumentModel(Base):
    __tablename__ = "course_documents"

    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id"), primary_key=True
    )
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id"), primary_key=True
    )


class ProgressStatus(str, enum.Enum):
    LOCKED = "LOCKED"
    MCQ_PHASE = "MCQ_PHASE"
    FRQ_PHASE = "FRQ_PHASE"
    MASTERED = "MASTERED"


class CourseTemplateModel(Base):
    __tablename__ = "course_templates"

    course_id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    file_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id"), nullable=False
    )
    structure: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class StudentProgressModel(Base):
    __tablename__ = "student_progress"

    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=ProgressStatus.LOCKED.value
    )
    continuous_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class FlashcardModel(Base):
    __tablename__ = "flashcards"

    card_id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(Uuid, nullable=False)
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    elapsed_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ── Learning Domain ─────────────────────────────────────────────────────────


class UnitModel(Base):
    __tablename__ = "units"
    __table_args__ = (Index("idx_units_course_id", "course_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    about: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class SectionModel(Base):
    __tablename__ = "sections"
    __table_args__ = (Index("idx_sections_unit_id", "unit_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("units.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class LessonModel(Base):
    __tablename__ = "lessons"
    __table_args__ = (Index("idx_lessons_section_id", "section_id", "display_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sections.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_lesson_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class PracticeModel(Base):
    __tablename__ = "practices"
    __table_args__ = (Index("idx_practices_section_id", "section_id", "display_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sections.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    required_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    practice_type: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default="practice"
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class QuizModel(Base):
    __tablename__ = "quizzes"
    __table_args__ = (Index("idx_quizzes_section_id", "section_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sections.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class CourseEnrollmentModel(Base):
    __tablename__ = "course_enrollments"

    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_enrollment_user_course"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id"), nullable=False
    )
    enrolled_at: Mapped[str] = mapped_column(String, nullable=False)
    # 'active' | 'completed' | 'dropped'
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")


class SectionUnlockOverrideModel(Base):
    __tablename__ = "section_unlock_overrides"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    section_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sections.id"), primary_key=True
    )
    unlocked_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    unlocked_at: Mapped[str] = mapped_column(String, nullable=False)


class UserLessonProgressModel(Base):
    __tablename__ = "user_lesson_progress"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    lesson_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lessons.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="NOT_STARTED")
    completed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_accessed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class UserPracticeProgressModel(Base):
    __tablename__ = "user_practice_progress"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    practice_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("practices.id"), primary_key=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="NOT_STARTED")


class UserQuizProgressModel(Base):
    __tablename__ = "user_quiz_progress"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), primary_key=True
    )
    quiz_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quizzes.id"), primary_key=True
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)


# ── Notes & Flashcards ───────────────────────────────────────────────────────


class UserNoteModel(Base):
    __tablename__ = "user_notes"
    __table_args__ = (
        Index("idx_user_notes_user_id", "user_id"),
        Index("idx_user_notes_unit_id", "unit_id"),
        Index("idx_user_notes_lesson_id", "lesson_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    lesson_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class UserFlashcardModel(Base):
    __tablename__ = "user_flashcards"
    __table_args__ = (
        Index("idx_user_flashcards_user_id", "user_id"),
        Index("idx_user_flashcards_created_by", "created_by"),
        Index("idx_user_flashcards_course_id", "course_id"),
        Index("idx_user_flashcards_unit_id", "unit_id"),
        Index("idx_user_flashcards_lesson_id", "lesson_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # NULL = course-scoped; NOT NULL = user-owned
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    # Exactly one of the three scope columns is set
    course_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("courses.id"), nullable=True
    )
    unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    lesson_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    is_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class UserFlashcardsRequestModel(Base):
    """Tracks in-flight flashcard generation requests.

    A partial unique index on (scope, target_id) for the active statuses
    guarantees only one pending/in_progress generation per target, so
    concurrent generate calls for the same lesson/unit share a single LLM run.
    """

    __tablename__ = "user_flashcards_request"
    __table_args__ = (
        Index("ix_user_flashcards_request_scope_target", "scope", "target_id"),
        Index("ix_user_flashcards_request_user_id", "user_id"),
        Index(
            "uq_user_flashcards_request_active",
            "scope",
            "target_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'in_progress')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # pending | in_progress | completed | failed
    status: Mapped[str] = mapped_column(String, nullable=False, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


# ── Item Progress (book-level) ────────────────────────────────────────────────
# Tracks per-student progress at the lp_book_item level.
# item_id is a UUID string referencing lp_book_item.id in the LP database.
# TODO: rename table to singular convention (item_progress → item_progress already singular)


class ItemProgressModel(Base):
    """Per-student progress for a single content item (lp_book_item)."""

    __tablename__ = "item_progress"
    __table_args__ = (
        Index("idx_item_progress_enrollment_id", "enrollment_id"),
        Index("idx_item_progress_item_id", "item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enrollment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("course_enrollments.id"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(String, nullable=False)  # lp_book_item UUID
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="not_started"
    )  # not_started | in_progress | completed
    completed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(String, nullable=False, default="")
