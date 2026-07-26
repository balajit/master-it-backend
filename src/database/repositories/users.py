from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models import (
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    UserModel,
    UserRoleModel,
)


async def create_local_user(
    email: str, password_hash: str, name: str = "", phone: str = ""
) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing = (
            (await session.execute(select(UserModel).where(UserModel.email == email)))
            .scalars()
            .first()
        )
        if existing:
            raise ValueError("Email already registered")

        user = UserModel(
            email=email, password_hash=password_hash, name=name, phone=phone
        )
        session.add(user)
        await session.flush()

        student_role: Optional[RoleModel] = (
            (
                await session.execute(
                    select(RoleModel).where(RoleModel.name == "Student")
                )
            )
            .scalars()
            .first()
        )
        if student_role:
            await session.execute(
                insert(UserRoleModel).values(user_id=user.id, role_id=student_role.id)
            )

        await session.commit()
        return user.id


async def get_user_roles(user_id: int) -> List[str]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(RoleModel.name)
            .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
            .where(UserRoleModel.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]


async def get_user_roles_with_permissions(user_id: int) -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        roles_rows = (
            await session.execute(
                select(RoleModel.id, RoleModel.name)
                .join(UserRoleModel, RoleModel.id == UserRoleModel.role_id)
                .where(UserRoleModel.user_id == user_id)
            )
        ).fetchall()

        result: List[Dict[str, Any]] = []
        for role_id, role_name in roles_rows:
            perms_rows = (
                await session.execute(
                    select(PermissionModel.id, PermissionModel.name)
                    .join(
                        RolePermissionModel,
                        PermissionModel.id == RolePermissionModel.permission_id,
                    )
                    .where(RolePermissionModel.role_id == role_id)
                )
            ).fetchall()
            result.append(
                {
                    "id": role_id,
                    "name": role_name,
                    "permissions": [{"id": p[0], "name": p[1]} for p in perms_rows],
                }
            )
        return result


async def assign_role(user_id: int, role_name: str) -> None:
    if role_name == "SuperUser":
        raise ValueError("SuperUser role cannot be assigned through the API")
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
        if not role:
            raise ValueError(f"Role '{role_name}' does not exist")
        await session.execute(
            insert(UserRoleModel).values(user_id=user_id, role_id=role.id)
        )
        await session.commit()


async def remove_role(user_id: int, role_name: str) -> None:
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
        if role:
            await session.execute(
                delete(UserRoleModel).where(
                    UserRoleModel.user_id == user_id,
                    UserRoleModel.role_id == role.id,
                )
            )
            await session.commit()


async def get_user_permissions(user_id: int) -> List[str]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(PermissionModel.name)
            .distinct()
            .join(
                RolePermissionModel,
                PermissionModel.id == RolePermissionModel.permission_id,
            )
            .join(UserRoleModel, RolePermissionModel.role_id == UserRoleModel.role_id)
            .where(UserRoleModel.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]


async def has_permission(user_id: int, permission_name: str) -> bool:
    perms: List[str] = await get_user_permissions(user_id)
    return "*" in perms or permission_name in perms


async def get_user_permissions_display(user_id: int) -> List[str]:
    perms: List[str] = await get_user_permissions(user_id)
    return [p for p in perms if p != "*"]


async def get_all_permissions() -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        perms = (
            (
                await session.execute(
                    select(PermissionModel).order_by(PermissionModel.name)
                )
            )
            .scalars()
            .all()
        )
        return [{"id": p.id, "name": p.name} for p in perms]


async def get_roles_with_permissions() -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        roles = (await session.execute(select(RoleModel))).scalars().all()

        result: List[Dict[str, Any]] = []
        for role in roles:
            perms_rows = (
                await session.execute(
                    select(PermissionModel.id, PermissionModel.name)
                    .join(
                        RolePermissionModel,
                        PermissionModel.id == RolePermissionModel.permission_id,
                    )
                    .where(RolePermissionModel.role_id == role.id)
                )
            ).fetchall()
            result.append(
                {
                    "id": role.id,
                    "name": role.name,
                    "permissions": [{"id": p[0], "name": p[1]} for p in perms_rows],
                }
            )
        return result


async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        user: Optional[UserModel] = (
            (await session.execute(select(UserModel).where(UserModel.email == email)))
            .scalars()
            .first()
        )
        if not user:
            return None
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture_url": user.picture_url,
            "password_hash": user.password_hash,
            "phone": user.phone,
            "google_id": user.google_id,
        }


async def upsert_user(google_id: str, email: str, name: str, picture_url: str) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user: Optional[UserModel] = (
            (
                await session.execute(
                    select(UserModel).where(UserModel.google_id == google_id)
                )
            )
            .scalars()
            .first()
        )
        if user:
            user.email = email
            user.name = name
            user.picture_url = picture_url
            await session.commit()
            return user.id

        email_user: Optional[UserModel] = (
            (await session.execute(select(UserModel).where(UserModel.email == email)))
            .scalars()
            .first()
        )
        if email_user:
            email_user.google_id = google_id
            email_user.name = name
            email_user.picture_url = picture_url
            await session.commit()
            return email_user.id

        new_user = UserModel(
            google_id=google_id, email=email, name=name, picture_url=picture_url
        )
        session.add(new_user)
        await session.flush()

        student_role: Optional[RoleModel] = (
            (
                await session.execute(
                    select(RoleModel).where(RoleModel.name == "Student")
                )
            )
            .scalars()
            .first()
        )
        if student_role:
            await session.execute(
                insert(UserRoleModel).values(
                    user_id=new_user.id, role_id=student_role.id
                )
            )

        await session.commit()
        return new_user.id


async def create_permission(name: str) -> int:
    async with AsyncSession(engine) as session:
        existing = (
            (
                await session.execute(
                    select(PermissionModel).where(PermissionModel.name == name)
                )
            )
            .scalars()
            .first()
        )
        if existing:
            raise ValueError(f"Permission '{name}' already exists")
        perm = PermissionModel(name=name)
        session.add(perm)
        await session.commit()
        await session.refresh(perm)
        return perm.id


async def list_users() -> List[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        users: List[UserModel] = (
            (await session.execute(select(UserModel).order_by(UserModel.id)))
            .scalars()
            .all()
        )
        result: List[Dict[str, Any]] = []
        for user in users:
            roles: List[str] = await get_user_roles(user.id)
            result.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "picture_url": user.picture_url,
                    "phone": user.phone,
                    "roles": roles,
                }
            )
        return result
