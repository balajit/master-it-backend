# AGENTS.md

## Project

## System Stack
- Framework: Python 3.10+ with FastAPI
- Dependency Engine: uv (Do not use raw pip or manual venv activations)
- Database: SQLite

## Commands

## Coding
- Think in terms of objects to represent the entities and state. Always create pydantic types and use collections and types from typing pakcage
- always follow type hinting.  All the variables and functions should have types including the return types.
- All feature changes require tests.
- All reported issues require a test to be added before the fix.
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`


## Conventions

- Package manager is **uv**. Do not use pip, poetry, or conda.
- Edit `pyproject.toml` via `uv add`/`uv remove`, not by hand.
- **Alembic migrations must be backward compatible and additive.** Existing databases can never be dropped or recreated. Drops are not the default strategy:
  - Never `drop_table`; create a new table instead.
  - Never run destructive SQL (`DROP`/`TRUNCATE`) in `upgrade()`.
  - Renames require the create-then-copy-then-drop pattern: add the new column, backfill data via `op.execute`, then drop the old column.
  - `drop_index`/`drop_constraint` are allowed; `drop_column` only with a replacement/backfill step.
- Migration history is a single baseline (`alembic/versions/b6c7d8e9f0a1_initial_schema.py`, revision `b6c7d8e9f0a1`, `down_revision=None`); new migrations chain from `head`. `src/tests/test_migrations_additive.py` enforces the rules above.

## Runtime Tools & Commands
- Environment Setup & Adding Modules: `uv add <package>`
- Hot-Reload Development Execution: `uv run fastapi dev src/main.py --port 5000`
