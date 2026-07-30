# UPDATEDB.md — Database Update Guide

This document describes every schema change introduced by the Book Model
re-engineering and how to apply them in any environment.

---

## Overview of Changes

Two databases are affected:

| Database | How tables are managed |
|---|---|
| **master-it** (PostgreSQL) | Alembic migrations via `./scripts/migrate.sh` |
| **learning-platform** (same PostgreSQL instance) | SQLAlchemy `create_all` on app startup — no Alembic |

---

## Prerequisites

- PostgreSQL running and reachable at the URL in your `.env`
- `DATABASE_URL` environment variable set (see `.env.example`)
- Python dependencies installed: `uv sync`

---

## Step 1 — Apply master-it Alembic Migrations

Run migrations via the wrapper script:

```bash
# From the project root
./scripts/migrate.sh testing
# or
./scripts/migrate.sh production
# or both
./scripts/migrate.sh
```

### What the migrations create

#### `a7f3c1b8e2d9` — LP Book Tables

Creates the four book-structure tables in the shared Postgres database.
These are managed by the LP ORM layer but live in the same DB as master-it.

| Table | Description |
|---|---|
| `lp_book_chapter` | One row per chapter in a processed document |
| `lp_book_lesson` | One row per lesson, FK → `lp_book_chapter` |
| `lp_book_page` | One row per page slice, FK → `lp_book_lesson` |
| `lp_book_item` | One row per content block, FK → `lp_book_page` |

Each table uses UUID PKs and CASCADE deletes. `lp_book_item` stores typed
content (text, heading, image, table, equation, code, list) plus `bbox`
and `style` JSON for frontend rendering.

#### `c9e2f4a1b7d3` — Item Progress

Creates the `item_progress` table for tracking per-student progress at the
individual content item level.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `enrollment_id` | INTEGER FK | → `course_enrollments.user_id` |
| `item_id` | VARCHAR | UUID of `lp_book_item` |
| `status` | VARCHAR | `not_started` \| `in_progress` \| `completed` |
| `completed_at` | VARCHAR | ISO timestamp, nullable |
| `created_at` | VARCHAR | ISO timestamp |
| `updated_at` | VARCHAR | ISO timestamp |

---

## Step 2 — LP Book Tables via App Startup

The LP book ORM models (`BookChapterRow`, `BookLessonRow`, `BookPageRow`,
`BookItemRow`) are registered in:

```
learning_platform/src/learning_platform/infrastructure/persistence/models/__init__.py
```

On application startup, `init_db()` in `src/database/seed.py` calls
`LpBase.metadata.create_all` which creates all LP tables (including the
four new book tables) if they do not already exist.

**If you ran the Alembic migration in Step 1, the tables already exist and
`create_all` will skip them.** No action required.

If you are setting up a brand-new environment and skipping Alembic (not
recommended for production), simply starting the application will create
all tables automatically.

---

## Step 3 — Verify

After applying migrations and starting the app, confirm the new tables exist:

```sql
-- Connect to your Postgres DB and run:
\dt lp_book_*
\dt item_progress

-- Expected output:
--   lp_book_chapter
--   lp_book_item
--   lp_book_lesson
--   lp_book_page
--   item_progress
```

Or using psql one-liner:

```bash
psql "$DATABASE_URL" -c "\dt lp_book_*" -c "\dt item_progress"
```

---

## Step 4 — Run Book Assembly Pipeline (Pipeline 2)

The new tables are populated by `BookPipeline` which must be triggered for
each document after Pipeline 1 (the parse/analysis pipeline) has completed.

`BookPipeline` reads LP artifacts (`lp_documents`, `lp_learning_units`) and
writes to `lp_book_chapter / lp_book_lesson / lp_book_page / lp_book_item`.

To trigger it programmatically:

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from learning_platform.pipeline.book_pipeline import BookPipeline

async def assemble_book(session: AsyncSession, document_id: str) -> None:
    pipeline = BookPipeline(session)
    book = await pipeline.run(UUID(document_id))
    print(f"Book assembled: {len(book.chapters)} chapters")
```

Until this pipeline runs for a document, `GET /api/courses/{id}/study-plan`
will return an empty `chapters` list for that document.

---

## Rollback

To undo the master-it Alembic changes:

```bash
# Roll back both new migrations
DATABASE_URL=postgresql+asyncpg://... uv run alembic downgrade b2c3d4e5f6a7
```

Note: `scripts/migrate.sh` is upgrade-only. Use raw Alembic commands for downgrade workflows.

This removes `item_progress`, `lp_book_item`, `lp_book_page`,
`lp_book_lesson`, and `lp_book_chapter` (in dependency order via CASCADE).

---

## Migration Chain Reference

```
d47d494bd230  baseline
  └─ 38ce77c986ab  learning domain indexes
       └─ 86e8229cd9b   rename columns
            └─ a1b2c3d4e5f6  study screen columns
                 └─ b2c3d4e5f6a7  enrollment tables
                      └─ b44ddc9f7522  lp_pipeline_logs
                           └─ 5e03115ba7f6  lp_document_process
                                └─ a7f3c1b8e2d9  lp_book_* tables  ← NEW
                                     └─ c9e2f4a1b7d3  item_progress  ← NEW
```
