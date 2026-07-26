import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv

load_dotenv()

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
        result = await session.execute(
            select(RoleModel).where(RoleModel.name == role_name)
        )
        if not result.fetchone():
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
        result = await session.execute(
            select(PermissionModel).where(PermissionModel.name == perm_name)
        )
        if not result.fetchone():
            session.add(PermissionModel(name=perm_name))
    await session.flush()
    print(f"Permissions ensured: {', '.join(permissions)}")


async def init_role_permissions(session: AsyncSession) -> None:
    assignments: dict[str, list[str]] = {
        "SuperUser": ["*"],
        "Administrator": ["permission:create"],
    }
    for role_name, perms in assignments.items():
        role_result = await session.execute(
            select(RoleModel).where(RoleModel.name == role_name)
        )
        role_row = role_result.fetchone()
        if not role_row:
            continue
        for perm_name in perms:
            perm_result = await session.execute(
                select(PermissionModel).where(PermissionModel.name == perm_name)
            )
            perm_row = perm_result.fetchone()
            if perm_row:
                existing = await session.execute(
                    select(RolePermissionModel).where(
                        RolePermissionModel.role_id == role_row.id,
                        RolePermissionModel.permission_id == perm_row.id,
                    )
                )
                if not existing.fetchone():
                    session.add(
                        RolePermissionModel(
                            role_id=role_row.id, permission_id=perm_row.id
                        )
                    )
    await session.flush()
    print("Role-permission assignments ensured")


async def init_superusers(session: AsyncSession) -> None:
    role_result = await session.execute(
        select(RoleModel).where(RoleModel.name == "SuperUser")
    )
    role_row = role_result.fetchone()
    if not role_row:
        print("SuperUser role not found, skipping user assignment")
        return
    for email in SUPERUSERS:
        user_result = await session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        user_row = user_result.fetchone()
        if not user_row:
            print(f"  User {email} not found, skipping")
            continue
        existing = await session.execute(
            select(UserRoleModel).where(
                UserRoleModel.user_id == user_row.id,
                UserRoleModel.role_id == role_row.id,
            )
        )
        if not existing.fetchone():
            session.add(UserRoleModel(user_id=user_row.id, role_id=role_row.id))
        print(f"  SuperUser assigned to {email}")
    await session.flush()
    print("SuperUser assignments ensured")


async def main() -> None:
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
