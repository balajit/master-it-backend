"""Persistence for flashcard generation request tracking.

Each generate call for a target is recorded in ``user_flashcards_request`` so
that a long-running LLM generation is only ever kicked off once per target.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserFlashcardsRequestModel
from database.session import engine

ACTIVE_STATUSES: Tuple[str, ...] = ("pending", "in_progress")


def _request_to_dict(request: UserFlashcardsRequestModel) -> Dict[str, Any]:
    return {
        "request_id": request.id,
        "user_id": request.user_id,
        "scope": request.scope,
        "target_id": request.target_id,
        "status": request.status,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
    }


async def get_active_flashcards_request(
    scope: str, target_id: UUID
) -> Optional[Dict[str, Any]]:
    """Return the in-flight generation request for a target, if any."""
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardsRequestModel)
            .where(
                UserFlashcardsRequestModel.scope == scope,
                UserFlashcardsRequestModel.target_id == target_id,
                UserFlashcardsRequestModel.status.in_(ACTIVE_STATUSES),
            )
            .order_by(UserFlashcardsRequestModel.created_at.desc())
            .limit(1)
        )
        request = result.scalars().first()
        return _request_to_dict(request) if request is not None else None


async def create_flashcards_request(
    scope: str, target_id: UUID, user_id: int
) -> Tuple[Dict[str, Any], bool]:
    """Atomically create an in-flight generation request.

    Returns ``(request, created)``. If another active request already exists
    for the same ``(scope, target_id)`` the existing request is returned with
    ``created=False``; otherwise a new ``in_progress`` row is inserted.
    """
    existing = await get_active_flashcards_request(scope, target_id)
    if existing is not None:
        return existing, False

    async with AsyncSession(engine) as session:
        request = UserFlashcardsRequestModel(
            scope=scope,
            target_id=target_id,
            user_id=user_id,
            status="in_progress",
        )
        session.add(request)
        try:
            await session.commit()
            await session.refresh(request)
            return _request_to_dict(request), True
        except IntegrityError:
            await session.rollback()
            existing = await get_active_flashcards_request(scope, target_id)
            if existing is None:
                raise
            return existing, False


async def complete_flashcards_request(
    request_id: UUID, status: str
) -> Optional[Dict[str, Any]]:
    """Mark a request as completed or failed."""
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(UserFlashcardsRequestModel).where(
                UserFlashcardsRequestModel.id == request_id
            )
        )
        request = result.scalars().first()
        if request is None:
            return None
        request.status = status
        await session.commit()
        await session.refresh(request)
        return _request_to_dict(request)
