"""Async session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a configured session factory."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
