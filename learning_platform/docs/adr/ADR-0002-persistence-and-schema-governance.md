# ADR-0002: Persistence Contracts and Alembic Governance

- Status: Accepted
- Date: 2026-07-28

## Context

LP persistence evolved quickly with JSON-heavy models and graph/sequence
relationships. Missing FK constraints and string-based timestamps increased risk
of data integrity drift and unsafe schema transitions.

## Decision

Standardize LP persistence contracts as follows:

1. JSON fields persist Python objects directly through SQLAlchemy JSON typing,
   with compatibility handling for legacy serialized string rows.
2. Enforce FK integrity for concept, graph, lesson, and checkpoint links.
3. Normalize selected `created_at` fields to timezone-aware `DateTime`.
4. Govern schema changes through Alembic revisions and validation scripts.

## Consequences

### Positive

- Better referential integrity and safer data semantics.
- Cleaner cross-database behavior for JSON fields.
- Repeatable migration verification via head/current checks and smoke tests.

### Trade-offs

- Migration complexity increases, especially for type conversions.
- Requires discipline to keep models and revisions aligned.

## Implementation References

- Model JSON type behavior:
  - `learning_platform/src/learning_platform/infrastructure/persistence/models/base.py`
- FK/timestamp model updates:
  - `learning_platform/src/learning_platform/infrastructure/persistence/models/concept.py`
  - `learning_platform/src/learning_platform/infrastructure/persistence/models/knowledge_graph.py`
  - `learning_platform/src/learning_platform/infrastructure/persistence/models/sequence.py`
  - `learning_platform/src/learning_platform/infrastructure/persistence/models/document.py`
- Migration revision:
  - `alembic/versions/9f4a2c1d8b7e_normalize_lp_timestamps_and_add_fks.py`
- Migration validation scripts:
  - `scripts/check_migrations.py`
  - `scripts/migration_smoke_test.py`
- Migration execution wrapper:
  - `scripts/migrate.sh`
