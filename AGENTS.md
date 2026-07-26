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
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`


## Conventions

- Package manager is **uv**. Do not use pip, poetry, or conda.
- Edit `pyproject.toml` via `uv add`/`uv remove`, not by hand.

## Runtime Tools & Commands
- Environment Setup & Adding Modules: `uv add <package>`
- Hot-Reload Development Execution: `uv run fastapi dev src/main.py --port 5000`
