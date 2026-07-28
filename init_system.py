import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

parser = argparse.ArgumentParser(
    description="System init: roles, permissions, superusers."
)
parser.add_argument(
    "--env",
    choices=["test", "prod"],
    default="test",
    help="Target environment (default: test — loads .env; prod — loads .env.production)",
)
args = parser.parse_args()

env_file = ".env.production" if args.env == "prod" else ".env"
load_dotenv(Path(__file__).parent / env_file)

from database import (
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    UserModel,
    UserRoleModel,
    engine,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SUPERUSERS: list[str] = ["thummala.gc1978@gmail.com"]


async def init_roles(session: AsyncSession) -> None:
    roles: tuple[str, ...] = (
        "Administrator",
        "Instructor",
        "Student",
        "Guest",
        "SuperUser",
    )
    for role_name in roles:
        existing = (
            (
                await session.execute(
                    select(RoleModel).where(RoleModel.name == role_name)
                )
            )
            .scalars()
            .first()
        )
        if not existing:
            session.add(RoleModel(name=role_name))
    await session.flush()
    print(f"Roles ensured: {', '.join(roles)}")


async def init_permissions(session: AsyncSession) -> None:
    permissions: tuple[str, ...] = (
        "course:create",
        "course:delete",
        "course:browse",
        "course:register",
        "course:unregister",
        "permission:create",
        "*",
    )
    for perm_name in permissions:
        existing = (
            (
                await session.execute(
                    select(PermissionModel).where(PermissionModel.name == perm_name)
                )
            )
            .scalars()
            .first()
        )
        if not existing:
            session.add(PermissionModel(name=perm_name))
    await session.flush()
    print(f"Permissions ensured: {', '.join(permissions)}")


async def init_role_permissions(session: AsyncSession) -> None:
    assignments: dict[str, list[str]] = {
        "SuperUser": ["*"],
        "Administrator": ["permission:create"],
    }
    for role_name, perms in assignments.items():
        role = (
            (
                await session.execute(
                    select(RoleModel).where(RoleModel.name == role_name)
                )
            )
            .scalars()
            .first()
        )
        if not role:
            continue
        for perm_name in perms:
            perm = (
                (
                    await session.execute(
                        select(PermissionModel).where(PermissionModel.name == perm_name)
                    )
                )
                .scalars()
                .first()
            )
            if not perm:
                continue
            existing = (
                (
                    await session.execute(
                        select(RolePermissionModel).where(
                            RolePermissionModel.role_id == role.id,
                            RolePermissionModel.permission_id == perm.id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if not existing:
                session.add(RolePermissionModel(role_id=role.id, permission_id=perm.id))
    await session.flush()
    print("Role-permission assignments ensured")


async def init_superusers(session: AsyncSession) -> None:
    role = (
        (await session.execute(select(RoleModel).where(RoleModel.name == "SuperUser")))
        .scalars()
        .first()
    )
    if not role:
        print("SuperUser role not found, skipping user assignment")
        return
    for email in SUPERUSERS:
        user = (
            (await session.execute(select(UserModel).where(UserModel.email == email)))
            .scalars()
            .first()
        )
        if not user:
            print(f"  User {email} not found, skipping")
            continue
        existing = (
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
        if not existing:
            session.add(UserRoleModel(user_id=user.id, role_id=role.id))
        print(f"  SuperUser assigned to {email}")
    await session.flush()
    print("SuperUser assignments ensured")


async def main() -> None:
    print(f"Target env: {args.env} (using {env_file})")
    async with AsyncSession(engine) as session:
        try:
            await init_roles(session)
            await init_permissions(session)
            await init_role_permissions(session)
            await init_superusers(session)
            await session.commit()
            print("\nSystem initialization complete.")
        except Exception as e:
            await session.rollback()
            print(f"Error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
