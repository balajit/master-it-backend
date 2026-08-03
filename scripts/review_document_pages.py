#!/usr/bin/env python3
"""Run ReviewerAgent on a sliced PDF page range.

Examples:
    uv run python scripts/review_document_pages.py \
      --document-id 00000000-0000-0000-0000-000000000001 --page-range 7-10 \
      --provider openai --model gpt-4o --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from learning_platform.agents.llm.adapter import LLMFactory
from learning_platform.agents.reviewer import ReviewerAgent
from learning_platform.agents.reviewer_models import (
    ReviewPageRangeRequest,
    ReviewerDocumentReviewRequest,
)
from learning_platform.config import Settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review a sliced document page range")
    parser.add_argument(
        "--document-id",
        required=True,
        help="LP document id (lp_documents.id)",
    )
    parser.add_argument(
        "--page-range",
        action="append",
        required=True,
        help="Inclusive page range as START-END (repeatable)",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "openai", "anthropic"],
        help="LLM provider override",
    )
    parser.add_argument("--model", help="LLM model override")
    parser.add_argument("--base-url", help="LLM base URL override")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON result payload",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging and print persisted DB reviewer rows",
    )
    return parser


def _build_settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    if args.provider:
        overrides["llm_provider"] = args.provider
    if args.model:
        overrides["llm_model"] = args.model
    if args.base_url:
        overrides["llm_base_url"] = args.base_url
    return Settings(**overrides)


async def _run(args: argparse.Namespace) -> int:
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        )

    settings = _build_settings(args)
    llm = LLMFactory.create(settings)
    agent = ReviewerAgent(llm=llm)

    page_ranges: list[ReviewPageRangeRequest] = []
    for raw_range in args.page_range:
        start_text, sep, end_text = str(raw_range).partition("-")
        if sep != "-":
            print(f"Error: invalid --page-range format: {raw_range}", file=sys.stderr)
            return 2
        page_ranges.append(
            ReviewPageRangeRequest(
                start_page=int(start_text),
                end_page=int(end_text),
            )
        )

    request = ReviewerDocumentReviewRequest(
        lp_documents_id=str(args.document_id),
        page_ranges=page_ranges,
    )

    result = await agent.areview_document(request)

    if args.debug:
        await _print_debug_reviewer_db_rows(
            requested_lp_documents_id=str(request.lp_documents_id)
        )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    page_reviews = result.get("page_reviews", [])
    print("Reviewer document run complete")
    print(
        f"- Resolved LP Document ID: {result.get('resolved_lp_documents_id', 'unknown')}"
    )
    print(f"- Aggregate Verdict: {result.get('aggregate_verdict', 'unknown')}")
    print(f"- Pages Reviewed: {len(page_reviews)}")
    return 0


async def _print_debug_reviewer_db_rows(*, requested_lp_documents_id: str) -> None:
    from sqlalchemy import text

    from learning_platform.api.deps import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        run_rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT
                        id,
                        requested_lp_documents_id,
                        resolved_lp_documents_id,
                        resolved_document_name,
                        status,
                        aggregate_verdict,
                        aggregate_summary,
                        metadata,
                        error_message,
                        created_at,
                        updated_at
                    FROM lp_reviewer_run
                    WHERE CAST(requested_lp_documents_id AS TEXT) = :requested_lp_documents_id
                    ORDER BY created_at DESC
                    LIMIT 5
                    """
                    ),
                    {"requested_lp_documents_id": requested_lp_documents_id},
                )
            )
            .mappings()
            .all()
        )

        print("[debug] lp_reviewer_run rows:")
        if not run_rows:
            print("[debug]   (none)")
            return

        for row in run_rows:
            print(f"[debug]   {json.dumps(dict(row), default=str, sort_keys=True)}")

        latest_run_id = str(run_rows[0]["id"])
        page_rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT
                        id,
                        reviewer_run_id,
                        lp_documents_id,
                        page_number,
                        review_status,
                        review_error,
                        extracted_text_char_count,
                        summary,
                        strengths,
                        issues,
                        recommendations,
                        verdict,
                        confidence,
                        metadata,
                        created_at
                    FROM lp_reviewer_page_result
                    WHERE CAST(reviewer_run_id AS TEXT) = :reviewer_run_id
                    ORDER BY page_number ASC, id ASC
                    """
                    ),
                    {"reviewer_run_id": latest_run_id},
                )
            )
            .mappings()
            .all()
        )

        print(f"[debug] lp_reviewer_page_result rows for run_id={latest_run_id}:")
        if not page_rows:
            print("[debug]   (none)")
            return
        for row in page_rows:
            print(f"[debug]   {json.dumps(dict(row), default=str, sort_keys=True)}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
