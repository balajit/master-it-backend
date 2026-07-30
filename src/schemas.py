from __future__ import annotations

import enum
from datetime import datetime
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

from learning_platform.presentation.models import ContentNode


class TokenPayload(BaseModel):
    id_token: str


class LocalRegister(BaseModel):
    email: EmailStr
    password: str
    name: str = ""
    phone: str = ""


class LocalLogin(BaseModel):
    email: EmailStr
    password: str


class Permission(BaseModel):
    id: int
    name: str


class Role(BaseModel):
    id: int
    name: str
    permissions: list[Permission]


class RoleList(BaseModel):
    roles: list[Role]


class CourseCreate(BaseModel):
    title: str
    description: str
    number_of_credits: int
    difficulty: str
    status: Literal["OPEN", "CLOSED", "COMING_SOON"] = "COMING_SOON"


class Course(BaseModel):
    id: int
    title: str
    description: str
    number_of_credits: int
    difficulty: str
    status: Literal["OPEN", "CLOSED", "COMING_SOON"]
    owner_id: int


class GrantPermission(BaseModel):
    role_name: str
    permission_names: List[str]


class CreatePermission(BaseModel):
    name: str


class RevokePermission(BaseModel):
    role_name: str
    permission_name: str


class AssignRole(BaseModel):
    role_name: str


class UserProfile(BaseModel):
    id: int
    email: str
    name: str
    picture_url: str
    phone: str
    auth_provider: str
    roles: List[Role]


class Document(BaseModel):
    id: str
    filename: str
    storage_path: str
    content_type: str
    size_bytes: int
    created_at: str


# ── Study Plan — Book-structured API ────────────────────────────────────────
# The study plan is now structured as: Course → Chapter → Lesson → Page → Item
# Each entity carries a stable UUID from the LP book pipeline.
# Content items are typed so the frontend can apply the correct HTML renderer.


class TextItem(BaseModel):
    type: Literal["text"] = "text"
    id: str
    order: int = 0
    content: str = ""
    level: int = 0
    bbox: Optional[dict] = None
    style: Optional[dict] = None


class HeadingItem(BaseModel):
    type: Literal["heading"] = "heading"
    id: str
    order: int = 0
    content: str = ""
    level: int = 1
    bbox: Optional[dict] = None
    style: Optional[dict] = None


class ImageItem(BaseModel):
    type: Literal["image"] = "image"
    id: str
    order: int = 0
    data: str = ""  # base64-encoded
    caption: Optional[str] = None
    bbox: Optional[dict] = None


class TableItem(BaseModel):
    type: Literal["table"] = "table"
    id: str
    order: int = 0
    caption: Optional[str] = None
    headers: List[str] = []
    rows: List[List[str]] = []
    bbox: Optional[dict] = None
    style: Optional[dict] = None


class EquationItem(BaseModel):
    type: Literal["equation"] = "equation"
    id: str
    order: int = 0
    latex: str = ""
    label: Optional[str] = None
    bbox: Optional[dict] = None


class CodeItem(BaseModel):
    type: Literal["code"] = "code"
    id: str
    order: int = 0
    content: str = ""
    language: Optional[str] = None
    bbox: Optional[dict] = None


class ListItem(BaseModel):
    type: Literal["list"] = "list"
    id: str
    order: int = 0
    ordered: bool = False
    items: List[str] = []
    bbox: Optional[dict] = None
    style: Optional[dict] = None


ContentItem = Annotated[
    TextItem | HeadingItem | ImageItem | TableItem | EquationItem | CodeItem | ListItem,
    Field(discriminator="type"),
]


class Page(BaseModel):
    """A page within a lesson — contains ordered content items."""

    id: str
    page_number: int = 0
    order: int = 0
    items: List[ContentItem] = []


class Lesson(BaseModel):
    """A lesson within a chapter — contains ordered pages."""

    id: str
    title: str = ""
    order: int = 0
    pages: List[Page] = []
    lesson_id: Optional[int] = None  # master-it LessonModel.id; None if not provisioned
    unit_id: Optional[int] = None  # master-it UnitModel.id; None if not provisioned


class Chapter(BaseModel):
    """A chapter within a course — contains ordered lessons."""

    id: str
    title: str = ""
    order: int = 0
    lessons: List[Lesson] = []
    unit_id: Optional[int] = None  # master-it UnitModel.id for this chapter's content


class CourseStudyPlanResponse(BaseModel):
    """Response for GET /api/courses/{course_id}/study-plan."""

    course_id: int
    course_title: str = ""
    chapters: List[Chapter] = []


# ── Study Plan legacy aliases (kept for backward-compat while old tests exist)
# TODO: remove once all callers are migrated to the new schema
StudyPlanLesson = Lesson
StudyPlanMilestone = Chapter
StudyPlanCheckpoint = Page
StudyPlanDetail = CourseStudyPlanResponse


# ── Learning Domain ─────────────────────────────────────────────────────────


class UnitCreate(BaseModel):
    title: str
    description: str = ""
    display_order: int = 0


class UnitUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    display_order: int | None = None


class UnitCrudResponse(BaseModel):
    """Response for unit CRUD operations — used by learning router."""

    id: int
    course_id: int
    title: str
    description: str
    display_order: int
    created_at: str
    updated_at: str


class SectionCreate(BaseModel):
    title: str
    estimated_minutes: int = 0
    display_order: int = 0


class SectionUpdate(BaseModel):
    title: str | None = None
    estimated_minutes: int | None = None
    display_order: int | None = None


class SectionCrudResponse(BaseModel):
    """Response for section CRUD operations — used by learning router."""

    id: int
    unit_id: int
    title: str
    estimated_minutes: int
    display_order: int
    created_at: str
    updated_at: str


class LessonCreate(BaseModel):
    title: str
    description: str = ""
    duration_minutes: int = 0
    display_order: int = 0


class LessonUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    display_order: int | None = None


class LessonCrudResponse(BaseModel):
    """Response for lesson CRUD operations — used by learning router."""

    id: int
    section_id: int
    title: str
    description: str
    duration_minutes: int
    display_order: int
    created_at: str
    updated_at: str


class PracticeCreate(BaseModel):
    title: str
    required_correct: int = 0
    total_questions: int = 0
    display_order: int = 0


class PracticeUpdate(BaseModel):
    title: str | None = None
    required_correct: int | None = None
    total_questions: int | None = None
    display_order: int | None = None


class PracticeCrudResponse(BaseModel):
    """Response for practice CRUD operations — used by learning router."""

    id: int
    section_id: int
    title: str
    required_correct: int
    total_questions: int
    display_order: int
    created_at: str
    updated_at: str


class QuizCreate(BaseModel):
    title: str


class QuizUpdate(BaseModel):
    title: str | None = None


class QuizCrudResponse(BaseModel):
    """Response for quiz CRUD operations — used by learning router."""

    id: int
    section_id: int
    title: str
    created_at: str
    updated_at: str


class SectionDetailResponse(BaseModel):
    """Section with nested children — used by learning router."""

    id: int
    unit_id: int
    title: str
    estimated_minutes: int
    display_order: int
    created_at: str
    updated_at: str
    lessons: List[LessonCrudResponse] = []
    practices: List[PracticeCrudResponse] = []
    quizzes: List[QuizCrudResponse] = []


# ── V1 API ─────────────────────────────────────────────────────────────────


class V1ErrorResponse(BaseModel):
    detail: str
    status_code: int


class PracticeSubmitRequest(BaseModel):
    answers: List[int] = []
    score: float = 0.0


class QuizSubmitRequest(BaseModel):
    answers: List[int] = []
    score: float = 0.0


class PracticeSubmitResponse(BaseModel):
    practice_id: int
    score: float
    passed: bool
    attempts: int
    best_score: float
    status: str


class QuizSubmitResponse(BaseModel):
    quiz_id: int
    score: float
    passed: bool
    completed_at: str


class UserLessonProgressUpdate(BaseModel):
    status: str
    completed_at: str | None = None


class UserPracticeProgressUpdate(BaseModel):
    attempts: int = 0
    best_score: float = 0.0
    status: str = "NOT_STARTED"


class UserQuizProgressUpdate(BaseModel):
    score: float | None = None
    completed_at: str | None = None


class UserLessonProgressResponse(BaseModel):
    """Response for user lesson progress — used by learning router."""

    user_id: int
    lesson_id: int
    status: str
    completed_at: str | None = None


class UserPracticeProgressResponse(BaseModel):
    """Response for user practice progress — used by learning router."""

    user_id: int
    practice_id: int
    attempts: int
    best_score: float
    status: str


class UserQuizProgressResponse(BaseModel):
    """Response for user quiz progress — used by learning router."""

    user_id: int
    quiz_id: int
    score: float | None = None
    completed_at: str | None = None


# ── Progress ────────────────────────────────────────────────────────────────


class ProgressStatus(str, enum.Enum):
    MASTERED = "mastered"
    PRACTICED = "practiced"
    FAMILIAR = "familiar"
    ATTEMPTED = "attempted"
    NOT_STARTED = "not_started"
    LOCKED = "locked"


class ProgressStats(BaseModel):
    total_items: int = 0
    completed: int = 0
    practiced: int = 0
    familiar: int = 0
    attempted: int = 0
    not_started: int = 0
    locked: int = 0
    mastery_pct: float = 0.0


# ── Learning Response Serializers ──────────────────────────────────────────
# Frontend-facing models — clean, flat naming.
# Hierarchy: Unit → Progress + About + Sections → Lessons, Practices, Goals


class GoalResponse(BaseModel):
    """A quiz/goal within a section — renamed from QuizWithProgress."""

    id: int
    title: str
    description: str = ""  # TODO: derive from db column once added
    score: Optional[float] = None
    completed_at: Optional[str] = None
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    activity_type: str = "quiz"  # TODO: derive from db column once added
    locked: bool = False
    action_label: str = "Start"  # "Start" | "Continue" | "Review"


class LessonResponse(BaseModel):
    """A lesson within a section — clean response serializer."""

    id: int
    title: str
    description: str
    duration_minutes: int
    duration_label: str = ""  # e.g. "5 min", "1 hr 10 min" — computed, not stored
    order: int
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    completed_at: Optional[str] = None
    sidebar_status: str = "not_started"  # "completed" | "in_progress" | "not_started"
    content: List[ContentNode] = []
    has_notes: bool = False
    has_flashcards: bool = False


class PracticeResponse(BaseModel):
    """A practice activity within a section — clean response serializer."""

    id: int
    title: str
    description: str = ""  # TODO: derive from db column once added
    required_correct: int
    total_questions: int
    order: int
    status: ProgressStatus = ProgressStatus.NOT_STARTED
    attempts: int = 0
    best_score: float = 0.0
    activity_type: str = "practice"  # "practice" | "project" | "self_test"
    locked: bool = False
    progress_label: str = ""  # e.g. "Score 12/15 to pass"
    action_label: str = "Start"  # "Start" | "Continue" | "Review"
    sidebar_status: str = "not_started"  # "completed" | "in_progress" | "not_started"


class ProgressSquareResponse(BaseModel):
    """A single square in the progress grid."""

    id: int
    title: str
    section_id: int
    section_title: str
    order: int
    status: ProgressStatus


class ProgressResponse(BaseModel):
    """Aggregated progress for the unit."""

    total: int = 0
    completed: int = 0
    mastered_pct: float = 0.0
    squares: List[ProgressSquareResponse] = []


class SectionResponse(BaseModel):
    """A section containing lessons, practices, and goals."""

    id: int
    title: str
    estimated_minutes: int
    order: int
    lessons: List[LessonResponse] = []
    practices: List[PracticeResponse] = []
    goals: List[GoalResponse] = []


class UnitResponse(BaseModel):
    """Top-level unit study page response — clean serializer for frontend."""

    id: int
    title: str
    description: str
    course_id: int
    progress: ProgressResponse
    about: str
    total_lessons: int = 0  # count of all lessons across all sections
    total_minutes: int = 0  # sum of all lesson duration_minutes
    sections: List[SectionResponse] = []
    has_notes: bool = False
    has_flashcards: bool = False


# ── Unit Summary (lightweight listing for study page nav) ──────────────────


class UnitSummary(BaseModel):
    """Lightweight unit listing item for the study page navigation."""

    id: int
    title: str
    description: str
    display_order: int
    total_sections: int = 0
    estimated_minutes: int = 0


# ── Resume ─────────────────────────────────────────────────────────────────


class ResumeResponse(BaseModel):
    """The lesson to resume for a given course — most recently accessed."""

    lesson_id: Optional[int] = None  # None if the user has no progress in this course
    unit_id: Optional[int] = None  # The unit that contains the lesson


# ── Enrollment ──────────────────────────────────────────────────────────────


class EnrollRequest(BaseModel):
    """Request body for course enrollment.

    source_document_id: if provided, the learning content (units/sections/lessons)
    will be generated from the corresponding study plan before progress is initialized.
    Leave None when the course content already exists in the learning hierarchy.
    """

    source_document_id: Optional[str] = None


class EnrollResponse(BaseModel):
    """Response from a successful enrollment or idempotent re-enroll."""

    course_id: int
    user_id: int
    enrolled_at: str
    # "enrolled" on first enrollment, "already_enrolled" on subsequent calls
    status: str
    lessons_initialized: int = 0
    practices_initialized: int = 0
    quizzes_initialized: int = 0


# ── Section Unlock ──────────────────────────────────────────────────────────


class SectionUnlockRequest(BaseModel):
    """Instructor request to manually unlock a section for a specific student."""

    user_id: int


# ── Notes ───────────────────────────────────────────────────────────────────


class NoteCreate(BaseModel):
    """Create a user note attached to exactly one unit or lesson."""

    content: str
    unit_id: Optional[int] = None
    lesson_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_target(self) -> NoteCreate:
        set_count = sum([self.unit_id is not None, self.lesson_id is not None])
        if set_count != 1:
            raise ValueError("Exactly one of unit_id or lesson_id must be provided.")
        return self


class NoteUpdate(BaseModel):
    content: str


class NoteResponse(BaseModel):
    id: int
    content: str
    unit_id: Optional[int] = None
    lesson_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ── Flashcards ───────────────────────────────────────────────────────────────


class FlashcardCreate(BaseModel):
    """Create a flashcard with user or course scope.

    Exactly one of course_id, unit_id, lesson_id must be set.
    scope='course' requires course_id; scope='user' requires unit_id or lesson_id.
    """

    front: str
    back: str
    scope: Literal["user", "course"]
    course_id: Optional[int] = None
    unit_id: Optional[int] = None
    lesson_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_scope_and_target(self) -> FlashcardCreate:
        set_count = sum(
            [
                self.course_id is not None,
                self.unit_id is not None,
                self.lesson_id is not None,
            ]
        )
        if set_count != 1:
            raise ValueError(
                "Exactly one of course_id, unit_id, or lesson_id must be provided."
            )
        if self.scope == "course" and self.course_id is None:
            raise ValueError("scope='course' requires course_id.")
        if self.scope == "user" and self.course_id is not None:
            raise ValueError("scope='user' cannot use course_id.")
        return self


class FlashcardUpdate(BaseModel):
    """Update front and/or back of a flashcard. At least one field required."""

    front: Optional[str] = None
    back: Optional[str] = None

    @model_validator(mode="after")
    def validate_at_least_one(self) -> FlashcardUpdate:
        if self.front is None and self.back is None:
            raise ValueError("At least one of front or back must be provided.")
        return self


class FlashcardResponse(BaseModel):
    id: int
    front: str
    back: str
    user_id: Optional[int] = None
    created_by: int
    course_id: Optional[int] = None
    unit_id: Optional[int] = None
    lesson_id: Optional[int] = None
    is_generated: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class FlashcardGenerateRequest(BaseModel):
    """Request AI generation of flashcards for a unit or lesson.

    force=True replaces any existing generated flashcards for the same target+scope.
    force=False (default) returns 409 if generated flashcards already exist.
    """

    scope: Literal["unit", "lesson"]
    target_id: int
    card_scope: Literal["user", "course"]
    force: bool = False


# ── Response schemas for OpenAPI spec completeness ───────────────────────────


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class GrantPermissionResponse(BaseModel):
    message: str
    permissions: List[str]


class MessageResponse(BaseModel):
    message: str


class UserProgressResponse(BaseModel):
    user_id: int
    lessons: List[UserLessonProgressResponse]
    practices: List[UserPracticeProgressResponse]
    quizzes: List[UserQuizProgressResponse]


class SectionUnlockResponse(BaseModel):
    section_id: int
    user_id: int
    items_unlocked: int


# ── Document pipeline response types ────────────────────────────────────────


class DocumentUploadResponse(BaseModel):
    """Response for POST /api/courses/{course_id}/documents."""

    id: str
    filename: str
    storage_path: str
    content_type: str
    size_bytes: int
    created_at: str


class DocumentProcessResponse(BaseModel):
    """Response for POST /api/documents/{document_id}/process."""

    doc_id: str
    title: str
    units_count: int
    concepts_count: int
    graph_nodes: int
    graph_edges: int
    lessons: int
    milestones: int


class DocumentProcessStage(BaseModel):
    """A persisted pipeline stage update."""

    stage: str
    result: str
    output: str = ""
    created_at: str = ""


class DocumentBookProcess(BaseModel):
    """Book pipeline process status summary."""

    status: str
    retry_count: int
    max_retries: int
    error_message: str | None = None
    updated_at: str = ""


class DocumentProcessRun(BaseModel):
    """One process run grouped by mode (process/retry/reprocess)."""

    process_id: int
    run_mode: str
    status: str
    retry_count: int
    max_retries: int
    error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""
    stages: List[DocumentProcessStage] = Field(default_factory=list)


class DocumentProcessStartResponse(BaseModel):
    """Response for kickoff/retry processing endpoints."""

    document_id: str
    lp_doc_id: str
    status: str
    already_started: bool
    can_retry: bool
    message: str
    latest_process_run: DocumentProcessRun
    process_runs: List[DocumentProcessRun] = Field(default_factory=list)
    book_pipeline: DocumentBookProcess | None = None


class DocumentTreeResponse(BaseModel):
    """Response for GET /api/documents/{document_id}/tree."""

    doc_id: str
    title: str
    total_nodes: int


class DocumentUnit(BaseModel):
    """A single learning unit within a document."""

    id: str
    title: str
    unit_type: str
    difficulty: str
    estimated_study_time_minutes: int


class DocumentUnitsResponse(BaseModel):
    """Response for GET /api/documents/{document_id}/units."""

    doc_id: str
    units: List[DocumentUnit]
    count: int


class DocumentConcept(BaseModel):
    """A single concept extracted from a document."""

    id: str
    name: str
    category: str
    importance: float


class DocumentConceptsResponse(BaseModel):
    """Response for GET /api/documents/{document_id}/concepts."""

    doc_id: str
    concepts: List[DocumentConcept]
    total_concepts: int
    total_relationships: int


class DocumentStudyPlanSummary(BaseModel):
    """Response for GET /api/documents/{document_id}/study-plan."""

    doc_id: str
    title: str
    total_lessons: int
    total_estimated_minutes: int
    milestones: int


class DocumentExportResponse(BaseModel):
    """Response for GET /api/documents/{document_id}/export/json."""

    doc_id: str
    export_dir: str
    files: List[str]
