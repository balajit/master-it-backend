"""Mapper protocols — interfaces for presentation mapping.

This module defines the Protocol classes that mapper implementations must
follow. By coding to these protocols, additional presentation formats can
be added later without changing the pipeline or existing mappers.

Design Principles
-----------------
- **No side effects**: Mappers only transform data, never mutate inputs.
- **Pure functions**: Each mapping function takes inputs and returns outputs
  with no hidden state.
- **Composability**: Mappers can be composed to build complex views.
- **Extensibility**: New presentation formats implement the same protocols.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from learning_platform.models.learning_unit import LearningUnit
from learning_platform.models.quiz import Quiz
from learning_platform.models.sequence import Lesson, Milestone
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.models import (
    LearningObjective,
    LessonCard,
    MilestoneCard,
    NavigationNode,
    PracticeCard,
    ProgressSummary,
    QuizCard,
    Section,
    UnitCard,
)

# ──────────────────────────────────────────────────────────────────────────────
# Individual Mapper Protocols
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class UnitMapper(Protocol):
    """Maps a pipeline LearningUnit to a presentation UnitCard."""

    def map_unit_card(
        self,
        unit: LearningUnit,
        progress: ProgressContext,
    ) -> UnitCard:
        """Transform a LearningUnit into a UnitCard.

        Parameters
        ----------
        unit : LearningUnit
            The pipeline learning unit.
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        UnitCard
            The presentation-ready unit card.
        """
        ...


@runtime_checkable
class SectionMapper(Protocol):
    """Maps a pipeline LearningUnit (MODULE-level) to a presentation Section."""

    def map_section(
        self,
        unit: LearningUnit,
        parent_unit: LearningUnit | None,
        child_units: list[LearningUnit],
        progress: ProgressContext,
    ) -> Section:
        """Transform a MODULE-level LearningUnit into a Section.

        Parameters
        ----------
        unit : LearningUnit
            The MODULE-level unit representing this section.
        parent_unit : LearningUnit | None
            The parent COURSE-level unit (for unit_id).
        child_units : list[LearningUnit]
            Child units within this section (for counts).
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        Section
            The presentation-ready section.
        """
        ...


@runtime_checkable
class LessonMapper(Protocol):
    """Maps a pipeline Lesson to a presentation LessonCard."""

    def map_lesson_card(
        self,
        lesson: Lesson,
        unit: LearningUnit,
        section_id: UUID,
        progress: ProgressContext,
    ) -> LessonCard:
        """Transform a Lesson into a LessonCard.

        Parameters
        ----------
        lesson : Lesson
            The pipeline lesson from the study plan.
        unit : LearningUnit
            The learning unit this lesson maps to.
        section_id : UUID
            The resolved section (MODULE) ID.
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        LessonCard
            The presentation-ready lesson card.
        """
        ...


@runtime_checkable
class PracticeMapper(Protocol):
    """Maps pipeline exercises to a presentation PracticeCard."""

    def map_practice_card(
        self,
        practice_id: UUID,
        unit: LearningUnit,
        section_id: UUID,
        title: str,
        order: int,
        total_questions: int,
        required_correct: int,
        progress: ProgressContext,
    ) -> PracticeCard:
        """Transform exercise data into a PracticeCard.

        Parameters
        ----------
        practice_id : UUID
            The unique identifier for this practice.
        unit : LearningUnit
            The learning unit containing this practice.
        section_id : UUID
            The resolved section ID.
        title : str
            The practice title.
        order : int
            Display order within the section.
        total_questions : int
            Number of questions in this practice.
        required_correct : int
            Number correct needed to pass.
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        PracticeCard
            The presentation-ready practice card.
        """
        ...


@runtime_checkable
class QuizMapper(Protocol):
    """Maps a pipeline Quiz to a presentation QuizCard."""

    def map_quiz_card(
        self,
        quiz: Quiz,
        section_id: UUID,
        order: int,
        progress: ProgressContext,
    ) -> QuizCard:
        """Transform a Quiz into a QuizCard.

        Parameters
        ----------
        quiz : Quiz
            The pipeline quiz object.
        section_id : UUID
            The resolved section ID.
        order : int
            Display order within the section.
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        QuizCard
            The presentation-ready quiz card.
        """
        ...


@runtime_checkable
class MilestoneMapper(Protocol):
    """Maps a pipeline Milestone to a presentation MilestoneCard."""

    def map_milestone_card(
        self,
        milestone: Milestone,
        unit_id: UUID,
        lessons: list[Lesson],
        progress: ProgressContext,
    ) -> MilestoneCard:
        """Transform a Milestone into a MilestoneCard.

        Parameters
        ----------
        milestone : Milestone
            The pipeline milestone object.
        unit_id : UUID
            The resolved unit ID (derived from contained lessons).
        lessons : list[Lesson]
            Lessons in this milestone (for completed count).
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        MilestoneCard
            The presentation-ready milestone card.
        """
        ...


@runtime_checkable
class ProgressMapper(Protocol):
    """Computes progress summary from context and pipeline data."""

    def map_progress_summary(
        self,
        unit: LearningUnit,
        progress: ProgressContext,
    ) -> ProgressSummary:
        """Compute aggregated progress for a unit.

        Parameters
        ----------
        unit : LearningUnit
            The pipeline learning unit.
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        ProgressSummary
            The presentation-ready progress summary.
        """
        ...


@runtime_checkable
class NavigationMapper(Protocol):
    """Maps a LearningUnit tree to navigation nodes."""

    def map_navigation(
        self,
        units: list[LearningUnit],
        progress: ProgressContext,
    ) -> list[NavigationNode]:
        """Transform a list of LearningUnits into navigation nodes.

        Parameters
        ----------
        units : list[LearningUnit]
            All units in the course (will be organized into a tree).
        progress : ProgressContext
            External context with user progress data.

        Returns
        -------
        list[NavigationNode]
            Flat list of navigation nodes with parent/child references.
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Aggregation Helpers
# ──────────────────────────────────────────────────────────────────────────────


def map_learning_objectives(
    objective_strings: list[str],
    annotation_ids: list[UUID] | None = None,
) -> list[LearningObjective]:
    """Transform a list of objective strings into LearningObjective objects.

    This is a pure helper function, not a protocol method.

    Parameters
    ----------
    objective_strings : list[str]
        Raw objective text strings from pipeline models.
    annotation_ids : list[UUID] | None
        Optional annotation IDs to link back to enrichment stage.

    Returns
    -------
    list[LearningObjective]
        Presentation-ready learning objectives.
    """
    objectives: list[LearningObjective] = []
    for i, text in enumerate(objective_strings):
        annotation_id = None
        if annotation_ids and i < len(annotation_ids):
            annotation_id = annotation_ids[i]
        objectives.append(
            LearningObjective(
                text=text,
                annotation_id=annotation_id,
                order=i,
            )
        )
    return objectives
