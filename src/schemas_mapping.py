"""Mapping API schemas — request/response models for the mapping namespace.

These schemas expose presentation models instead of canonical pipeline models.
They are used by the mapping API endpoints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from learning_platform.presentation.mappers.configuration import (
    GoalCardPlacementStrategy,
    LessonGroupingStrategy,
    MappingConfiguration,
    OrderingStrategy,
    PracticeGroupingStrategy,
    QuizPlacementStrategy,
    SectionGroupingStrategy,
    StudyTimeCalculationStrategy,
)
from learning_platform.presentation.models import (
    CardStatus,
    ContentNode,
    DifficultyLevel,
)


# ──────────────────────────────────────────────────────────────────────────────
# Configuration Schemas
# ──────────────────────────────────────────────────────────────────────────────


class SectionConfigSchema(BaseModel):
    """Schema for section grouping configuration."""

    grouping: SectionGroupingStrategy = SectionGroupingStrategy.BY_MODULE_LEVEL
    title_template: str = "{unit_title}"
    show_empty_sections: bool = False
    min_lessons_per_section: int = 0


class LessonConfigSchema(BaseModel):
    """Schema for lesson grouping and ordering configuration."""

    grouping: LessonGroupingStrategy = LessonGroupingStrategy.BY_ORDER
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN
    show_learning_objectives: bool = True
    show_difficulty: bool = True
    show_estimated_time: bool = True


class PracticeConfigSchema(BaseModel):
    """Schema for practice activity grouping configuration."""

    grouping: PracticeGroupingStrategy = PracticeGroupingStrategy.BY_SECTION
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN
    default_required_correct: int = 1
    default_total_questions: int = 1


class QuizConfigSchema(BaseModel):
    """Schema for quiz placement configuration."""

    placement: QuizPlacementStrategy = QuizPlacementStrategy.AT_SECTION_END
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN
    show_time_limit: bool = True
    show_passing_score: bool = True


class GoalConfigSchema(BaseModel):
    """Schema for goal card (milestone) placement configuration."""

    placement: GoalCardPlacementStrategy = GoalCardPlacementStrategy.BETWEEN_SECTIONS
    show_completed_count: bool = True
    show_estimated_time: bool = True


class StudyTimeConfigSchema(BaseModel):
    """Schema for study time calculation configuration."""

    strategy: StudyTimeCalculationStrategy = StudyTimeCalculationStrategy.SUM_CHILDREN
    fixed_minutes_per_lesson: int = 15
    words_per_minute: int = 200
    exercise_minutes_each: int = 5


class NavigationConfigSchema(BaseModel):
    """Schema for navigation hierarchy configuration."""

    include_root: bool = True
    highlight_current: bool = True
    show_status: bool = True
    max_depth: int | None = None


class StatusLegendConfigSchema(BaseModel):
    """Schema for status legend configuration."""

    show_legend: bool = True


class MappingConfigurationSchema(BaseModel):
    """Schema for complete mapping configuration.

    This is the request/response model for the mapping API endpoints.
    It mirrors the MappingConfiguration dataclass but uses Pydantic models.
    """

    section: SectionConfigSchema = Field(default_factory=SectionConfigSchema)
    lesson: LessonConfigSchema = Field(default_factory=LessonConfigSchema)
    practice: PracticeConfigSchema = Field(default_factory=PracticeConfigSchema)
    quiz: QuizConfigSchema = Field(default_factory=QuizConfigSchema)
    goal: GoalConfigSchema = Field(default_factory=GoalConfigSchema)
    study_time: StudyTimeConfigSchema = Field(default_factory=StudyTimeConfigSchema)
    navigation: NavigationConfigSchema = Field(default_factory=NavigationConfigSchema)
    status_legend: StatusLegendConfigSchema = Field(
        default_factory=StatusLegendConfigSchema
    )
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN

    def to_mapping_config(self) -> MappingConfiguration:
        """Convert to the internal MappingConfiguration dataclass."""
        return MappingConfiguration(
            section=self._map_section_config(),
            lesson=self._map_lesson_config(),
            practice=self._map_practice_config(),
            quiz=self._map_quiz_config(),
            goal=self._map_goal_config(),
            study_time=self._map_study_time_config(),
            navigation=self._map_navigation_config(),
            status_legend=self._map_status_legend_config(),
            ordering=self.ordering,
        )

    def _map_section_config(self) -> Any:
        """Map section config to internal type."""
        from learning_platform.presentation.mappers.configuration import SectionConfig

        return SectionConfig(
            grouping=self.section.grouping,
            title_template=self.section.title_template,
            show_empty_sections=self.section.show_empty_sections,
            min_lessons_per_section=self.section.min_lessons_per_section,
        )

    def _map_lesson_config(self) -> Any:
        """Map lesson config to internal type."""
        from learning_platform.presentation.mappers.configuration import LessonConfig

        return LessonConfig(
            grouping=self.lesson.grouping,
            ordering=self.lesson.ordering,
            show_learning_objectives=self.lesson.show_learning_objectives,
            show_difficulty=self.lesson.show_difficulty,
            show_estimated_time=self.lesson.show_estimated_time,
        )

    def _map_practice_config(self) -> Any:
        """Map practice config to internal type."""
        from learning_platform.presentation.mappers.configuration import PracticeConfig

        return PracticeConfig(
            grouping=self.practice.grouping,
            ordering=self.practice.ordering,
            default_required_correct=self.practice.default_required_correct,
            default_total_questions=self.practice.default_total_questions,
        )

    def _map_quiz_config(self) -> Any:
        """Map quiz config to internal type."""
        from learning_platform.presentation.mappers.configuration import QuizConfig

        return QuizConfig(
            placement=self.quiz.placement,
            ordering=self.quiz.ordering,
            show_time_limit=self.quiz.show_time_limit,
            show_passing_score=self.quiz.show_passing_score,
        )

    def _map_goal_config(self) -> Any:
        """Map goal config to internal type."""
        from learning_platform.presentation.mappers.configuration import GoalConfig

        return GoalConfig(
            placement=self.goal.placement,
            show_completed_count=self.goal.show_completed_count,
            show_estimated_time=self.goal.show_estimated_time,
        )

    def _map_study_time_config(self) -> Any:
        """Map study time config to internal type."""
        from learning_platform.presentation.mappers.configuration import StudyTimeConfig

        return StudyTimeConfig(
            strategy=self.study_time.strategy,
            fixed_minutes_per_lesson=self.study_time.fixed_minutes_per_lesson,
            words_per_minute=self.study_time.words_per_minute,
            exercise_minutes_each=self.study_time.exercise_minutes_each,
        )

    def _map_navigation_config(self) -> Any:
        """Map navigation config to internal type."""
        from learning_platform.presentation.mappers.configuration import (
            NavigationConfig,
        )

        return NavigationConfig(
            include_root=self.navigation.include_root,
            highlight_current=self.navigation.highlight_current,
            show_status=self.navigation.show_status,
            max_depth=self.navigation.max_depth,
        )

    def _map_status_legend_config(self) -> Any:
        """Map status legend config to internal type."""
        from learning_platform.presentation.mappers.configuration import (
            StatusLegendConfig,
        )

        return StatusLegendConfig(
            show_legend=self.status_legend.show_legend,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Presentation Model Schemas (for API responses)
# ──────────────────────────────────────────────────────────────────────────────


class LearningObjectiveSchema(BaseModel):
    """Schema for learning objective in API response."""

    text: str
    annotation_id: str | None = None
    order: int = 0


class NodeRefSchema(BaseModel):
    """Schema for a reference to a document node."""

    node_id: str
    summary: str = ""


class UnitCardSchema(BaseModel):
    """Schema for UnitCard in API response."""

    unit_id: str
    title: str
    description: str = ""
    difficulty: DifficultyLevel = DifficultyLevel.BEGINNER
    estimated_minutes: int = 0
    total_sections: int = 0
    total_lessons: int = 0
    course_id: int | None = None
    progress_pct: float = 0.0


class SectionSchema(BaseModel):
    """Schema for Section in API response."""

    section_id: str
    unit_id: str
    title: str
    order: int = 0
    estimated_minutes: int = 0
    lesson_count: int = 0
    practice_count: int = 0
    quiz_count: int = 0
    completed_count: int = 0
    start_page: int = 0
    end_page: int = 0


class LessonCardSchema(BaseModel):
    """Schema for LessonCard in API response."""

    lesson_id: str
    unit_id: str
    section_id: str
    title: str
    description: str = ""
    order: int = 0
    duration_minutes: int = 0
    difficulty: DifficultyLevel = DifficultyLevel.BEGINNER
    status: CardStatus = CardStatus.NOT_STARTED
    learning_objectives: list[LearningObjectiveSchema] = Field(default_factory=list)
    start_page: int = 0
    end_page: int = 0
    completed_at: str | None = None
    content_references: list[NodeRefSchema] = Field(default_factory=list)
    definitions: list[NodeRefSchema] = Field(default_factory=list)
    examples: list[NodeRefSchema] = Field(default_factory=list)
    figures: list[NodeRefSchema] = Field(default_factory=list)
    tables: list[NodeRefSchema] = Field(default_factory=list)
    equations: list[NodeRefSchema] = Field(default_factory=list)
    content: list[ContentNode] = Field(default_factory=list)


class ExerciseOptionSchema(BaseModel):
    """Schema for an exercise answer option."""

    label: str = ""
    text: str = ""
    is_correct: bool = False
    explanation: str = ""


class PracticeCardSchema(BaseModel):
    """Schema for PracticeCard in API response."""

    practice_id: str
    unit_id: str
    section_id: str
    title: str
    order: int = 0
    required_correct: int = 0
    total_questions: int = 0
    status: CardStatus = CardStatus.NOT_STARTED
    attempts: int = 0
    best_score: float = 0.0
    question_text: str = ""
    exercise_type: str = ""
    options: list[ExerciseOptionSchema] = Field(default_factory=list)
    solution: str = ""
    explanation: str = ""


class QuizCardSchema(BaseModel):
    """Schema for QuizCard in API response."""

    quiz_id: str
    unit_id: str
    section_id: str
    title: str
    order: int = 0
    total_points: int = 0
    passing_points: int = 0
    time_limit_minutes: int | None = None
    status: CardStatus = CardStatus.NOT_STARTED
    score: float | None = None
    completed_at: str | None = None


class MilestoneCardSchema(BaseModel):
    """Schema for MilestoneCard in API response."""

    milestone_id: str
    unit_id: str
    title: str
    description: str = ""
    order: int = 0
    estimated_minutes: int = 0
    lesson_count: int = 0
    completed_lesson_count: int = 0
    status: CardStatus = CardStatus.NOT_STARTED


class ProgressSummarySchema(BaseModel):
    """Schema for ProgressSummary in API response."""

    total_items: int = 0
    completed_items: int = 0
    mastery_pct: float = 0.0
    total_minutes_studied: int = 0
    estimated_remaining_minutes: int = 0


class NavigationNodeSchema(BaseModel):
    """Schema for NavigationNode in API response."""

    node_id: str
    node_type: str
    title: str
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    unit_id: str | None = None
    order: int = 0
    is_current: bool = False
    is_accessible: bool = True
    status: CardStatus = CardStatus.NOT_STARTED


class StatusLegendSchema(BaseModel):
    """Schema for StatusLegend in API response."""

    status: CardStatus
    label: str
    description: str
    icon_name: str = ""
    color_hex: str = ""


class PageViewSchema(BaseModel):
    """Schema for PageView in API response."""

    page_number: int
    title: str = ""
    text_preview: str = ""
    full_text: str = ""
    unit_ids: list[str] = Field(default_factory=list)
    annotation_ids: list[str] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# API Response Schemas
# ──────────────────────────────────────────────────────────────────────────────


class MappingResponse(BaseModel):
    """Response for GET /documents/{docId}/mapping."""

    doc_id: str
    configuration: MappingConfigurationSchema
    unit: UnitCardSchema
    sections: list[SectionSchema] = Field(default_factory=list)
    lessons: list[LessonCardSchema] = Field(default_factory=list)
    practices: list[PracticeCardSchema] = Field(default_factory=list)
    quizzes: list[QuizCardSchema] = Field(default_factory=list)
    milestones: list[MilestoneCardSchema] = Field(default_factory=list)
    pages: list[PageViewSchema] = Field(default_factory=list)
    progress: ProgressSummarySchema = Field(default_factory=ProgressSummarySchema)
    navigation: list[NavigationNodeSchema] = Field(default_factory=list)
    status_legend: list[StatusLegendSchema] = Field(default_factory=list)


class MappingUpdateRequest(BaseModel):
    """Request body for PUT /documents/{docId}/mapping."""

    configuration: MappingConfigurationSchema


class MappingUpdateResponse(BaseModel):
    """Response for PUT /documents/{docId}/mapping."""

    doc_id: str
    configuration: MappingConfigurationSchema
    message: str = "Mapping updated successfully"


class RegenerateResponse(BaseModel):
    """Response for POST /documents/{docId}/mapping/regenerate."""

    doc_id: str
    configuration: MappingConfigurationSchema
    message: str = "Presentation regenerated successfully"


class ResetResponse(BaseModel):
    """Response for POST /documents/{docId}/mapping/reset."""

    doc_id: str
    configuration: MappingConfigurationSchema
    message: str = "Mapping reset to defaults"


class PreviewResponse(BaseModel):
    """Response for GET /documents/{docId}/mapping/preview."""

    doc_id: str
    configuration: MappingConfigurationSchema
    unit: UnitCardSchema
    sections: list[SectionSchema] = Field(default_factory=list)
    lessons: list[LessonCardSchema] = Field(default_factory=list)
    pages: list[PageViewSchema] = Field(default_factory=list)
    preview_mode: bool = True
