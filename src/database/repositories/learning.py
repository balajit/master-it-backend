"""Repository functions for the Learning domain (Units, Sections, Lessons, Practices, Quizzes, User Progress)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models import (
    CourseModel,
    LessonModel,
    PracticeModel,
    QuizModel,
    SectionModel,
    UnitModel,
    UserLessonProgressModel,
    UserPracticeProgressModel,
    UserQuizProgressModel,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Units ───────────────────────────────────────────────────────────────────


async def create_unit(
    course_id: int,
    title: str,
    description: str = "",
    display_order: int = 0,
) -> int:
    now = _now()
    async with AsyncSession(engine) as session:
        course = (
            (
                await session.execute(
                    select(CourseModel).where(CourseModel.id == course_id)
                )
            )
            .scalars()
            .first()
        )
        if not course:
            raise ValueError(f"Course {course_id} not found")
        unit = UnitModel(
            course_id=course_id,
            title=title,
            description=description,
            display_order=display_order,
            created_at=now,
            updated_at=now,
        )
        session.add(unit)
        await session.commit()
        await session.refresh(unit)
        return unit.id


async def get_unit(unit_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        unit = (
            (await session.execute(select(UnitModel).where(UnitModel.id == unit_id)))
            .scalars()
            .first()
        )
        if not unit:
            return None
        return _unit_to_dict(unit)


async def list_units(course_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        units = (
            (
                await session.execute(
                    select(UnitModel)
                    .where(UnitModel.course_id == course_id)
                    .order_by(UnitModel.display_order)
                )
            )
            .scalars()
            .all()
        )
        return [_unit_to_dict(u) for u in units]


async def update_unit(
    unit_id: int,
    title: str | None = None,
    description: str | None = None,
    display_order: int | None = None,
) -> bool:
    async with AsyncSession(engine) as session:
        unit = (
            (await session.execute(select(UnitModel).where(UnitModel.id == unit_id)))
            .scalars()
            .first()
        )
        if not unit:
            return False
        if title is not None:
            unit.title = title
        if description is not None:
            unit.description = description
        if display_order is not None:
            unit.display_order = display_order
        unit.updated_at = _now()
        await session.commit()
        return True


async def delete_unit(unit_id: int) -> bool:
    async with AsyncSession(engine) as session:
        sections = (
            (
                await session.execute(
                    select(SectionModel).where(SectionModel.unit_id == unit_id)
                )
            )
            .scalars()
            .all()
        )
        for section in sections:
            await _delete_section_children(session, section.id)
            await session.delete(section)
        result = await session.execute(delete(UnitModel).where(UnitModel.id == unit_id))
        await session.commit()
        return result.rowcount > 0


def _unit_to_dict(unit: UnitModel) -> Dict[str, Any]:
    return {
        "id": unit.id,
        "course_id": unit.course_id,
        "title": unit.title,
        "description": unit.description,
        "about": unit.about,
        "display_order": unit.display_order,
        "created_at": unit.created_at,
        "updated_at": unit.updated_at,
    }


# ── Sections ────────────────────────────────────────────────────────────────


async def create_section(
    unit_id: int,
    title: str,
    estimated_minutes: int = 0,
    display_order: int = 0,
) -> int:
    now = _now()
    async with AsyncSession(engine) as session:
        unit = (
            (await session.execute(select(UnitModel).where(UnitModel.id == unit_id)))
            .scalars()
            .first()
        )
        if not unit:
            raise ValueError(f"Unit {unit_id} not found")
        section = SectionModel(
            unit_id=unit_id,
            title=title,
            estimated_minutes=estimated_minutes,
            display_order=display_order,
            created_at=now,
            updated_at=now,
        )
        session.add(section)
        await session.commit()
        await session.refresh(section)
        return section.id


async def get_section(section_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        section = (
            (
                await session.execute(
                    select(SectionModel).where(SectionModel.id == section_id)
                )
            )
            .scalars()
            .first()
        )
        if not section:
            return None
        return _section_to_dict(section)


async def list_sections(unit_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        sections = (
            (
                await session.execute(
                    select(SectionModel)
                    .where(SectionModel.unit_id == unit_id)
                    .order_by(SectionModel.display_order)
                )
            )
            .scalars()
            .all()
        )
        return [_section_to_dict(s) for s in sections]


async def update_section(
    section_id: int,
    title: str | None = None,
    estimated_minutes: int | None = None,
    display_order: int | None = None,
) -> bool:
    async with AsyncSession(engine) as session:
        section = (
            (
                await session.execute(
                    select(SectionModel).where(SectionModel.id == section_id)
                )
            )
            .scalars()
            .first()
        )
        if not section:
            return False
        if title is not None:
            section.title = title
        if estimated_minutes is not None:
            section.estimated_minutes = estimated_minutes
        if display_order is not None:
            section.display_order = display_order
        section.updated_at = _now()
        await session.commit()
        return True


async def delete_section(section_id: int) -> bool:
    async with AsyncSession(engine) as session:
        await _delete_section_children(session, section_id)
        result = await session.execute(
            delete(SectionModel).where(SectionModel.id == section_id)
        )
        await session.commit()
        return result.rowcount > 0


async def _delete_section_children(session: AsyncSession, section_id: int) -> None:
    await session.execute(
        delete(LessonModel).where(LessonModel.section_id == section_id)
    )
    await session.execute(
        delete(PracticeModel).where(PracticeModel.section_id == section_id)
    )
    await session.execute(delete(QuizModel).where(QuizModel.section_id == section_id))


def _section_to_dict(section: SectionModel) -> Dict[str, Any]:
    return {
        "id": section.id,
        "unit_id": section.unit_id,
        "title": section.title,
        "estimated_minutes": section.estimated_minutes,
        "display_order": section.display_order,
        "created_at": section.created_at,
        "updated_at": section.updated_at,
    }


# ── Lessons ─────────────────────────────────────────────────────────────────


async def create_lesson(
    section_id: int,
    title: str,
    description: str = "",
    duration_minutes: int = 0,
    display_order: int = 0,
    plan_lesson_id: Optional[str] = None,
) -> int:
    now = _now()
    async with AsyncSession(engine) as session:
        section = (
            (
                await session.execute(
                    select(SectionModel).where(SectionModel.id == section_id)
                )
            )
            .scalars()
            .first()
        )
        if not section:
            raise ValueError(f"Section {section_id} not found")
        lesson = LessonModel(
            section_id=section_id,
            title=title,
            description=description,
            duration_minutes=duration_minutes,
            display_order=display_order,
            plan_lesson_id=plan_lesson_id,
            created_at=now,
            updated_at=now,
        )
        session.add(lesson)
        await session.commit()
        await session.refresh(lesson)
        return lesson.id


async def get_lesson(lesson_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        lesson = (
            (
                await session.execute(
                    select(LessonModel).where(LessonModel.id == lesson_id)
                )
            )
            .scalars()
            .first()
        )
        if not lesson:
            return None
        return _lesson_to_dict(lesson)


async def list_lessons(section_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        lessons = (
            (
                await session.execute(
                    select(LessonModel)
                    .where(LessonModel.section_id == section_id)
                    .order_by(LessonModel.display_order)
                )
            )
            .scalars()
            .all()
        )
        return [_lesson_to_dict(lesson) for lesson in lessons]


async def update_lesson(
    lesson_id: int,
    title: str | None = None,
    description: str | None = None,
    duration_minutes: int | None = None,
    display_order: int | None = None,
) -> bool:
    async with AsyncSession(engine) as session:
        lesson = (
            (
                await session.execute(
                    select(LessonModel).where(LessonModel.id == lesson_id)
                )
            )
            .scalars()
            .first()
        )
        if not lesson:
            return False
        if title is not None:
            lesson.title = title
        if description is not None:
            lesson.description = description
        if duration_minutes is not None:
            lesson.duration_minutes = duration_minutes
        if display_order is not None:
            lesson.display_order = display_order
        lesson.updated_at = _now()
        await session.commit()
        return True


async def delete_lesson(lesson_id: int) -> bool:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            delete(LessonModel).where(LessonModel.id == lesson_id)
        )
        await session.commit()
        return result.rowcount > 0


def _lesson_to_dict(lesson: LessonModel) -> Dict[str, Any]:
    return {
        "id": lesson.id,
        "section_id": lesson.section_id,
        "title": lesson.title,
        "description": lesson.description,
        "duration_minutes": lesson.duration_minutes,
        "display_order": lesson.display_order,
        "plan_lesson_id": lesson.plan_lesson_id,
        "created_at": lesson.created_at,
        "updated_at": lesson.updated_at,
    }


# ── Practices ───────────────────────────────────────────────────────────────


async def create_practice(
    section_id: int,
    title: str,
    required_correct: int = 0,
    total_questions: int = 0,
    display_order: int = 0,
) -> int:
    now = _now()
    async with AsyncSession(engine) as session:
        section = (
            (
                await session.execute(
                    select(SectionModel).where(SectionModel.id == section_id)
                )
            )
            .scalars()
            .first()
        )
        if not section:
            raise ValueError(f"Section {section_id} not found")
        practice = PracticeModel(
            section_id=section_id,
            title=title,
            required_correct=required_correct,
            total_questions=total_questions,
            display_order=display_order,
            created_at=now,
            updated_at=now,
        )
        session.add(practice)
        await session.commit()
        await session.refresh(practice)
        return practice.id


async def get_practice(practice_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        practice = (
            (
                await session.execute(
                    select(PracticeModel).where(PracticeModel.id == practice_id)
                )
            )
            .scalars()
            .first()
        )
        if not practice:
            return None
        return _practice_to_dict(practice)


async def list_practices(section_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        practices = (
            (
                await session.execute(
                    select(PracticeModel)
                    .where(PracticeModel.section_id == section_id)
                    .order_by(PracticeModel.display_order)
                )
            )
            .scalars()
            .all()
        )
        return [_practice_to_dict(p) for p in practices]


async def update_practice(
    practice_id: int,
    title: str | None = None,
    required_correct: int | None = None,
    total_questions: int | None = None,
    display_order: int | None = None,
) -> bool:
    async with AsyncSession(engine) as session:
        practice = (
            (
                await session.execute(
                    select(PracticeModel).where(PracticeModel.id == practice_id)
                )
            )
            .scalars()
            .first()
        )
        if not practice:
            return False
        if title is not None:
            practice.title = title
        if required_correct is not None:
            practice.required_correct = required_correct
        if total_questions is not None:
            practice.total_questions = total_questions
        if display_order is not None:
            practice.display_order = display_order
        practice.updated_at = _now()
        await session.commit()
        return True


async def delete_practice(practice_id: int) -> bool:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            delete(PracticeModel).where(PracticeModel.id == practice_id)
        )
        await session.commit()
        return result.rowcount > 0


def _practice_to_dict(practice: PracticeModel) -> Dict[str, Any]:
    return {
        "id": practice.id,
        "section_id": practice.section_id,
        "title": practice.title,
        "required_correct": practice.required_correct,
        "total_questions": practice.total_questions,
        "display_order": practice.display_order,
        "practice_type": practice.practice_type,
        "created_at": practice.created_at,
        "updated_at": practice.updated_at,
    }


# ── Quizzes ─────────────────────────────────────────────────────────────────


async def create_quiz(
    section_id: int,
    title: str,
) -> int:
    now = _now()
    async with AsyncSession(engine) as session:
        section = (
            (
                await session.execute(
                    select(SectionModel).where(SectionModel.id == section_id)
                )
            )
            .scalars()
            .first()
        )
        if not section:
            raise ValueError(f"Section {section_id} not found")
        quiz = QuizModel(
            section_id=section_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        session.add(quiz)
        await session.commit()
        await session.refresh(quiz)
        return quiz.id


async def get_quiz(quiz_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        quiz = (
            (await session.execute(select(QuizModel).where(QuizModel.id == quiz_id)))
            .scalars()
            .first()
        )
        if not quiz:
            return None
        return _quiz_to_dict(quiz)


async def list_quizzes(section_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        quizzes = (
            (
                await session.execute(
                    select(QuizModel).where(QuizModel.section_id == section_id)
                )
            )
            .scalars()
            .all()
        )
        return [_quiz_to_dict(q) for q in quizzes]


async def update_quiz(
    quiz_id: int,
    title: str | None = None,
) -> bool:
    async with AsyncSession(engine) as session:
        quiz = (
            (await session.execute(select(QuizModel).where(QuizModel.id == quiz_id)))
            .scalars()
            .first()
        )
        if not quiz:
            return False
        if title is not None:
            quiz.title = title
        quiz.updated_at = _now()
        await session.commit()
        return True


async def delete_quiz(quiz_id: int) -> bool:
    async with AsyncSession(engine) as session:
        result = await session.execute(delete(QuizModel).where(QuizModel.id == quiz_id))
        await session.commit()
        return result.rowcount > 0


def _quiz_to_dict(quiz: QuizModel) -> Dict[str, Any]:
    return {
        "id": quiz.id,
        "section_id": quiz.section_id,
        "title": quiz.title,
        "created_at": quiz.created_at,
        "updated_at": quiz.updated_at,
    }


# ── Batch Queries ───────────────────────────────────────────────────────────


async def list_lessons_for_sections(
    section_ids: List[int],
) -> List[Dict[str, Any]]:
    """Return all lessons for the given section IDs in a single query."""
    if not section_ids:
        return []
    async with AsyncSession(engine) as session:
        lessons = (
            (
                await session.execute(
                    select(LessonModel)
                    .where(LessonModel.section_id.in_(section_ids))
                    .order_by(LessonModel.section_id, LessonModel.display_order)
                )
            )
            .scalars()
            .all()
        )
        return [_lesson_to_dict(lesson) for lesson in lessons]


async def list_practices_for_sections(
    section_ids: List[int],
) -> List[Dict[str, Any]]:
    """Return all practices for the given section IDs in a single query."""
    if not section_ids:
        return []
    async with AsyncSession(engine) as session:
        practices = (
            (
                await session.execute(
                    select(PracticeModel)
                    .where(PracticeModel.section_id.in_(section_ids))
                    .order_by(PracticeModel.section_id, PracticeModel.display_order)
                )
            )
            .scalars()
            .all()
        )
        return [_practice_to_dict(p) for p in practices]


async def list_quizzes_for_sections(
    section_ids: List[int],
) -> List[Dict[str, Any]]:
    """Return all quizzes for the given section IDs in a single query."""
    if not section_ids:
        return []
    async with AsyncSession(engine) as session:
        quizzes = (
            (
                await session.execute(
                    select(QuizModel)
                    .where(QuizModel.section_id.in_(section_ids))
                    .order_by(QuizModel.section_id)
                )
            )
            .scalars()
            .all()
        )
        return [_quiz_to_dict(q) for q in quizzes]


async def get_lesson_progress_for_user(
    user_id: int, lesson_ids: List[int]
) -> Dict[int, Dict[str, Any]]:
    """Return all lesson progress for a user, keyed by lesson_id."""
    if not lesson_ids:
        return {}
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(UserLessonProgressModel).where(
                        UserLessonProgressModel.user_id == user_id,
                        UserLessonProgressModel.lesson_id.in_(lesson_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            r.lesson_id: {
                "user_id": r.user_id,
                "lesson_id": r.lesson_id,
                "status": r.status,
                "completed_at": r.completed_at,
                "last_accessed_at": r.last_accessed_at,
            }
            for r in rows
        }


async def get_practice_progress_for_user(
    user_id: int, practice_ids: List[int]
) -> Dict[int, Dict[str, Any]]:
    """Return all practice progress for a user, keyed by practice_id."""
    if not practice_ids:
        return {}
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(UserPracticeProgressModel).where(
                        UserPracticeProgressModel.user_id == user_id,
                        UserPracticeProgressModel.practice_id.in_(practice_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            r.practice_id: {
                "user_id": r.user_id,
                "practice_id": r.practice_id,
                "attempts": r.attempts,
                "best_score": r.best_score,
                "status": r.status,
            }
            for r in rows
        }


async def get_quiz_progress_for_user(
    user_id: int, quiz_ids: List[int]
) -> Dict[int, Dict[str, Any]]:
    """Return all quiz progress for a user, keyed by quiz_id."""
    if not quiz_ids:
        return {}
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(UserQuizProgressModel).where(
                        UserQuizProgressModel.user_id == user_id,
                        UserQuizProgressModel.quiz_id.in_(quiz_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            r.quiz_id: {
                "user_id": r.user_id,
                "quiz_id": r.quiz_id,
                "score": r.score,
                "completed_at": r.completed_at,
            }
            for r in rows
        }


# ── User Lesson Progress ────────────────────────────────────────────────────


async def get_user_lesson_progress(
    user_id: int, lesson_id: int
) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = (
            (
                await session.execute(
                    select(UserLessonProgressModel).where(
                        UserLessonProgressModel.user_id == user_id,
                        UserLessonProgressModel.lesson_id == lesson_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not result:
            return None
        return {
            "user_id": result.user_id,
            "lesson_id": result.lesson_id,
            "status": result.status,
            "completed_at": result.completed_at,
            "last_accessed_at": result.last_accessed_at,
        }


async def upsert_user_lesson_progress(
    user_id: int,
    lesson_id: int,
    status: str = "NOT_STARTED",
    completed_at: str | None = None,
    last_accessed_at: str | None = None,
) -> None:
    """Upsert using ON CONFLICT — single query instead of read-then-write."""
    async with AsyncSession(engine) as session:
        stmt = (
            pg_insert(UserLessonProgressModel)
            .values(
                user_id=user_id,
                lesson_id=lesson_id,
                status=status,
                completed_at=completed_at,
                last_accessed_at=last_accessed_at,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "lesson_id"],
                set_={
                    "status": status,
                    "completed_at": completed_at,
                    "last_accessed_at": last_accessed_at,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── User Practice Progress ──────────────────────────────────────────────────


async def get_user_practice_progress(
    user_id: int, practice_id: int
) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = (
            (
                await session.execute(
                    select(UserPracticeProgressModel).where(
                        UserPracticeProgressModel.user_id == user_id,
                        UserPracticeProgressModel.practice_id == practice_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not result:
            return None
        return {
            "user_id": result.user_id,
            "practice_id": result.practice_id,
            "attempts": result.attempts,
            "best_score": result.best_score,
            "status": result.status,
        }


async def upsert_user_practice_progress(
    user_id: int,
    practice_id: int,
    attempts: int = 0,
    best_score: float = 0.0,
    status: str = "NOT_STARTED",
) -> None:
    """Upsert using ON CONFLICT — single query instead of read-then-write."""
    async with AsyncSession(engine) as session:
        stmt = (
            pg_insert(UserPracticeProgressModel)
            .values(
                user_id=user_id,
                practice_id=practice_id,
                attempts=attempts,
                best_score=best_score,
                status=status,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "practice_id"],
                set_={
                    "attempts": attempts,
                    "best_score": best_score,
                    "status": status,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── User Quiz Progress ──────────────────────────────────────────────────────


async def get_user_quiz_progress(
    user_id: int, quiz_id: int
) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = (
            (
                await session.execute(
                    select(UserQuizProgressModel).where(
                        UserQuizProgressModel.user_id == user_id,
                        UserQuizProgressModel.quiz_id == quiz_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not result:
            return None
        return {
            "user_id": result.user_id,
            "quiz_id": result.quiz_id,
            "score": result.score,
            "completed_at": result.completed_at,
        }


async def upsert_user_quiz_progress(
    user_id: int,
    quiz_id: int,
    score: float | None = None,
    completed_at: str | None = None,
) -> None:
    """Upsert using ON CONFLICT — single query instead of read-then-write."""
    async with AsyncSession(engine) as session:
        stmt = (
            pg_insert(UserQuizProgressModel)
            .values(
                user_id=user_id,
                quiz_id=quiz_id,
                score=score,
                completed_at=completed_at,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "quiz_id"],
                set_={
                    "score": score,
                    "completed_at": completed_at,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── Aggregate Progress ──────────────────────────────────────────────────────


async def get_all_user_progress(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return all progress records for a user grouped by type."""
    async with AsyncSession(engine) as session:
        lessons = (
            (
                await session.execute(
                    select(UserLessonProgressModel).where(
                        UserLessonProgressModel.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        practices = (
            (
                await session.execute(
                    select(UserPracticeProgressModel).where(
                        UserPracticeProgressModel.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        quizzes = (
            (
                await session.execute(
                    select(UserQuizProgressModel).where(
                        UserQuizProgressModel.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            "lessons": [
                {
                    "user_id": lp.user_id,
                    "lesson_id": lp.lesson_id,
                    "status": lp.status,
                    "completed_at": lp.completed_at,
                }
                for lp in lessons
            ],
            "practices": [
                {
                    "user_id": pp.user_id,
                    "practice_id": pp.practice_id,
                    "attempts": pp.attempts,
                    "best_score": pp.best_score,
                    "status": pp.status,
                }
                for pp in practices
            ],
            "quizzes": [
                {
                    "user_id": qp.user_id,
                    "quiz_id": qp.quiz_id,
                    "score": qp.score,
                    "completed_at": qp.completed_at,
                }
                for qp in quizzes
            ],
        }


# ── Plan ID cross-reference lookups ─────────────────────────────────────────


async def get_lessons_by_plan_ids(plan_lesson_ids: List[str]) -> List[Dict[str, Any]]:
    """Batch-fetch lessons by their LP LearningUnit UUID (plan_lesson_id).

    Used by the study-plan router to back-populate master-it integer PKs
    into the book-structured response so the frontend can call
    progress/notes/flashcard APIs with integer IDs.
    """
    if not plan_lesson_ids:
        return []
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(LessonModel).where(
                        LessonModel.plan_lesson_id.in_(plan_lesson_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
    return [_lesson_to_dict(r) for r in rows]


async def get_lessons_by_plan_ids_for_course(
    course_id: int,
    plan_lesson_ids: List[str],
) -> List[Dict[str, Any]]:
    """Batch-fetch lessons by LP plan IDs restricted to one course.

    This prevents accidental cross-course matches when different courses
    reference the same LP lesson IDs.
    """
    if not plan_lesson_ids:
        return []

    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(LessonModel)
                    .join(SectionModel, SectionModel.id == LessonModel.section_id)
                    .join(UnitModel, UnitModel.id == SectionModel.unit_id)
                    .where(
                        UnitModel.course_id == course_id,
                        LessonModel.plan_lesson_id.in_(plan_lesson_ids),
                    )
                )
            )
            .scalars()
            .all()
        )

    return [_lesson_to_dict(r) for r in rows]


async def get_sections_by_ids(section_ids: List[int]) -> List[Dict[str, Any]]:
    """Batch-fetch sections by their integer PKs.

    Used alongside get_lessons_by_plan_ids to resolve unit_id from
    lesson → section → unit without an N+1 query pattern.
    """
    if not section_ids:
        return []
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(SectionModel).where(SectionModel.id.in_(section_ids))
                )
            )
            .scalars()
            .all()
        )
    return [_section_to_dict(r) for r in rows]


# ── Resume ──────────────────────────────────────────────────────────────────


async def get_resume_lesson(user_id: int, course_id: int) -> Optional[Dict[str, Any]]:
    """Return the most recently accessed lesson for a user in a given course.

    Joins user_lesson_progress → lessons → sections → units filtered by course_id.
    Returns a dict with lesson_id and unit_id, or None if no progress exists.
    """
    async with AsyncSession(engine) as session:
        result = (
            await session.execute(
                select(
                    UserLessonProgressModel.lesson_id,
                    SectionModel.unit_id,
                )
                .join(
                    LessonModel,
                    LessonModel.id == UserLessonProgressModel.lesson_id,
                )
                .join(
                    SectionModel,
                    SectionModel.id == LessonModel.section_id,
                )
                .join(
                    UnitModel,
                    UnitModel.id == SectionModel.unit_id,
                )
                .where(
                    UserLessonProgressModel.user_id == user_id,
                    UnitModel.course_id == course_id,
                    UserLessonProgressModel.last_accessed_at.isnot(None),
                )
                .order_by(UserLessonProgressModel.last_accessed_at.desc())
                .limit(1)
            )
        ).first()
        if result is None:
            return None
        return {"lesson_id": result.lesson_id, "unit_id": result.unit_id}
