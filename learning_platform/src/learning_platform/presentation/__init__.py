"""Presentation models — immutable view models for the study screen.

These models represent the learning experience as shown to students,
rather than the internal processing pipeline.  They reference existing
pipeline objects by ID wherever possible to avoid data duplication.

Design Principles
-----------------
- **Immutable**: Models use ``model_config = {"frozen": True}`` where practical.
- **No persistence logic**: Pure data transfer objects, no DB operations.
- **ID references**: Reference pipeline objects (``LearningUnit``, ``Lesson``,
  ``Quiz``, etc.) by UUID rather than embedding duplicate data.
"""

from learning_platform.presentation.models import (
    CardStatus,
    CardType,
    DifficultyLevel,
    LearningObjective,
    LessonCard,
    Metadata,
    MilestoneCard,
    NavigationNode,
    NavigationNodeType,
    PageView,
    PracticeCard,
    ProgressSummary,
    QuizCard,
    Section,
    StatusLegend,
    StudyExperience,
    UnitCard,
)

__all__: list[str] = [
    "CardStatus",
    "CardType",
    "DifficultyLevel",
    "LearningObjective",
    "LessonCard",
    "Metadata",
    "MilestoneCard",
    "NavigationNode",
    "NavigationNodeType",
    "PageView",
    "PracticeCard",
    "ProgressSummary",
    "QuizCard",
    "Section",
    "StatusLegend",
    "StudyExperience",
    "UnitCard",
]
