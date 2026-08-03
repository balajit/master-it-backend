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
from collections.abc import Iterable
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException

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
from database.repositories.documents import get_document
from database.repositories.learning import (
    create_lesson,
    create_practice,
    create_quiz,
    create_section,
    create_unit,
    get_lessons_by_plan_ids_for_course,
    get_section,
    list_lessons_for_sections,
    list_practices_for_sections,
    list_quizzes_for_sections,
    list_sections,
    list_units,
)
from schemas import EnrollResponse
from services.lp_results import (
    lp_doc_uuid_from_external_id,
    lp_doc_uuid_from_storage_path,
)

logger: logging.Logger = logging.getLogger(__name__)


def _missing_plan_lesson_ids(
    expected_plan_lesson_ids: set[str],
    lesson_rows: Iterable[Dict[str, Any]],
) -> set[str]:
    found_plan_ids: set[str] = {
        str(row["plan_lesson_id"]) for row in lesson_rows if row.get("plan_lesson_id")
    }
    return expected_plan_lesson_ids - found_plan_ids


def _extract_expected_plan_lesson_ids(plan: Any) -> set[str]:
    expected: set[str] = set()
    missing_identity_titles: list[str] = []

    for lesson in plan.lessons:
        plan_lesson_id_value = getattr(lesson, "unit_id", None)
        if plan_lesson_id_value is None:
            lesson_title = (
                str(getattr(lesson, "title", "")).strip() or "(untitled lesson)"
            )
            missing_identity_titles.append(lesson_title)
            continue
        expected.add(str(plan_lesson_id_value))

    if missing_identity_titles:
        raise HTTPException(
            status_code=409,
            detail=(
                "Study plan is incomplete: one or more lessons are missing LP lesson IDs "
                f"({', '.join(missing_identity_titles[:3])})"
            ),
        )

    return expected


async def _fetch_lp_study_plan(source_document_id: str) -> Any:
    try:
        doc_uuid = await _resolve_source_document_lp_uuid(source_document_id)
    except HTTPException:
        raise

    try:
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

        try:
            async with factory() as session:
                repo = StudyPlanRepository(session)
                plan = await repo.find_by_document(doc_uuid)
        finally:
            await lp_engine.dispose()

        if plan is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Study plan is not ready for the provided source document. "
                    "Process the document completely before enrollment."
                ),
            )

        return plan
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to fetch study plan for document %s", source_document_id
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to load study plan for strict enrollment provisioning",
        ) from exc


async def _resolve_source_document_lp_uuid(source_document_id: str) -> UUID:
    """Resolve source_document_id into the canonical LP document UUID.

    Supported identifiers:
      - LP UUID / LP external SHA-style identifier
      - master-it DocumentModel.id (maps via storage_path -> stable_doc_id)
    """
    document_row = await get_document(source_document_id)
    if document_row is not None:
        storage_path_raw = document_row.get("storage_path")
        storage_path = (
            str(storage_path_raw).strip() if storage_path_raw is not None else ""
        )
        if not storage_path:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Invalid source_document_id: document has no storage path for LP lookup"
                ),
            )
        return lp_doc_uuid_from_storage_path(storage_path)

    lp_doc_uuid = lp_doc_uuid_from_external_id(source_document_id)
    if lp_doc_uuid is not None:
        return lp_doc_uuid

    raise HTTPException(
        status_code=409,
        detail=f"Invalid source_document_id: {source_document_id}",
    )


# ── Main entry point ──────────────────────────────────────────────────────


async def provision_enrollment(
    user_id: int,
    course_id: int,
    source_document_id: Optional[str] = None,
) -> EnrollResponse:
    """Provision a student's enrollment for a course.

    If source_document_id is provided, strict provisioning is validated first.
    For already-enrolled users, this means source-linked provisioning can still
    fail and return an error before the idempotent already_enrolled response.

    DB round-trips (on first enrollment): 5 reads + 3 batch writes + 1 enroll write.
    """
    # ── Flow B: provision content from study plan ──────────────────────────
    if source_document_id is not None:
        await _provision_content_from_study_plan(
            course_id=course_id,
            source_document_id=source_document_id,
        )

    # ── Idempotency check ──────────────────────────────────────────────────
    existing = await get_enrollment(user_id, course_id)
    if existing is not None:
        return EnrollResponse(
            course_id=course_id,
            user_id=user_id,
            enrolled_at=existing["enrolled_at"],
            status="already_enrolled",
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

    Strict behavior:
      - source_document_id must resolve to a ready LP study plan
      - all LP lesson IDs must exist and map after provisioning
      - partial course mappings fail with HTTP 409
    """
    plan = await _fetch_lp_study_plan(source_document_id)
    expected_plan_lesson_ids = _extract_expected_plan_lesson_ids(plan)
    if not expected_plan_lesson_ids:
        raise HTTPException(
            status_code=409,
            detail=(
                "Study plan has no lessons to provision. "
                "Resolve study-plan generation before strict enrollment."
            ),
        )

    existing_rows = await get_lessons_by_plan_ids_for_course(
        course_id,
        list(expected_plan_lesson_ids),
    )
    missing_before = _missing_plan_lesson_ids(expected_plan_lesson_ids, existing_rows)
    if not missing_before:
        logger.info(
            "Study plan content already provisioned for course %d and document %s",
            course_id,
            source_document_id,
        )
        return

    if expected_plan_lesson_ids and len(missing_before) < len(expected_plan_lesson_ids):
        raise HTTPException(
            status_code=409,
            detail=(
                "Course has partial study-plan provisioning. "
                "Resolve the incomplete lesson mapping before enrollment."
            ),
        )

    existing_units = await list_units(course_id)
    existing_titles: set[str] = {str(unit.get("title", "")) for unit in existing_units}
    if str(plan.title) in existing_titles:
        raise HTTPException(
            status_code=409,
            detail=(
                "Course content conflicts with the requested study plan title. "
                "Resolve existing course content before strict enrollment provisioning."
            ),
        )

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
            plan_lesson_id_value = getattr(lesson, "unit_id", None)
            if plan_lesson_id_value is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Study plan is incomplete: lesson is missing LP lesson ID "
                        f"('{lesson.title}')"
                    ),
                )
            await create_lesson(
                section_id=section_id,
                title=lesson.title,
                description=lesson.description or "",
                duration_minutes=lesson.estimated_minutes or 0,
                display_order=lesson.order,
                plan_lesson_id=str(plan_lesson_id_value),
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

    mapped_after_rows = await get_lessons_by_plan_ids_for_course(
        course_id,
        list(expected_plan_lesson_ids),
    )
    missing_after = _missing_plan_lesson_ids(
        expected_plan_lesson_ids, mapped_after_rows
    )
    if missing_after:
        raise HTTPException(
            status_code=409,
            detail=(
                "Strict enrollment provisioning failed to map all lessons. "
                f"Missing {len(missing_after)} lesson mapping(s)."
            ),
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
