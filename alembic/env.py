"""Alembic environment configuration for async PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

from database.base import Base

# Ensure project root is on sys.path so learning_platform package is importable
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from learning_platform.infrastructure.persistence.models import Base as LpBase  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Merge both metadata sets so Alembic tracks core + LP tables as one.
target_metadata = Base.metadata
for _table_name, _table in LpBase.metadata.tables.items():
    if _table_name not in target_metadata:
        target_metadata._add_table(_table_name, _table.schema, _table)

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres_user:secure_password_here@localhost:5433/learning_platform_testing",
)


def _admin_url(database_url: str) -> str:
    """Return a connection URL pointing to the 'postgres' maintenance database."""
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/postgres"))


async def _ensure_database_exists(database_url: str) -> None:
    """Create the target database if it does not already exist."""
    parsed = urlparse(database_url)
    db_name: str = parsed.path.lstrip("/")
    admin_url: str = _admin_url(database_url)

    engine = create_async_engine(
        admin_url, isolation_level="AUTOCOMMIT", poolclass=pool.NullPool
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            exists: bool = result.scalar() is not None
            if not exists:
                # Database names cannot be parameterised in DDL
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await engine.dispose()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = DATABASE_URL.replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Exclude tables not owned by Base.metadata from autogenerate."""
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    return True


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    await _ensure_database_exists(DATABASE_URL)
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DATABASE_URL
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
