import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from database import (
    CourseModel,
    RoleModel,
    UserModel,
    UserRoleModel,
    engine,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SQLITE_BACKUP: str = os.getenv(
    "SQLITE_BACKUP", "backups/master_it_production_20260719_151853.db"
)

SUPERUSER_EMAIL: str = "thummala.gc1978@gmail.com"
SUPERUSER_NAME: str = "Balaji Thummala"


async def ensure_superuser(pg_session: AsyncSession) -> dict[str, int]:
    email_map: dict[str, int] = {}
    result = await pg_session.execute(
        select(UserModel).where(UserModel.email == SUPERUSER_EMAIL)
    )
    user = result.scalars().first()
    if user:
        email_map[SUPERUSER_EMAIL] = user.id
        print(f"  SuperUser {SUPERUSER_EMAIL} already exists (id={user.id})")
    else:
        su = UserModel(email=SUPERUSER_EMAIL, name=SUPERUSER_NAME, picture_url="")
        pg_session.add(su)
        await pg_session.flush()
        email_map[SUPERUSER_EMAIL] = su.id

        sr = (
            (
                await pg_session.execute(
                    select(RoleModel).where(RoleModel.name == "Student")
                )
            )
            .scalars()
            .first()
        )
        if sr:
            pg_session.add(UserRoleModel(user_id=su.id, role_id=sr.id))

        sur = (
            (
                await pg_session.execute(
                    select(RoleModel).where(RoleModel.name == "SuperUser")
                )
            )
            .scalars()
            .first()
        )
        if sur:
            pg_session.add(UserRoleModel(user_id=su.id, role_id=sur.id))

        print(f"  Created SuperUser {SUPERUSER_EMAIL} (id={su.id})")

    return email_map


async def migrate_user(
    sqlite_conn: sqlite3.Connection, pg_session: AsyncSession, email_map: dict[str, int]
) -> int:
    users = sqlite_conn.execute("SELECT * FROM users").fetchall()
    columns = [
        desc[0] for desc in sqlite_conn.execute("SELECT * FROM users").description
    ]
    count = 0
    for row in users:
        data = dict(zip(columns, row))
        if data["email"] in email_map:
            continue
        existing = await pg_session.execute(
            select(UserModel).where(UserModel.email == data["email"])
        )
        if existing.fetchone():
            continue
        user = UserModel(
            google_id=data.get("google_id"),
            email=data["email"],
            name=data.get("name", ""),
            picture_url=data.get("picture_url", ""),
            password_hash=data.get("password_hash"),
            phone=data.get("phone"),
        )
        pg_session.add(user)
        await pg_session.flush()
        email_map[data["email"]] = user.id
        count += 1
    return count


async def migrate_courses(
    sqlite_conn: sqlite3.Connection, pg_session: AsyncSession, email_map: dict[str, int]
) -> int:
    courses = sqlite_conn.execute("SELECT * FROM courses").fetchall()
    columns = [
        desc[0] for desc in sqlite_conn.execute("SELECT * FROM courses").description
    ]
    default_owner_id: int = list(email_map.values())[0] if email_map else 1
    count = 0
    for row in courses:
        data = dict(zip(columns, row))
        existing = await pg_session.execute(
            select(CourseModel).where(CourseModel.title == data["title"])
        )
        if existing.fetchone():
            continue
        course = CourseModel(
            title=data["title"],
            description=data.get("description", ""),
            number_of_credits=data.get("number_of_credits", 0),
            difficulty=data.get("difficulty", "beginner"),
            status=data.get("status", "COMING_SOON"),
            owner_id=default_owner_id,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )
        pg_session.add(course)
        await pg_session.flush()
        count += 1
    return count


async def migrate_user_roles(
    sqlite_conn: sqlite3.Connection, pg_session: AsyncSession, email_map: dict[str, int]
) -> int:
    user_roles = sqlite_conn.execute("SELECT * FROM user_roles").fetchall()
    count = 0
    for user_id, role_id in user_roles:
        user_result = sqlite_conn.execute(
            "SELECT email FROM users WHERE id = ?", (user_id,)
        )
        user_row = user_result.fetchone()
        if not user_row:
            continue
        email = user_row[0]
        pg_user_id = email_map.get(email)
        if not pg_user_id:
            continue

        role_result = sqlite_conn.execute(
            "SELECT name FROM roles WHERE id = ?", (role_id,)
        )
        role_row = role_result.fetchone()
        if not role_row:
            continue
        role_name = role_row[0]

        pg_role = (
            (
                await pg_session.execute(
                    select(RoleModel).where(RoleModel.name == role_name)
                )
            )
            .scalars()
            .first()
        )
        if not pg_role:
            continue

        existing = await pg_session.execute(
            select(UserRoleModel).where(
                UserRoleModel.user_id == pg_user_id,
                UserRoleModel.role_id == pg_role.id,
            )
        )
        if not existing.fetchone():
            pg_session.add(UserRoleModel(user_id=pg_user_id, role_id=pg_role.id))
            count += 1
    return count


async def main() -> None:
    if not Path(SQLITE_BACKUP).exists():
        print(f"Error: SQLite backup not found at {SQLITE_BACKUP}")
        sys.exit(1)

    print(f"Reading from: {SQLITE_BACKUP}")
    sqlite_conn = sqlite3.connect(SQLITE_BACKUP)
    sqlite_conn.row_factory = sqlite3.Row

    async with AsyncSession(engine) as pg_session:
        try:
            print("\n=== Ensuring SuperUser ===")
            email_map: dict[str, int] = await ensure_superuser(pg_session)

            print("\n=== Migrating Users from SQLite ===")
            user_count = await migrate_user(sqlite_conn, pg_session, email_map)
            print(f"  Migrated {user_count} additional user(s)")

            print("\n=== Migrating Courses ===")
            course_count = await migrate_courses(sqlite_conn, pg_session, email_map)
            print(f"  Migrated {course_count} course(s)")

            print("\n=== Migrating User Roles ===")
            role_count = await migrate_user_roles(sqlite_conn, pg_session, email_map)
            print(f"  Migrated {role_count} role assignment(s)")

            await pg_session.commit()
            print("\n=== Migration Complete ===")

            courses = (
                (await pg_session.execute(select(CourseModel).order_by(CourseModel.id)))
                .scalars()
                .all()
            )
            print(f"\nPostgreSQL courses ({len(courses)}):")
            for c in courses:
                print(f"  {c.id}: {c.title}")

            users = (
                (await pg_session.execute(select(UserModel).order_by(UserModel.id)))
                .scalars()
                .all()
            )
            print(f"\nPostgreSQL users ({len(users)}):")
            for u in users:
                roles_result = await pg_session.execute(
                    select(RoleModel.name)
                    .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
                    .where(UserRoleModel.user_id == u.id)
                )
                roles = [r[0] for r in roles_result.fetchall()]
                print(f"  {u.email}: {roles}")

        except Exception as e:
            await pg_session.rollback()
            print(f"Error: {e}")
            raise

    sqlite_conn.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
