"""API request and response schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

# ── Document Upload ──────────────────────────────────────────────────────────


class DocumentUploadResponse(BaseModel):
    """Response after uploading a document file."""

    doc_id: UUID
    filename: str
    message: str = "Document uploaded successfully"


# ── Document Processing ─────────────────────────────────────────────────────


class DocumentProcessResponse(BaseModel):
    """Response after running the full pipeline on a document."""

    doc_id: UUID
    title: str = ""
    units_count: int = 0
    concepts_count: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0
    lessons: int = 0
    milestones: int = 0
    message: str = "Pipeline completed successfully"


# ── Canonical Document Tree ─────────────────────────────────────────────────


class DocumentTreeNodeResponse(BaseModel):
    """A single node in the canonical document tree."""

    id: UUID
    type: str
    page: int = 0
    level: int = 0
    title: str = ""
    text: str = ""
    children: list[DocumentTreeNodeResponse] = Field(default_factory=list)


class DocumentTreeResponse(BaseModel):
    """The canonical document tree for a processed document."""

    doc_id: UUID
    source: str = ""
    title: str = ""
    total_nodes: int = 0
    root: DocumentTreeNodeResponse | None = None


# ── Learning Units ──────────────────────────────────────────────────────────


class LearningUnitResponse(BaseModel):
    """A single learning unit."""

    id: UUID
    unit_type: str
    title: str
    description: str = ""
    difficulty: str = "basic"
    estimated_study_time_minutes: int = 0
    learning_objectives: list[str] = Field(default_factory=list)
    parent_id: UUID | None = None


class UnitsListResponse(BaseModel):
    """All learning units for a document."""

    doc_id: UUID
    units: list[LearningUnitResponse] = Field(default_factory=list)
    count: int = 0


# ── Concept Graph ───────────────────────────────────────────────────────────


class ConceptResponse(BaseModel):
    """A single concept."""

    id: UUID
    name: str
    category: str
    importance: float = 0.0
    mention_count: int = 0
    aliases: list[str] = Field(default_factory=list)


class ConceptRelationshipResponse(BaseModel):
    """A relationship between two concepts."""

    source_id: UUID
    target_id: UUID
    source_name: str = ""
    target_name: str = ""
    relation_type: str
    weight: float = 1.0


class ConceptGraphResponse(BaseModel):
    """The concept graph for a document."""

    doc_id: UUID
    concepts: list[ConceptResponse] = Field(default_factory=list)
    relationships: list[ConceptRelationshipResponse] = Field(default_factory=list)
    total_concepts: int = 0
    total_relationships: int = 0


# ── Study Plan ──────────────────────────────────────────────────────────────


class LessonResponse(BaseModel):
    """A single lesson in the study plan."""

    id: UUID
    unit_id: UUID
    order: int = 0
    title: str = ""
    description: str = ""
    lesson_type: str = "core"
    difficulty: str = "basic"
    estimated_minutes: int = 0
    milestone_id: UUID | None = None


class MilestoneResponse(BaseModel):
    """A milestone grouping lessons."""

    id: UUID
    order: int = 0
    title: str = ""
    description: str = ""
    estimated_minutes: int = 0
    lesson_count: int = 0


class CheckpointResponse(BaseModel):
    """A checkpoint assessment."""

    id: UUID
    milestone_id: UUID
    order: int = 0
    title: str = ""
    checkpoint_type: str = "self_test"
    estimated_minutes: int = 0


class StudyPlanResponse(BaseModel):
    """The study plan for a document."""

    doc_id: UUID
    title: str = ""
    description: str = ""
    total_estimated_minutes: int = 0
    total_lessons: int = 0
    lessons: list[LessonResponse] = Field(default_factory=list)
    milestones: list[MilestoneResponse] = Field(default_factory=list)
    checkpoints: list[CheckpointResponse] = Field(default_factory=list)


# ── Error ───────────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
