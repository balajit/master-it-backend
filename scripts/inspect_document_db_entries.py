#!/usr/bin/env python3
"""Inspect DB artifacts created for a document.

This script helps answer: "what rows were created for this document?"
across the main app tables and learning-platform (LP) pipeline tables.

It supports lookups by:
- main app ``documents.id`` (recommended)
- document filename (substring match)

Example:
    uv run python scripts/inspect_document_db_entries.py \
      --document-id 7f3cf7e4-1126-f240-09dc-afb0fd3eafed \
      --database-url "$DATABASE_URL"
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class DocumentRecord:
    """Main app document row."""

    id: str
    filename: str
    storage_path: str
    content_type: str
    size_bytes: int
    created_at: str


@dataclass(frozen=True)
class ResolvedDocument:
    """Document plus derived LP identifiers used by downstream tables."""

    record: DocumentRecord
    abs_path: str
    lp_doc_hash: str
    lp_doc_uuid: UUID


@dataclass(frozen=True)
class SqlCheck:
    """A named SQL statement to execute."""

    name: str
    sql: str
    params: tuple[Any, ...]


@dataclass(frozen=True)
class LpDocumentRecord:
    """LP canonical document row."""

    id: UUID
    source: str
    title: str
    owner_sub: str | None
    created_at: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect DB entries for a document")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "").strip(),
        help="Database URL (defaults to DATABASE_URL env)",
    )
    parser.add_argument("--document-id", default="", help="Main app documents.id")
    parser.add_argument(
        "--document-name",
        default="",
        help="Filename fragment to search in documents.filename",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=5,
        help="Max document candidates for --document-name (default: 5)",
    )
    parser.add_argument(
        "--row-limit",
        type=int,
        default=20,
        help="Max rows printed for per-table detail queries (default: 20)",
    )
    parser.add_argument(
        "--show-sql",
        action="store_true",
        help="Print SQL text before each query",
    )
    return parser.parse_args()


def _to_asyncpg_dsn(database_url: str) -> str:
    """Convert SQLAlchemy asyncpg URL form to asyncpg DSN."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _stable_doc_id(file_path: str) -> str:
    """Match learning_platform.service.stable_doc_id behavior."""
    resolved = str(Path(file_path).resolve())
    return hashlib.sha256(resolved.encode()).hexdigest()


def _serialize_value(value: Any) -> Any:
    """Convert values to JSON-safe primitives for display."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, dict, tuple)):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    return value


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert asyncpg row to plain dict."""
    return {key: _serialize_value(value) for key, value in dict(row).items()}


def _print_json(title: str, payload: Any) -> None:
    """Pretty-print JSON section."""
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, default=str))


async def _find_documents(
    conn: asyncpg.Connection,
    *,
    document_id: str,
    document_name: str,
    candidate_limit: int,
) -> list[DocumentRecord]:
    """Resolve target document rows from main app documents table."""
    if document_id:
        rows = await conn.fetch(
            """
            SELECT id, filename, storage_path, content_type, size_bytes, created_at
            FROM documents
            WHERE id = $1
            """,
            document_id,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, filename, storage_path, content_type, size_bytes, created_at
            FROM documents
            WHERE filename ILIKE $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            f"%{document_name}%",
            candidate_limit,
        )

    result: list[DocumentRecord] = []
    for row in rows:
        result.append(
            DocumentRecord(
                id=str(row["id"]),
                filename=str(row["filename"]),
                storage_path=str(row["storage_path"]),
                content_type=str(row["content_type"]),
                size_bytes=int(row["size_bytes"]),
                created_at=str(row["created_at"]),
            )
        )
    return result


def _resolve_document(record: DocumentRecord) -> ResolvedDocument:
    """Compute LP IDs from the main document record."""
    abs_path = str(Path(record.storage_path).resolve())
    lp_doc_hash = _stable_doc_id(record.storage_path)
    lp_doc_uuid = UUID(lp_doc_hash[:32])
    return ResolvedDocument(
        record=record,
        abs_path=abs_path,
        lp_doc_hash=lp_doc_hash,
        lp_doc_uuid=lp_doc_uuid,
    )


def _parse_lp_uuid(value: str) -> UUID | None:
    """Try to parse LP UUID from a raw identifier."""
    raw = value.strip()
    if not raw:
        return None

    try:
        return UUID(raw)
    except ValueError:
        pass

    if len(raw) >= 32:
        try:
            return UUID(raw[:32])
        except ValueError:
            return None
    return None


def _build_checks(target: ResolvedDocument, row_limit: int) -> list[SqlCheck]:
    """Build SQL checks for the selected document."""
    checks: list[SqlCheck] = [
        SqlCheck(
            name="documents (main app)",
            sql="""
            SELECT id, filename, storage_path, content_type, size_bytes, created_at
            FROM documents
            WHERE id = $1
            """,
            params=(target.record.id,),
        ),
        SqlCheck(
            name="course_documents links",
            sql="""
            SELECT course_id, document_id
            FROM course_documents
            WHERE document_id = $1
            ORDER BY course_id ASC
            """,
            params=(target.record.id,),
        ),
        SqlCheck(
            name="lp_document_process runs for abs_path",
            sql="""
            SELECT id, source, abs_path, status, run_mode, retry_count, max_retries,
                   last_completed_stage, failed_stage, error_message, created_at, updated_at
            FROM lp_document_process
            WHERE abs_path = $1
            ORDER BY id ASC
            """,
            params=(target.abs_path,),
        ),
        SqlCheck(
            name="lp_pipeline_logs grouped by process/stage",
            sql="""
            SELECT pl.document_process_id, pl.stage, pl.result, COUNT(*) AS row_count,
                   MIN(pl.created_at) AS first_seen, MAX(pl.created_at) AS last_seen
            FROM lp_pipeline_logs pl
            JOIN lp_document_process dp ON dp.id = pl.document_process_id
            WHERE dp.abs_path = $1
            GROUP BY pl.document_process_id, pl.stage, pl.result
            ORDER BY pl.document_process_id ASC, pl.stage ASC
            """,
            params=(target.abs_path,),
        ),
        SqlCheck(
            name="lp_documents exact id",
            sql="""
            SELECT id, source, title, owner_sub, created_at
            FROM lp_documents
            WHERE id = $1
            """,
            params=(target.lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_documents by source variants",
            sql="""
            SELECT id, source, title, owner_sub, created_at
            FROM lp_documents
            WHERE source IN ($1, $2, $3)
            ORDER BY created_at DESC
            """,
            params=(
                target.record.storage_path,
                target.abs_path,
                target.record.filename,
            ),
        ),
        SqlCheck(
            name="lp artifact counts by document_id",
            sql="""
            SELECT 'lp_learning_units' AS table_name, COUNT(*)::bigint AS row_count
              FROM lp_learning_units WHERE document_id = $1
            UNION ALL
            SELECT 'lp_annotations', COUNT(*)::bigint
              FROM lp_annotations WHERE document_id = $1
            UNION ALL
            SELECT 'lp_concepts', COUNT(*)::bigint
              FROM lp_concepts WHERE document_id = $1
            UNION ALL
            SELECT 'lp_concept_relationships', COUNT(*)::bigint
              FROM lp_concept_relationships WHERE document_id = $1
            UNION ALL
            SELECT 'lp_knowledge_graphs', COUNT(*)::bigint
              FROM lp_knowledge_graphs WHERE document_id = $1
            UNION ALL
            SELECT 'lp_study_plans', COUNT(*)::bigint
              FROM lp_study_plans WHERE document_id = $1
            UNION ALL
            SELECT 'lp_book_chapter', COUNT(*)::bigint
              FROM lp_book_chapter WHERE document_id = $1
            ORDER BY table_name ASC
            """,
            params=(target.lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_lessons/milestones/checkpoints via study_plan",
            sql="""
            SELECT
                (SELECT COUNT(*)::bigint
                   FROM lp_lessons l
                   JOIN lp_study_plans sp ON sp.id = l.study_plan_id
                  WHERE sp.document_id = $1) AS lesson_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_milestones m
                   JOIN lp_study_plans sp ON sp.id = m.study_plan_id
                  WHERE sp.document_id = $1) AS milestone_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_checkpoints c
                   JOIN lp_study_plans sp ON sp.id = c.study_plan_id
                  WHERE sp.document_id = $1) AS checkpoint_count
            """,
            params=(target.lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_book_lesson/page/item counts via joins",
            sql="""
            SELECT
                (SELECT COUNT(*)::bigint
                   FROM lp_book_lesson bl
                   JOIN lp_book_chapter bc ON bc.id = bl.chapter_id
                  WHERE bc.document_id = $1) AS book_lesson_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_book_page bp
                   JOIN lp_book_lesson bl ON bl.id = bp.lesson_id
                   JOIN lp_book_chapter bc ON bc.id = bl.chapter_id
                  WHERE bc.document_id = $1) AS book_page_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_book_item bi
                   JOIN lp_book_page bp ON bp.id = bi.page_id
                   JOIN lp_book_lesson bl ON bl.id = bp.lesson_id
                   JOIN lp_book_chapter bc ON bc.id = bl.chapter_id
                  WHERE bc.document_id = $1) AS book_item_count
            """,
            params=(target.lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_book_process rows (hash/uuid)",
            sql="""
            SELECT id, document_id, status, retry_count, max_retries, error_message, created_at, updated_at
            FROM lp_book_process
            WHERE document_id IN ($1, $2)
            ORDER BY id ASC
            """,
            params=(target.lp_doc_hash, str(target.lp_doc_uuid)),
        ),
        SqlCheck(
            name="latest lp_pipeline_logs detail",
            sql=f"""
            SELECT pl.id, pl.document_process_id, pl.stage, pl.result, pl.output, pl.created_at
            FROM lp_pipeline_logs pl
            JOIN lp_document_process dp ON dp.id = pl.document_process_id
            WHERE dp.abs_path = $1
            ORDER BY pl.id DESC
            LIMIT {int(row_limit)}
            """,
            params=(target.abs_path,),
        ),
    ]
    return checks


async def _run_check(
    conn: asyncpg.Connection,
    check: SqlCheck,
    *,
    show_sql: bool,
) -> list[dict[str, Any]]:
    """Execute a SQL check and return rows as dictionaries."""
    print(f"\n--- {check.name} ---")
    if show_sql:
        print(check.sql.strip())
        print(f"params={check.params}")

    rows = await conn.fetch(check.sql, *check.params)
    data = [_row_to_dict(row) for row in rows]
    _print_json(check.name, data)
    return data


async def _find_lp_document(
    conn: asyncpg.Connection,
    *,
    lp_doc_uuid: UUID,
) -> LpDocumentRecord | None:
    """Load LP canonical document row by UUID."""
    row = await conn.fetchrow(
        """
        SELECT id, source, title, owner_sub, created_at
        FROM lp_documents
        WHERE id = $1
        """,
        lp_doc_uuid,
    )
    if row is None:
        return None

    return LpDocumentRecord(
        id=UUID(str(row["id"])),
        source=str(row["source"] or ""),
        title=str(row["title"] or ""),
        owner_sub=str(row["owner_sub"]) if row["owner_sub"] is not None else None,
        created_at=str(row["created_at"]),
    )


def _build_lp_only_checks(
    *,
    lp_doc_uuid: UUID,
    lp_doc_hash_hints: tuple[str, ...],
    abs_path_hints: tuple[str, ...],
    source_hints: tuple[str, ...],
    row_limit: int,
) -> list[SqlCheck]:
    """Build SQL checks when caller starts from an LP document ID."""
    book_process_hints: list[str] = [str(lp_doc_uuid), *lp_doc_hash_hints]

    checks: list[SqlCheck] = [
        SqlCheck(
            name="lp_documents exact id",
            sql="""
            SELECT id, source, title, owner_sub, created_at
            FROM lp_documents
            WHERE id = $1
            """,
            params=(lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_document_process using source/abs_path hints",
            sql="""
            SELECT id, source, abs_path, status, run_mode, retry_count, max_retries,
                   last_completed_stage, failed_stage, error_message, created_at, updated_at
            FROM lp_document_process
            WHERE abs_path = ANY($1::text[])
               OR source = ANY($2::text[])
            ORDER BY id ASC
            """,
            params=(list(abs_path_hints), list(source_hints)),
        ),
        SqlCheck(
            name="lp_pipeline_logs grouped using source/abs_path hints",
            sql="""
            SELECT pl.document_process_id, pl.stage, pl.result, COUNT(*) AS row_count,
                   MIN(pl.created_at) AS first_seen, MAX(pl.created_at) AS last_seen
            FROM lp_pipeline_logs pl
            JOIN lp_document_process dp ON dp.id = pl.document_process_id
            WHERE dp.abs_path = ANY($1::text[])
               OR dp.source = ANY($2::text[])
            GROUP BY pl.document_process_id, pl.stage, pl.result
            ORDER BY pl.document_process_id ASC, pl.stage ASC
            """,
            params=(list(abs_path_hints), list(source_hints)),
        ),
        SqlCheck(
            name="lp artifact counts by document_id",
            sql="""
            SELECT 'lp_learning_units' AS table_name, COUNT(*)::bigint AS row_count
              FROM lp_learning_units WHERE document_id = $1
            UNION ALL
            SELECT 'lp_annotations', COUNT(*)::bigint
              FROM lp_annotations WHERE document_id = $1
            UNION ALL
            SELECT 'lp_concepts', COUNT(*)::bigint
              FROM lp_concepts WHERE document_id = $1
            UNION ALL
            SELECT 'lp_concept_relationships', COUNT(*)::bigint
              FROM lp_concept_relationships WHERE document_id = $1
            UNION ALL
            SELECT 'lp_knowledge_graphs', COUNT(*)::bigint
              FROM lp_knowledge_graphs WHERE document_id = $1
            UNION ALL
            SELECT 'lp_study_plans', COUNT(*)::bigint
              FROM lp_study_plans WHERE document_id = $1
            UNION ALL
            SELECT 'lp_book_chapter', COUNT(*)::bigint
              FROM lp_book_chapter WHERE document_id = $1
            ORDER BY table_name ASC
            """,
            params=(lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_lessons/milestones/checkpoints via study_plan",
            sql="""
            SELECT
                (SELECT COUNT(*)::bigint
                   FROM lp_lessons l
                   JOIN lp_study_plans sp ON sp.id = l.study_plan_id
                  WHERE sp.document_id = $1) AS lesson_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_milestones m
                   JOIN lp_study_plans sp ON sp.id = m.study_plan_id
                  WHERE sp.document_id = $1) AS milestone_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_checkpoints c
                   JOIN lp_study_plans sp ON sp.id = c.study_plan_id
                  WHERE sp.document_id = $1) AS checkpoint_count
            """,
            params=(lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_book_lesson/page/item counts via joins",
            sql="""
            SELECT
                (SELECT COUNT(*)::bigint
                   FROM lp_book_lesson bl
                   JOIN lp_book_chapter bc ON bc.id = bl.chapter_id
                  WHERE bc.document_id = $1) AS book_lesson_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_book_page bp
                   JOIN lp_book_lesson bl ON bl.id = bp.lesson_id
                   JOIN lp_book_chapter bc ON bc.id = bl.chapter_id
                  WHERE bc.document_id = $1) AS book_page_count,
                (SELECT COUNT(*)::bigint
                   FROM lp_book_item bi
                   JOIN lp_book_page bp ON bp.id = bi.page_id
                   JOIN lp_book_lesson bl ON bl.id = bp.lesson_id
                   JOIN lp_book_chapter bc ON bc.id = bl.chapter_id
                  WHERE bc.document_id = $1) AS book_item_count
            """,
            params=(lp_doc_uuid,),
        ),
        SqlCheck(
            name="lp_book_process rows by document_id hints",
            sql="""
            SELECT id, document_id, status, retry_count, max_retries, error_message, created_at, updated_at
            FROM lp_book_process
            WHERE document_id = ANY($1::text[])
            ORDER BY id ASC
            """,
            params=(book_process_hints,),
        ),
        SqlCheck(
            name="latest lp_pipeline_logs detail using source/abs_path hints",
            sql=f"""
            SELECT pl.id, pl.document_process_id, pl.stage, pl.result, pl.output, pl.created_at
            FROM lp_pipeline_logs pl
            JOIN lp_document_process dp ON dp.id = pl.document_process_id
            WHERE dp.abs_path = ANY($1::text[])
               OR dp.source = ANY($2::text[])
            ORDER BY pl.id DESC
            LIMIT {int(row_limit)}
            """,
            params=(list(abs_path_hints), list(source_hints)),
        ),
    ]
    return checks


async def _inspect_lp_document_id(
    conn: asyncpg.Connection,
    *,
    raw_document_id: str,
    lp_doc_uuid: UUID,
    row_limit: int,
    show_sql: bool,
) -> None:
    """Inspect LP artifacts directly when input ID is an LP UUID-style value."""
    lp_doc = await _find_lp_document(conn, lp_doc_uuid=lp_doc_uuid)
    source_hints: list[str] = []
    abs_path_hints: list[str] = []
    hash_hints: list[str] = []

    if lp_doc is not None and lp_doc.source:
        source_hints.append(lp_doc.source)
        resolved = str(Path(lp_doc.source).resolve())
        abs_path_hints.extend([lp_doc.source, resolved])
        hash_hints.append(_stable_doc_id(lp_doc.source))

    if raw_document_id:
        source_hints.append(raw_document_id)
        abs_path_hints.append(raw_document_id)

    source_hints = sorted({hint for hint in source_hints if hint})
    abs_path_hints = sorted({hint for hint in abs_path_hints if hint})
    hash_hints = sorted({hint for hint in hash_hints if hint})

    _print_json(
        "lp-target",
        {
            "raw_document_id": raw_document_id,
            "lp_doc_uuid": str(lp_doc_uuid),
            "lp_document_row_found": lp_doc is not None,
            "lp_source": lp_doc.source if lp_doc is not None else "",
            "abs_path_hints": abs_path_hints,
            "source_hints": source_hints,
            "lp_doc_hash_hints": hash_hints,
        },
    )

    checks = _build_lp_only_checks(
        lp_doc_uuid=lp_doc_uuid,
        lp_doc_hash_hints=tuple(hash_hints),
        abs_path_hints=tuple(abs_path_hints),
        source_hints=tuple(source_hints),
        row_limit=row_limit,
    )
    for check in checks:
        await _run_check(conn, check, show_sql=show_sql)


async def _inspect_target(
    conn: asyncpg.Connection,
    target: ResolvedDocument,
    *,
    row_limit: int,
    show_sql: bool,
) -> None:
    """Run all checks for a resolved document target."""
    _print_json(
        "target",
        {
            "document_id": target.record.id,
            "filename": target.record.filename,
            "storage_path": target.record.storage_path,
            "abs_path": target.abs_path,
            "lp_doc_hash": target.lp_doc_hash,
            "lp_doc_uuid": str(target.lp_doc_uuid),
        },
    )

    checks = _build_checks(target, row_limit)
    for check in checks:
        await _run_check(conn, check, show_sql=show_sql)


async def _run() -> int:
    args = _parse_args()

    if not args.database_url:
        print(
            "[fail] DATABASE_URL missing. Pass --database-url or export DATABASE_URL."
        )
        return 1

    if not args.document_id and not args.document_name:
        print("[fail] Provide --document-id or --document-name")
        return 1

    dsn = _to_asyncpg_dsn(str(args.database_url))
    conn = await asyncpg.connect(dsn=dsn)
    try:
        records = await _find_documents(
            conn,
            document_id=str(args.document_id).strip(),
            document_name=str(args.document_name).strip(),
            candidate_limit=int(args.candidate_limit),
        )
        if not records:
            raw_document_id = str(args.document_id).strip()
            lp_doc_uuid = _parse_lp_uuid(raw_document_id)
            if lp_doc_uuid is None:
                print("[info] No matching documents found in main documents table.")
                return 0

            print(
                "[info] No main-table match; treating input as LP document identifier"
            )
            await _inspect_lp_document_id(
                conn,
                raw_document_id=raw_document_id,
                lp_doc_uuid=lp_doc_uuid,
                row_limit=int(args.row_limit),
                show_sql=bool(args.show_sql),
            )
            return 0

        print(f"[info] Found {len(records)} document candidate(s)")
        for index, record in enumerate(records, start=1):
            print(
                f"  {index}. id={record.id} filename={record.filename} "
                f"created_at={record.created_at}"
            )

        for record in records:
            target = _resolve_document(record)
            await _inspect_target(
                conn,
                target,
                row_limit=int(args.row_limit),
                show_sql=bool(args.show_sql),
            )
        return 0
    finally:
        await conn.close()


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception as exc:
        print(f"[fail] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
