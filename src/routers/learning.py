"""Learning domain routes — Units, Sections, Lessons, Practices, Quizzes, User Progress."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from database import (
    create_lesson,
    create_practice,
    create_quiz,
    create_section,
    create_unit,
    delete_lesson,
    delete_practice,
    delete_quiz,
    delete_section,
    delete_unit,
    get_course,
    get_lesson,
    get_practice,
    get_quiz,
    get_section,
    get_unit,
    get_user_lesson_progress,
    get_user_practice_progress,
    get_user_quiz_progress,
    list_lessons,
    list_practices,
    list_quizzes,
    list_sections,
    list_units,
    update_lesson,
    update_practice,
    update_quiz,
    update_section,
    update_unit,
    upsert_user_lesson_progress,
    upsert_user_practice_progress,
    upsert_user_quiz_progress,
)
from schemas import (
    LessonCreate,
    LessonCrudResponse,
    LessonUpdate,
    PracticeCreate,
    PracticeCrudResponse,
    PracticeUpdate,
    QuizCreate,
    QuizCrudResponse,
    QuizUpdate,
    SectionCreate,
    SectionCrudResponse,
    SectionDetailResponse,
    SectionUpdate,
    UnitCreate,
    UnitCrudResponse,
    UnitUpdate,
    UserLessonProgressResponse,
    UserLessonProgressUpdate,
    UserPracticeProgressResponse,
    UserPracticeProgressUpdate,
    UserQuizProgressResponse,
    UserQuizProgressUpdate,
)
from services.learning import invalidate_study_page_cache

router: APIRouter = APIRouter(prefix="/api", tags=["learning"])
logger: logging.Logger = logging.getLogger(__name__)


async def _resolve_unit_id_for_item(
    section_id: int | None = None,
    lesson_id: int | None = None,
    practice_id: int | None = None,
    quiz_id: int | None = None,
) -> int | None:
    """Resolve unit_id from a content item, returning None if not found."""
    sid = section_id
    if sid is None and lesson_id is not None:
        lesson = await get_lesson(lesson_id)
        if lesson:
            sid = lesson["section_id"]
    if sid is None and practice_id is not None:
        practice = await get_practice(practice_id)
        if practice:
            sid = practice["section_id"]
    if sid is None and quiz_id is not None:
        quiz = await get_quiz(quiz_id)
        if quiz:
            sid = quiz["section_id"]
    if sid is None:
        return None
    section = await get_section(sid)
    return section["unit_id"] if section else None


# ── Units ───────────────────────────────────────────────────────────────────


@router.post(
    "/courses/{course_id}/units", status_code=201, response_model=UnitCrudResponse
)
async def create_unit_endpoint(
    course_id: int,
    payload: UnitCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UnitCrudResponse:
    course = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    try:
        unit_id = await create_unit(
            course_id=course_id,
            title=payload.title,
            description=payload.description,
            display_order=payload.display_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    unit = await get_unit(unit_id)
    logger.info(
        "Unit %d created in course %d by user %s", unit_id, course_id, user["id"]
    )
    invalidate_study_page_cache(unit_id)
    return UnitCrudResponse(**unit)


@router.get("/courses/{course_id}/units", response_model=List[UnitCrudResponse])
async def list_units_endpoint(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[UnitCrudResponse]:
    course = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    units = await list_units(course_id)
    return [UnitCrudResponse(**u) for u in units]


@router.get("/units/{unit_id}", response_model=UnitCrudResponse)
async def get_unit_endpoint(
    unit_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UnitCrudResponse:
    unit = await get_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return UnitCrudResponse(**unit)


@router.put("/units/{unit_id}", response_model=UnitCrudResponse)
async def update_unit_endpoint(
    unit_id: int,
    payload: UnitUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UnitCrudResponse:
    updated = await update_unit(
        unit_id,
        title=payload.title,
        description=payload.description,
        display_order=payload.display_order,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Unit not found")
    unit = await get_unit(unit_id)
    logger.info("Unit %d updated by user %s", unit_id, user["id"])
    invalidate_study_page_cache(unit_id)
    return UnitCrudResponse(**unit)


@router.delete("/units/{unit_id}", status_code=204)
async def delete_unit_endpoint(
    unit_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    deleted = await delete_unit(unit_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Unit not found")
    logger.info("Unit %d deleted by user %s", unit_id, user["id"])
    invalidate_study_page_cache(unit_id)


# ── Sections ────────────────────────────────────────────────────────────────


@router.post(
    "/units/{unit_id}/sections", status_code=201, response_model=SectionCrudResponse
)
async def create_section_endpoint(
    unit_id: int,
    payload: SectionCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> SectionCrudResponse:
    unit = await get_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    try:
        section_id = await create_section(
            unit_id=unit_id,
            title=payload.title,
            estimated_minutes=payload.estimated_minutes,
            display_order=payload.display_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    section = await get_section(section_id)
    logger.info(
        "Section %d created in unit %d by user %s", section_id, unit_id, user["id"]
    )
    invalidate_study_page_cache(unit_id)
    return SectionCrudResponse(**section)


@router.get("/units/{unit_id}/sections", response_model=List[SectionCrudResponse])
async def list_sections_endpoint(
    unit_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[SectionCrudResponse]:
    unit = await get_unit(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    sections = await list_sections(unit_id)
    return [SectionCrudResponse(**s) for s in sections]


@router.get("/sections/{section_id}", response_model=SectionDetailResponse)
async def get_section_endpoint(
    section_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> SectionDetailResponse:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    lessons = await list_lessons(section_id)
    practices = await list_practices(section_id)
    quizzes = await list_quizzes(section_id)
    return SectionDetailResponse(
        id=section["id"],
        unit_id=section["unit_id"],
        title=section["title"],
        estimated_minutes=section["estimated_minutes"],
        display_order=section["display_order"],
        created_at=section["created_at"],
        updated_at=section["updated_at"],
        lessons=[LessonCrudResponse(**lesson) for lesson in lessons],
        practices=[PracticeCrudResponse(**p) for p in practices],
        quizzes=[QuizCrudResponse(**q) for q in quizzes],
    )


@router.put("/sections/{section_id}", response_model=SectionCrudResponse)
async def update_section_endpoint(
    section_id: int,
    payload: SectionUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> SectionCrudResponse:
    updated = await update_section(
        section_id,
        title=payload.title,
        estimated_minutes=payload.estimated_minutes,
        display_order=payload.display_order,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Section not found")
    section = await get_section(section_id)
    logger.info("Section %d updated by user %s", section_id, user["id"])
    invalidate_study_page_cache(section["unit_id"])
    return SectionCrudResponse(**section)


@router.delete("/sections/{section_id}", status_code=204)
async def delete_section_endpoint(
    section_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    unit_id = section["unit_id"]
    deleted = await delete_section(section_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Section not found")
    logger.info("Section %d deleted by user %s", section_id, user["id"])
    invalidate_study_page_cache(unit_id)


# ── Lessons ─────────────────────────────────────────────────────────────────


@router.post(
    "/sections/{section_id}/lessons", status_code=201, response_model=LessonCrudResponse
)
async def create_lesson_endpoint(
    section_id: int,
    payload: LessonCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> LessonCrudResponse:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        lesson_id = await create_lesson(
            section_id=section_id,
            title=payload.title,
            description=payload.description,
            duration_minutes=payload.duration_minutes,
            display_order=payload.display_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    lesson = await get_lesson(lesson_id)
    logger.info(
        "Lesson %d created in section %d by user %s", lesson_id, section_id, user["id"]
    )
    unit_id = await _resolve_unit_id_for_item(section_id=section_id)
    invalidate_study_page_cache(unit_id)
    return LessonCrudResponse(**lesson)


@router.get("/sections/{section_id}/lessons", response_model=List[LessonCrudResponse])
async def list_lessons_endpoint(
    section_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[LessonCrudResponse]:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    lessons = await list_lessons(section_id)
    return [LessonCrudResponse(**lesson) for lesson in lessons]


@router.get("/lessons/{lesson_id}", response_model=LessonCrudResponse)
async def get_lesson_endpoint(
    lesson_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> LessonCrudResponse:
    lesson = await get_lesson(lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return LessonCrudResponse(**lesson)


@router.put("/lessons/{lesson_id}", response_model=LessonCrudResponse)
async def update_lesson_endpoint(
    lesson_id: int,
    payload: LessonUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> LessonCrudResponse:
    updated = await update_lesson(
        lesson_id,
        title=payload.title,
        description=payload.description,
        duration_minutes=payload.duration_minutes,
        display_order=payload.display_order,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson = await get_lesson(lesson_id)
    logger.info("Lesson %d updated by user %s", lesson_id, user["id"])
    return LessonCrudResponse(**lesson)


@router.delete("/lessons/{lesson_id}", status_code=204)
async def delete_lesson_endpoint(
    lesson_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    unit_id = await _resolve_unit_id_for_item(lesson_id=lesson_id)
    deleted = await delete_lesson(lesson_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lesson not found")
    logger.info("Lesson %d deleted by user %s", lesson_id, user["id"])
    invalidate_study_page_cache(unit_id)


# ── Practices ───────────────────────────────────────────────────────────────


@router.post(
    "/sections/{section_id}/practices",
    status_code=201,
    response_model=PracticeCrudResponse,
)
async def create_practice_endpoint(
    section_id: int,
    payload: PracticeCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> PracticeCrudResponse:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        practice_id = await create_practice(
            section_id=section_id,
            title=payload.title,
            required_correct=payload.required_correct,
            total_questions=payload.total_questions,
            display_order=payload.display_order,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    practice = await get_practice(practice_id)
    logger.info(
        "Practice %d created in section %d by user %s",
        practice_id,
        section_id,
        user["id"],
    )
    unit_id = await _resolve_unit_id_for_item(section_id=section_id)
    invalidate_study_page_cache(unit_id)
    return PracticeCrudResponse(**practice)


@router.get(
    "/sections/{section_id}/practices", response_model=List[PracticeCrudResponse]
)
async def list_practices_endpoint(
    section_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[PracticeCrudResponse]:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    practices = await list_practices(section_id)
    return [PracticeCrudResponse(**p) for p in practices]


@router.get("/practices/{practice_id}", response_model=PracticeCrudResponse)
async def get_practice_endpoint(
    practice_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> PracticeCrudResponse:
    practice = await get_practice(practice_id)
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")
    return PracticeCrudResponse(**practice)


@router.put("/practices/{practice_id}", response_model=PracticeCrudResponse)
async def update_practice_endpoint(
    practice_id: int,
    payload: PracticeUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> PracticeCrudResponse:
    updated = await update_practice(
        practice_id,
        title=payload.title,
        required_correct=payload.required_correct,
        total_questions=payload.total_questions,
        display_order=payload.display_order,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Practice not found")
    practice = await get_practice(practice_id)
    logger.info("Practice %d updated by user %s", practice_id, user["id"])
    return PracticeCrudResponse(**practice)


@router.delete("/practices/{practice_id}", status_code=204)
async def delete_practice_endpoint(
    practice_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    unit_id = await _resolve_unit_id_for_item(practice_id=practice_id)
    deleted = await delete_practice(practice_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Practice not found")
    logger.info("Practice %d deleted by user %s", practice_id, user["id"])
    invalidate_study_page_cache(unit_id)


# ── Quizzes ─────────────────────────────────────────────────────────────────


@router.post(
    "/sections/{section_id}/quizzes", status_code=201, response_model=QuizCrudResponse
)
async def create_quiz_endpoint(
    section_id: int,
    payload: QuizCreate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> QuizCrudResponse:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    try:
        quiz_id = await create_quiz(
            section_id=section_id,
            title=payload.title,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    quiz = await get_quiz(quiz_id)
    logger.info(
        "Quiz %d created in section %d by user %s", quiz_id, section_id, user["id"]
    )
    unit_id = await _resolve_unit_id_for_item(section_id=section_id)
    invalidate_study_page_cache(unit_id)
    return QuizCrudResponse(**quiz)


@router.get("/sections/{section_id}/quizzes", response_model=List[QuizCrudResponse])
async def list_quizzes_endpoint(
    section_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[QuizCrudResponse]:
    section = await get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    quizzes = await list_quizzes(section_id)
    return [QuizCrudResponse(**q) for q in quizzes]


@router.get("/quizzes/{quiz_id}", response_model=QuizCrudResponse)
async def get_quiz_endpoint(
    quiz_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> QuizCrudResponse:
    quiz = await get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return QuizCrudResponse(**quiz)


@router.put("/quizzes/{quiz_id}", response_model=QuizCrudResponse)
async def update_quiz_endpoint(
    quiz_id: int,
    payload: QuizUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> QuizCrudResponse:
    updated = await update_quiz(
        quiz_id,
        title=payload.title,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Quiz not found")
    quiz = await get_quiz(quiz_id)
    logger.info("Quiz %d updated by user %s", quiz_id, user["id"])
    return QuizCrudResponse(**quiz)


@router.delete("/quizzes/{quiz_id}", status_code=204)
async def delete_quiz_endpoint(
    quiz_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    unit_id = await _resolve_unit_id_for_item(quiz_id=quiz_id)
    deleted = await delete_quiz(quiz_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Quiz not found")
    logger.info("Quiz %d deleted by user %s", quiz_id, user["id"])
    invalidate_study_page_cache(unit_id)


# ── User Lesson Progress ────────────────────────────────────────────────────


@router.get(
    "/users/{user_id}/lessons/{lesson_id}/progress",
    response_model=UserLessonProgressResponse,
)
async def get_user_lesson_progress_endpoint(
    user_id: int,
    lesson_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserLessonProgressResponse:
    progress = await get_user_lesson_progress(user_id, lesson_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found")
    return UserLessonProgressResponse(**progress)


@router.put(
    "/users/{user_id}/lessons/{lesson_id}/progress",
    response_model=UserLessonProgressResponse,
)
async def upsert_user_lesson_progress_endpoint(
    user_id: int,
    lesson_id: int,
    payload: UserLessonProgressUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserLessonProgressResponse:
    await upsert_user_lesson_progress(
        user_id=user_id,
        lesson_id=lesson_id,
        status=payload.status,
        completed_at=payload.completed_at,
    )
    progress = await get_user_lesson_progress(user_id, lesson_id)
    assert progress is not None
    unit_id = await _resolve_unit_id_for_item(lesson_id=lesson_id)
    invalidate_study_page_cache(unit_id)
    return UserLessonProgressResponse(**progress)


# ── User Practice Progress ──────────────────────────────────────────────────


@router.get(
    "/users/{user_id}/practices/{practice_id}/progress",
    response_model=UserPracticeProgressResponse,
)
async def get_user_practice_progress_endpoint(
    user_id: int,
    practice_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserPracticeProgressResponse:
    progress = await get_user_practice_progress(user_id, practice_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found")
    return UserPracticeProgressResponse(**progress)


@router.put(
    "/users/{user_id}/practices/{practice_id}/progress",
    response_model=UserPracticeProgressResponse,
)
async def upsert_user_practice_progress_endpoint(
    user_id: int,
    practice_id: int,
    payload: UserPracticeProgressUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserPracticeProgressResponse:
    await upsert_user_practice_progress(
        user_id=user_id,
        practice_id=practice_id,
        attempts=payload.attempts,
        best_score=payload.best_score,
        status=payload.status,
    )
    progress = await get_user_practice_progress(user_id, practice_id)
    assert progress is not None
    unit_id = await _resolve_unit_id_for_item(practice_id=practice_id)
    invalidate_study_page_cache(unit_id)
    return UserPracticeProgressResponse(**progress)


# ── User Quiz Progress ──────────────────────────────────────────────────────


@router.get(
    "/users/{user_id}/quizzes/{quiz_id}/progress",
    response_model=UserQuizProgressResponse,
)
async def get_user_quiz_progress_endpoint(
    user_id: int,
    quiz_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserQuizProgressResponse:
    progress = await get_user_quiz_progress(user_id, quiz_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Progress not found")
    return UserQuizProgressResponse(**progress)


@router.put(
    "/users/{user_id}/quizzes/{quiz_id}/progress",
    response_model=UserQuizProgressResponse,
)
async def upsert_user_quiz_progress_endpoint(
    user_id: int,
    quiz_id: int,
    payload: UserQuizProgressUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
) -> UserQuizProgressResponse:
    await upsert_user_quiz_progress(
        user_id=user_id,
        quiz_id=quiz_id,
        score=payload.score,
        completed_at=payload.completed_at,
    )
    progress = await get_user_quiz_progress(user_id, quiz_id)
    assert progress is not None
    unit_id = await _resolve_unit_id_for_item(quiz_id=quiz_id)
    invalidate_study_page_cache(unit_id)
    return UserQuizProgressResponse(**progress)
