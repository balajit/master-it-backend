"""Base repository — shared async CRUD helpers for all repositories."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import select

_LOG = logging.getLogger(__name__)

ModelT = TypeVar("ModelT")


class BaseRepository[ModelT]:
    """Abstract base for async repositories.

    Subclasses set ``model_class`` to the ORM row class.
    All methods accept an ``AsyncSession`` per call (no implicit session).
    """

    model_class: type[ModelT]

    def __init__(self, session: Any) -> None:
        self._session = session

    async def save(self, instance: ModelT) -> ModelT:
        """Insert or update a single row."""
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def save_all(self, instances: Sequence[ModelT]) -> list[ModelT]:
        """Insert or update multiple rows."""
        self._session.add_all(list(instances))
        await self._session.flush()
        return list(instances)

    async def find_by_id(self, pk: Any) -> ModelT | None:
        """Look up a row by primary key."""
        return await self._session.get(self.model_class, pk)

    async def find_all(self) -> Sequence[ModelT]:
        """Return every row of this type."""
        result = await self._session.execute(select(self.model_class))
        return result.scalars().all()

    async def delete(self, instance: ModelT) -> None:
        """Delete a single row."""
        await self._session.delete(instance)
        await self._session.flush()

    async def delete_all(self) -> int:
        """Delete every row of this type.  Returns count deleted."""
        from sqlalchemy import delete

        stmt = delete(self.model_class)
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]
