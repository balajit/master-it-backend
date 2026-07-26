import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from database import CourseModel, engine, list_courses
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

courses: list[tuple[str, str, int, str, str]] = [
    ("Intro to CS", "Computer Science fundamentals", 3, "beginner", "OPEN"),
    ("Data Structures", "Arrays, trees, graphs", 4, "intermediate", "OPEN"),
    ("Machine Learning", "ML fundamentals with Python", 3, "advanced", "COMING_SOON"),
    ("Web Development", "Full-stack with React & FastAPI", 4, "intermediate", "OPEN"),
    ("Database Design", "SQL and NoSQL patterns", 3, "beginner", "CLOSED"),
    ("Chemistry", "Introduction to Chemistry", 3, "beginner", "OPEN"),
]


async def main() -> None:
    from datetime import datetime, timezone

    now: str = datetime.now(timezone.utc).isoformat()

    async with AsyncSession(engine) as session:
        for title, desc, credits, diff, status in courses:
            result = await session.execute(
                select(CourseModel).where(CourseModel.title == title)
            )
            if result.fetchone():
                print(f"Skipped: {title} already exists")
                continue
            course = CourseModel(
                title=title,
                description=desc,
                number_of_credits=credits,
                difficulty=diff,
                status=status,
                owner_id=1,
                created_at=now,
                updated_at=now,
            )
            session.add(course)
            await session.flush()
            print(f"Created: {title} (id={course.id})")

        await session.commit()

    all_courses = await list_courses()
    print(f"\nTotal courses: {len(all_courses)}")


if __name__ == "__main__":
    asyncio.run(main())
