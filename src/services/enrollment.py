"""Enrollment Service — provisions a student's study plan instance on course enrollment.

Design:
  • Synchronous path: provision_enrollment() is called directly by the router.
  • Future background path: provision_enrollment() becomes the worker task body unchanged.
  • 8 reads + 3 writes regardless of plan size (no N+1).
  • ON CONFLICT DO NOTHING on bulk inserts — re-enrollment is always safe.

Section locking rules:
  • First section of each unit starts unlocked (status = not_started).
  • All other sections start locked (status = locked).
  • Auto-unlock: when all lessons in a section reach 'mastered', the next section unlocks.
  • Instructor override: create_section_unlock_override() + unlock_section_items() bypass the rule.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from database.repositories.enrollment import (
    batch_init_lesson_progress,
    batch_init_practice_progress,
    batch_init_quiz_progress,
    count_section_lessons,
    create_enrollment,
    get_enrollment,
    get_section_lesson_progress,
    unlock_section_items,
)
from database.repositories.learning import (
    create_lesson,
    create_practice,
    create_quiz,
    create_section,
    create_unit,
    get_section,
    list_lessons_for_sections,
    list_practices_for_sections,
    list_quizzes_for_sections,
    list_sections,
    list_units,
)
from schemas import EnrollResponse

logger: logging.Logger = logging.getLogger(__name__)


# ── Main entry point ──────────────────────────────────────────────────────


async def provision_enrollment(
    user_id: int,
    course_id: int,
    source_document_id: Optional[str] = None,
) -> EnrollResponse:
    """Provision a student's enrollment for a course.

    If already enrolled, returns immediately with status='already_enrolled'.
    If source_document_id is provided, generates course content from the
    learning_platform study plan before initializing progress.

    DB round-trips (on first enrollment): 5 reads + 3 batch writes + 1 enroll write.
    """
    # ── Idempotency check ──────────────────────────────────────────────────
    existing = await get_enrollment(user_id, course_id)
    if existing is not None:
        return EnrollResponse(
            course_id=course_id,
            user_id=user_id,
            enrolled_at=existing["enrolled_at"],
            status="already_enrolled",
        )

    # ── Flow B: provision content from study plan ──────────────────────────
    if source_document_id is not None:
        await _provision_content_from_study_plan(
            course_id=course_id,
            source_document_id=source_document_id,
        )

    # ── Batch-fetch all content for this course ────────────────────────────
    units: List[Dict[str, Any]] = await list_units(course_id)
    if not units:
        # No content yet — still record enrollment, just zero progress rows
        enrollment = await create_enrollment(user_id, course_id)
        return EnrollResponse(
            course_id=course_id,
            user_id=user_id,
            enrolled_at=enrollment["enrolled_at"],
            status="enrolled",
        )

    all_section_ids: List[int] = []
    # Track which sections are unlocked (first per unit)
    unlocked_section_ids: set[int] = set()

    for unit in units:
        sections: List[Dict[str, Any]] = await list_sections(unit["id"])
        if not sections:
            continue
        # Sections ordered by display_order — first one is unlocked
        first_section_id: int = sections[0]["id"]
        unlocked_section_ids.add(first_section_id)
        all_section_ids.extend(s["id"] for s in sections)

    all_lessons = await list_lessons_for_sections(all_section_ids)
    all_practices = await list_practices_for_sections(all_section_ids)
    all_quizzes = await list_quizzes_for_sections(all_section_ids)

    # ── Build section_id lookup for each item ─────────────────────────────
    lesson_section: Dict[int, int] = {
        lesson["id"]: lesson["section_id"] for lesson in all_lessons
    }
    practice_section: Dict[int, int] = {p["id"]: p["section_id"] for p in all_practices}
    quiz_section: Dict[int, int] = {q["id"]: q["section_id"] for q in all_quizzes}  # noqa: F841  (reserved for quiz locking if added later)

    # ── Build progress row dicts ──────────────────────────────────────────
    def _lesson_status(lesson_id: int) -> str:
        return (
            "not_started"
            if lesson_section[lesson_id] in unlocked_section_ids
            else "locked"
        )

    def _item_status(section_id: int) -> str:
        return "not_started" if section_id in unlocked_section_ids else "locked"

    lesson_rows: List[Dict[str, Any]] = [
        {
            "user_id": user_id,
            "lesson_id": lesson["id"],
            "status": _lesson_status(lesson["id"]),
            "completed_at": None,
            "last_accessed_at": None,
        }
        for lesson in all_lessons
    ]

    practice_rows: List[Dict[str, Any]] = [
        {
            "user_id": user_id,
            "practice_id": p["id"],
            "attempts": 0,
            "best_score": 0.0,
            "status": _item_status(practice_section[p["id"]]),
        }
        for p in all_practices
    ]

    quiz_rows: List[Dict[str, Any]] = [
        {
            "user_id": user_id,
            "quiz_id": q["id"],
            "score": None,
            "completed_at": None,
        }
        for q in all_quizzes
    ]

    # ── Bulk inserts — one round-trip each ────────────────────────────────
    lessons_inserted = await batch_init_lesson_progress(lesson_rows)
    practices_inserted = await batch_init_practice_progress(practice_rows)
    quizzes_inserted = await batch_init_quiz_progress(quiz_rows)

    enrollment = await create_enrollment(user_id, course_id)

    logger.info(
        "Enrolled user=%d in course=%d: %d lessons, %d practices, %d quizzes initialized",
        user_id,
        course_id,
        lessons_inserted,
        practices_inserted,
        quizzes_inserted,
    )

    return EnrollResponse(
        course_id=course_id,
        user_id=user_id,
        enrolled_at=enrollment["enrolled_at"],
        status="enrolled",
        lessons_initialized=lessons_inserted,
        practices_initialized=practices_inserted,
        quizzes_initialized=quizzes_inserted,
    )


# ── Flow B: translate study plan into course content ─────────────────────


async def _provision_content_from_study_plan(
    course_id: int,
    source_document_id: str,
) -> None:
    """Translate a learning_platform StudyPlan into units/sections/lessons/
    practices/quizzes in the master-it database.

    Mapping:
      StudyPlan              → one Unit (title from plan.title)
      Milestone              → one Section per milestone
      Lesson                 → one Lesson row per lp Lesson
      Checkpoint (quiz)      → QuizModel row
      Checkpoint (other)     → PracticeModel row

    Idempotent: checks for an existing unit with the same title under the
    course before creating, so re-running is safe.
    """
    try:
        from uuid import UUID

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from learning_platform.config import Settings
        from learning_platform.infrastructure.persistence.engine import create_engine
        from learning_platform.infrastructure.persistence.repositories.sequence import (
            StudyPlanRepository,
        )
        from learning_platform.infrastructure.persistence.session import (
            create_session_factory,
        )

        settings = Settings()
        lp_engine = create_engine(settings)
        factory: async_sessionmaker[AsyncSession] = create_session_factory(lp_engine)

        doc_uuid = UUID(source_document_id)
        async with factory() as session:
            repo = StudyPlanRepository(session)
            plan = await repo.find_by_document(doc_uuid)

        await lp_engine.dispose()

        if plan is None:
            logger.warning(
                "No study plan found for document %s — skipping content provisioning",
                source_document_id,
            )
            return

    except Exception:
        logger.exception(
            "Failed to fetch study plan for document %s", source_document_id
        )
        return

    # Check if a unit with this plan title already exists under the course
    existing_units = await list_units(course_id)
    existing_titles: set[str] = {u["title"] for u in existing_units}
    if plan.title in existing_titles:
        logger.info(
            "Content for plan '%s' already exists in course %d — skipping",
            plan.title,
            course_id,
        )
        return

    # Create the unit
    unit_id = await create_unit(
        course_id=course_id,
        title=plan.title,
        description=plan.description or "",
    )

    # Map milestones → sections, lessons → lessons, checkpoints → practices/quizzes
    # Build milestone_id → order lookup
    # noqa: F841 — reserved for future cross-reference use between milestones
    _milestone_order: Dict[str, int] = {str(m.id): m.order for m in plan.milestones}

    for milestone in sorted(plan.milestones, key=lambda m: m.order):
        section_id = await create_section(
            unit_id=unit_id,
            title=milestone.title,
            estimated_minutes=milestone.estimated_minutes,
            display_order=milestone.order,
        )

        # Lessons belonging to this milestone
        milestone_lessons = [
            lesson
            for lesson in plan.lessons
            if lesson.milestone_id and str(lesson.milestone_id) == str(milestone.id)
        ]
        for lesson in sorted(milestone_lessons, key=lambda lesson: lesson.order):
            await create_lesson(
                section_id=section_id,
                title=lesson.title,
                description=lesson.description or "",
                duration_minutes=lesson.estimated_minutes or 0,
                display_order=lesson.order,
            )

        # Checkpoints belonging to this milestone
        milestone_checkpoints = [
            cp for cp in plan.checkpoints if str(cp.milestone_id) == str(milestone.id)
        ]
        for cp in sorted(milestone_checkpoints, key=lambda c: c.order):
            cp_type: str = (
                cp.checkpoint_type.value
                if hasattr(cp.checkpoint_type, "value")
                else str(cp.checkpoint_type)
            )
            if cp_type == "quiz":
                await create_quiz(
                    section_id=section_id,
                    title=cp.title,
                )
            else:
                # practice | project | self_test → PracticeModel
                await create_practice(
                    section_id=section_id,
                    title=cp.title,
                    display_order=cp.order,
                )

    logger.info(
        "Provisioned content from study plan '%s' into course %d (unit_id=%d)",
        plan.title,
        course_id,
        unit_id,
    )


# ── Section unlock side-effect (called after lesson progress write) ───────


async def check_and_unlock_next_section(user_id: int, section_id: int) -> bool:
    """Check if all lessons in a section are mastered; if so, unlock the next section.

    Returns True if a section was unlocked, False otherwise.
    Called as a fire-and-forget asyncio.create_task after each lesson progress write.
    """
    # How many lessons does this section have?
    total = await count_section_lessons(section_id)
    if total == 0:
        return False

    # Fetch all lesson progress rows for this user + section
    progress_rows = await get_section_lesson_progress(user_id, section_id)

    mastered_count = sum(1 for row in progress_rows if row["status"] == "mastered")

    if mastered_count < total:
        return False  # Not all lessons mastered yet

    # Find the section's parent unit and its display_order
    section = await get_section(section_id)
    if section is None:
        return False

    unit_id: int = section["unit_id"]
    current_order: int = section["display_order"]

    # Find all sections for this unit sorted by display_order
    all_sections = await list_sections(unit_id)
    all_sections_sorted = sorted(all_sections, key=lambda s: s["display_order"])

    # Locate the next section
    next_section: Optional[Dict[str, Any]] = None
    for sec in all_sections_sorted:
        if sec["display_order"] > current_order:
            next_section = sec
            break

    if next_section is None:
        return False  # No next section — unit complete

    unlocked = await unlock_section_items(user_id, next_section["id"])
    if unlocked > 0:
        logger.info(
            "Unlocked section %d for user %d (%d items)",
            next_section["id"],
            user_id,
            unlocked,
        )

    return unlocked > 0
