"""Persistence for flashcard generation request tracking.

Each generate call for a target is recorded in ``user_flashcards_request`` so
that a long-running LLM generation is only ever kicked off once per target.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserFlashcardsRequestModel
from database.session import engine

ACTIVE_STATUSES: Tuple[str, ...] = ("pending", "in_progress")

# A request that has not been touched within this window is treated as
# abandoned (e.g. the process crashed mid-generation or an exception escaped
# before the request could be marked failed). Abandoned requests are expired
# on the next generate call so the target can be reprocessed.
STALE_AFTER_SECONDS: int = 300


def _as_utc(value: datetime) -> datetime:
    """Normalize a DB timestamp to an aware UTC datetime for comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stale_cutoff(stale_after_seconds: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)


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


def _is_stale(request: UserFlashcardsRequestModel, stale_after_seconds: int) -> bool:
    """Return True when an active request has not been touched recently."""
    if stale_after_seconds is None:
        return False
    heartbeat = request.updated_at or request.created_at
    if heartbeat is None:
        return False
    return _as_utc(heartbeat) < _stale_cutoff(stale_after_seconds)


async def get_active_flashcards_request(
    scope: str, target_id: UUID, stale_after_seconds: int = STALE_AFTER_SECONDS
) -> Optional[Dict[str, Any]]:
    """Return the in-flight generation request for a target, if any.

    A request is only considered in-flight while it is ``pending``/``in_progress``
    and has been touched within ``stale_after_seconds``. Requests that outlived
    the window are treated as abandoned and are not returned, so the target can
    be reprocessed.
    """
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
        if request is None or _is_stale(request, stale_after_seconds):
            return None
        return _request_to_dict(request)


async def create_flashcards_request(
    scope: str,
    target_id: UUID,
    user_id: int,
    stale_after_seconds: int = STALE_AFTER_SECONDS,
) -> Tuple[Dict[str, Any], bool]:
    """Atomically create an in-flight generation request.

    Returns ``(request, created)``. If another active request already exists
    for the same ``(scope, target_id)`` the existing request is returned with
    ``created=False``; otherwise a new ``in_progress`` row is inserted.

    Any abandoned request (still ``pending``/``in_progress`` but untouched for
    longer than ``stale_after_seconds``) is expired to ``failed`` first, so a
    target that crashed mid-generation can be reprocessed.
    """
    existing = await get_active_flashcards_request(
        scope, target_id, stale_after_seconds
    )
    if existing is not None:
        return existing, False

    async with AsyncSession(engine) as session:
        await _expire_stale_requests(session, scope, target_id, stale_after_seconds)

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
            existing = await get_active_flashcards_request(
                scope, target_id, stale_after_seconds
            )
            if existing is None:
                raise
            return existing, False


async def _expire_stale_requests(
    session: AsyncSession,
    scope: str,
    target_id: UUID,
    stale_after_seconds: int,
) -> None:
    """Mark abandoned active requests as ``failed`` so the lock is released."""
    if stale_after_seconds is None:
        return
    result = await session.execute(
        select(UserFlashcardsRequestModel).where(
            UserFlashcardsRequestModel.scope == scope,
            UserFlashcardsRequestModel.target_id == target_id,
            UserFlashcardsRequestModel.status.in_(ACTIVE_STATUSES),
        )
    )
    stale = [
        request
        for request in result.scalars().all()
        if _is_stale(request, stale_after_seconds)
    ]
    if not stale:
        return
    for request in stale:
        request.status = "failed"
    await session.flush()


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
