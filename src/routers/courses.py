import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from database import (
    create_course,
    delete_course,
    get_course,
    get_documents_by_course,
    list_courses,
)
from schemas import (
    Course,
    CourseCreate,
    CourseStudyPlanResponse,
    StudyPlanCheckpoint,
    StudyPlanDetail,
    StudyPlanLesson,
    StudyPlanMilestone,
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
    """Return study plans for all documents attached to a course."""
    course = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    documents = await get_documents_by_course(course_id)

    study_plans: List[StudyPlanDetail] = []
    for doc in documents:
        plan = await _fetch_study_plan(doc["id"])
        if plan is not None:
            study_plans.append(plan)

    return CourseStudyPlanResponse(
        course_id=course_id,
        course_title=course["title"],
        documents_processed=len(study_plans),
        study_plans=study_plans,
    )


async def _fetch_study_plan(doc_id_str: str) -> StudyPlanDetail | None:
    """Fetch a study plan from the learning_platform database for a given document ID."""
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
        engine = create_engine(settings)
        factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)

        doc_uuid = UUID(doc_id_str)
        async with factory() as session:
            repo = StudyPlanRepository(session)
            plan = await repo.find_by_document(doc_uuid)

        await engine.dispose()

        if plan is None:
            return None

        return StudyPlanDetail(
            doc_id=doc_id_str,
            title=plan.title,
            description=plan.description,
            total_estimated_minutes=plan.total_estimated_minutes,
            total_lessons=plan.total_lessons,
            lessons=[
                StudyPlanLesson(
                    id=str(lesson.id),
                    unit_id=str(lesson.unit_id),
                    order=lesson.order,
                    title=lesson.title,
                    description=lesson.description,
                    lesson_type=lesson.lesson_type.value,
                    difficulty=lesson.difficulty,
                    estimated_minutes=lesson.estimated_minutes,
                    milestone_id=str(lesson.milestone_id)
                    if lesson.milestone_id
                    else None,
                )
                for lesson in plan.lessons
            ],
            milestones=[
                StudyPlanMilestone(
                    id=str(m.id),
                    order=m.order,
                    title=m.title,
                    description=m.description,
                    estimated_minutes=m.estimated_minutes,
                    lesson_count=len(m.lesson_ids),
                )
                for m in plan.milestones
            ],
            checkpoints=[
                StudyPlanCheckpoint(
                    id=str(cp.id),
                    milestone_id=str(cp.milestone_id),
                    order=cp.order,
                    title=cp.title,
                    checkpoint_type=cp.checkpoint_type.value,
                    estimated_minutes=cp.estimated_minutes,
                )
                for cp in plan.checkpoints
            ],
        )
    except Exception:
        logger.debug("No study plan found for document %s", doc_id_str)
        return None
