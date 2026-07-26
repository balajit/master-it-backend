#!/usr/bin/env python3
"""
Driver script for the Learning Platform API.

Authenticates via the main app, uploads a document to the learning_platform,
runs the full processing pipeline, and retrieves all outputs.

Usage:
    uv run learning_platform/driver.py [path_to_document]

Requires environment variables:
    JWT_SECRET       – shared secret for token validation
    MAIN_APP_URL     – base URL of the main FastAPI app  (default http://localhost:5000)
    LP_APP_URL       – base URL of the learning_platform API (default http://localhost:8000)
    AUTH_EMAIL       – email for login                 (default admin@example.com)
    AUTH_PASSWORD    – password for login              (default admin123)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

# ── Configuration ─────────────────────────────────────────────────────────────

MAIN_APP_URL: str = os.environ.get("MAIN_APP_URL", "http://localhost:5000")
LP_APP_URL: str = os.environ.get("LP_APP_URL", f"{MAIN_APP_URL}/lp")
AUTH_EMAIL: str = os.environ.get("AUTH_EMAIL", "abc@gmail.com")
AUTH_PASSWORD: str = os.environ.get("AUTH_PASSWORD", "abc")

MOCK_PDF_CONTENT: bytes = b"%PDF-1.4 Mock document for pipeline test"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n {title}\n{'=' * 60}")


def _ok(msg: str, data: Any = None) -> None:
    print(f"[OK] {msg}")
    if data is not None:
        print(json.dumps(data, indent=2, default=str))


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)


# ── Auth ──────────────────────────────────────────────────────────────────────


def login(client: httpx.Client) -> str:
    """Authenticate against the main app and return the JWT access token."""
    _section("1. LOGIN")
    resp = client.post(
        f"{MAIN_APP_URL}/api/auth/login",
        json={"email": AUTH_EMAIL, "password": AUTH_PASSWORD},
    )
    resp.raise_for_status()
    token: str = resp.json()["access_token"]
    _ok("Logged in", {"token_prefix": token + "..."})
    return token


# ── Document pipeline ─────────────────────────────────────────────────────────


def upload_document(
    client: httpx.Client,
    token: str,
    file_path: Path,
) -> str:
    """Upload a file and return the doc_id."""
    _section("2. UPLOAD DOCUMENT")
    with open(file_path, "rb") as f:
        resp = client.post(
            f"{LP_APP_URL}/api/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (file_path.name, f, "application/pdf")},
        )
    resp.raise_for_status()
    doc_id: str = resp.json()["doc_id"]
    _ok("Document uploaded", resp.json())
    return doc_id

def process_document(client: httpx.Client, token: str, doc_id: str) -> dict[str, Any]:
    """Run the full processing pipeline and return the response."""
    _section("3. PROCESS DOCUMENT")
    resp = client.post(
        f"{LP_APP_URL}/api/documents/{doc_id}/process",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    _ok("Pipeline completed", data)
    return data


def get_tree(client: httpx.Client, token: str, doc_id: str) -> dict[str, Any]:
    """Retrieve the canonical document tree."""
    _section("4. DOCUMENT TREE")
    resp = client.get(
        f"{LP_APP_URL}/api/documents/{doc_id}/tree",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    _ok(f"Tree has {data.get('total_nodes', 0)} nodes", data)
    return data


def get_units(client: httpx.Client, token: str, doc_id: str) -> dict[str, Any]:
    """Retrieve extracted learning units."""
    _section("5. LEARNING UNITS")
    resp = client.get(
        f"{LP_APP_URL}/api/documents/{doc_id}/units",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    _ok(f"{data.get('count', 0)} units extracted", data)
    return data


def get_concepts(client: httpx.Client, token: str, doc_id: str) -> dict[str, Any]:
    """Retrieve the concept graph."""
    _section("6. CONCEPT GRAPH")
    resp = client.get(
        f"{LP_APP_URL}/api/documents/{doc_id}/concepts",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    _ok(
        f"{data.get('total_concepts', 0)} concepts, "
        f"{data.get('total_relationships', 0)} relationships",
        data,
    )
    return data


def get_study_plan(client: httpx.Client, token: str, doc_id: str) -> dict[str, Any]:
    """Retrieve the structured study plan."""
    _section("7. STUDY PLAN")
    resp = client.get(
        f"{LP_APP_URL}/api/documents/{doc_id}/study-plan",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    _ok(f"{data.get('total_lessons', 0)} lessons planned", data)
    return data


def export_json(client: httpx.Client, token: str, doc_id: str) -> dict[str, Any]:
    """Download the full JSON export."""
    _section("8. JSON EXPORT")
    resp = client.get(
        f"{LP_APP_URL}/api/documents/{doc_id}/export/json",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    _ok("Export summary", data)
    return data


def list_courses(client: httpx.Client, token: str) -> dict[str, Any]:
    """List all courses."""
    _section("9. LIST COURSES")
    resp = client.get(
        f"{LP_APP_URL}/api/courses/",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    _ok(f"{data.get('count', 0)} courses", data)
    return data


# ── Pipeline runner ───────────────────────────────────────────────────────────


def _run_pipeline(client: httpx.Client, token: str, file_path: Path) -> None:
    doc_id = upload_document(client, token, file_path)
    process_document(client, token, doc_id)
    get_tree(client, token, doc_id)
    get_units(client, token, doc_id)
    get_concepts(client, token, doc_id)
    get_study_plan(client, token, doc_id)
    export_json(client, token, doc_id)
    list_courses(client, token)

    _section("COMPLETE")
    print("[OK] All steps executed successfully.")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    target_file: str | None = sys.argv[1] if len(sys.argv) > 1 else None

    client = httpx.Client(base_url=LP_APP_URL, timeout=12000000.0)

    try:
        token = login(client)

        if target_file:
            file_path = Path(target_file)
            if not file_path.exists():
                _fail(f"File not found: {file_path}")
                sys.exit(1)
            _run_pipeline(client, token, file_path)
        else:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(MOCK_PDF_CONTENT)
                file_path = Path(tmp.name)
            try:
                _run_pipeline(client, token, file_path)
            finally:
                file_path.unlink(missing_ok=True)

    except httpx.HTTPStatusError as exc:
        _fail(f"HTTP {exc.response.status_code}: {exc.response.text}")
        sys.exit(1)
    except httpx.RequestError as exc:
        _fail(f"Connection error: {exc}")
        sys.exit(1)
    finally:
        client.close()



if __name__ == "__main__":
    main()
