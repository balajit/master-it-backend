"""Course endpoints — CRUD and book-structured study plan."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from database import (
    create_course,
    delete_course,
    get_course,
    get_documents_by_course,
    list_courses,
)
from database.repositories.learning import get_lessons_by_plan_ids, get_sections_by_ids
from schemas import (
    Chapter,
    Course,
    CourseCreate,
    CourseStudyPlanResponse,
    Lesson,
    Page,
)

router: APIRouter = APIRouter(prefix="/api", tags=["courses"])
logger: logging.Logger = logging.getLogger(__name__)


@router.get("/courses", response_model=List[Course])
async def get_courses(
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[Course]:
    rows = await list_courses()
    return [Course(**r) for r in rows]


@router.post("/courses", status_code=201, response_model=Course)
async def add_course(
    course: CourseCreate, user: Dict[str, Any] = Depends(get_current_user)
) -> Course:
    logger.info(
        "Creating course '%s' by user %s (%s)",
        course.title,
        user["id"],
        user["email"],
    )
    course_id: int
    try:
        course_id = await create_course(
            title=course.title,
            description=course.description,
            number_of_credits=course.number_of_credits,
            difficulty=course.difficulty,
            status=course.status,
            owner_id=user["id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    logger.info("Course created with id=%d", course_id)
    return Course(id=course_id, **course.model_dump(), owner_id=user["id"])


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course_endpoint(
    course_id: int, user: Dict[str, Any] = Depends(get_current_user)
) -> None:
    deleted: bool = await delete_course(course_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Course not found")
    logger.info("Course %d deleted by user %s", course_id, user["id"])


@router.get("/courses/{course_id}/study-plan", response_model=CourseStudyPlanResponse)
async def get_course_study_plan(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> CourseStudyPlanResponse:
    """Return the book-structured study plan for a course.

    Reads the CanonicalBook produced by Pipeline 2 (BookPipeline) from the
    learning_platform database.  The response is structured as:
        Course → Chapter → Lesson → Page → ContentItem

    Each Lesson in the response includes:
      - lesson_id: master-it LessonModel.id (int) — use with progress/notes/flashcard APIs
      - unit_id: master-it UnitModel.id (int) — use with unit-scoped notes/flashcard APIs
    """
    course = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    documents = await get_documents_by_course(course_id)

    # Collect chapters from all documents attached to this course.
    # Multiple documents result in their chapters being concatenated.
    all_chapters: list[Chapter] = []
    chapter_order_offset: int = 0

    for doc in documents:
        doc_chapters = await _fetch_book_chapters(doc["id"], chapter_order_offset)
        all_chapters.extend(doc_chapters)
        chapter_order_offset += len(doc_chapters)

    return CourseStudyPlanResponse(
        course_id=course_id,
        course_title=course["title"],
        chapters=all_chapters,
    )


async def _fetch_book_chapters(doc_id_str: str, order_offset: int = 0) -> list[Chapter]:
    """Fetch book chapters from the LP database for a given document ID.

    Also back-populates master-it integer PKs (lesson_id, unit_id) on each
    Lesson by joining BookLesson.unit_id → LessonModel.plan_lesson_id.

    Returns an empty list if no book has been assembled for the document yet.
    """
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from learning_platform.config import Settings
        from learning_platform.infrastructure.persistence.engine import create_engine
        from learning_platform.infrastructure.persistence.repositories.book import (
            BookRepository,
        )
        from learning_platform.infrastructure.persistence.session import (
            create_session_factory,
        )

        settings = Settings()
        engine = create_engine(settings)
        factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)

        doc_uuid = UUID(doc_id_str)

        async with factory() as session:
            repo = BookRepository(session)
            book = await repo.find_by_document(doc_uuid)

        await engine.dispose()

        if book is None:
            return []

        # ── Collect all LP LearningUnit UUIDs from book lessons ──────────
        # BookLesson.unit_id == StudyPlan.Lesson.unit_id == lp_learning_unit.id
        # This is stored as LessonModel.plan_lesson_id during enrollment.
        plan_lesson_ids: list[str] = []
        for bc in book.chapters:
            for bl in bc.lessons:
                if bl.unit_id is not None:
                    plan_lesson_ids.append(str(bl.unit_id))

        # ── Batch-fetch master-it lesson rows by plan_lesson_id ───────────
        lesson_rows = await get_lessons_by_plan_ids(plan_lesson_ids)
        # map: plan_lesson_id → lesson_dict
        plan_to_lesson: dict[str, dict] = {
            r["plan_lesson_id"]: r for r in lesson_rows if r.get("plan_lesson_id")
        }

        # ── Batch-fetch sections to resolve unit_id ───────────────────────
        section_ids_seen: list[int] = list(
            {r["section_id"] for r in lesson_rows if r.get("section_id")}
        )
        section_rows = await get_sections_by_ids(section_ids_seen)
        section_to_unit: dict[int, int] = {s["id"]: s["unit_id"] for s in section_rows}

        # ── Build chapters with integer PKs ──────────────────────────────
        chapters: list[Chapter] = []
        for bc in book.chapters:
            lessons: list[Lesson] = []
            chapter_unit_id: int | None = None

            for bl in bc.lessons:
                pages: list[Page] = []
                for bp in bl.pages:
                    pages.append(
                        Page(
                            id=str(bp.id),
                            page_number=bp.page_number,
                            order=bp.order,
                            items=[_serialize_item(item) for item in bp.items],
                        )
                    )

                # Resolve integer PKs
                lesson_id: int | None = None
                lesson_unit_id: int | None = None
                if bl.unit_id is not None:
                    lesson_row = plan_to_lesson.get(str(bl.unit_id))
                    if lesson_row:
                        lesson_id = lesson_row["id"]
                        lesson_unit_id = section_to_unit.get(lesson_row["section_id"])
                        if chapter_unit_id is None:
                            chapter_unit_id = lesson_unit_id

                lessons.append(
                    Lesson(
                        id=str(bl.id),
                        title=bl.title,
                        order=bl.order,
                        pages=pages,
                        lesson_id=lesson_id,
                        unit_id=lesson_unit_id,
                    )
                )

            chapters.append(
                Chapter(
                    id=str(bc.id),
                    title=bc.title,
                    order=bc.order + order_offset,
                    lessons=lessons,
                    unit_id=chapter_unit_id,
                )
            )
        return chapters

    except Exception:
        logger.debug("No book found for document %s", doc_id_str, exc_info=True)
        return []


def _serialize_item(item: object) -> dict:
    """Convert a ContentItem domain object to a dict for the API response."""
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {}
