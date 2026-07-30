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

import asyncio
import logging
import os
import portalocker
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy.exc import IntegrityError

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
from schemas import (
    DocumentBookProcess,
    Document,
    DocumentConceptsResponse,
    DocumentConcept,
    DocumentExportResponse,
    DocumentProcessRun,
    DocumentProcessStage,
    DocumentProcessStartResponse,
    DocumentStudyPlanSummary,
    DocumentTreeResponse,
    DocumentUnit,
    DocumentUnitsResponse,
    DocumentUploadResponse,
)
from services.lp_results import (
    load_pipeline_result_from_persistence,
    lp_doc_uuid_from_storage_path,
)

router: APIRouter = APIRouter(prefix="/api", tags=["documents"])
logger: logging.Logger = logging.getLogger(__name__)

UPLOAD_PATH: str = os.getenv("UPLOAD_PATH", "uploads")
REGISTRY_FILE_NAME: str = "registry.txt"
MAX_UPLOAD_BYTES: int = int(
    os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
)  # 50 MB

_SAFE_FILENAME_RE: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9._-]")


async def _load_result_or_404(
    *,
    storage_path: str,
    lp: LearningPlatformService,
) -> Any:
    lp_doc_id = stable_doc_id(storage_path)
    lp_doc_uuid = lp_doc_uuid_from_storage_path(storage_path)

    cached = lp.get_cached(lp_doc_id)
    if cached is not None:
        return cached

    cached = lp.get_cached(str(lp_doc_uuid))
    if cached is not None:
        return cached

    try:
        loaded = await load_pipeline_result_from_persistence(lp_doc_uuid)
    except Exception:
        logger.exception("Failed loading persisted LP result for %s", lp_doc_uuid)
        loaded = None
    if loaded is None:
        raise HTTPException(
            status_code=404, detail="Document not processed — call /process first"
        )
    return loaded


def _sanitize_filename(name: str) -> str:
    """Strip path separators and dangerous characters from an uploaded filename."""
    base: str = Path(name).name
    safe: str = _SAFE_FILENAME_RE.sub("_", base)
    return safe or "unnamed"


def _relative_source(storage_path: str) -> str:
    """Compute an upload-root relative source path used by LP queue rows."""
    resolved_storage = Path(storage_path).resolve()
    resolved_upload_root = Path(UPLOAD_PATH).resolve()
    try:
        return resolved_storage.relative_to(resolved_upload_root).as_posix()
    except ValueError:
        return resolved_storage.name


async def _ensure_lp_document_process(storage_path: str) -> tuple[Any, bool]:
    """Ensure an LP queue row exists for *storage_path*.

    Returns (row, already_started).
    """
    from learning_platform.api.deps import get_session_factory
    from learning_platform.infrastructure.persistence.repositories.document_process import (
        DocumentProcessRepository,
    )

    resolved_storage_path = str(Path(storage_path).resolve())
    source = _relative_source(storage_path)

    session_factory = get_session_factory()
    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        existing = await repo.find_active_by_abs_path(resolved_storage_path)
        if existing is not None:
            return existing, True

        latest = await repo.find_latest_by_abs_path(resolved_storage_path)
        if latest is not None:
            return latest, True

        try:
            created = await repo.create_entry(
                source=source, abs_path=resolved_storage_path
            )
            await session.commit()
            return created, False
        except IntegrityError:
            await session.rollback()
            active = await repo.find_active_by_abs_path(resolved_storage_path)
            if active is not None:
                return active, True
            raise


async def _retry_lp_document_process(storage_path: str) -> Any:
    """Create a new pending LP queue row for explicit retry of a failed run."""
    from learning_platform.api.deps import get_session_factory
    from learning_platform.infrastructure.persistence.repositories.document_process import (
        DocumentProcessRepository,
    )

    resolved_storage_path = str(Path(storage_path).resolve())

    session_factory = get_session_factory()
    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        active = await repo.find_active_by_abs_path(resolved_storage_path)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail="Document processing is already pending or in progress",
            )

        latest = await repo.find_latest_by_abs_path(resolved_storage_path)
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail="Document processing has not been started for this document",
            )

        if latest.status != "failed":
            raise HTTPException(
                status_code=409,
                detail="Retry is only allowed when processing is failed",
            )

        try:
            retry_row = await repo.create_retry_entry(latest)
            await session.commit()
            return retry_row
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Document processing is already pending or in progress",
            ) from exc


async def _reprocess_lp_document_process(storage_path: str) -> Any:
    """Create a new pending LP queue row for explicit reprocessing."""
    from learning_platform.api.deps import get_session_factory
    from learning_platform.infrastructure.persistence.repositories.document_process import (
        DocumentProcessRepository,
    )

    resolved_storage_path = str(Path(storage_path).resolve())
    session_factory = get_session_factory()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        active = await repo.find_active_by_abs_path(resolved_storage_path)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail="Document processing is already pending or in progress",
            )

        latest = await repo.find_latest_by_abs_path(resolved_storage_path)
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail="Document processing has not been started for this document",
            )

        if latest.status not in {"completed", "failed"}:
            raise HTTPException(
                status_code=409,
                detail="Document processing is not eligible for reprocess",
            )

        try:
            reprocess_row = await repo.create_reprocess_entry(latest)
            await session.commit()
            return reprocess_row
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Document processing is already pending or in progress",
            ) from exc


async def _kickoff_lp_processing() -> None:
    """Kick the LP poller once so queued work starts quickly."""
    from learning_platform.api.app import get_poller_instance

    poller = get_poller_instance()
    if poller is None:
        return

    try:
        await poller._process_pending()
    except Exception:
        logger.exception("Failed to trigger LP processing kick")


def _can_retry_from_status(status: str) -> bool:
    """Return whether explicit user retry is currently allowed."""
    return status == "failed"


def _combined_status(
    process_status: str,
    book_status: str | None,
) -> str:
    """Collapse primary+book statuses into a single user-facing status."""
    if book_status == "failed":
        return "failed"
    if book_status in {"pending", "processing"}:
        return "processing"
    return process_status


def _message_for_started_process(
    status: str,
    process_status: str,
    book_status: str | None,
) -> str:
    """Build user-facing message for already-started process calls."""
    if process_status == "completed" and book_status in {"pending", "processing"}:
        return "Primary pipeline completed; book pipeline is still running"
    if book_status == "failed" or (
        process_status == "completed" and status == "failed"
    ):
        return "Book pipeline failed; call /process/retry to retry"
    if status == "completed":
        return "Document processing already completed"
    if status == "failed":
        return "Document processing failed; call /process/retry to retry"
    return "Document processing already started"


def _format_datetime(value: Any) -> str:
    """Format datetime-like values to ISO string for API output."""
    if value is None:
        return ""
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    return str(value)


async def _load_pipeline_stage_details(process_id: int) -> List[DocumentProcessStage]:
    """Load persisted pipeline stage records for a process id."""
    from learning_platform.api.deps import get_session_factory
    from learning_platform.infrastructure.persistence.models.pipeline_log import (
        PipelineLogRow,
    )
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(PipelineLogRow)
                    .where(PipelineLogRow.document_process_id == process_id)
                    .order_by(PipelineLogRow.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    return [
        DocumentProcessStage(
            stage=str(row.stage),
            result=str(row.result),
            output=str(row.output or ""),
            created_at=_format_datetime(row.created_at),
        )
        for row in rows
    ]


async def _load_process_runs(abs_path: str) -> List[DocumentProcessRun]:
    """Load all process runs for this file path with grouped stages."""
    from learning_platform.api.deps import get_session_factory
    from learning_platform.infrastructure.persistence.models.pipeline_log import (
        PipelineLogRow,
    )
    from learning_platform.infrastructure.persistence.repositories.document_process import (
        DocumentProcessRepository,
    )
    from sqlalchemy import select

    session_factory = get_session_factory()
    runs: List[DocumentProcessRun] = []

    async with session_factory() as session:
        proc_repo = DocumentProcessRepository(session)
        rows = (
            (
                await session.execute(
                    select(proc_repo.model_class)
                    .where(proc_repo.model_class.abs_path == abs_path)
                    .order_by(proc_repo.model_class.id.asc())
                )
            )
            .scalars()
            .all()
        )

        for row in rows:
            stage_rows = (
                (
                    await session.execute(
                        select(PipelineLogRow)
                        .where(PipelineLogRow.document_process_id == row.id)
                        .order_by(PipelineLogRow.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )

            stages = [
                DocumentProcessStage(
                    stage=str(stage_row.stage),
                    result=str(stage_row.result),
                    output=str(stage_row.output or ""),
                    created_at=_format_datetime(stage_row.created_at),
                )
                for stage_row in stage_rows
            ]
            if not stages:
                stages = [
                    DocumentProcessStage(
                        stage="pipeline",
                        result=str(row.status),
                        output=str(row.error_message or ""),
                        created_at=_format_datetime(row.updated_at),
                    )
                ]

            runs.append(
                DocumentProcessRun(
                    process_id=int(row.id),
                    run_mode=str(getattr(row, "run_mode", "process") or "process"),
                    status=str(row.status),
                    retry_count=int(row.retry_count),
                    max_retries=int(row.max_retries),
                    error_message=(
                        str(row.error_message)
                        if row.error_message is not None
                        else None
                    ),
                    created_at=_format_datetime(row.created_at),
                    updated_at=_format_datetime(row.updated_at),
                    stages=stages,
                )
            )

    return runs


async def _load_book_process_summary(lp_doc_id: str) -> DocumentBookProcess | None:
    """Load current book pipeline process summary for a document id."""
    from learning_platform.api.deps import get_session_factory
    from learning_platform.infrastructure.persistence.repositories.book_process import (
        BookProcessRepository,
    )

    session_factory = get_session_factory()
    async with session_factory() as session:
        repo = BookProcessRepository(session)
        row = await repo.find_by_document_id(lp_doc_id)
        if row is None:
            from uuid import UUID

            try:
                canonical_uuid_id = str(UUID(lp_doc_id[:32]))
            except Exception:
                canonical_uuid_id = ""
            if canonical_uuid_id:
                row = await repo.find_by_document_id(canonical_uuid_id)

    if row is None:
        return None

    return DocumentBookProcess(
        status=str(row.status),
        retry_count=int(row.retry_count),
        max_retries=int(row.max_retries),
        error_message=str(row.error_message) if row.error_message is not None else None,
        updated_at=_format_datetime(row.updated_at),
    )


async def _build_process_start_response(
    *,
    document_id: str,
    storage_path: str,
    process_row: Any,
    already_started: bool,
    message: str,
) -> DocumentProcessStartResponse:
    """Build a kickoff response with persisted stage/book details."""
    lp_doc_id = stable_doc_id(storage_path)
    response_message = message
    status: str = str(process_row.status)
    pipeline_stages: List[DocumentProcessStage] = []
    process_runs: List[DocumentProcessRun] = []
    book_pipeline: DocumentBookProcess | None = None

    try:
        pipeline_stages = await _load_pipeline_stage_details(int(process_row.id))
    except Exception:
        logger.exception(
            "Failed loading pipeline stages for process_id=%s",
            getattr(process_row, "id", ""),
        )

    try:
        process_runs = await _load_process_runs(str(process_row.abs_path))
    except Exception:
        logger.exception(
            "Failed loading process runs for abs_path=%s",
            getattr(process_row, "abs_path", ""),
        )

    try:
        book_pipeline = await _load_book_process_summary(lp_doc_id)
    except Exception:
        logger.exception(
            "Failed loading book pipeline summary for lp_doc_id=%s", lp_doc_id
        )

    if book_pipeline is not None:
        status = _combined_status(status, book_pipeline.status)

    default_stage = DocumentProcessStage(
        stage="pipeline",
        result=str(getattr(process_row, "status", "pending")),
        output=str(getattr(process_row, "error_message", "") or ""),
        created_at=_format_datetime(getattr(process_row, "updated_at", "")),
    )

    if not pipeline_stages:
        pipeline_stages = [default_stage]

    if not process_runs:
        process_runs = [
            DocumentProcessRun(
                process_id=int(process_row.id),
                run_mode=str(getattr(process_row, "run_mode", "process") or "process"),
                status=str(getattr(process_row, "status", "pending")),
                retry_count=int(getattr(process_row, "retry_count", 0)),
                max_retries=int(getattr(process_row, "max_retries", 3)),
                error_message=(
                    str(getattr(process_row, "error_message", ""))
                    if getattr(process_row, "error_message", None) is not None
                    else None
                ),
                created_at=_format_datetime(getattr(process_row, "created_at", "")),
                updated_at=_format_datetime(getattr(process_row, "updated_at", "")),
                stages=[default_stage],
            )
        ]

    latest_process_run = process_runs[-1]

    if (
        book_pipeline is not None
        and str(getattr(process_row, "status", "")) == "completed"
        and status == "processing"
    ):
        response_message = "Primary pipeline completed; book pipeline is still running"
    elif (
        book_pipeline is not None
        and str(getattr(process_row, "status", "")) == "completed"
        and status == "failed"
    ):
        response_message = "Book pipeline failed; call /process/retry to retry"

    return DocumentProcessStartResponse(
        document_id=document_id,
        lp_doc_id=lp_doc_id,
        status=status,
        already_started=already_started,
        can_retry=_can_retry_from_status(status),
        message=response_message,
        latest_process_run=latest_process_run,
        process_runs=process_runs,
        book_pipeline=book_pipeline,
    )


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


@router.post(
    "/courses/{course_id}/documents",
    status_code=201,
    response_model=DocumentUploadResponse,
)
async def upload_document(
    course_id: int,
    file: UploadFile,
    user: Dict[str, Any] = Depends(get_current_user),
) -> DocumentUploadResponse:
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
    return DocumentUploadResponse(**doc)


@router.get("/courses/{course_id}/documents", response_model=List[Document])
async def list_course_documents(
    course_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
) -> List[Document]:
    """List all documents associated with a course."""
    course: Dict[str, Any] | None = await get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    docs: List[Dict[str, Any]] = await get_course_documents(course_id)
    return [Document(**d) for d in docs]


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


@router.post(
    "/documents/{document_id}/process",
    response_model=DocumentProcessStartResponse,
    status_code=202,
)
async def process_document(
    document_id: str,
    response: Response,
    user: Dict[str, Any] = Depends(get_current_user),
) -> DocumentProcessStartResponse:
    """Start LP processing if needed and return queue status immediately."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_path: str = doc["storage_path"]
    if not Path(storage_path).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {storage_path}")

    try:
        process_row, already_started = await _ensure_lp_document_process(storage_path)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to enqueue document %s for processing: %s", document_id, exc
        )
        raise HTTPException(
            status_code=500, detail="Failed to start processing"
        ) from exc

    if already_started:
        response.status_code = 200
    else:
        asyncio.create_task(_kickoff_lp_processing())

    process_status: str = str(process_row.status)
    lp_doc_id: str = stable_doc_id(storage_path)
    book_summary: DocumentBookProcess | None = None
    try:
        book_summary = await _load_book_process_summary(lp_doc_id)
    except Exception:
        logger.exception(
            "Failed loading book pipeline summary for lp_doc_id=%s", lp_doc_id
        )

    status: str = _combined_status(
        process_status,
        book_summary.status if book_summary is not None else None,
    )

    if already_started:
        message = _message_for_started_process(
            status,
            process_status,
            book_summary.status if book_summary is not None else None,
        )
    else:
        message = "Document processing started"

    return await _build_process_start_response(
        document_id=document_id,
        storage_path=storage_path,
        process_row=process_row,
        already_started=already_started,
        message=message,
    )


@router.post(
    "/documents/{document_id}/process/retry",
    response_model=DocumentProcessStartResponse,
    status_code=202,
)
async def retry_document_processing(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> DocumentProcessStartResponse:
    """Explicitly retry a failed document processing job."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_path: str = doc["storage_path"]
    if not Path(storage_path).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {storage_path}")

    try:
        process_row = await _retry_lp_document_process(storage_path)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to retry document %s processing: %s", document_id, exc)
        raise HTTPException(
            status_code=500, detail="Failed to retry processing"
        ) from exc

    asyncio.create_task(_kickoff_lp_processing())

    return await _build_process_start_response(
        document_id=document_id,
        storage_path=storage_path,
        process_row=process_row,
        already_started=False,
        message="Document processing retry started",
    )


@router.post(
    "/documents/{document_id}/process/reprocess",
    response_model=DocumentProcessStartResponse,
    status_code=202,
)
async def reprocess_document(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
) -> DocumentProcessStartResponse:
    """Explicitly reprocess a previously finished document processing job."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    storage_path: str = doc["storage_path"]
    if not Path(storage_path).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {storage_path}")

    try:
        process_row = await _reprocess_lp_document_process(storage_path)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to reprocess document %s: %s", document_id, exc)
        raise HTTPException(
            status_code=500, detail="Failed to reprocess document"
        ) from exc

    asyncio.create_task(_kickoff_lp_processing())

    return await _build_process_start_response(
        document_id=document_id,
        storage_path=storage_path,
        process_row=process_row,
        already_started=False,
        message="Document reprocessing started",
    )


@router.get("/documents/{document_id}/tree", response_model=DocumentTreeResponse)
async def get_document_tree(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> DocumentTreeResponse:
    """Return the canonical document tree for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await _load_result_or_404(storage_path=doc["storage_path"], lp=lp)
    lp_doc_id = stable_doc_id(doc["storage_path"])

    return DocumentTreeResponse(
        doc_id=lp_doc_id,
        title=result.document.title,
        total_nodes=len(result.document.nodes),
    )


@router.get("/documents/{document_id}/units", response_model=DocumentUnitsResponse)
async def get_document_units(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> DocumentUnitsResponse:
    """Return all learning units for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await _load_result_or_404(storage_path=doc["storage_path"], lp=lp)
    lp_doc_id = stable_doc_id(doc["storage_path"])

    return DocumentUnitsResponse(
        doc_id=lp_doc_id,
        units=[
            DocumentUnit(
                id=str(u.id),
                title=u.title,
                unit_type=u.unit_type.value,
                difficulty=u.difficulty.value,
                estimated_study_time_minutes=u.estimated_study_time_minutes,
            )
            for u in result.units
        ],
        count=len(result.units),
    )


@router.get(
    "/documents/{document_id}/concepts", response_model=DocumentConceptsResponse
)
async def get_document_concepts(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> DocumentConceptsResponse:
    """Return all concepts for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await _load_result_or_404(storage_path=doc["storage_path"], lp=lp)
    lp_doc_id = stable_doc_id(doc["storage_path"])

    return DocumentConceptsResponse(
        doc_id=lp_doc_id,
        concepts=[
            DocumentConcept(
                id=str(c.id),
                name=c.name,
                category=c.category.value,
                importance=c.importance,
            )
            for c in result.concepts.concepts
        ],
        total_concepts=len(result.concepts.concepts),
        total_relationships=len(result.concepts.relationships),
    )


@router.get(
    "/documents/{document_id}/study-plan",
    response_model=DocumentStudyPlanSummary,
)
async def get_document_study_plan(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> DocumentStudyPlanSummary:
    """Return the study plan summary for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await _load_result_or_404(storage_path=doc["storage_path"], lp=lp)
    lp_doc_id = stable_doc_id(doc["storage_path"])

    return DocumentStudyPlanSummary(
        doc_id=lp_doc_id,
        title=result.study_plan.title,
        total_lessons=result.study_plan.total_lessons,
        total_estimated_minutes=result.study_plan.total_estimated_minutes,
        milestones=len(result.study_plan.milestones),
    )


@router.get(
    "/documents/{document_id}/export/json",
    response_model=DocumentExportResponse,
)
async def export_document_json(
    document_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    lp: LearningPlatformService = Depends(get_service),
) -> DocumentExportResponse:
    """Export all pipeline results as JSON for a processed document."""
    doc: Dict[str, Any] | None = await get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await _load_result_or_404(storage_path=doc["storage_path"], lp=lp)
    lp_doc_id = stable_doc_id(doc["storage_path"])

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

    return DocumentExportResponse(
        doc_id=lp_doc_id,
        export_dir=str(export_dir),
        files=[
            "document.json",
            "learning_units.json",
            "annotations.json",
            "concepts.json",
            "knowledge_graph.json",
            "study_plan.json",
        ],
    )
