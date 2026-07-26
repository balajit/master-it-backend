"""Document processing routes — process a file and view canonical results.

The learning platform is modular and oblivious to the owning application.
It works with *file paths* and *canonical documents* only.  It does not
know about courses, uploaded-document entities, or file storage decisions.

The owning application (``src/``) is responsible for:
- Uploading files and creating document records
- Associating documents with courses
- Calling ``POST /process`` with a file path to trigger the pipeline
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.api.auth import get_current_user
from learning_platform.api.deps import get_pipeline_orchestrator, get_session
from learning_platform.api.schemas import (
    CheckpointResponse,
    ConceptGraphResponse,
    ConceptRelationshipResponse,
    ConceptResponse,
    DocumentProcessResponse,
    DocumentTreeNodeResponse,
    DocumentTreeResponse,
    ErrorResponse,
    LearningUnitResponse,
    LessonResponse,
    MilestoneResponse,
    StudyPlanResponse,
    UnitsListResponse,
)
from learning_platform.cache import pipeline_cache
from learning_platform.infrastructure.persistence.repositories.annotation import (
    AnnotationRepository,
)
from learning_platform.infrastructure.persistence.repositories.concept import ConceptRepository
from learning_platform.infrastructure.persistence.repositories.document import DocumentRepository
from learning_platform.infrastructure.persistence.repositories.knowledge_graph import (
    KnowledgeGraphRepository,
)
from learning_platform.infrastructure.persistence.repositories.learning_unit import (
    LearningUnitRepository,
)
from learning_platform.infrastructure.persistence.repositories.sequence import StudyPlanRepository
from learning_platform.models.document import DocumentNode
from learning_platform.pipeline.orchestrator import PipelineOrchestrator

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schema for /process ─────────────────────────────────────────────


class ProcessRequest(BaseModel):
    """Request body for the process endpoint."""

    file_path: str = Field(
        ...,
        description=("Path to the document file, either absolute or relative to the UPLOAD_DIR."),
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _build_tree_node(node: DocumentNode) -> DocumentTreeNodeResponse:
    """Recursively build a tree response from a DocumentNode."""
    content = node.content
    content_type = content.type
    title = ""
    text = ""

    if hasattr(content, "level"):
        title = content_type
    if hasattr(content, "text") and hasattr(content.text, "plain_text"):
        text = content.text.plain_text
    elif hasattr(content, "code"):
        text = content.code[:200]
    elif hasattr(content, "latex"):
        text = content.latex[:200]
    elif hasattr(content, "term"):
        title = content.term
        text = content.definition

    return DocumentTreeNodeResponse(
        id=node.id,
        type=content_type,
        page=node.page,
        level=node.level,
        title=title,
        text=text[:500] if text else "",
        children=[_build_tree_node(child) for child in node.children],
    )


def _resolve_file_path(file_path: str) -> str:
    """Resolve a file path to an absolute path.

    If the path is relative, it is resolved against the UPLOAD_DIR
    environment variable (default ``uploads``).
    """
    p = Path(file_path)
    if p.is_absolute():
        return str(p)
    import os

    upload_dir = Path(os.getenv("UPLOAD_PATH", "uploads"))
    return str(upload_dir / p)


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "/process",
    response_model=DocumentProcessResponse,
    status_code=201,
    summary="Process a document through the full pipeline",
    description=(
        "Accept a file path, run the complete processing pipeline (parse, "
        "normalize, enrich, build learning units, extract concepts, build "
        "knowledge graph, generate study plan), persist the canonical "
        "document, and return summary counts."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file path"},
        500: {"model": ErrorResponse, "description": "Pipeline error"},
    },
)
async def process_document(
    body: ProcessRequest,
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> DocumentProcessResponse:
    """Run the full pipeline on the file at *file_path*."""
    source = _resolve_file_path(body.file_path)
    if not Path(source).exists():
        raise HTTPException(status_code=400, detail=f"File not found: {source}")

    try:
        result = await asyncio.to_thread(orchestrator.run, source)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline failed: {exc}",
        ) from exc

    # Use root node id as the canonical doc id
    root_id = result.document.nodes[0].id if result.document.nodes else None
    doc_id_str = str(root_id) if root_id is not None else "unknown"

    pipeline_cache.set(doc_id_str, result)

    doc_repo = DocumentRepository(session)
    unit_repo = LearningUnitRepository(session)
    ann_repo = AnnotationRepository(session)
    concept_repo = ConceptRepository(session)
    graph_repo = KnowledgeGraphRepository(session)
    plan_repo = StudyPlanRepository(session)

    await doc_repo.save_document(result.document)
    if root_id is not None:
        await unit_repo.save_all_units(result.units, root_id)
        await ann_repo.save_all_annotations(result.annotations, root_id)
        await concept_repo.save_concept_map(result.concepts, root_id)
        await graph_repo.save_graph(result.graph, root_id)
        await plan_repo.save_plan(result.study_plan, root_id)
    await session.commit()

    return DocumentProcessResponse(
        doc_id=root_id or UUID(int=0),
        title=result.document.title,
        units_count=len(result.units),
        concepts_count=len(result.concepts.concepts),
        graph_nodes=len(result.graph.nodes),
        graph_edges=len(result.graph.edges),
        lessons=result.study_plan.total_lessons,
        milestones=len(result.study_plan.milestones),
    )


@router.get(
    "/{doc_id}/tree",
    response_model=DocumentTreeResponse,
    summary="View the canonical document tree",
    description="Return the hierarchical document tree with all nodes.",
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def view_document_tree(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> DocumentTreeResponse:
    """View the canonical document tree for a processed document."""
    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        doc = cached.document
    else:
        repo = DocumentRepository(session)
        doc = await repo.find_document(doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    root_node = doc.nodes[0] if doc.nodes else None
    root_response = _build_tree_node(root_node) if root_node else None

    return DocumentTreeResponse(
        doc_id=doc_id,
        source=doc.source,
        title=doc.title,
        total_nodes=len(doc.nodes),
        root=root_response,
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
) -> DocumentProcessResponse:
    """Run enrichment (or full pipeline if not yet processed)."""
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
    raise HTTPException(
        status_code=404,
        detail=f"Document {doc_id} not found — call /process first",
    )


@router.get(
    "/{doc_id}/units",
    response_model=UnitsListResponse,
    summary="View learning units",
    description="Return all learning units extracted from the document.",
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def view_learning_units(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> UnitsListResponse:
    """View all learning units for a document."""
    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        units = cached.units
    else:
        repo = LearningUnitRepository(session)
        units = await repo.find_by_document(doc_id)
        if not units:
            raise HTTPException(
                status_code=404,
                detail=f"No learning units found for document {doc_id}",
            )

    return UnitsListResponse(
        doc_id=doc_id,
        units=[
            LearningUnitResponse(
                id=u.id,
                unit_type=u.unit_type.value,
                title=u.title,
                description=u.description,
                difficulty=u.difficulty.value,
                estimated_study_time_minutes=u.estimated_study_time_minutes,
                learning_objectives=u.learning_objectives,
                parent_id=u.parent_id,
            )
            for u in units
        ],
        count=len(units),
    )


@router.get(
    "/{doc_id}/concepts",
    response_model=ConceptGraphResponse,
    summary="View the concept graph",
    description="Return all concepts and their relationships.",
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def view_concept_graph(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> ConceptGraphResponse:
    """View the concept graph for a document."""
    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        cmap = cached.concepts
    else:
        repo = ConceptRepository(session)
        cmap = await repo.find_by_document(doc_id)
        if not cmap.concepts:
            raise HTTPException(
                status_code=404,
                detail=f"No concepts found for document {doc_id}",
            )

    name_map = {c.id: c.name for c in cmap.concepts}

    return ConceptGraphResponse(
        doc_id=doc_id,
        concepts=[
            ConceptResponse(
                id=c.id,
                name=c.name,
                category=c.category.value,
                importance=c.importance,
                mention_count=c.mention_count,
                aliases=c.aliases,
            )
            for c in cmap.concepts
        ],
        relationships=[
            ConceptRelationshipResponse(
                source_id=r.source_id,
                target_id=r.target_id,
                source_name=name_map.get(r.source_id, ""),
                target_name=name_map.get(r.target_id, ""),
                relation_type=r.relation_type.value,
                weight=r.weight,
            )
            for r in cmap.relationships
        ],
        total_concepts=len(cmap.concepts),
        total_relationships=len(cmap.relationships),
    )


@router.get(
    "/{doc_id}/study-plan",
    response_model=StudyPlanResponse,
    summary="View the study plan",
    description="Return the structured study plan.",
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def view_study_plan(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> StudyPlanResponse:
    """View the study plan for a document."""
    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        plan = cached.study_plan
    else:
        repo = StudyPlanRepository(session)
        plan = await repo.find_by_document(doc_id)
        if plan is None:
            raise HTTPException(
                status_code=404,
                detail=f"No study plan found for document {doc_id}",
            )

    return StudyPlanResponse(
        doc_id=doc_id,
        title=plan.title,
        description=plan.description,
        total_estimated_minutes=plan.total_estimated_minutes,
        total_lessons=plan.total_lessons,
        lessons=[
            LessonResponse(
                id=l.id,
                unit_id=l.unit_id,
                order=l.order,
                title=l.title,
                description=l.description,
                lesson_type=l.lesson_type.value,
                difficulty=l.difficulty,
                estimated_minutes=l.estimated_minutes,
                milestone_id=l.milestone_id,
            )
            for l in plan.lessons
        ],
        milestones=[
            MilestoneResponse(
                id=m.id,
                order=m.order,
                title=m.title,
                description=m.description,
                estimated_minutes=m.estimated_minutes,
                lesson_count=len(m.lesson_ids),
            )
            for m in plan.milestones
        ],
        checkpoints=[
            CheckpointResponse(
                id=cp.id,
                milestone_id=cp.milestone_id,
                order=cp.order,
                title=cp.title,
                checkpoint_type=cp.checkpoint_type.value,
                estimated_minutes=cp.estimated_minutes,
            )
            for cp in plan.checkpoints
        ],
    )


@router.get(
    "/{doc_id}/export/json",
    summary="Download JSON export",
    description="Export all pipeline results as JSON.",
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def export_json(
    doc_id: UUID,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Download the full pipeline output as JSON."""
    from learning_platform.infrastructure.persistence.exporters.json_exporter import (
        JsonExporter,
    )

    cached = pipeline_cache.get(str(doc_id))
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {doc_id} not found or not processed",
        )

    export_dir = Path("exports") / str(doc_id)
    export_dir.mkdir(parents=True, exist_ok=True)

    exporter = JsonExporter(export_dir)
    exporter.export_all(
        document=cached.document,
        units=cached.units,
        annotations=cached.annotations,
        concepts=cached.concepts,
        graph=cached.graph,
        plan=cached.study_plan,
    )

    return {
        "doc_id": str(doc_id),
        "source": cached.document.source,
        "title": cached.document.title,
        "units_count": len(cached.units),
        "concepts_count": len(cached.concepts.concepts),
        "graph_nodes": len(cached.graph.nodes),
        "lessons": cached.study_plan.total_lessons,
        "files": [
            "document.json",
            "learning_units.json",
            "annotations.json",
            "concepts.json",
            "knowledge_graph.json",
            "study_plan.json",
        ],
        "export_dir": str(export_dir),
    }
