import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from database import (
    CourseModel,
    RoleModel,
    UserRoleModel,
    UserModel,
    engine,
    list_courses,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

TESTING_URL: str = os.getenv(
    "TESTING_DATABASE_URL",
    "postgresql+asyncpg://postgres_user:secure_password_here@localhost:5433/learning_platform_testing",
)

from sqlalchemy.ext.asyncio import create_async_engine

testing_engine = create_async_engine(TESTING_URL, echo=False)


async def main() -> None:
    now: str = datetime.now(timezone.utc).isoformat()

    async with AsyncSession(testing_engine) as test_session:
        async with AsyncSession(engine) as prod_session:
            # Copy new users
            existing_users_result = await prod_session.execute(select(UserModel.email))
            existing_users: set[str] = {r[0] for r in existing_users_result.fetchall()}

            users_result = await test_session.execute(select(UserModel))
            users = users_result.fetchall()
            copied_users: int = 0
            for user in users:
                if user.email not in existing_users:
                    new_user = UserModel(
                        google_id=user.google_id,
                        email=user.email,
                        name=user.name,
                        picture_url=user.picture_url,
                        password_hash=user.password_hash,
                        phone=user.phone,
                    )
                    prod_session.add(new_user)
                    await prod_session.flush()

                    # Assign Student role
                    student_role = await prod_session.execute(
                        select(RoleModel).where(RoleModel.name == "Student")
                    )
                    student_row = student_role.fetchone()
                    if student_row:
                        prod_session.add(
                            UserRoleModel(user_id=new_user.id, role_id=student_row.id)
                        )
                    copied_users += 1

            print(f"Copied {copied_users} new user(s)")

            # Copy new courses
            existing_courses_result = await prod_session.execute(
                select(CourseModel.title)
            )
            existing_courses: set[str] = {
                r[0] for r in existing_courses_result.fetchall()
            }

            courses_result = await test_session.execute(select(CourseModel))
            courses = courses_result.fetchall()
            copied_courses: int = 0
            for course in courses:
                if course.title not in existing_courses:
                    new_course = CourseModel(
                        title=course.title,
                        description=course.description,
                        number_of_credits=course.number_of_credits,
                        difficulty=course.difficulty,
                        status=course.status,
                        owner_id=course.owner_id,
                        created_at=now,
                        updated_at=now,
                    )
                    prod_session.add(new_course)
                    copied_courses += 1

            print(f"Copied {copied_courses} new course(s)")

            # Copy user role assignments
            copied_roles: int = 0
            for user in users:
                prod_user_result = await prod_session.execute(
                    select(UserModel).where(UserModel.email == user.email)
                )
                prod_user = prod_user_result.fetchone()
                if not prod_user:
                    continue

                # Get roles from testing
                test_roles_result = await test_session.execute(
                    select(RoleModel.name)
                    .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
                    .where(UserRoleModel.user_id == user.id)
                )
                test_roles = test_roles_result.fetchall()

                for (role_name,) in test_roles:
                    role_result = await prod_session.execute(
                        select(RoleModel).where(RoleModel.name == role_name)
                    )
                    role = role_result.fetchone()
                    if role:
                        existing_role = await prod_session.execute(
                            select(UserRoleModel).where(
                                UserRoleModel.user_id == prod_user.id,
                                UserRoleModel.role_id == role.id,
                            )
                        )
                        if not existing_role.fetchone():
                            prod_session.add(
                                UserRoleModel(user_id=prod_user.id, role_id=role.id)
                            )
                            copied_roles += 1

            print(f"Copied {copied_roles} role assignment(s)")
            await prod_session.commit()

            # Show final state
            print()
            all_courses = await list_courses()
            print(f"Production courses ({len(all_courses)}):")
            for c in all_courses:
                print(f"  {c['id']}: {c['title']}")

            users_result = await prod_session.execute(
                select(UserModel).order_by(UserModel.id)
            )
            prod_users = users_result.fetchall()
            print(f"\nProduction users ({len(prod_users)}):")
            for user in prod_users:
                roles_result = await prod_session.execute(
                    select(RoleModel.name)
                    .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
                    .where(UserRoleModel.user_id == user.id)
                )
                roles = [r[0] for r in roles_result.fetchall()]
                print(f"  {user.email}: {roles}")

    await engine.dispose()
    await testing_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
