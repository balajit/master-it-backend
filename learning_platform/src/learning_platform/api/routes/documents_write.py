"""Document write routes: upload, process, and enrich."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.api.auth import get_current_user
from learning_platform.api.deps import (
    get_pipeline_orchestrator,
    get_session,
    get_settings_dependency,
)
from learning_platform.api.schemas import DocumentProcessResponse, ErrorResponse
from learning_platform.cache import pipeline_cache
from learning_platform.config import Settings
from learning_platform.pipeline.orchestrator import PipelineOrchestrator
from learning_platform.security import InvalidPathError, sanitize_filename
from learning_platform.service import LearningPlatformService, get_service

from .documents_common import (
    authorize_persisted_document_owner,
    authorize_upload_owner,
    copy_upload_file,
    get_path_class,
    resolve_uploaded_source,
    user_subject,
    write_upload_owner_sub,
)

router = APIRouter()


class UploadResponse(BaseModel):
    """Response for the upload endpoint."""

    doc_id: UUID
    filename: str


class ProcessRequest(BaseModel):
    """Backward-compatible request body for legacy process endpoint."""

    file_path: str


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=201,
    summary="Upload a document file",
    description=(
        "Accept a file upload, store it under a new UUID, and return the "
        "``doc_id`` to use in subsequent pipeline calls."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "No filename provided"},
    },
)
async def upload_document(
    file: UploadFile,
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings_dependency),
) -> UploadResponse:
    """Store the uploaded file and return a stable doc_id."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        safe_filename = sanitize_filename(file.filename)
    except InvalidPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc_id = uuid4()
    owner_sub = user_subject(user)
    path_class = get_path_class()
    upload_base_dir = path_class(settings.upload_path)
    dest_dir = upload_base_dir / str(doc_id)
    await run_in_threadpool(dest_dir.mkdir, parents=True, exist_ok=True)
    await run_in_threadpool(write_upload_owner_sub, dest_dir, owner_sub)
    destination = dest_dir / safe_filename

    await run_in_threadpool(copy_upload_file, file.file, destination)

    return UploadResponse(doc_id=doc_id, filename=safe_filename)


@router.post(
    "/{doc_id}/process",
    response_model=DocumentProcessResponse,
    status_code=200,
    summary="Process a document through the full pipeline",
    description=(
        "Run the complete processing pipeline on a previously uploaded document "
        "(parse, normalize, enrich, build learning units, extract concepts, build "
        "knowledge graph, generate study plan), persist the canonical document, "
        "and return summary counts."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Uploaded file not found"},
        500: {"model": ErrorResponse, "description": "Pipeline error"},
    },
)
async def process_document(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
    service: LearningPlatformService = Depends(get_service),
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),  # type: ignore[assignment]
    settings: Settings = Depends(get_settings_dependency),
) -> DocumentProcessResponse:
    """Run the full pipeline on the file previously uploaded under *doc_id*."""
    path_class = get_path_class()
    upload_base_dir = path_class(settings.upload_path)
    upload_dir = upload_base_dir / str(doc_id)
    upload_dir_exists = await run_in_threadpool(upload_dir.exists)
    if not upload_dir_exists:
        raise HTTPException(status_code=404, detail=f"Uploaded file not found for {doc_id}")

    await run_in_threadpool(authorize_upload_owner, upload_dir, user)
    source_path = await run_in_threadpool(resolve_uploaded_source, upload_dir, doc_id)
    source = str(source_path)

    try:
        result = await service.process(
            source,
            session=session,
            orchestrator=orchestrator,
            doc_id=doc_id,
            owner_sub=user_subject(user),
            dedupe_by_source=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {exc}") from exc

    return DocumentProcessResponse(
        doc_id=doc_id,
        title=result.document.title,
        units_count=len(result.units),
        concepts_count=len(result.concepts.concepts),
        graph_nodes=len(result.graph.nodes),
        graph_edges=len(result.graph.edges),
        lessons=result.study_plan.total_lessons,
        milestones=len(result.study_plan.milestones),
    )


@router.post(
    "/{doc_id}/enrich",
    response_model=DocumentProcessResponse,
    summary="Run enrichment on a document",
    description=(
        "Run the processing pipeline. If the document has already been "
        "processed, returns the cached result."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
        500: {"model": ErrorResponse, "description": "Pipeline error"},
    },
)
async def enrich_document(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
    service: LearningPlatformService = Depends(get_service),
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),  # type: ignore[assignment]
    settings: Settings = Depends(get_settings_dependency),
) -> DocumentProcessResponse:
    """Return cached result if available, otherwise run the full pipeline."""
    await authorize_persisted_document_owner(session, doc_id, user)

    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        return DocumentProcessResponse(
            doc_id=doc_id,
            title=cached.document.title,
            units_count=len(cached.units),
            concepts_count=len(cached.concepts.concepts),
            graph_nodes=len(cached.graph.nodes),
            graph_edges=len(cached.graph.edges),
            lessons=cached.study_plan.total_lessons,
            milestones=len(cached.study_plan.milestones),
            message="Document already processed (cached result)",
        )

    path_class = get_path_class()
    upload_base_dir = path_class(settings.upload_path)
    upload_dir = upload_base_dir / str(doc_id)
    upload_dir_exists = await run_in_threadpool(upload_dir.exists)
    if not upload_dir_exists:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    await run_in_threadpool(authorize_upload_owner, upload_dir, user)
    source_path = await run_in_threadpool(resolve_uploaded_source, upload_dir, doc_id)
    source = str(source_path)

    try:
        result = await service.process(
            source,
            session=session,
            orchestrator=orchestrator,
            doc_id=doc_id,
            owner_sub=user_subject(user),
            dedupe_by_source=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {exc}") from exc

    return DocumentProcessResponse(
        doc_id=doc_id,
        title=result.document.title,
        units_count=len(result.units),
        concepts_count=len(result.concepts.concepts),
        graph_nodes=len(result.graph.nodes),
        graph_edges=len(result.graph.edges),
        lessons=result.study_plan.total_lessons,
        milestones=len(result.study_plan.milestones),
    )
