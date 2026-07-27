"""Document routes — CRUD, course association, and LP pipeline integration.

The main app owns:
- File storage (uploads/{course_id}/{filename})
- DocumentModel records in its own database
- CourseDocumentModel associations

The learning platform (LP) owns:
- Canonical document processing (pipeline)
- Canonical document, learning units, concepts, study plan

Previously, LP endpoints were reached via an in-process ASGI proxy
(``httpx.ASGITransport``), which created a second LP FastAPI instance with its
own isolated ``pipeline_cache``, causing cache misses on every lookup.

This router now calls ``LearningPlatformService`` directly — a Python-level
facade over the same orchestrator and cache that the LP sub-app uses.  Both
paths share the same ``pipeline_cache`` singleton.
"""

from __future__ import annotations

import logging
import os
import portalocker
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from auth import get_current_user
from database import (
    attach_document_to_course,
    create_document,
    delete_document,
    get_course,
    get_course_documents,
    get_document,
)
from learning_platform.service import (
    LearningPlatformService,
    get_service,
    stable_doc_id,
)

router: APIRouter = APIRouter(prefix="/api", tags=["documents"])
logger: logging.Logger = logging.getLogger(__name__)

UPLOAD_PATH: str = os.getenv("UPLOAD_PATH", "uploads")
REGISTRY_FILE_NAME: str = "registry.txt"
MAX_UPLOAD_BYTES: int = int(
    os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
)  # 50 MB

_SAFE_FILENAME_RE: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9._-]")


def _sanitize_filename(name: str) -> str:
    """Strip path separators and dangerous characters from an uploaded filename."""
    base: str = Path(name).name
    safe: str = _SAFE_FILENAME_RE.sub("_", base)
    return safe or "unnamed"


# ── Document CRUD ────────────────────────────────────────────────────────────
def register_document(uploaded_file: str) -> None:
    file_path = os.path.join(UPLOAD_PATH, REGISTRY_FILE_NAME)
    if not os.path.exists(file_path):
        with open(file_path, "a", encoding="utf-8"):
            pass  # Just opening in 'a' mode creates it safely

    with open(file_path, "a", encoding="utf-8") as file:
        try:
            portalocker.lock(file, portalocker.LOCK_EX)
            if not uploaded_file.endswith("\n"):
                uploaded_file += "\n"
            file.write(uploaded_file)
            file.flush()
        finally:
            portalocker.unlock(file)


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

    register_document(f"{course_id}/{safe_name}")

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


# ── LP pipeline integration ──────────────────────────────────────────────────


@router.post("/documents/{document_id}/process")
async def process_document(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> JSONResponse:
    """Trigger LP pipeline processing for an uploaded document.

    Resolves the storage path from the DocumentModel and calls the LP
    service directly — no HTTP round-trip, no duplicate app instance.
    The pipeline result is stored in the shared ``pipeline_cache`` under
    ``stable_doc_id(storage_path)`` so all subsequent reads hit the same key.
    """
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_path: str = doc["storage_path"]
    if not Path(storage_path).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {storage_path}")

    try:
        result = await lp.process(storage_path)
    except Exception as exc:
        logger.error("Pipeline failed for document %s: %s", document_id, exc)
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {exc}") from exc

    lp_doc_id = stable_doc_id(storage_path)

    return JSONResponse(
        content={
            "doc_id": lp_doc_id,
            "title": result.document.title,
            "units_count": len(result.units),
            "concepts_count": len(result.concepts.concepts),
            "graph_nodes": len(result.graph.nodes),
            "graph_edges": len(result.graph.edges),
            "lessons": result.study_plan.total_lessons,
            "milestones": len(result.study_plan.milestones),
        },
        status_code=200,
    )


@router.get("/documents/{document_id}/tree")
async def get_document_tree(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> JSONResponse:
    """Return the canonical document tree for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    lp_doc_id = stable_doc_id(doc["storage_path"])
    result = lp.get_cached(lp_doc_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Document not processed — call /process first"
        )

    return JSONResponse(
        content={
            "doc_id": lp_doc_id,
            "title": result.document.title,
            "total_nodes": len(result.document.nodes),
        }
    )


@router.get("/documents/{document_id}/units")
async def get_document_units(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> JSONResponse:
    """Return all learning units for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    lp_doc_id = stable_doc_id(doc["storage_path"])
    result = lp.get_cached(lp_doc_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Document not processed — call /process first"
        )

    return JSONResponse(
        content={
            "doc_id": lp_doc_id,
            "units": [
                {
                    "id": str(u.id),
                    "title": u.title,
                    "unit_type": u.unit_type.value,
                    "difficulty": u.difficulty.value,
                    "estimated_study_time_minutes": u.estimated_study_time_minutes,
                }
                for u in result.units
            ],
            "count": len(result.units),
        }
    )


@router.get("/documents/{document_id}/concepts")
async def get_document_concepts(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> JSONResponse:
    """Return all concepts for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    lp_doc_id = stable_doc_id(doc["storage_path"])
    result = lp.get_cached(lp_doc_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Document not processed — call /process first"
        )

    return JSONResponse(
        content={
            "doc_id": lp_doc_id,
            "concepts": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "category": c.category.value,
                    "importance": c.importance,
                }
                for c in result.concepts.concepts
            ],
            "total_concepts": len(result.concepts.concepts),
            "total_relationships": len(result.concepts.relationships),
        }
    )


@router.get("/documents/{document_id}/study-plan")
async def get_document_study_plan(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> JSONResponse:
    """Return the study plan for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    lp_doc_id = stable_doc_id(doc["storage_path"])
    result = lp.get_cached(lp_doc_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Document not processed — call /process first"
        )

    return JSONResponse(
        content={
            "doc_id": lp_doc_id,
            "title": result.study_plan.title,
            "total_lessons": result.study_plan.total_lessons,
            "total_estimated_minutes": result.study_plan.total_estimated_minutes,
            "milestones": len(result.study_plan.milestones),
        }
    )


@router.get("/documents/{document_id}/export/json")
async def export_document_json(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> JSONResponse:
    """Export all pipeline results as JSON for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    lp_doc_id = stable_doc_id(doc["storage_path"])
    result = lp.get_cached(lp_doc_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Document not processed — call /process first"
        )

    from learning_platform.infrastructure.persistence.exporters.json_exporter import (
        JsonExporter,
    )

    export_dir = Path("exports") / lp_doc_id
    export_dir.mkdir(parents=True, exist_ok=True)
    exporter = JsonExporter(export_dir)
    exporter.export_all(
        document=result.document,
        units=result.units,
        annotations=result.annotations,
        concepts=result.concepts,
        graph=result.graph,
        plan=result.study_plan,
    )

    return JSONResponse(
        content={
            "doc_id": lp_doc_id,
            "export_dir": str(export_dir),
            "files": [
                "document.json",
                "learning_units.json",
                "annotations.json",
                "concepts.json",
                "knowledge_graph.json",
                "study_plan.json",
            ],
        }
    )
