"""Repository functions for course enrollment and section unlock overrides."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models import (
    CourseEnrollmentModel,
    LessonModel,
    PracticeModel,
    QuizModel,
    SectionUnlockOverrideModel,
    UserLessonProgressModel,
    UserPracticeProgressModel,
    UserQuizProgressModel,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Enrollment ──────────────────────────────────────────────────────────────


async def get_enrollment(user_id: int, course_id: int) -> Optional[Dict[str, Any]]:
    """Return the enrollment record if it exists, else None."""
    async with AsyncSession(engine) as session:
        row = (
            (
                await session.execute(
                    select(CourseEnrollmentModel).where(
                        CourseEnrollmentModel.user_id == user_id,
                        CourseEnrollmentModel.course_id == course_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not row:
            return None
        return {
            "user_id": row.user_id,
            "course_id": row.course_id,
            "enrolled_at": row.enrolled_at,
            "status": row.status,
        }


async def create_enrollment(user_id: int, course_id: int) -> Dict[str, Any]:
    """Insert a new enrollment row and return it."""
    now = _now()
    async with AsyncSession(engine) as session:
        row = CourseEnrollmentModel(
            user_id=user_id,
            course_id=course_id,
            enrolled_at=now,
            status="active",
        )
        session.add(row)
        await session.commit()
    return {
        "user_id": user_id,
        "course_id": course_id,
        "enrolled_at": now,
        "status": "active",
    }


async def list_course_enrollments(course_id: int) -> List[Dict[str, Any]]:
    """Return all enrollments for a course."""
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(CourseEnrollmentModel).where(
                        CourseEnrollmentModel.course_id == course_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "user_id": r.user_id,
                "course_id": r.course_id,
                "enrolled_at": r.enrolled_at,
                "status": r.status,
            }
            for r in rows
        ]


# ── Batch progress initialization ───────────────────────────────────────────


async def batch_init_lesson_progress(
    rows: List[Dict[str, Any]],
) -> int:
    """Bulk-insert lesson progress rows.  ON CONFLICT DO NOTHING — never
    overwrites existing progress so re-enrollment is safe.

    Each dict must have: user_id, lesson_id, status, completed_at (nullable),
    last_accessed_at (nullable).
    Returns count of rows actually inserted.
    """
    if not rows:
        return 0
    async with AsyncSession(engine) as session:
        stmt = (
            pg_insert(UserLessonProgressModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["user_id", "lesson_id"])
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0


async def batch_init_practice_progress(
    rows: List[Dict[str, Any]],
) -> int:
    """Bulk-insert practice progress rows.  ON CONFLICT DO NOTHING.

    Each dict must have: user_id, practice_id, attempts, best_score, status.
    """
    if not rows:
        return 0
    async with AsyncSession(engine) as session:
        stmt = (
            pg_insert(UserPracticeProgressModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["user_id", "practice_id"])
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0


async def batch_init_quiz_progress(
    rows: List[Dict[str, Any]],
) -> int:
    """Bulk-insert quiz progress rows.  ON CONFLICT DO NOTHING.

    Each dict must have: user_id, quiz_id, score (nullable), completed_at (nullable).
    """
    if not rows:
        return 0
    async with AsyncSession(engine) as session:
        stmt = (
            pg_insert(UserQuizProgressModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["user_id", "quiz_id"])
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0


# ── Section unlock overrides ─────────────────────────────────────────────────


async def create_section_unlock_override(
    user_id: int,
    section_id: int,
    unlocked_by: Optional[int] = None,
) -> None:
    """Record that an instructor manually unlocked a section for a student."""
    now = _now()
    async with AsyncSession(engine) as session:
        stmt = (
            pg_insert(SectionUnlockOverrideModel)
            .values(
                user_id=user_id,
                section_id=section_id,
                unlocked_by=unlocked_by,
                unlocked_at=now,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "section_id"],
                set_={"unlocked_by": unlocked_by, "unlocked_at": now},
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── Section lesson progress (for unlock check) ───────────────────────────────


async def get_section_lesson_progress(
    user_id: int, section_id: int
) -> List[Dict[str, Any]]:
    """Return all lesson progress rows for a user within a specific section.

    Used to determine whether a section is fully mastered (all lessons done).
    """
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(UserLessonProgressModel)
                    .join(
                        LessonModel,
                        LessonModel.id == UserLessonProgressModel.lesson_id,
                    )
                    .where(
                        UserLessonProgressModel.user_id == user_id,
                        LessonModel.section_id == section_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "user_id": r.user_id,
                "lesson_id": r.lesson_id,
                "status": r.status,
                "completed_at": r.completed_at,
            }
            for r in rows
        ]


async def count_section_lessons(section_id: int) -> int:
    """Return the total number of lessons in a section."""
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(LessonModel).where(LessonModel.section_id == section_id)
                )
            )
            .scalars()
            .all()
        )
        return len(rows)


# ── Unlock section items ──────────────────────────────────────────────────────


async def unlock_section_items(user_id: int, section_id: int) -> int:
    """Upsert all locked lessons/practices/quizzes in a section to 'not_started'.

    Returns the total number of rows affected.
    """
    total: int = 0
    async with AsyncSession(engine) as session:
        # Lessons
        lessons = (
            (
                await session.execute(
                    select(LessonModel).where(LessonModel.section_id == section_id)
                )
            )
            .scalars()
            .all()
        )
        lesson_ids: List[int] = [lesson.id for lesson in lessons]

        if lesson_ids:
            lesson_rows = [
                {
                    "user_id": user_id,
                    "lesson_id": lid,
                    "status": "not_started",
                    "completed_at": None,
                    "last_accessed_at": None,
                }
                for lid in lesson_ids
            ]
            stmt = (
                pg_insert(UserLessonProgressModel)
                .values(lesson_rows)
                .on_conflict_do_update(
                    index_elements=["user_id", "lesson_id"],
                    set_={"status": "not_started"},
                    where=(UserLessonProgressModel.status == "locked"),
                )
            )
            result = await session.execute(stmt)
            total += result.rowcount or 0

        # Practices
        practices = (
            (
                await session.execute(
                    select(PracticeModel).where(PracticeModel.section_id == section_id)
                )
            )
            .scalars()
            .all()
        )
        practice_ids: List[int] = [p.id for p in practices]

        if practice_ids:
            practice_rows = [
                {
                    "user_id": user_id,
                    "practice_id": pid,
                    "attempts": 0,
                    "best_score": 0.0,
                    "status": "not_started",
                }
                for pid in practice_ids
            ]
            stmt_p = (
                pg_insert(UserPracticeProgressModel)
                .values(practice_rows)
                .on_conflict_do_update(
                    index_elements=["user_id", "practice_id"],
                    set_={"status": "not_started"},
                    where=(UserPracticeProgressModel.status == "locked"),
                )
            )
            result_p = await session.execute(stmt_p)
            total += result_p.rowcount or 0

        # Quizzes
        quizzes = (
            (
                await session.execute(
                    select(QuizModel).where(QuizModel.section_id == section_id)
                )
            )
            .scalars()
            .all()
        )
        quiz_ids: List[int] = [q.id for q in quizzes]

        if quiz_ids:
            quiz_rows = [
                {
                    "user_id": user_id,
                    "quiz_id": qid,
                    "score": None,
                    "completed_at": None,
                }
                for qid in quiz_ids
            ]
            stmt_q = (
                pg_insert(UserQuizProgressModel)
                .values(quiz_rows)
                .on_conflict_do_update(
                    index_elements=["user_id", "quiz_id"],
                    set_={"status": "not_started"},
                    where=(UserQuizProgressModel.completed_at.is_(None)),
                )
            )
            result_q = await session.execute(stmt_q)
            total += result_q.rowcount or 0

        await session.commit()

    return total
