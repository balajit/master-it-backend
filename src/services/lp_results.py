"""Helpers to resolve and load persisted LP pipeline results."""

from __future__ import annotations

from uuid import UUID

from learning_platform.api.deps import get_session_factory
from learning_platform.cache import pipeline_cache
from learning_platform.infrastructure.persistence.repositories.annotation import (
    AnnotationRepository,
)
from learning_platform.infrastructure.persistence.repositories.concept import (
    ConceptRepository,
)
from learning_platform.infrastructure.persistence.repositories.document import (
    DocumentRepository,
)
from learning_platform.infrastructure.persistence.repositories.knowledge_graph import (
    KnowledgeGraphRepository,
)
from learning_platform.infrastructure.persistence.repositories.learning_unit import (
    LearningUnitRepository,
)
from learning_platform.infrastructure.persistence.repositories.sequence import (
    StudyPlanRepository,
)
from learning_platform.models.knowledge_graph import KnowledgeGraph
from learning_platform.models.sequence import StudyPlan
from learning_platform.pipeline.orchestrator import PipelineResult
from learning_platform.service import stable_doc_id


def lp_doc_uuid_from_storage_path(storage_path: str) -> UUID:
    """Return canonical LP UUID for a storage path."""
    return UUID(stable_doc_id(storage_path)[:32])


def lp_doc_uuid_from_external_id(value: str) -> UUID | None:
    """Parse a UUID or SHA-style LP external identifier into a UUID."""
    try:
        return UUID(value)
    except ValueError:
        pass

    if len(value) < 32:
        return None

    try:
        return UUID(value[:32])
    except ValueError:
        return None


def _empty_study_plan() -> StudyPlan:
    return StudyPlan(
        title="",
        description="",
        lessons=[],
        milestones=[],
        checkpoints=[],
        total_estimated_minutes=0,
        total_lessons=0,
    )


def _empty_graph() -> KnowledgeGraph:
    return KnowledgeGraph(nodes=[], edges=[])


async def load_pipeline_result_from_persistence(doc_id: UUID) -> PipelineResult | None:
    """Load a pipeline result from persisted LP artifacts and warm cache."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        doc_repo = DocumentRepository(session)
        unit_repo = LearningUnitRepository(session)
        ann_repo = AnnotationRepository(session)
        concept_repo = ConceptRepository(session)
        graph_repo = KnowledgeGraphRepository(session)
        plan_repo = StudyPlanRepository(session)

        document = await doc_repo.find_document(doc_id)
        if document is None:
            return None

        units = await unit_repo.find_by_document(doc_id)
        annotations = await ann_repo.find_by_document(doc_id)
        concepts = await concept_repo.find_by_document(doc_id)
        graph = await graph_repo.find_by_document(doc_id)
        study_plan = await plan_repo.find_by_document(doc_id)

    result = PipelineResult(
        document=document,
        annotations=annotations,
        units=units,
        concepts=concepts,
        graph=graph or _empty_graph(),
        study_plan=study_plan or _empty_study_plan(),
        pages=[],
        events=[],
        retry_results={},
    )
    pipeline_cache.set(str(doc_id), result)
    return result
