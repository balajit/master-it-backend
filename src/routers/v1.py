"""V1 API — versioned REST endpoints for the learning platform."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from auth import get_current_user
from learning_platform.agents.curator import CuratorAgent
from database import (
    get_all_user_progress,
    get_course,
    get_lesson,
    get_practice,
    get_quiz,
    get_section,
    get_user_lesson_progress,
    get_user_practice_progress,
    get_user_quiz_progress,
    list_courses,
    list_units,
    upsert_user_lesson_progress,
    upsert_user_practice_progress,
    upsert_user_quiz_progress,
)
from schemas import (
    Course,
    EnrollRequest,
    EnrollResponse,
    FlashcardCreate,
    FlashcardGenerateRequest,
    FlashcardRequestResponse,
    FlashcardResponse,
    FlashcardUpdate,
    GoalResponse,
    LessonResponse,
    NoteCreate,
    NoteResponse,
    NoteUpdate,
    PracticeResponse,
    PracticeSubmitRequest,
    PracticeSubmitResponse,
    ProgressStatus,
    QuizSubmitRequest,
    QuizSubmitResponse,
    ResumeResponse,
    SectionUnlockRequest,
    SectionUnlockResponse,
    UnitResponse,
    UnitSummary,
    UserLessonProgressResponse,
    UserLessonProgressUpdate,
    UserPracticeProgressResponse,
    UserPracticeProgressUpdate,
    UserProgressResponse,
    UserQuizProgressResponse,
    UserQuizProgressUpdate,
)
from services.enrollment import check_and_unlock_next_section, provision_enrollment
from services.flashcard_generator import FlashCardGenerator
from services.flashcards import generate_flashcards
from services.learning import (
    format_duration,
    get_unit_details,
    invalidate_study_page_cache,
)
from services.progress import (
    _action_label,
    determine_lesson_status,
    determine_practice_status,
    determine_quiz_status,
    to_sidebar_status,
)

router: APIRouter = APIRouter(prefix="/api/v1", tags=["v1"])
logger: logging.Logger = logging.getLogger(__name__)


async def _resolve_unit_id_from_lesson(lesson_id: int) -> int | None:
    """Resolve unit_id from a lesson via its section."""
    lesson = await get_lesson(lesson_id)
    if not lesson:
        return None
    section = await get_section(lesson["section_id"])
    return section["unit_id"] if section else None


async def _resolve_unit_id_from_practice(practice_id: int) -> int | None:
    """Resolve unit_id from a practice via its section."""
    practice = await get_practice(practice_id)
    if not practice:
        return None
    section = await get_section(practice["section_id"])
    return section["unit_id"] if section else None


async def _resolve_unit_id_from_quiz(quiz_id: int) -> int | None:
    """Resolve unit_id from a quiz via its section."""
    quiz = await get_quiz(quiz_id)
    if not quiz:
        return None
    section = await get_section(quiz["section_id"])
    return section["unit_id"] if section else None


# ── Courses ─────────────────────────────────────────────────────────────────


@router.get("/courses", response_model=List[Course])
async def list_courses_v1(
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[Course]:
    courses = await list_courses()
    return [Course(**c) for c in courses]


@router.get("/courses/{course_id}", response_model=Course)
async def get_course_v1(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Course:
    course = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return Course(**course)


# ── Units ───────────────────────────────────────────────────────────────────


@router.get("/units/{unit_id}", response_model=UnitResponse)
async def get_unit_v1(
    unit_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UnitResponse:
    result = await get_unit_details(unit_id=unit_id, user_id=user["id"])
    if not result:
        raise HTTPException(status_code=404, detail="Unit not found")
    return result


# ── Lessons ─────────────────────────────────────────────────────────────────


@router.get("/lessons/{lesson_id}", response_model=LessonResponse)
async def get_lesson_v1(
    lesson_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> LessonResponse:
    lesson = await get_lesson(lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    progress = await get_user_lesson_progress(user["id"], lesson_id)
    status = determine_lesson_status(progress)
    return LessonResponse(
        id=lesson["id"],
        title=lesson["title"],
        description=lesson["description"],
        duration_minutes=lesson["duration_minutes"],
        duration_label=format_duration(lesson["duration_minutes"]),
        order=lesson["display_order"],
        status=status,
        completed_at=progress["completed_at"] if progress else None,
        sidebar_status=to_sidebar_status(status),
    )


# ── Practices ───────────────────────────────────────────────────────────────


@router.get("/practices/{practice_id}", response_model=PracticeResponse)
async def get_practice_v1(
    practice_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> PracticeResponse:
    practice = await get_practice(practice_id)
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")
    progress = await get_user_practice_progress(user["id"], practice_id)
    status = determine_practice_status(progress, practice["required_correct"])
    req: int = practice["required_correct"]
    total: int = practice["total_questions"]
    progress_label: str = f"Score {req}/{total} to pass" if total > 0 else ""
    return PracticeResponse(
        id=practice["id"],
        title=practice["title"],
        required_correct=req,
        total_questions=total,
        order=practice["display_order"],
        status=status,
        attempts=progress["attempts"] if progress else 0,
        best_score=progress["best_score"] if progress else 0.0,
        # TODO: derive from db column once added
        activity_type=practice.get("practice_type") or "practice",
        locked=status == ProgressStatus.LOCKED,
        progress_label=progress_label,
        action_label=_action_label(status),
        sidebar_status=to_sidebar_status(status),
    )


@router.post("/practices/{practice_id}/submit", response_model=PracticeSubmitResponse)
async def submit_practice_v1(
    practice_id: int,
    payload: PracticeSubmitRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> PracticeSubmitResponse:
    practice = await get_practice(practice_id)
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    score: float = payload.score
    required: int = practice["required_correct"]
    passed: bool = score >= required if required > 0 else score > 0

    progress = await get_user_practice_progress(user["id"], practice_id)
    attempts: int = (progress["attempts"] if progress else 0) + 1
    best_score: float = max(score, progress["best_score"] if progress else 0.0)
    status: str = (
        ProgressStatus.MASTERED.value if passed else ProgressStatus.ATTEMPTED.value
    )

    await upsert_user_practice_progress(
        user_id=user["id"],
        practice_id=practice_id,
        attempts=attempts,
        best_score=best_score,
        status=status,
    )

    logger.info(
        "Practice %d submitted by user %s: score=%.1f passed=%s",
        practice_id,
        user["id"],
        score,
        passed,
    )

    unit_id = await _resolve_unit_id_from_practice(practice_id)
    invalidate_study_page_cache(unit_id)

    return PracticeSubmitResponse(
        practice_id=practice_id,
        score=score,
        passed=passed,
        attempts=attempts,
        best_score=best_score,
        status=status,
    )


# ── Quizzes ─────────────────────────────────────────────────────────────────


@router.get("/quizzes/{quiz_id}", response_model=GoalResponse)
async def get_quiz_v1(
    quiz_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> GoalResponse:
    quiz = await get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    progress = await get_user_quiz_progress(user["id"], quiz_id)
    status = determine_quiz_status(progress)
    return GoalResponse(
        id=quiz["id"],
        title=quiz["title"],
        score=progress["score"] if progress else None,
        completed_at=progress["completed_at"] if progress else None,
        status=status,
        locked=status == ProgressStatus.LOCKED,
        action_label=_action_label(status),
    )


@router.post("/quizzes/{quiz_id}/submit", response_model=QuizSubmitResponse)
async def submit_quiz_v1(
    quiz_id: int,
    payload: QuizSubmitRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> QuizSubmitResponse:
    quiz = await get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    score: float = payload.score
    passing_score: float = 70.0
    passed: bool = score >= passing_score
    now: str = datetime.now(timezone.utc).isoformat()

    await upsert_user_quiz_progress(
        user_id=user["id"],
        quiz_id=quiz_id,
        score=score,
        completed_at=now,
    )

    logger.info(
        "Quiz %d submitted by user %s: score=%.1f passed=%s",
        quiz_id,
        user["id"],
        score,
        passed,
    )

    unit_id = await _resolve_unit_id_from_quiz(quiz_id)
    invalidate_study_page_cache(unit_id)

    return QuizSubmitResponse(
        quiz_id=quiz_id,
        score=score,
        passed=passed,
        completed_at=now,
    )


# ── User Progress ───────────────────────────────────────────────────────────


@router.get("/users/me/progress", response_model=UserProgressResponse)
async def get_user_progress_v1(
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserProgressResponse:
    all_progress = await get_all_user_progress(user["id"])
    return UserProgressResponse(
        user_id=user["id"],
        lessons=all_progress["lessons"],
        practices=all_progress["practices"],
        quizzes=all_progress["quizzes"],
    )


@router.patch(
    "/users/me/lessons/{lesson_id}", response_model=UserLessonProgressResponse
)
async def update_lesson_progress_v1(
    lesson_id: int,
    payload: UserLessonProgressUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserLessonProgressResponse:
    lesson = await get_lesson(lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    await upsert_user_lesson_progress(
        user_id=user["id"],
        lesson_id=lesson_id,
        status=payload.status,
        completed_at=payload.completed_at,
        last_accessed_at=datetime.now(timezone.utc).isoformat(),
    )

    progress = await get_user_lesson_progress(user["id"], lesson_id)
    assert progress is not None
    logger.info(
        "Lesson %d progress updated by user %s: status=%s",
        lesson_id,
        user["id"],
        payload.status,
    )
    unit_id = await _resolve_unit_id_from_lesson(lesson_id)
    invalidate_study_page_cache(unit_id)
    # Fire-and-forget: check if this section is now fully mastered and unlock the next
    asyncio.create_task(check_and_unlock_next_section(user["id"], lesson["section_id"]))
    return UserLessonProgressResponse(**progress)


@router.patch(
    "/users/me/practices/{practice_id}", response_model=UserPracticeProgressResponse
)
async def update_practice_progress_v1(
    practice_id: int,
    payload: UserPracticeProgressUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserPracticeProgressResponse:
    practice = await get_practice(practice_id)
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    await upsert_user_practice_progress(
        user_id=user["id"],
        practice_id=practice_id,
        attempts=payload.attempts,
        best_score=payload.best_score,
        status=payload.status,
    )

    progress = await get_user_practice_progress(user["id"], practice_id)
    assert progress is not None
    logger.info(
        "Practice %d progress updated by user %s: status=%s",
        practice_id,
        user["id"],
        payload.status,
    )
    unit_id = await _resolve_unit_id_from_practice(practice_id)
    invalidate_study_page_cache(unit_id)
    return UserPracticeProgressResponse(**progress)


@router.patch("/users/me/quizzes/{quiz_id}", response_model=UserQuizProgressResponse)
async def update_quiz_progress_v1(
    quiz_id: int,
    payload: UserQuizProgressUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserQuizProgressResponse:
    quiz = await get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    await upsert_user_quiz_progress(
        user_id=user["id"],
        quiz_id=quiz_id,
        score=payload.score,
        completed_at=payload.completed_at,
    )

    progress = await get_user_quiz_progress(user["id"], quiz_id)
    assert progress is not None
    logger.info(
        "Quiz %d progress updated by user %s: score=%s",
        quiz_id,
        user["id"],
        payload.score,
    )
    unit_id = await _resolve_unit_id_from_quiz(quiz_id)
    invalidate_study_page_cache(unit_id)
    return UserQuizProgressResponse(**progress)


# ── Units listing (study page nav) ──────────────────────────────────────────


@router.get("/courses/{course_id}/units", response_model=List[UnitSummary])
async def list_units_v1(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[UnitSummary]:
    units = await list_units(course_id)
    return [
        UnitSummary(
            id=u["id"],
            title=u["title"],
            description=u["description"],
            display_order=u["display_order"],
            # TODO: compute total_sections and estimated_minutes from sections table
            total_sections=0,
            estimated_minutes=0,
        )
        for u in units
    ]


# ── Resume ───────────────────────────────────────────────────────────────────


@router.get("/users/me/courses/{course_id}/resume", response_model=ResumeResponse)
async def get_resume_v1(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> ResumeResponse:
    from database.repositories.learning import get_resume_lesson

    row = await get_resume_lesson(user_id=user["id"], course_id=course_id)
    if row is None:
        return ResumeResponse(lesson_id=None, unit_id=None)
    return ResumeResponse(lesson_id=row["lesson_id"], unit_id=row["unit_id"])


# ── Enrollment ────────────────────────────────────────────────────────────────


@router.post("/courses/{course_id}/enroll", response_model=EnrollResponse)
async def enroll_in_course_v1(
    course_id: int,
    payload: EnrollRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> EnrollResponse:
    """Enroll the authenticated user in a course.

    Idempotent — calling again returns status='already_enrolled' with no duplicate writes.
    Pass source_document_id to generate course content from a study plan (Flow B).
    """
    course = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    return await provision_enrollment(
        user_id=user["id"],
        course_id=course_id,
        source_document_id=payload.source_document_id,
    )


# ── Section unlock (instructor) ───────────────────────────────────────────────


@router.post("/sections/{section_id}/unlock", response_model=SectionUnlockResponse)
async def unlock_section_v1(
    section_id: int,
    payload: SectionUnlockRequest,
    user: Dict[str, Any] = Depends(get_current_user),
) -> SectionUnlockResponse:
    """Manually unlock a section for a specific student.

    Inserts a section_unlock_overrides record and batch-upserts all locked
    items in the section to not_started.  No role guard for now — RBAC to
    be added in a future iteration.
    """
    from database import create_section_unlock_override, unlock_section_items

    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")

    await create_section_unlock_override(
        user_id=payload.user_id,
        section_id=section_id,
        unlocked_by=user["id"],
    )
    count = await unlock_section_items(payload.user_id, section_id)

    logger.info(
        "Section %d manually unlocked for user %d by user %d (%d items)",
        section_id,
        payload.user_id,
        user["id"],
        count,
    )

    # Invalidate cached study page so the next fetch reflects the new unlock
    unit_id = section.get("unit_id")
    if unit_id:
        invalidate_study_page_cache(unit_id)

    return SectionUnlockResponse(
        section_id=section_id,
        user_id=payload.user_id,
        items_unlocked=count,
    )


# ── Notes ─────────────────────────────────────────────────────────────────


@router.post("/notes", response_model=NoteResponse, status_code=201)
async def create_note(
    body: NoteCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> NoteResponse:
    from database.repositories.notes import create_note as _create_note

    note = await _create_note(
        user_id=user["id"],
        content=body.content,
        unit_id=body.unit_id,
        lesson_id=body.lesson_id,
    )
    if isinstance(body.unit_id, int):
        invalidate_study_page_cache(body.unit_id)
    return NoteResponse(**note)


@router.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    body: NoteUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> NoteResponse:
    from database.repositories.notes import update_note as _update_note

    note = await _update_note(note_id=note_id, user_id=user["id"], content=body.content)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found or access denied")
    if isinstance(note.get("unit_id"), int):
        invalidate_study_page_cache(note["unit_id"])
    return NoteResponse(**note)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: UUID,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    from database.repositories.notes import delete_note as _delete_note

    # Fetch before delete to know unit_id for cache invalidation
    from database.repositories.notes import get_note_by_id as _get_note

    note = await _get_note(note_id)
    if note is None or note["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Note not found or access denied")
    await _delete_note(note_id=note_id, user_id=user["id"])
    if isinstance(note.get("unit_id"), int):
        invalidate_study_page_cache(note["unit_id"])


@router.get("/units/{unit_id}/notes", response_model=List[NoteResponse])
async def get_unit_notes(
    unit_id: UUID,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[NoteResponse]:
    from database.repositories.notes import get_notes_for_unit

    notes = await get_notes_for_unit(unit_id=unit_id, user_id=user["id"])
    return [NoteResponse(**n) for n in notes]


@router.get("/lessons/{lesson_id}/notes", response_model=List[NoteResponse])
async def get_lesson_notes(
    lesson_id: UUID,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[NoteResponse]:
    from database.repositories.notes import get_notes_for_lesson

    notes = await get_notes_for_lesson(lesson_id=lesson_id, user_id=user["id"])
    return [NoteResponse(**n) for n in notes]


@router.get("/courses/{course_id}/notes", response_model=List[NoteResponse])
async def get_course_notes(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[NoteResponse]:
    from database.repositories.notes import get_notes_by_course
    from database.repositories.learning import (
        list_units,
        list_sections,
        list_lessons_for_sections,
    )

    # Resolve all unit_ids and lesson_ids for this course
    units = await list_units(course_id)
    unit_ids: List[int] = [u["id"] for u in units]
    section_ids: List[int] = []
    for uid in unit_ids:
        secs = await list_sections(uid)
        section_ids.extend(s["id"] for s in secs)
    all_lessons = await list_lessons_for_sections(section_ids)
    lesson_ids: List[int] = [lesson["id"] for lesson in all_lessons]

    notes = await get_notes_by_course(
        course_id=course_id,
        user_id=user["id"],
        unit_ids=unit_ids,
        lesson_ids=lesson_ids,
    )
    return [NoteResponse(**n) for n in notes]


# ── Flashcards ────────────────────────────────────────────────────────────


@router.post("/flashcards", response_model=FlashcardResponse, status_code=201)
async def create_flashcard(
    body: FlashcardCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> FlashcardResponse:
    from database.repositories.flashcards import create_flashcard as _create_flashcard

    owner_id = user["id"] if body.scope == "user" else None
    card = await _create_flashcard(
        created_by=user["id"],
        front=body.front,
        back=body.back,
        user_id=owner_id,
        course_id=body.course_id,
        unit_id=body.unit_id,
        lesson_id=body.lesson_id,
        is_generated=False,
    )
    if isinstance(body.unit_id, int):
        invalidate_study_page_cache(body.unit_id)
    return FlashcardResponse(**card)


@router.post(
    "/flashcards/generate",
    response_model=Union[List[FlashcardResponse], FlashcardRequestResponse],
    status_code=201,
)
async def generate_flashcards_endpoint(
    body: FlashcardGenerateRequest,
    response: Response,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Union[List[FlashcardResponse], FlashcardRequestResponse]:
    if body.scope == "lesson":
        result = await _generate_lesson_flashcards(
            lesson_id=body.target_id,
            card_scope=body.card_scope,
            user_id=user["id"],
        )
        if isinstance(result, FlashcardRequestResponse):
            response.status_code = 200
        return result

    cards = await generate_flashcards(
        scope=body.scope,
        target_id=body.target_id,
        card_scope=body.card_scope,
        user_id=user["id"],
        force=body.force,
    )
    return [FlashcardResponse(**c) for c in cards]


async def _generate_lesson_flashcards(
    *,
    lesson_id: UUID,
    card_scope: str,
    user_id: int,
) -> Union[List[FlashcardResponse], FlashcardRequestResponse]:
    """Generate flashcards for a lesson via the Curator agent.

    The (long-running) LLM call is guarded by a row in
    ``user_flashcards_request``: if a generation request for the lesson is
    already in flight, the existing request is returned instead of running
    again.  Newly generated cards are appended — existing generated cards for
    the lesson are never deleted and never treated as a conflict.
    """
    from database.repositories.flashcard_requests import (
        complete_flashcards_request as _complete_flashcards_request,
        create_flashcards_request as _create_flashcards_request,
    )
    from database.repositories.flashcards import (
        bulk_create_flashcards as _bulk_create_flashcards,
    )

    request, created = await _create_flashcards_request(
        scope="lesson", target_id=lesson_id, user_id=user_id
    )
    if not created:
        return FlashcardRequestResponse(**request)

    owner_id: Optional[int] = user_id if card_scope == "user" else None
    generator = FlashCardGenerator(lesson_id=lesson_id, curator=CuratorAgent())
    try:
        seeds = await generator.generate()
        records = [
            {
                "created_by": user_id,
                "front": seed["front"],
                "back": seed["back"],
                "user_id": owner_id,
                "course_id": None,
                "unit_id": None,
                "lesson_id": lesson_id,
                "is_generated": True,
            }
            for seed in seeds
        ]
        result = await _bulk_create_flashcards(records)
        await _complete_flashcards_request(request["request_id"], "completed")
        invalidate_study_page_cache(None)
        return [FlashcardResponse(**c) for c in result]
    except Exception:
        logger.exception("Flashcard generation failed for lesson %s", lesson_id)
        await _complete_flashcards_request(request["request_id"], "failed")
        return []


@router.put("/flashcards/{card_id}", response_model=FlashcardResponse)
async def update_flashcard(
    card_id: UUID,
    body: FlashcardUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> FlashcardResponse:
    from database.repositories.flashcards import update_flashcard as _update_flashcard

    card = await _update_flashcard(
        card_id=card_id,
        created_by=user["id"],
        front=body.front,
        back=body.back,
    )
    if card is None:
        raise HTTPException(
            status_code=404, detail="Flashcard not found or access denied"
        )
    if isinstance(card.get("unit_id"), int):
        invalidate_study_page_cache(card["unit_id"])
    return FlashcardResponse(**card)


@router.delete("/flashcards/{card_id}", status_code=204)
async def delete_flashcard(
    card_id: UUID,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    from database.repositories.flashcards import (
        delete_flashcard as _delete_flashcard,
        get_flashcard_by_id,
    )

    card = await get_flashcard_by_id(card_id)
    if card is None or card["created_by"] != user["id"]:
        raise HTTPException(
            status_code=404, detail="Flashcard not found or access denied"
        )
    await _delete_flashcard(card_id=card_id, created_by=user["id"])
    if isinstance(card.get("unit_id"), int):
        invalidate_study_page_cache(card["unit_id"])


@router.get("/units/{unit_id}/flashcards", response_model=List[FlashcardResponse])
async def get_unit_flashcards(
    unit_id: UUID,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[FlashcardResponse]:
    from database.repositories.flashcards import get_flashcards_for_unit

    cards = await get_flashcards_for_unit(unit_id=unit_id, user_id=user["id"])
    return [FlashcardResponse(**c) for c in cards]


@router.get("/lessons/{lesson_id}/flashcards", response_model=List[FlashcardResponse])
async def get_lesson_flashcards(
    lesson_id: UUID,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[FlashcardResponse]:
    from database.repositories.flashcards import get_flashcards_for_lesson

    cards = await get_flashcards_for_lesson(lesson_id=lesson_id, user_id=user["id"])
    return [FlashcardResponse(**c) for c in cards]


@router.get("/courses/{course_id}/flashcards", response_model=List[FlashcardResponse])
async def get_course_flashcards(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[FlashcardResponse]:
    from database.repositories.flashcards import get_flashcards_for_course

    cards = await get_flashcards_for_course(course_id=course_id, user_id=user["id"])
    return [FlashcardResponse(**c) for c in cards]
