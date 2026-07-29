"""Courses routes — list available courses."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.api.auth import get_current_user
from learning_platform.api.deps import get_session

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Response schemas ─────────────────────────────────────────────────────────


class CourseResponse(BaseModel):
    """Summary of a single course."""

    id: UUID
    title: str
    description: str


class CoursesListResponse(BaseModel):
    """List of courses."""

    courses: list[CourseResponse]
    count: int


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=CoursesListResponse,
    summary="List all courses",
    description="Return all available courses.",
)
async def list_courses(
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> CoursesListResponse:
    """Return all courses from the database."""
    _ = user
    try:
        result = await session.execute(text("SELECT id, title, description FROM lp_courses"))
        rows = result.mappings().all()
        courses = [
            CourseResponse(
                id=row["id"],
                title=row["title"],
                description=row["description"],
            )
            for row in rows
        ]
    except Exception as exc:
        logger.exception("Failed to fetch courses")
        raise HTTPException(status_code=500, detail="Failed to fetch courses") from exc

    return CoursesListResponse(courses=courses, count=len(courses))
