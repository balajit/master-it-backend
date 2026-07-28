from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, model_validator

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


# ── Study Plan ──────────────────────────────────────────────────────────────


class StudyPlanLesson(BaseModel):
    id: str
    unit_id: str
    order: int = 0
    title: str = ""
    description: str = ""
    lesson_type: str = "core"
    difficulty: str = "basic"
    estimated_minutes: int = 0
    milestone_id: str | None = None


class StudyPlanMilestone(BaseModel):
    id: str
    order: int = 0
    title: str = ""
    description: str = ""
    estimated_minutes: int = 0
    lesson_count: int = 0


class StudyPlanCheckpoint(BaseModel):
    id: str
    milestone_id: str
    order: int = 0
    title: str = ""
    checkpoint_type: str = "self_test"
    estimated_minutes: int = 0


class StudyPlanDetail(BaseModel):
    doc_id: str
    title: str = ""
    description: str = ""
    total_estimated_minutes: int = 0
    total_lessons: int = 0
    lessons: List[StudyPlanLesson] = []
    milestones: List[StudyPlanMilestone] = []
    checkpoints: List[StudyPlanCheckpoint] = []


class CourseStudyPlanResponse(BaseModel):
    course_id: int
    course_title: str = ""
    documents_processed: int = 0
    study_plans: List[StudyPlanDetail] = []


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
    lessons: List[dict]
    practices: List[dict]
    quizzes: List[dict]


class SectionUnlockResponse(BaseModel):
    section_id: int
    user_id: int
    items_unlocked: int
