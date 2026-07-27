#!/usr/bin/env python3
"""init_env.py — Bootstrap a fresh master-it-backend environment.

Usage:
    uv run scripts/init_env.py [--env (test|prod)] [--superuser EMAIL] [--skip-docker]

Steps performed:
  1. Validate required environment variables / .env file
  2. Start the correct Postgres container via docker-compose (unless --skip-docker)
  3. Wait for Postgres to accept connections (up to 30 s)
  4. Run all Alembic migrations (uv run alembic upgrade head)
  5. Seed roles, permissions, and role-permission assignments
  6. Seed sample courses (dev/test only)
  7. Assign SuperUser role to designated email addresses
  8. Print a summary

Idempotent — safe to run multiple times; nothing is duplicated.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Bootstrap path so src/ imports resolve ──────────────────────────────────
ROOT: Path = Path(__file__).resolve().parent.parent
SRC: Path = ROOT / "src"
sys.path.insert(0, str(SRC))

# Load .env before any database imports
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

# ── Imports that need DATABASE_URL already in env ────────────────────────────
from datetime import datetime, timezone  # noqa: E402

import asyncpg  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from database import engine  # noqa: E402
from database.models import (  # noqa: E402
    CourseModel,
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    UserModel,
    UserRoleModel,
)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the master-it-backend environment."
    )
    parser.add_argument(
        "--env",
        choices=["test", "prod"],
        default="test",
        help="Target environment (default: test — maps to postgres_test container on port 5433)",
    )
    parser.add_argument(
        "--superuser",
        metavar="EMAIL",
        action="append",
        dest="superusers",
        default=[],
        help="Email address to assign the SuperUser role. Can be repeated.",
    )
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip docker-compose up (use when Postgres is already running externally).",
    )
    parser.add_argument(
        "--skip-courses",
        action="store_true",
        help="Skip seeding sample courses.",
    )
    return parser.parse_args()


# ── Docker ───────────────────────────────────────────────────────────────────


def _start_docker(env: str) -> None:
    service = "postgres_test" if env == "test" else "postgres_prod"
    print(f"[docker] Starting service '{service}' …")
    result = subprocess.run(
        ["docker-compose", "up", "-d", service],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[docker] stdout: {result.stdout}")
        print(f"[docker] stderr: {result.stderr}")
        sys.exit(f"[docker] Failed to start {service}. Check docker-compose.yaml.")
    print(f"[docker] {service} started (or already running).")


# ── Postgres readiness probe ──────────────────────────────────────────────────


async def _wait_for_postgres(database_url: str, timeout: int = 30) -> None:
    """Poll until Postgres accepts a connection or timeout expires."""
    # Convert asyncpg-style URL for asyncpg.connect
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            conn = await asyncpg.connect(dsn=url)
            await conn.close()
            print(f"[postgres] Ready after {attempt} attempt(s).")
            return
        except Exception:
            print(f"[postgres] Not ready yet (attempt {attempt}), retrying …")
            await asyncio.sleep(2)
    sys.exit("[postgres] Timed out waiting for Postgres to become available.")


# ── Alembic migration ─────────────────────────────────────────────────────────


def _run_migrations() -> None:
    print("[alembic] Running migrations …")
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr)
        sys.exit("[alembic] Migration failed.")
    print("[alembic] Migrations complete.")


# ── Seed helpers ──────────────────────────────────────────────────────────────


ROLES: tuple[str, ...] = (
    "SuperUser",
    "Administrator",
    "Instructor",
    "Student",
    "Guest",
)

PERMISSIONS: tuple[str, ...] = (
    "*",
    "course:create",
    "course:delete",
    "course:browse",
    "course:register",
    "course:unregister",
    "permission:create",
    "section:unlock",
    "enrollment:manage",
)

# role → list of permission names
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "SuperUser": ["*"],
    "Administrator": [
        "permission:create",
        "course:create",
        "course:delete",
        "enrollment:manage",
        "section:unlock",
    ],
    "Instructor": ["course:create", "course:browse", "section:unlock"],
    "Student": ["course:browse", "course:register", "course:unregister"],
    "Guest": ["course:browse"],
}

SAMPLE_COURSES: list[tuple[str, str, int, str, str]] = [
    (
        "Intro to Computer Science",
        "Computer Science fundamentals",
        3,
        "beginner",
        "OPEN",
    ),
    (
        "Data Structures & Algorithms",
        "Arrays, trees, graphs, complexity",
        4,
        "intermediate",
        "OPEN",
    ),
    (
        "Machine Learning Fundamentals",
        "ML fundamentals with Python",
        3,
        "advanced",
        "COMING_SOON",
    ),
    (
        "Full-Stack Web Development",
        "React & FastAPI end-to-end",
        4,
        "intermediate",
        "OPEN",
    ),
    ("Database Design", "SQL and NoSQL patterns", 3, "beginner", "OPEN"),
    ("Introduction to Chemistry", "Atoms, molecules, reactions", 3, "beginner", "OPEN"),
]


async def _seed_roles(session: AsyncSession) -> dict[str, int]:
    """Ensure all roles exist. Returns {name: id}."""
    role_ids: dict[str, int] = {}
    for name in ROLES:
        row = (
            (await session.execute(select(RoleModel).where(RoleModel.name == name)))
            .scalars()
            .first()
        )
        if not row:
            row = RoleModel(name=name)
            session.add(row)
            await session.flush()
            print(f"  [+] Role: {name}")
        else:
            print(f"  [=] Role already exists: {name}")
        role_ids[name] = row.id
    return role_ids


async def _seed_permissions(session: AsyncSession) -> dict[str, int]:
    """Ensure all permissions exist. Returns {name: id}."""
    perm_ids: dict[str, int] = {}
    for name in PERMISSIONS:
        row = (
            (
                await session.execute(
                    select(PermissionModel).where(PermissionModel.name == name)
                )
            )
            .scalars()
            .first()
        )
        if not row:
            row = PermissionModel(name=name)
            session.add(row)
            await session.flush()
            print(f"  [+] Permission: {name}")
        else:
            print(f"  [=] Permission already exists: {name}")
        perm_ids[name] = row.id
    return perm_ids


async def _seed_role_permissions(
    session: AsyncSession,
    role_ids: dict[str, int],
    perm_ids: dict[str, int],
) -> None:
    """Assign permissions to roles."""
    for role_name, perm_names in ROLE_PERMISSIONS.items():
        role_id = role_ids.get(role_name)
        if role_id is None:
            continue
        for perm_name in perm_names:
            perm_id = perm_ids.get(perm_name)
            if perm_id is None:
                continue
            existing = (
                (
                    await session.execute(
                        select(RolePermissionModel).where(
                            RolePermissionModel.role_id == role_id,
                            RolePermissionModel.permission_id == perm_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if not existing:
                session.add(RolePermissionModel(role_id=role_id, permission_id=perm_id))
                print(f"  [+] {role_name} → {perm_name}")
    await session.flush()


async def _seed_courses(session: AsyncSession, owner_id: int = 1) -> int:
    """Seed sample courses. Returns count of newly created courses."""
    now: str = datetime.now(timezone.utc).isoformat()
    created = 0
    for title, desc, credits, diff, status in SAMPLE_COURSES:
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
            print(f"  [=] Course already exists: {title}")
            continue
        course = CourseModel(
            title=title,
            description=desc,
            number_of_credits=credits,
            difficulty=diff,
            status=status,
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
        )
        session.add(course)
        await session.flush()
        print(f"  [+] Course: {title} (id={course.id})")
        created += 1
    return created


async def _assign_superusers(
    session: AsyncSession,
    emails: list[str],
    role_ids: dict[str, int],
) -> None:
    """Assign the SuperUser role to given email addresses (users must exist)."""
    superuser_role_id = role_ids.get("SuperUser")
    if superuser_role_id is None:
        print("  [!] SuperUser role not found, skipping user assignments.")
        return

    for email in emails:
        user = (
            (await session.execute(select(UserModel).where(UserModel.email == email)))
            .scalars()
            .first()
        )
        if not user:
            print(
                f"  [!] User {email} not found — register first, then re-run to assign SuperUser."
            )
            continue
        existing = (
            (
                await session.execute(
                    select(UserRoleModel).where(
                        UserRoleModel.user_id == user.id,
                        UserRoleModel.role_id == superuser_role_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not existing:
            session.add(UserRoleModel(user_id=user.id, role_id=superuser_role_id))
            print(f"  [+] SuperUser assigned to {email}")
        else:
            print(f"  [=] {email} already has SuperUser role")
    await session.flush()


# ── Main ─────────────────────────────────────────────────────────────────────


async def main(args: argparse.Namespace) -> None:
    database_url: str = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres_user:secure_password_here@localhost:5433/learning_platform_testing",
    )

    print("=" * 60)
    print("  master-it-backend — Environment Initialization")
    print("=" * 60)
    print(f"  Target env  : {args.env}")
    print(f"  Database    : {database_url.split('@')[-1]}")  # hide credentials
    print(f"  Superusers  : {args.superusers or '(none specified)'}")
    print()

    # Step 1 — Docker
    if not args.skip_docker:
        _start_docker(args.env)
    else:
        print("[docker] Skipped (--skip-docker).")

    # Step 2 — Wait for Postgres
    print("[postgres] Waiting for database to accept connections …")
    await _wait_for_postgres(database_url)

    # Step 3 — Alembic migrations
    _run_migrations()

    # Step 4 — Seed
    print("\n[seed] Seeding roles and permissions …")
    async with AsyncSession(engine) as session:
        try:
            role_ids = await _seed_roles(session)
            perm_ids = await _seed_permissions(session)
            await _seed_role_permissions(session, role_ids, perm_ids)

            if not args.skip_courses:
                print("\n[seed] Seeding sample courses …")
                # owner_id=1 is the first user; safe for seed data
                await _seed_courses(session, owner_id=1)

            if args.superusers:
                print("\n[seed] Assigning SuperUser role …")
                await _assign_superusers(session, args.superusers, role_ids)

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    print("\n" + "=" * 60)
    print("  Initialization complete.")
    print()
    print("  Next steps:")
    print("    1. Register your first user via POST /api/auth/register")
    print("    2. Re-run with --superuser <EMAIL> to elevate that user")
    print("    3. Start the server:  uv run fastapi dev src/main.py --port 5000")
    print("=" * 60)


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        sys.exit("\nAborted.")
