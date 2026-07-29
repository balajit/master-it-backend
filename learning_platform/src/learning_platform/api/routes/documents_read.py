"""Document read routes: tree, units, concepts, study-plan, and export."""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.api.auth import get_current_user
from learning_platform.api.deps import get_session
from learning_platform.api.schemas import (
    CheckpointResponse,
    ConceptGraphResponse,
    ConceptRelationshipResponse,
    ConceptResponse,
    DocumentTreeResponse,
    ErrorResponse,
    LearningUnitResponse,
    LessonResponse,
    MilestoneResponse,
    StudyPlanResponse,
    UnitsListResponse,
)
from learning_platform.cache import pipeline_cache

from .documents_common import (
    authorize_persisted_document_owner,
    build_tree_node,
    get_concept_repository_class,
    get_document_repository_class,
    get_learning_unit_repository_class,
    get_path_class,
    get_study_plan_repository_class,
)

router = APIRouter()


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
    await authorize_persisted_document_owner(session, doc_id, user)

    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        document = cached.document
    else:
        repo_class = get_document_repository_class()
        repo = repo_class(session)
        document = await repo.find_document(doc_id)
        if document is None:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    root_node = document.nodes[0] if document.nodes else None
    root_response = build_tree_node(root_node) if root_node else None

    return DocumentTreeResponse(
        doc_id=doc_id,
        source=document.source,
        title=document.title,
        total_nodes=len(document.nodes),
        root=root_response,
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
    await authorize_persisted_document_owner(session, doc_id, user)

    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        units = cached.units
    else:
        repo_class = get_learning_unit_repository_class()
        repo = repo_class(session)
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
                id=unit.id,
                unit_type=unit.unit_type.value,
                title=unit.title,
                description=unit.description,
                difficulty=unit.difficulty.value,
                estimated_study_time_minutes=unit.estimated_study_time_minutes,
                learning_objectives=unit.learning_objectives,
                parent_id=unit.parent_id,
            )
            for unit in units
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
    await authorize_persisted_document_owner(session, doc_id, user)

    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        concept_map = cached.concepts
    else:
        repo_class = get_concept_repository_class()
        repo = repo_class(session)
        concept_map = await repo.find_by_document(doc_id)
        if not concept_map.concepts:
            raise HTTPException(
                status_code=404,
                detail=f"No concepts found for document {doc_id}",
            )

    name_map = {concept.id: concept.name for concept in concept_map.concepts}

    return ConceptGraphResponse(
        doc_id=doc_id,
        concepts=[
            ConceptResponse(
                id=concept.id,
                name=concept.name,
                category=concept.category.value,
                importance=concept.importance,
                mention_count=concept.mention_count,
                aliases=concept.aliases,
            )
            for concept in concept_map.concepts
        ],
        relationships=[
            ConceptRelationshipResponse(
                source_id=relationship.source_id,
                target_id=relationship.target_id,
                source_name=name_map.get(relationship.source_id, ""),
                target_name=name_map.get(relationship.target_id, ""),
                relation_type=relationship.relation_type.value,
                weight=relationship.weight,
            )
            for relationship in concept_map.relationships
        ],
        total_concepts=len(concept_map.concepts),
        total_relationships=len(concept_map.relationships),
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
    await authorize_persisted_document_owner(session, doc_id, user)

    cached = pipeline_cache.get(str(doc_id))
    if cached is not None:
        plan = cached.study_plan
    else:
        repo_class = get_study_plan_repository_class()
        repo = repo_class(session)
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
                id=lesson.id,
                unit_id=lesson.unit_id,
                order=lesson.order,
                title=lesson.title,
                description=lesson.description,
                lesson_type=lesson.lesson_type.value,
                difficulty=lesson.difficulty,
                estimated_minutes=lesson.estimated_minutes,
                milestone_id=lesson.milestone_id,
            )
            for lesson in plan.lessons
        ],
        milestones=[
            MilestoneResponse(
                id=milestone.id,
                order=milestone.order,
                title=milestone.title,
                description=milestone.description,
                estimated_minutes=milestone.estimated_minutes,
                lesson_count=len(milestone.lesson_ids),
            )
            for milestone in plan.milestones
        ],
        checkpoints=[
            CheckpointResponse(
                id=checkpoint.id,
                milestone_id=checkpoint.milestone_id,
                order=checkpoint.order,
                title=checkpoint.title,
                checkpoint_type=checkpoint.checkpoint_type.value,
                estimated_minutes=checkpoint.estimated_minutes,
            )
            for checkpoint in plan.checkpoints
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
    session: AsyncSession = Depends(get_session),  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Download the full pipeline output as JSON."""
    from learning_platform.infrastructure.persistence.exporters.json_exporter import (
        JsonExporter,
    )

    await authorize_persisted_document_owner(session, doc_id, user)

    cached = pipeline_cache.get(str(doc_id))
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {doc_id} not found or not processed",
        )

    path_class = get_path_class()
    export_dir = path_class(os.getenv("EXPORT_PATH", "exports")) / str(doc_id)
    await run_in_threadpool(export_dir.mkdir, parents=True, exist_ok=True)

    exporter = JsonExporter(export_dir)
    await run_in_threadpool(
        exporter.export_all,
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
