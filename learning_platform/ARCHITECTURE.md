## Architecture

You are a senior software architect.

Design a production-quality Python project for a document processing and learning platform.

Requirements:

- Python 3.12
- Poetry
- Pydantic v2
- SQLAlchemy
- NetworkX
- FastAPI
- pytest
- mypy
- Ruff
- uv

The system must have the following pipeline:

Document
→ Parser
→ Canonical Document Model
→ Structural Normalizer
→ Semantic Enrichment
→ Learning Unit Builder
→ Knowledge Graph Builder
→ Learning Sequence Builder

Generate

- folder structure
- module responsibilities
- interfaces
- dependency flow

Follow SOLID principles.

No business logic yet.

Only architecture.