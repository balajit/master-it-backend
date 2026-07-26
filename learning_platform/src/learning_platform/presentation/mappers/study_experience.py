"""Study Experience Mapper — orchestrates the full presentation mapping.

This module defines the protocol for assembling a complete StudyExperience
from pipeline output and external context. It coordinates individual
mappers to build the full view model.

Design Principles
-----------------
- **Single responsibility**: Only orchestrates; delegates to individual mappers.
- **No side effects**: Pure transformation pipeline.
- **Composable**: Individual mappers can be used independently or composed.
- **Extensible**: New formats implement the same protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from learning_platform.models.learning_unit import LearningUnit
from learning_platform.models.quiz import Quiz
from learning_platform.models.sequence import Lesson, StudyPlan
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.models import StudyExperience


@runtime_checkable
class StudyExperienceMapper(Protocol):
    """Protocol for assembling a complete StudyExperience.

    Implementations coordinate multiple mappers to transform pipeline
    output into the full presentation model shown on the study screen.
    """

    def map_study_experience(
        self,
        unit: LearningUnit,
        child_units: list[LearningUnit],
        study_plan: StudyPlan,
        quizzes: list[Quiz],
        progress: ProgressContext,
    ) -> StudyExperience:
        """Assemble a complete StudyExperience from pipeline data.

        Parameters
        ----------
        unit : LearningUnit
            The root unit being studied.
        child_units : list[LearningUnit]
            All descendant units (sections, lessons, topics).
        study_plan : StudyPlan
            The generated study plan with lessons and milestones.
        quizzes : list[Quiz]
            Generated quizzes for this unit.
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        StudyExperience
            The complete presentation model for the study screen.
        """
        ...

    def map_section_experience(
        self,
        section_unit: LearningUnit,
        parent_unit: LearningUnit,
        lesson_units: list[LearningUnit],
        lessons: list[Lesson],
        quizzes: list[Quiz],
        progress: ProgressContext,
    ) -> StudyExperience:
        """Assemble a StudyExperience for a single section.

        This is a convenience method for section-level views that need
        only the section's content, not the full unit.

        Parameters
        ----------
        section_unit : LearningUnit
            The MODULE-level unit representing this section.
        parent_unit : LearningUnit
            The parent COURSE-level unit.
        lesson_units : list[LearningUnit]
            LESSON-level units within this section.
        lessons : list[Lesson]
            Lessons from the study plan for this section.
        quizzes : list[Quiz]
            Quizzes for this section.
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        StudyExperience
            The section-scoped presentation model.
        """
        ...
