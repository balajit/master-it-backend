#!/usr/bin/env python3
"""Reusable live-flow check for /api/documents/{document_id}/process idempotency.

This script validates the behavior exercised during manual debugging:
- authenticate (or use a provided bearer token)
- call /process and wait for terminal status
- call /process again to simulate refresh
- assert no new processing run was created by refresh

Example:
    uv run python scripts/test_document_process_idempotency.py \
      --document-id 4bc2ab8a8c294d7cae74003c7de88eff \
      --email user@example.com \
      --password 'secret' \
      --database-url "$DATABASE_URL"
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Literal

import asyncpg
import httpx
from pydantic import BaseModel, Field


TERMINAL_STATUSES: set[str] = {"completed", "failed"}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class ProcessStage(BaseModel):
    stage: str
    result: str
    output: str
    created_at: str


class ProcessRun(BaseModel):
    process_id: int
    run_mode: str
    status: str
    retry_count: int
    max_retries: int
    error_message: str | None = None
    created_at: str
    updated_at: str
    stages: list[ProcessStage] = Field(default_factory=list)


class BookProcessSummary(BaseModel):
    status: str
    retry_count: int
    max_retries: int
    error_message: str | None = None
    updated_at: str


class ProcessStartResponse(BaseModel):
    document_id: str
    lp_doc_id: str
    status: str
    already_started: bool
    can_retry: bool
    message: str
    latest_process_run: ProcessRun
    process_runs: list[ProcessRun] = Field(default_factory=list)
    book_pipeline: BookProcessSummary | None = None


class ProcessApiResult(BaseModel):
    status_code: int
    payload: ProcessStartResponse


class DbSnapshot(BaseModel):
    abs_path: str
    process_count: int
    latest_process_id: int | None
    latest_status: str | None
    latest_stage_count: int


class ScriptArgs(BaseModel):
    base_url: str
    document_id: str
    token: str | None
    email: str | None
    password: str | None
    database_url: str | None
    poll_interval_seconds: float
    max_polls: int
    post_refresh_wait_seconds: float
    expected_terminal_status: Literal["completed", "failed", "any"]
    request_timeout_seconds: float


def _to_asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _parse_args() -> ScriptArgs:
    parser = argparse.ArgumentParser(
        description="Test /process idempotency against a live backend"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://127.0.0.1:5000"),
        help="Backend base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--document-id",
        required=True,
        help="Document ID from main app documents table",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("TEST_AUTH_TOKEN"),
        help="Bearer token; skips login when provided",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("TEST_USER_EMAIL"),
        help="Login email (required when --token is not provided)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("TEST_USER_PASSWORD"),
        help="Login password (required when --token is not provided)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Optional DATABASE_URL for DB-level assertions",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=2.0,
        help="Sleep interval between poll attempts (default: %(default)s)",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=45,
        help="Max poll attempts while waiting for terminal status",
    )
    parser.add_argument(
        "--post-refresh-wait-seconds",
        type=float,
        default=2.0,
        help="Wait after refresh call before DB snapshot",
    )
    parser.add_argument(
        "--expected-terminal-status",
        choices=["completed", "failed", "any"],
        default="completed",
        help="Expected terminal status before refresh checks",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP request timeout in seconds",
    )

    raw = parser.parse_args()
    return ScriptArgs(
        base_url=str(raw.base_url).rstrip("/"),
        document_id=str(raw.document_id).strip(),
        token=str(raw.token).strip() if raw.token else None,
        email=str(raw.email).strip() if raw.email else None,
        password=str(raw.password).strip() if raw.password else None,
        database_url=str(raw.database_url).strip() if raw.database_url else None,
        poll_interval_seconds=float(raw.poll_interval_seconds),
        max_polls=int(raw.max_polls),
        post_refresh_wait_seconds=float(raw.post_refresh_wait_seconds),
        expected_terminal_status=raw.expected_terminal_status,
        request_timeout_seconds=float(raw.request_timeout_seconds),
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def _authenticate(client: httpx.AsyncClient, args: ScriptArgs) -> str:
    if args.token:
        return args.token

    _require(
        bool(args.email and args.password),
        "Provide --token or both --email and --password",
    )

    response = await client.post(
        f"{args.base_url}/api/auth/login",
        json={"email": args.email, "password": args.password},
    )
    _require(
        response.status_code == 200,
        f"Login failed with status {response.status_code}: {response.text}",
    )

    token_response = TokenResponse.model_validate(response.json())
    return token_response.access_token


async def _call_process(
    client: httpx.AsyncClient,
    args: ScriptArgs,
    token: str,
) -> ProcessApiResult:
    response = await client.post(
        f"{args.base_url}/api/documents/{args.document_id}/process",
        headers={"Authorization": f"Bearer {token}"},
    )
    _require(
        response.status_code in {200, 202},
        f"/process failed with status {response.status_code}: {response.text}",
    )

    payload = ProcessStartResponse.model_validate(response.json())
    return ProcessApiResult(status_code=response.status_code, payload=payload)


async def _wait_for_terminal(
    client: httpx.AsyncClient,
    args: ScriptArgs,
    token: str,
    initial: ProcessApiResult,
) -> ProcessApiResult:
    current = initial
    if current.payload.status in TERMINAL_STATUSES:
        return current

    for attempt in range(1, args.max_polls + 1):
        await asyncio.sleep(args.poll_interval_seconds)
        current = await _call_process(client, args, token)
        print(
            f"[poll {attempt}/{args.max_polls}] status={current.payload.status} "
            f"process_id={current.payload.latest_process_run.process_id}"
        )
        if current.payload.status in TERMINAL_STATUSES:
            return current

    raise TimeoutError(
        f"Timed out waiting for terminal status; last status={current.payload.status}"
    )


async def _get_document_abs_path(conn: asyncpg.Connection, document_id: str) -> str:
    storage_path = await conn.fetchval(
        "SELECT storage_path FROM documents WHERE id = $1",
        document_id,
    )
    _require(storage_path is not None, f"Document {document_id} not found in documents")
    return str(Path(str(storage_path)).resolve())


async def _snapshot_process_state(
    conn: asyncpg.Connection,
    abs_path: str,
) -> DbSnapshot:
    rows = await conn.fetch(
        """
        SELECT id, status
        FROM lp_document_process
        WHERE abs_path = $1
        ORDER BY id ASC
        """,
        abs_path,
    )

    process_count = len(rows)
    latest_process_id: int | None = int(rows[-1]["id"]) if rows else None
    latest_status: str | None = str(rows[-1]["status"]) if rows else None

    latest_stage_count = 0
    if latest_process_id is not None:
        stage_count_value = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM lp_pipeline_logs
            WHERE document_process_id = $1
            """,
            latest_process_id,
        )
        latest_stage_count = int(stage_count_value or 0)

    return DbSnapshot(
        abs_path=abs_path,
        process_count=process_count,
        latest_process_id=latest_process_id,
        latest_status=latest_status,
        latest_stage_count=latest_stage_count,
    )


def _assert_expected_terminal_status(args: ScriptArgs, status: str) -> None:
    if args.expected_terminal_status == "any":
        return
    _require(
        status == args.expected_terminal_status,
        "Terminal status mismatch: "
        f"expected={args.expected_terminal_status}, actual={status}",
    )


def _assert_api_idempotency(
    terminal_result: ProcessApiResult,
    refresh_result: ProcessApiResult,
) -> None:
    _require(refresh_result.status_code == 200, "Refresh call should return HTTP 200")
    _require(
        refresh_result.payload.already_started,
        "Refresh call should report already_started=true",
    )
    _require(
        refresh_result.payload.latest_process_run.process_id
        == terminal_result.payload.latest_process_run.process_id,
        "Refresh call created a new process_id unexpectedly",
    )
    _require(
        len(refresh_result.payload.process_runs)
        == len(terminal_result.payload.process_runs),
        "Refresh call changed process_runs length unexpectedly",
    )


def _assert_db_idempotency(before: DbSnapshot, after: DbSnapshot) -> None:
    _require(
        before.process_count == after.process_count,
        "DB check failed: lp_document_process row count changed after refresh",
    )
    _require(
        before.latest_process_id == after.latest_process_id,
        "DB check failed: latest process id changed after refresh",
    )
    _require(
        before.latest_stage_count == after.latest_stage_count,
        "DB check failed: latest process stage count changed after refresh",
    )


async def _run(args: ScriptArgs) -> int:
    timeout = httpx.Timeout(args.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        token = await _authenticate(client, args)
        print("[info] authenticated")

        db_conn: asyncpg.Connection | None = None
        abs_path: str | None = None
        if args.database_url:
            db_conn = await asyncpg.connect(dsn=_to_asyncpg_dsn(args.database_url))
            abs_path = await _get_document_abs_path(db_conn, args.document_id)
            print(f"[info] resolved abs_path={abs_path}")

        try:
            first = await _call_process(client, args, token)
            print(
                f"[step] first /process: http={first.status_code} "
                f"status={first.payload.status} "
                f"process_id={first.payload.latest_process_run.process_id}"
            )

            terminal = await _wait_for_terminal(client, args, token, first)
            print(
                f"[step] terminal status reached: {terminal.payload.status} "
                f"(process_id={terminal.payload.latest_process_run.process_id})"
            )
            _assert_expected_terminal_status(args, terminal.payload.status)

            before_snapshot: DbSnapshot | None = None
            if db_conn is not None and abs_path is not None:
                before_snapshot = await _snapshot_process_state(db_conn, abs_path)
                print(
                    "[db-before] "
                    f"runs={before_snapshot.process_count} "
                    f"latest_id={before_snapshot.latest_process_id} "
                    f"latest_stage_count={before_snapshot.latest_stage_count}"
                )

            refresh = await _call_process(client, args, token)
            print(
                f"[step] refresh /process: http={refresh.status_code} "
                f"status={refresh.payload.status} "
                f"already_started={refresh.payload.already_started} "
                f"process_id={refresh.payload.latest_process_run.process_id}"
            )

            _assert_api_idempotency(terminal, refresh)

            if (
                db_conn is not None
                and abs_path is not None
                and before_snapshot is not None
            ):
                await asyncio.sleep(args.post_refresh_wait_seconds)
                after_snapshot = await _snapshot_process_state(db_conn, abs_path)
                print(
                    "[db-after] "
                    f"runs={after_snapshot.process_count} "
                    f"latest_id={after_snapshot.latest_process_id} "
                    f"latest_stage_count={after_snapshot.latest_stage_count}"
                )
                _assert_db_idempotency(before_snapshot, after_snapshot)

        finally:
            if db_conn is not None:
                await db_conn.close()

    print("[ok] /process idempotency check passed")
    return 0


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"[fail] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
