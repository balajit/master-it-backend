from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models import SessionModel, UserModel
from database.repositories.users import (
    get_user_permissions,
    get_user_permissions_display,
    get_user_roles,
)


async def create_session(session_id: str, user_id: int, days: int = 7) -> None:
    expires_at: str = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    async with AsyncSession(engine) as session:
        await session.execute(
            insert(SessionModel).values(
                id=session_id, user_id=user_id, expires_at=expires_at
            )
        )
        await session.commit()


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(
                SessionModel.id,
                SessionModel.user_id,
                SessionModel.expires_at,
                UserModel.email,
                UserModel.name,
                UserModel.picture_url,
                UserModel.phone,
                UserModel.google_id,
            )
            .join(UserModel, SessionModel.user_id == UserModel.id)
            .where(SessionModel.id == session_id)
        )
        row = result.fetchone()
        if not row:
            return None

        expires_at: datetime = datetime.fromisoformat(row.expires_at)
        if expires_at < datetime.now(timezone.utc):
            await delete_session(session_id)
            return None

        roles: List[str] = await get_user_roles(row.user_id)
        permissions: List[str] = await get_user_permissions_display(row.user_id)
        all_permissions: List[str] = await get_user_permissions(row.user_id)

        return {
            "id": row.id,
            "user_id": row.user_id,
            "expires_at": row.expires_at,
            "email": row.email,
            "name": row.name,
            "picture_url": row.picture_url,
            "phone": row.phone,
            "google_id": row.google_id,
            "auth_provider": "google" if row.google_id else "local",
            "roles": roles,
            "permissions": permissions,
            "_all_permissions": all_permissions,
        }


async def delete_session(session_id: str) -> None:
    async with AsyncSession(engine) as session:
        await session.execute(delete(SessionModel).where(SessionModel.id == session_id))
        await session.commit()
