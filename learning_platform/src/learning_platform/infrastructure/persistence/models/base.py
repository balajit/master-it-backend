"""SQLAlchemy declarative base and shared column types."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import JSON, TypeDecorator
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class JsonType(TypeDecorator[list[dict[str, object]]]):
    """Portable JSON column — stores dicts/lists as JSON text.

    Works identically on SQLite (TEXT) and PostgreSQL (JSONB via dialect).
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, default=str)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value
