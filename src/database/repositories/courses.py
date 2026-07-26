from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models import CourseModel


async def create_course(
    title: str,
    description: str,
    number_of_credits: int,
    difficulty: str,
    status: str = "COMING_SOON",
    owner_id: int = 0,
) -> int:
    from datetime import datetime, timezone

    now: str = datetime.now(timezone.utc).isoformat()
    async with AsyncSession(engine) as session:
        existing = (
            (
                await session.execute(
                    select(CourseModel).where(CourseModel.title == title)
                )
            )
            .scalars()
            .first()
        )
        if existing:
            raise ValueError(f"Course '{title}' already exists")
        course = CourseModel(
            title=title,
            description=description,
            number_of_credits=number_of_credits,
            difficulty=difficulty,
            status=status,
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
        )
        session.add(course)
        await session.commit()
        await session.refresh(course)
        return course.id


async def get_course(course_id: int) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        course: Optional[CourseModel] = (
            (
                await session.execute(
                    select(CourseModel).where(CourseModel.id == course_id)
                )
            )
            .scalars()
            .first()
        )
        if not course:
            return None
        return {
            "id": course.id,
            "title": course.title,
            "description": course.description,
            "number_of_credits": course.number_of_credits,
            "difficulty": course.difficulty,
            "status": course.status,
            "owner_id": course.owner_id,
            "created_at": course.created_at,
            "updated_at": course.updated_at,
        }


async def list_courses() -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        courses: List[CourseModel] = (
            (
                await session.execute(
                    select(CourseModel).order_by(CourseModel.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "number_of_credits": c.number_of_credits,
                "difficulty": c.difficulty,
                "status": c.status,
                "owner_id": c.owner_id,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            }
            for c in courses
        ]


async def delete_course(course_id: int) -> bool:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            delete(CourseModel).where(CourseModel.id == course_id)
        )
        await session.commit()
        return result.rowcount > 0
