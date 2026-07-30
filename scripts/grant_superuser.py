#!/usr/bin/env python3
"""Grant SuperUser role to a user in testing or production DB.

This script is idempotent:
- creates the ``SuperUser`` role if missing
- creates the wildcard permission ``*`` if missing
- links ``SuperUser`` -> ``*`` if missing
- links user -> ``SuperUser`` if missing

Usage:
    uv run python scripts/grant_superuser.py --env testing
    uv run python scripts/grant_superuser.py --env production
    uv run python scripts/grant_superuser.py --env testing --email user@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT: Path = Path(__file__).resolve().parent.parent
SRC: Path = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from database.models import (  # noqa: E402
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    UserModel,
    UserRoleModel,
)

DEFAULT_EMAIL: str = "thummala.gc1978@gmail.com"
SUPERUSER_ROLE: str = "SuperUser"
WILDCARD_PERMISSION: str = "*"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grant SuperUser role to a user")
    parser.add_argument(
        "--env",
        choices=["testing", "production"],
        required=True,
        help="Target database environment",
    )
    parser.add_argument(
        "--email",
        default=DEFAULT_EMAIL,
        help=f"User email to grant SuperUser (default: {DEFAULT_EMAIL})",
    )
    return parser.parse_args()


def _load_database_url(env_name: str) -> str:
    env_file: Path = ROOT / f".env.{env_name}"
    if not env_file.exists():
        raise FileNotFoundError(f"Missing env file: {env_file}")

    env_values: dict[str, str | None] = dotenv_values(env_file)
    raw_url: str | None = env_values.get("DATABASE_URL")
    database_url: str = str(raw_url).strip() if raw_url is not None else ""
    if not database_url:
        raise ValueError(f"DATABASE_URL is missing in {env_file.name}")
    return database_url


async def _grant_superuser(database_url: str, target_email: str, env_name: str) -> None:
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    role_created: bool = False
    permission_created: bool = False
    role_permission_link_created: bool = False
    user_role_link_created: bool = False

    try:
        async with session_factory() as session:
            user: UserModel | None = (
                (
                    await session.execute(
                        select(UserModel).where(UserModel.email == target_email)
                    )
                )
                .scalars()
                .first()
            )
            if user is None:
                raise ValueError(
                    f"User '{target_email}' does not exist in {env_name} DB. "
                    "Create the user first, then run this script again."
                )

            role: RoleModel | None = (
                (
                    await session.execute(
                        select(RoleModel).where(RoleModel.name == SUPERUSER_ROLE)
                    )
                )
                .scalars()
                .first()
            )
            if role is None:
                role = RoleModel(name=SUPERUSER_ROLE)
                session.add(role)
                await session.flush()
                role_created = True

            permission: PermissionModel | None = (
                (
                    await session.execute(
                        select(PermissionModel).where(
                            PermissionModel.name == WILDCARD_PERMISSION
                        )
                    )
                )
                .scalars()
                .first()
            )
            if permission is None:
                permission = PermissionModel(name=WILDCARD_PERMISSION)
                session.add(permission)
                await session.flush()
                permission_created = True

            role_permission: RolePermissionModel | None = (
                (
                    await session.execute(
                        select(RolePermissionModel).where(
                            RolePermissionModel.role_id == role.id,
                            RolePermissionModel.permission_id == permission.id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if role_permission is None:
                session.add(
                    RolePermissionModel(
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )
                role_permission_link_created = True

            user_role: UserRoleModel | None = (
                (
                    await session.execute(
                        select(UserRoleModel).where(
                            UserRoleModel.user_id == user.id,
                            UserRoleModel.role_id == role.id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if user_role is None:
                session.add(UserRoleModel(user_id=user.id, role_id=role.id))
                user_role_link_created = True

            await session.commit()

        print(f"[ok] SuperUser grant complete ({env_name} DB)")
        print(f"     user: {target_email}")
        print(f"     role created: {role_created}")
        print(f"     wildcard permission created: {permission_created}")
        print(f"     role->permission linked: {role_permission_link_created}")
        print(f"     user->role linked: {user_role_link_created}")
    finally:
        await engine.dispose()


async def main() -> None:
    args = _parse_args()
    env_name: str = args.env
    target_email: str = str(args.email).strip()
    if not target_email:
        raise ValueError("--email cannot be empty")

    database_url: str = _load_database_url(env_name)
    print(f"[info] Using DATABASE_URL from .env.{env_name}")
    await _grant_superuser(database_url, target_email, env_name)


if __name__ == "__main__":
    asyncio.run(main())
