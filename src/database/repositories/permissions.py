from __future__ import annotations

from typing import Optional

from sqlalchemy import select, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models import PermissionModel, RoleModel, RolePermissionModel


async def grant_permission(role_name: str, permission_name: str) -> None:
    if permission_name == "*" and role_name != "SuperUser":
        raise ValueError("Wildcard permission can only be assigned to SuperUser")
    async with AsyncSession(engine) as session:
        role: Optional[RoleModel] = (
            (
                await session.execute(
                    select(RoleModel).where(RoleModel.name == role_name)
                )
            )
            .scalars()
            .first()
        )
        perm: Optional[PermissionModel] = (
            (
                await session.execute(
                    select(PermissionModel).where(
                        PermissionModel.name == permission_name
                    )
                )
            )
            .scalars()
            .first()
        )
        if not role:
            raise ValueError(f"Role '{role_name}' does not exist")
        if not perm:
            raise ValueError(f"Permission '{permission_name}' does not exist")
        await session.execute(
            insert(RolePermissionModel).values(role_id=role.id, permission_id=perm.id)
        )
        await session.commit()


async def revoke_permission(role_name: str, permission_name: str) -> None:
    async with AsyncSession(engine) as session:
        role: Optional[RoleModel] = (
            (
                await session.execute(
                    select(RoleModel).where(RoleModel.name == role_name)
                )
            )
            .scalars()
            .first()
        )
        perm: Optional[PermissionModel] = (
            (
                await session.execute(
                    select(PermissionModel).where(
                        PermissionModel.name == permission_name
                    )
                )
            )
            .scalars()
            .first()
        )
        if role and perm:
            await session.execute(
                delete(RolePermissionModel).where(
                    RolePermissionModel.role_id == role.id,
                    RolePermissionModel.permission_id == perm.id,
                )
            )
            await session.commit()
