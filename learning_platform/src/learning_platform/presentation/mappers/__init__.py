"""Presentation Mappers — transform pipeline output to UI-specific models.

This package contains the mapping layer that transforms canonical domain
models (from the pipeline) into presentation models (for the study screen).

Architecture
------------
::

    Pipeline
          ↓
    Canonical Domain Models
          ↓
    Presentation Mapper  ← You are here
          ↓
    Learning Experience Models
          ↓
    REST API

Design Principles
-----------------
- **No side effects**: Mappers only transform data, never mutate inputs.
- **Pure functions**: Each mapping function takes inputs and returns outputs.
- **Configurable**: Layout rules are controlled by MappingConfiguration.
- **Extensible**: New presentation formats implement the same protocols.
- **Decoupled**: Mappers don't know about DB, HTTP, or other I/O.

Usage
-----
::

    from learning_platform.presentation.mappers import (
        PipelineOutput,
        ProgressContext,
        MappingConfiguration,
        create_learning_experience,
    )

    # Prepare pipeline output
    pipeline_output = PipelineOutput(
        document=doc,
        learning_units=units,
        annotations=annotations,
        concept_map=concept_map,
        knowledge_graph=kg,
        study_plan=plan,
        quizzes=quizzes,
    )

    # Create context with user progress
    ctx = ProgressContext(user_id=123, course_id=456, ...)

    # Use default configuration
    experience = create_learning_experience(pipeline_output, ctx)

    # Or use custom configuration
    config = MappingConfiguration(
        section=SectionConfig(
            grouping=SectionGroupingStrategy.FLAT,
        ),
    )
    experience = create_learning_experience(pipeline_output, ctx, config)
"""

from learning_platform.presentation.mappers.configuration import (
    DifficultyMapping,
    GoalCardPlacementStrategy,
    GoalConfig,
    LessonConfig,
    LessonGroupingStrategy,
    MappingConfiguration,
    NavigationConfig,
    OrderingStrategy,
    PracticeConfig,
    PracticeGroupingStrategy,
    QuizConfig,
    QuizPlacementStrategy,
    SectionConfig,
    SectionGroupingStrategy,
    StatusLegendConfig,
    StatusMapping,
    StudyTimeCalculationStrategy,
    StudyTimeConfig,
    create_compact_config,
    create_default_config,
    create_linear_config,
    create_quiz_focused_config,
    get_preset_config,
    register_preset,
)
from learning_platform.presentation.mappers.context import (
    LessonProgress,
    PracticeProgress,
    ProgressContext,
    ProgressStatus,
    QuizProgress,
    UnitProgress,
)
from learning_platform.presentation.mappers.learning_experience import (
    LearningExperienceMapper,
    PipelineOutput,
    create_learning_experience,
)
from learning_platform.presentation.mappers.protocols import (
    LessonMapper,
    MilestoneMapper,
    NavigationMapper,
    PracticeMapper,
    ProgressMapper,
    QuizMapper,
    SectionMapper,
    UnitMapper,
    map_learning_objectives,
)
from learning_platform.presentation.mappers.study_experience import (
    StudyExperienceMapper,
)

__all__: list[str] = [
    # Configuration
    "MappingConfiguration",
    "SectionConfig",
    "SectionGroupingStrategy",
    "LessonConfig",
    "LessonGroupingStrategy",
    "PracticeConfig",
    "PracticeGroupingStrategy",
    "QuizConfig",
    "QuizPlacementStrategy",
    "GoalConfig",
    "GoalCardPlacementStrategy",
    "OrderingStrategy",
    "StudyTimeCalculationStrategy",
    "StudyTimeConfig",
    "DifficultyMapping",
    "StatusMapping",
    "NavigationConfig",
    "StatusLegendConfig",
    "create_default_config",
    "create_compact_config",
    "create_quiz_focused_config",
    "create_linear_config",
    "get_preset_config",
    "register_preset",
    # Context
    "LessonProgress",
    "PracticeProgress",
    "ProgressContext",
    "ProgressStatus",
    "QuizProgress",
    "UnitProgress",
    # Learning Experience Mapper
    "LearningExperienceMapper",
    "PipelineOutput",
    "create_learning_experience",
    # Protocols
    "LessonMapper",
    "MilestoneMapper",
    "NavigationMapper",
    "PracticeMapper",
    "ProgressMapper",
    "QuizMapper",
    "SectionMapper",
    "StudyExperienceMapper",
    "UnitMapper",
    # Helpers
    "map_learning_objectives",
]
