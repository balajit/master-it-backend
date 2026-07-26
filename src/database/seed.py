from __future__ import annotations

from sqlalchemy import select, insert

from database.base import Base, engine
from database.models import (
    PermissionModel,
    RoleModel,
    RolePermissionModel,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Seed roles
        for role_name in (
            "Administrator",
            "Instructor",
            "Student",
            "Guest",
            "SuperUser",
        ):
            result = await conn.execute(
                select(RoleModel.id).where(RoleModel.name == role_name)
            )
            if not result.fetchone():
                await conn.execute(insert(RoleModel).values(name=role_name))

        # Seed permissions
        perm_names: tuple[str, ...] = (
            "course:create",
            "course:delete",
            "course:browse",
            "course:register",
            "course:unregister",
            "permission:create",
            "*",
        )
        for perm_name in perm_names:
            result = await conn.execute(
                select(PermissionModel.id).where(PermissionModel.name == perm_name)
            )
            if not result.fetchone():
                await conn.execute(insert(PermissionModel).values(name=perm_name))

        # Assign wildcard to SuperUser
        superuser_row = (
            await conn.execute(
                select(RoleModel.id, RoleModel.name).where(
                    RoleModel.name == "SuperUser"
                )
            )
        ).fetchone()
        wildcard_row = (
            await conn.execute(
                select(PermissionModel.id, PermissionModel.name).where(
                    PermissionModel.name == "*"
                )
            )
        ).fetchone()
        if superuser_row and wildcard_row:
            existing = await conn.execute(
                select(RolePermissionModel).where(
                    RolePermissionModel.role_id == superuser_row[0],
                    RolePermissionModel.permission_id == wildcard_row[0],
                )
            )
            if not existing.scalars().first():
                await conn.execute(
                    insert(RolePermissionModel).values(
                        role_id=superuser_row[0], permission_id=wildcard_row[0]
                    )
                )

        # Assign permission:create to Administrator
        admin_row = (
            await conn.execute(
                select(RoleModel.id, RoleModel.name).where(
                    RoleModel.name == "Administrator"
                )
            )
        ).fetchone()
        perm_create_row = (
            await conn.execute(
                select(PermissionModel.id, PermissionModel.name).where(
                    PermissionModel.name == "permission:create"
                )
            )
        ).fetchone()
        if admin_row and perm_create_row:
            existing = await conn.execute(
                select(RolePermissionModel).where(
                    RolePermissionModel.role_id == admin_row[0],
                    RolePermissionModel.permission_id == perm_create_row[0],
                )
            )
            if not existing.scalars().first():
                await conn.execute(
                    insert(RolePermissionModel).values(
                        role_id=admin_row[0], permission_id=perm_create_row[0]
                    )
                )
