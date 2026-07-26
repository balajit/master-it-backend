"""Mapping Configuration — controls how pipeline output is transformed to presentation.

This module defines the configuration models that control the layout and
behavior of the presentation mapping layer. By changing configuration,
different learning platform layouts can be supported without modifying code.

Design Principles
-----------------
- **Immutable**: Configuration is frozen after creation.
- **Declarative**: Describes *what* should happen, not *how*.
- **Composable**: Individual configs can be mixed and matched.
- **Extensible**: New layout options can be added without breaking existing ones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from learning_platform.presentation.models import CardStatus, DifficultyLevel

# ──────────────────────────────────────────────────────────────────────────────
# Enums for Configuration Options
# ──────────────────────────────────────────────────────────────────────────────


class SectionGroupingStrategy(StrEnum):
    """How units are grouped into sections."""

    BY_MODULE_LEVEL = "by_module_level"
    """Group by MODULE-level LearningUnit (current default)."""

    BY_DIFFICULTY = "by_difficulty"
    """Group lessons by difficulty level."""

    BY_TOPIC = "by_topic"
    """Group by topic/category metadata."""

    FLAT = "flat"
    """No grouping — all lessons in a single section."""


class LessonGroupingStrategy(StrEnum):
    """How lessons are organized within sections."""

    BY_ORDER = "by_order"
    """Follow the study plan order (current default)."""

    BY_DIFFICULTY_ASC = "by_difficulty_asc"
    """Sort by difficulty, easiest first."""

    BY_DIFFICULTY_DESC = "by_difficulty_desc"
    """Sort by difficulty, hardest first."""

    BY_ESTIMATED_TIME = "by_estimated_time"
    """Sort by estimated study time."""

    BY_PREREQUISITES = "by_prerequisites"
    """Sort based on prerequisite relationships."""


class PracticeGroupingStrategy(StrEnum):
    """How practice activities are organized."""

    BY_SECTION = "by_section"
    """Group practices under their parent section (current default)."""

    BY_LESSON = "by_lesson"
    """Group practices under their associated lesson."""

    FLAT = "flat"
    """All practices in a single list, no grouping."""


class QuizPlacementStrategy(StrEnum):
    """Where quizzes appear in the study experience."""

    AT_SECTION_END = "at_section_end"
    """Quizzes appear at the end of each section."""

    AT_MILESTONE_END = "at_milestone_end"
    """Quizzes appear at the end of each milestone."""

    INLINE = "inline"
    """Quizzes appear inline with lessons, based on order."""

    SEPARATE_TAB = "separate_tab"
    """Quizzes are separated into their own tab/view."""


class GoalCardPlacementStrategy(StrEnum):
    """Where goal cards (milestones/checkpoints) appear."""

    BETWEEN_SECTIONS = "between_sections"
    """Goals appear between sections."""

    AFTER_SECTION = "after_section"
    """Goals appear after each section."""

    AT_END = "at_end"
    """All goals appear at the end."""

    INLINE = "inline"
    """Goals appear inline with content."""


class OrderingStrategy(StrEnum):
    """How items are ordered within their group."""

    BY_STUDY_PLAN = "by_study_plan"
    """Follow the study plan order (current default)."""

    BY_TITLE_ALPHA = "by_title_alpha"
    """Sort alphabetically by title."""

    BY_DIFFICULTY = "by_difficulty"
    """Sort by difficulty level."""

    BY_ESTIMATED_TIME = "by_estimated_time"
    """Sort by estimated study time."""


class StudyTimeCalculationStrategy(StrEnum):
    """How estimated study time is calculated."""

    SUM_CHILDREN = "sum_children"
    """Sum of all child unit times (current default)."""

    WEIGHTED_AVERAGE = "weighted_average"
    """Weighted average based on content complexity."""

    FIXED_PER_LESSON = "fixed_per_lesson"
    """Fixed time per lesson (e.g., 15 minutes)."""

    CUSTOM = "custom"
    """Use custom calculation function."""


# ──────────────────────────────────────────────────────────────────────────────
# Mapping Functions (Protocol Types)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DifficultyMapping:
    """Maps pipeline difficulty strings to presentation DifficultyLevel."""

    basic: DifficultyLevel = DifficultyLevel.BEGINNER
    beginner: DifficultyLevel = DifficultyLevel.BEGINNER
    intermediate: DifficultyLevel = DifficultyLevel.INTERMEDIATE
    advanced: DifficultyLevel = DifficultyLevel.ADVANCED
    default: DifficultyLevel = DifficultyLevel.BEGINNER

    def map_difficulty(self, difficulty: str) -> DifficultyLevel:
        """Map a difficulty string to a DifficultyLevel."""
        lower = difficulty.lower()
        if lower == "basic":
            return self.basic
        if lower == "beginner":
            return self.beginner
        if lower == "intermediate":
            return self.intermediate
        if lower == "advanced":
            return self.advanced
        return self.default


@dataclass(frozen=True)
class StatusMapping:
    """Maps pipeline progress statuses to presentation CardStatus."""

    not_started: CardStatus = CardStatus.NOT_STARTED
    in_progress: CardStatus = CardStatus.IN_PROGRESS
    completed: CardStatus = CardStatus.COMPLETED
    mastered: CardStatus = CardStatus.MASTERED
    practiced: CardStatus = CardStatus.PRACTICED
    attempted: CardStatus = CardStatus.ATTEMPTED
    default: CardStatus = CardStatus.NOT_STARTED


@dataclass(frozen=True)
class StudyTimeConfig:
    """Configuration for estimated study time calculation."""

    strategy: StudyTimeCalculationStrategy = StudyTimeCalculationStrategy.SUM_CHILDREN
    fixed_minutes_per_lesson: int = 15
    words_per_minute: int = 200
    exercise_minutes_each: int = 5
    custom_function: Callable[[Any], int] | None = None


@dataclass(frozen=True)
class SectionConfig:
    """Configuration for section grouping."""

    grouping: SectionGroupingStrategy = SectionGroupingStrategy.BY_MODULE_LEVEL
    title_template: str = "{unit_title}"
    """Template for section titles. Supports {unit_title}, {order}, {difficulty}."""
    show_empty_sections: bool = False
    min_lessons_per_section: int = 0


@dataclass(frozen=True)
class LessonConfig:
    """Configuration for lesson grouping and ordering."""

    grouping: LessonGroupingStrategy = LessonGroupingStrategy.BY_ORDER
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN
    show_learning_objectives: bool = True
    show_difficulty: bool = True
    show_estimated_time: bool = True


@dataclass(frozen=True)
class PracticeConfig:
    """Configuration for practice activity grouping."""

    grouping: PracticeGroupingStrategy = PracticeGroupingStrategy.BY_SECTION
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN
    default_required_correct: int = 1
    default_total_questions: int = 1


@dataclass(frozen=True)
class QuizConfig:
    """Configuration for quiz placement."""

    placement: QuizPlacementStrategy = QuizPlacementStrategy.AT_SECTION_END
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN
    show_time_limit: bool = True
    show_passing_score: bool = True


@dataclass(frozen=True)
class GoalConfig:
    """Configuration for goal card (milestone) placement."""

    placement: GoalCardPlacementStrategy = GoalCardPlacementStrategy.BETWEEN_SECTIONS
    show_completed_count: bool = True
    show_estimated_time: bool = True


@dataclass(frozen=True)
class NavigationConfig:
    """Configuration for navigation hierarchy."""

    include_root: bool = True
    highlight_current: bool = True
    show_status: bool = True
    max_depth: int | None = None
    """Maximum depth to display. None means unlimited."""


@dataclass(frozen=True)
class StatusLegendConfig:
    """Configuration for status legend items."""

    show_legend: bool = True
    custom_legend: list[dict[str, str]] | None = None
    """Override the default legend with custom items."""


# ──────────────────────────────────────────────────────────────────────────────
# Root Configuration
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MappingConfiguration:
    """Complete configuration for the presentation mapping layer.

    This model controls all aspects of how pipeline output is transformed
    into the presentation model. By creating different configurations,
    different learning platform layouts can be supported without changing
    code.

    Example
    -------
    ::

        # Default configuration
        default_config = MappingConfiguration()

        # Compact layout for mobile
        mobile_config = MappingConfiguration(
            section=SectionConfig(
                grouping=SectionGroupingStrategy.FLAT,
                show_empty_sections=False,
            ),
            lesson=LessonConfig(
                show_estimated_time=False,
            ),
        )

        # Quiz-focused layout
        quiz_config = MappingConfiguration(
            quiz=QuizConfig(
                placement=QuizPlacementStrategy.INLINE,
            ),
            goal=GoalConfig(
                placement=GoalCardPlacementStrategy.AT_END,
            ),
        )
    """

    # ── Section Configuration ──
    section: SectionConfig = field(default_factory=SectionConfig)

    # ── Lesson Configuration ──
    lesson: LessonConfig = field(default_factory=LessonConfig)

    # ── Practice Configuration ──
    practice: PracticeConfig = field(default_factory=PracticeConfig)

    # ── Quiz Configuration ──
    quiz: QuizConfig = field(default_factory=QuizConfig)

    # ── Goal Configuration ──
    goal: GoalConfig = field(default_factory=GoalConfig)

    # ── Difficulty Mapping ──
    difficulty_mapping: DifficultyMapping = field(default_factory=DifficultyMapping)

    # ── Status Mapping ──
    status_mapping: StatusMapping = field(default_factory=StatusMapping)

    # ── Study Time Configuration ──
    study_time: StudyTimeConfig = field(default_factory=StudyTimeConfig)

    # ── Navigation Configuration ──
    navigation: NavigationConfig = field(default_factory=NavigationConfig)

    # ── Status Legend Configuration ──
    status_legend: StatusLegendConfig = field(default_factory=StatusLegendConfig)

    # ── Global Ordering ──
    ordering: OrderingStrategy = OrderingStrategy.BY_STUDY_PLAN


# ──────────────────────────────────────────────────────────────────────────────
# Preset Configurations
# ──────────────────────────────────────────────────────────────────────────────


def create_default_config() -> MappingConfiguration:
    """Create the default mapping configuration."""
    return MappingConfiguration()


def create_compact_config() -> MappingConfiguration:
    """Create a compact configuration for mobile or small screens."""
    return MappingConfiguration(
        section=SectionConfig(
            grouping=SectionGroupingStrategy.FLAT,
            show_empty_sections=False,
        ),
        lesson=LessonConfig(
            show_estimated_time=False,
            show_difficulty=False,
        ),
        navigation=NavigationConfig(
            max_depth=2,
        ),
    )


def create_quiz_focused_config() -> MappingConfiguration:
    """Create a configuration focused on quizzes and assessments."""
    return MappingConfiguration(
        quiz=QuizConfig(
            placement=QuizPlacementStrategy.INLINE,
            show_time_limit=True,
            show_passing_score=True,
        ),
        goal=GoalConfig(
            placement=GoalCardPlacementStrategy.AT_END,
        ),
    )


def create_linear_config() -> MappingConfiguration:
    """Create a linear configuration that enforces sequential completion."""
    return MappingConfiguration(
        section=SectionConfig(
            grouping=SectionGroupingStrategy.BY_MODULE_LEVEL,
            min_lessons_per_section=1,
        ),
        lesson=LessonConfig(
            ordering=OrderingStrategy.BY_STUDY_PLAN,
        ),
        navigation=NavigationConfig(
            highlight_current=True,
            show_status=True,
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Configuration Registry
# ──────────────────────────────────────────────────────────────────────────────


CONFIGURATION_PRESETS: dict[str, MappingConfiguration] = {
    "default": create_default_config(),
    "compact": create_compact_config(),
    "quiz_focused": create_quiz_focused_config(),
    "linear": create_linear_config(),
}


def get_preset_config(name: str) -> MappingConfiguration:
    """Get a preset configuration by name.

    Parameters
    ----------
    name : str
        The name of the preset configuration.

    Returns
    -------
    MappingConfiguration
        The preset configuration.

    Raises
    ------
    KeyError
        If the preset name is not found.
    """
    if name not in CONFIGURATION_PRESETS:
        available = ", ".join(CONFIGURATION_PRESETS.keys())
        raise KeyError(f"Unknown preset '{name}'. Available: {available}")
    return CONFIGURATION_PRESETS[name]


def register_preset(name: str, config: MappingConfiguration) -> None:
    """Register a custom preset configuration.

    Parameters
    ----------
    name : str
        The name for the preset.
    config : MappingConfiguration
        The configuration to register.
    """
    CONFIGURATION_PRESETS[name] = config
