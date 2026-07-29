"""Learning Experience Mapper public API and composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from learning_platform.models.annotation import Annotation
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.learning_unit import LearningUnit, UnitType
from learning_platform.presentation.mappers.configuration import (
    MappingConfiguration,
    create_default_config,
)
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.mappers.learning_experience_content import (
    LearningExperienceContentMixin,
)
from learning_platform.presentation.mappers.learning_experience_indices import (
    LearningExperienceIndicesMixin,
)
from learning_platform.presentation.mappers.learning_experience_navigation_pages import (
    LearningExperienceNavigationPagesMixin,
)
from learning_platform.presentation.mappers.learning_experience_output import PipelineOutput
from learning_platform.presentation.mappers.learning_experience_status_legend import (
    build_status_legend_from_config as _build_status_legend_from_config,
)
from learning_platform.presentation.models import StudyExperience


@dataclass
class LearningExperienceMapper(
    LearningExperienceContentMixin,
    LearningExperienceNavigationPagesMixin,
    LearningExperienceIndicesMixin,
):
    """Transforms pipeline output into a StudyExperience."""

    config: MappingConfiguration = field(default_factory=create_default_config)

    _units_by_id: dict[UUID, LearningUnit] = field(default_factory=dict)
    _unit_ids_by_type: dict[UnitType, list[UUID]] = field(default_factory=dict)
    _annotations: list[Annotation] = field(default_factory=list)
    _document: CanonicalDocument | None = None

    _descendant_ids: dict[UUID, set[UUID]] = field(default_factory=dict)
    _lesson_counts: dict[UUID, int] = field(default_factory=dict)
    _exercise_counts: dict[UUID, int] = field(default_factory=dict)
    _lesson_ids: dict[UUID, set[UUID]] = field(default_factory=dict)
    _page_ranges: dict[UUID, tuple[int, int]] = field(default_factory=dict)
    _section_ids: dict[UUID, UUID] = field(default_factory=dict)
    _exercises_index: dict[UUID, list[tuple[UUID, str]]] = field(default_factory=dict)

    def map(
        self,
        pipeline_output: PipelineOutput,
        progress: ProgressContext,
    ) -> StudyExperience:
        """Transform pipeline output into a StudyExperience."""
        self._build_indices(pipeline_output.learning_units)
        self._annotations = pipeline_output.annotations
        self._document = pipeline_output.document
        self._compute_memoized_indices(pipeline_output.pages)

        root_unit = self._find_root_unit(pipeline_output.learning_units)
        if root_unit is None:
            raise ValueError("No root COURSE unit found in learning units")

        unit_card = self._build_unit_card(root_unit, progress)
        sections = self._build_sections(root_unit, pipeline_output, progress)
        lessons = self._build_lessons(
            pipeline_output.study_plan,
            progress,
            pipeline_output.pages,
        )
        practices = self._build_practices(root_unit, sections, progress)
        quizzes = self._build_quizzes(pipeline_output.quizzes, progress)
        milestones = self._build_milestones(
            pipeline_output.study_plan.milestones,
            pipeline_output.study_plan.lessons,
            root_unit.id,
            progress,
        )
        pages = self._build_pages(pipeline_output.pages, pipeline_output.learning_units)
        progress_summary = self._build_progress_summary(root_unit, progress)
        navigation = self._build_navigation(root_unit, progress)
        status_legend = _build_status_legend_from_config(self.config)

        return StudyExperience(
            unit=unit_card,
            sections=sections,
            lessons=lessons,
            practices=practices,
            quizzes=quizzes,
            milestones=milestones,
            pages=pages,
            progress=progress_summary,
            navigation=navigation,
            status_legend=status_legend,
        )


def create_learning_experience(
    pipeline_output: PipelineOutput,
    progress: ProgressContext,
    config: MappingConfiguration | None = None,
) -> StudyExperience:
    """Create a StudyExperience from pipeline output and user progress."""
    if config is None:
        config = create_default_config()

    mapper = LearningExperienceMapper(config=config)
    return mapper.map(pipeline_output, progress)
