"""Course endpoints — CRUD and book-structured study plan."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from auth import get_current_user
from database import (
    create_course,
    delete_course,
    get_course,
    get_documents_by_course,
    list_courses,
)
from database.repositories.learning import (
    get_lessons_by_titles_for_course,
    get_lessons_by_plan_ids_for_course,
    get_sections_by_ids,
)
from schemas import (
    Chapter,
    Course,
    CourseCreate,
    CourseStudyPlanDocument,
    CourseStudyPlanResponse,
    Lesson,
    Page,
)
from services.lp_results import lp_doc_uuid_from_storage_path

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

    # New shape: keep per-document plans and maintain a deprecated
    # flattened chapters list for backward compatibility.
    documents_payload: list[CourseStudyPlanDocument] = []
    all_chapters: list[Chapter] = []
    chapter_order_offset: int = 0

    skipped_documents: list[str] = []

    for doc in documents:
        document_id = str(doc.get("id") or "")
        document_name = str(doc.get("filename") or "")
        storage_path = str(doc.get("storage_path") or "").strip()
        if not storage_path:
            skipped_documents.append(document_id)
            documents_payload.append(
                CourseStudyPlanDocument(
                    document_id=document_id,
                    document_name=document_name,
                    chapters=[],
                )
            )
            continue

        lp_doc_uuid = lp_doc_uuid_from_storage_path(storage_path)
        doc_chapters = await _fetch_book_chapters(str(lp_doc_uuid), course_id, 0)

        documents_payload.append(
            CourseStudyPlanDocument(
                document_id=document_id,
                document_name=document_name,
                chapters=doc_chapters,
            )
        )

        if not doc_chapters:
            skipped_documents.append(document_id)
            continue

        all_chapters.extend(
            [
                chapter.model_copy(
                    update={"order": chapter.order + chapter_order_offset}
                )
                for chapter in doc_chapters
            ]
        )
        chapter_order_offset += len(doc_chapters)

    if skipped_documents:
        logger.info(
            "Study plan for course %d skipped %d document(s) without book output: %s",
            course_id,
            len(skipped_documents),
            ", ".join(skipped_documents),
        )

    return CourseStudyPlanResponse(
        course_id=course_id,
        course_title=course["title"],
        documents=documents_payload,
        chapters=all_chapters,
    )


async def _fetch_book_chapters(
    doc_id_str: str,
    course_id: int,
    order_offset: int = 0,
) -> list[Chapter]:
    """Fetch book chapters from the LP database for a given document ID.

    Also back-populates master-it integer PKs (lesson_id, unit_id) on each
    Lesson by joining BookLesson.unit_id → LessonModel.plan_lesson_id.

    Returns an empty list if no book has been assembled for the document yet.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from learning_platform.config import Settings
    from learning_platform.infrastructure.persistence.engine import create_engine
    from learning_platform.infrastructure.persistence.repositories.book import (
        BookRepository,
    )
    from learning_platform.infrastructure.persistence.repositories.learning_unit import (
        LearningUnitRepository,
    )
    from learning_platform.infrastructure.persistence.session import (
        create_session_factory,
    )

    settings = Settings()
    engine = create_engine(settings)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)

    try:
        doc_uuid = UUID(doc_id_str)

        async with factory() as session:
            repo = BookRepository(session)
            book = await repo.find_by_document(doc_uuid)
            unit_repo = LearningUnitRepository(session)
            learning_units = await unit_repo.find_by_document(doc_uuid)

        if book is None:
            return []

        unit_title_by_id: dict[UUID, str] = {
            unit.id: unit.title.strip()
            for unit in learning_units
            if unit.title and unit.title.strip()
        }

        plan_lesson_ids: list[str] = []
        lesson_titles: set[str] = set()
        for bc in book.chapters:
            for bl in bc.lessons:
                if bl.unit_id is not None:
                    plan_lesson_ids.append(str(bl.unit_id))
                    unit_title = unit_title_by_id.get(bl.unit_id, "").strip()
                    if unit_title:
                        lesson_titles.add(unit_title)
                lesson_title = bl.title.strip()
                if lesson_title:
                    lesson_titles.add(lesson_title)

        lesson_rows_by_plan_id = await get_lessons_by_plan_ids_for_course(
            course_id, plan_lesson_ids
        )
        lesson_rows_by_title = await get_lessons_by_titles_for_course(
            course_id,
            list(lesson_titles),
        )
        plan_to_lesson: dict[str, dict[str, Any]] = {
            str(row["plan_lesson_id"]): row
            for row in lesson_rows_by_plan_id
            if row.get("plan_lesson_id")
        }

        title_to_lessons: dict[str, list[dict[str, Any]]] = {}
        for row in lesson_rows_by_title:
            raw_title = row.get("title")
            if raw_title is None:
                continue
            title = str(raw_title).strip()
            if not title:
                continue
            title_to_lessons.setdefault(title.lower(), []).append(row)

        for rows in title_to_lessons.values():
            rows.sort(
                key=lambda value: (value.get("display_order", 0), value.get("id", 0))
            )

        section_ids_seen: list[int] = list(
            {
                int(row["section_id"])
                for row in [*lesson_rows_by_plan_id, *lesson_rows_by_title]
                if isinstance(row.get("section_id"), int)
            }
        )

        section_rows = await get_sections_by_ids(section_ids_seen)
        section_to_unit: dict[int, int] = {s["id"]: s["unit_id"] for s in section_rows}
        assigned_lesson_ids: set[int] = set()

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
                            metadata=bp.metadata or {},
                        )
                    )

                lesson_id: int | None = None
                lesson_unit_id: int | None = None
                if bl.unit_id is not None:
                    lesson_row = plan_to_lesson.get(str(bl.unit_id))
                else:
                    lesson_row = None

                if lesson_row is None:
                    fallback_titles: list[str] = []
                    lesson_title = bl.title.strip()
                    if lesson_title:
                        fallback_titles.append(lesson_title)
                    if bl.unit_id is not None:
                        unit_title = unit_title_by_id.get(bl.unit_id, "").strip()
                        if unit_title and unit_title not in fallback_titles:
                            fallback_titles.append(unit_title)

                    for fallback_title in fallback_titles:
                        candidates = title_to_lessons.get(fallback_title.lower(), [])
                        available = [
                            row
                            for row in candidates
                            if isinstance(row.get("id"), int)
                            and row["id"] not in assigned_lesson_ids
                        ]
                        if available:
                            lesson_row = available[0]
                            break

                if lesson_row and isinstance(lesson_row.get("id"), int):
                    raw_lesson_id = lesson_row.get("id")
                    raw_section_id = lesson_row.get("section_id")
                    if isinstance(raw_lesson_id, int):
                        lesson_id = raw_lesson_id
                        assigned_lesson_ids.add(lesson_id)
                    if isinstance(raw_section_id, int):
                        lesson_unit_id = section_to_unit.get(raw_section_id)
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
    except ValidationError as exc:
        logger.exception("Invalid book payload for document %s", doc_id_str)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to serialize study plan for document {doc_id_str}",
        ) from exc
    except ValueError as exc:
        logger.exception("Invalid document UUID for study plan lookup: %s", doc_id_str)
        raise HTTPException(
            status_code=500,
            detail=f"Invalid LP document ID for study plan lookup: {doc_id_str}",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed loading study plan book for document %s", doc_id_str)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load study plan for document {doc_id_str}",
        ) from exc
    finally:
        await engine.dispose()


def _serialize_item(item: object) -> dict:
    """Convert a ContentItem domain object to a dict for the API response."""
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        raw_payload = model_dump(mode="json")
        if not isinstance(raw_payload, Mapping):
            return {}
        payload = dict(raw_payload)
        item_id = payload.get("id")
        if item_id is not None:
            payload["id"] = str(item_id)
        return payload
    if isinstance(item, dict):
        payload = dict(item)
        item_id = payload.get("id")
        if item_id is not None:
            payload["id"] = str(item_id)
        return payload
    return {}
