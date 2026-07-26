"""Async SQLAlchemy engine factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from learning_platform.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create an async engine from settings."""
    return create_async_engine(settings.database_url, echo=settings.debug)
