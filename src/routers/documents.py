"""Document routes — CRUD, course association, and proxy to LP processing.

The main app owns:
- File storage (uploads/{course_id}/{filename})
- DocumentModel records in its own database
- CourseDocumentModel associations

The learning platform (LP) owns:
- Canonical document processing (pipeline)
- Canonical document, learning units, concepts, study plan

This router proxies processing and view requests to the LP sub-app
via in-process ASGI transport (no network round-trip).
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from auth import get_current_user
from database import (
    attach_document_to_course,
    create_document,
    delete_document,
    get_course,
    get_course_documents,
    get_document,
)

router: APIRouter = APIRouter(prefix="/api", tags=["documents"])
logger: logging.Logger = logging.getLogger(__name__)

UPLOAD_PATH: str = os.getenv("UPLOAD_PATH", "uploads")
MAX_UPLOAD_BYTES: int = int(
    os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
)  # 50 MB

_SAFE_FILENAME_RE: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9._-]")

# Lazy singleton for the LP sub-app (avoids creating a new FastAPI per request)
_lp_app: Any = None


def _get_lp_app() -> Any:
    """Return the LP FastAPI app, creating it once on first use."""
    global _lp_app
    if _lp_app is None:
        from learning_platform.api.app import create_app

        _lp_app = create_app()
    return _lp_app


def _sanitize_filename(name: str) -> str:
    """Strip path separators and dangerous characters from an uploaded filename."""
    base: str = Path(name).name
    safe: str = _SAFE_FILENAME_RE.sub("_", base)
    return safe or "unnamed"


# ── Document CRUD ────────────────────────────────────────────────────────────


@router.post("/courses/{course_id}/documents", status_code=201)
async def upload_document(
    course_id: int,
    file: UploadFile,
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload a document and associate it with a course.

    Stores the file at ``uploads/{course_id}/{sanitized_filename}``.
    Creates a DocumentModel record and a CourseDocumentModel link.
    """
    course: Dict[str, Any] | None = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    content: bytes = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )

    doc_id: str = uuid.uuid4().hex
    safe_name: str = _sanitize_filename(file.filename or "unnamed")
    course_dir: Path = Path(UPLOAD_PATH) / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    storage_path: str = str(course_dir / safe_name)

    with open(storage_path, "wb") as f:
        f.write(content)

    doc: Dict[str, Any] = await create_document(
        doc_id=doc_id,
        filename=safe_name,
        storage_path=storage_path,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
    )
    await attach_document_to_course(course_id, doc_id)

    logger.info(
        "Document '%s' uploaded to course %d by user %s",
        doc["filename"],
        course_id,
        user["id"],
    )
    return doc


@router.get("/courses/{course_id}/documents")
async def list_course_documents(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List all documents associated with a course."""
    course: Dict[str, Any] | None = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    docs: List[Dict[str, Any]] = await get_course_documents(course_id)
    return docs


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document_endpoint(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> None:
    """Delete a document record, its file, and its course associations."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_path: str = doc["storage_path"]
    deleted: bool = await delete_document(document_id)
    if deleted and os.path.exists(storage_path):
        os.remove(storage_path)
        course_dir: Path = Path(storage_path).parent
        if course_dir.exists() and not any(course_dir.iterdir()):
            course_dir.rmdir()

    logger.info("Document %s deleted by user %s", document_id, user["id"])


# ── Proxied LP endpoints ────────────────────────────────────────────────────


@router.post("/documents/{document_id}/process")
async def process_document(
    document_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> JSONResponse:
    """Trigger LP pipeline processing for an uploaded document.

    Reads the storage path from the DocumentModel and forwards it to the
    LP ``POST /api/documents/process`` endpoint.
    """
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return await _lp_proxy(
        request,
        "/api/documents/process",
        method="POST",
        json={"file_path": doc["storage_path"]},
    )


@router.get("/documents/{document_id}/tree")
async def get_document_tree(
    document_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> JSONResponse:
    """Proxy to LP tree endpoint."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _lp_proxy(request, f"/api/documents/{document_id}/tree")


@router.get("/documents/{document_id}/units")
async def get_document_units(
    document_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> JSONResponse:
    """Proxy to LP learning units endpoint."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _lp_proxy(request, f"/api/documents/{document_id}/units")


@router.get("/documents/{document_id}/concepts")
async def get_document_concepts(
    document_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> JSONResponse:
    """Proxy to LP concepts endpoint."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _lp_proxy(request, f"/api/documents/{document_id}/concepts")


@router.get("/documents/{document_id}/study-plan")
async def get_document_study_plan(
    document_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> JSONResponse:
    """Proxy to LP study plan endpoint."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _lp_proxy(request, f"/api/documents/{document_id}/study-plan")


@router.get("/documents/{document_id}/export/json")
async def export_document_json(
    document_id: str,
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
) -> JSONResponse:
    """Proxy to LP JSON export endpoint."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _lp_proxy(request, f"/api/documents/{document_id}/export/json")


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _lp_proxy(
    request: Request,
    path: str,
    method: str = "GET",
    json: dict[str, Any] | None = None,
) -> JSONResponse:
    """Forward a request to the LP sub-app via in-process ASGI transport.

    Calls the LP app directly (not through the ``/lp`` mount prefix).
    Auth header is forwarded from the original request so the LP's own
    ``get_current_user`` dependency can validate the token.
    """
    auth_header: str = request.headers.get("authorization", "")

    headers: dict[str, str] = {}
    if auth_header:
        headers["Authorization"] = auth_header

    transport = ASGITransport(app=_get_lp_app())

    async with AsyncClient(transport=transport, base_url="http://internal") as client:
        resp = await client.request(
            method=method,
            url=path,
            json=json,
            headers=headers,
        )

    try:
        content = resp.json()
    except Exception:
        content = {"detail": resp.text}

    return JSONResponse(content=content, status_code=resp.status_code)
