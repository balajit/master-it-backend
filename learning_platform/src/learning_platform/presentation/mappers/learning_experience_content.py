"""Section, lesson, practice, quiz, milestone, and progress mapping."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from learning_platform.models.annotation import Annotation, ObjectiveAnnotation
from learning_platform.models.document import CanonicalDocument, Exercise
from learning_platform.models.learning_unit import LearningUnit, UnitType
from learning_platform.models.page_context import PageContext
from learning_platform.models.quiz import Quiz
from learning_platform.models.sequence import Milestone, StudyPlan
from learning_platform.presentation.mappers.configuration import (
    MappingConfiguration,
    SectionGroupingStrategy,
)
from learning_platform.presentation.mappers.context import ProgressContext, ProgressStatus
from learning_platform.presentation.mappers.learning_experience_output import PipelineOutput
from learning_platform.presentation.mappers.protocols import map_learning_objectives
from learning_platform.presentation.models import (
    DifficultyLevel,
    ExerciseOption,
    LearningObjective,
    MilestoneCard,
    PracticeCard,
    ProgressSummary,
    QuizCard,
    Section,
    UnitCard,
)


class LearningExperienceContentMixin:
    """Builds StudyExperience content sections and cards."""

    config: MappingConfiguration
    _units_by_id: dict[UUID, LearningUnit]
    _annotations: list[Annotation]
    _document: CanonicalDocument | None
    _lesson_counts: dict[UUID, int]
    _exercise_counts: dict[UUID, int]
    _lesson_ids: dict[UUID, set[UUID]]
    _section_ids: dict[UUID, UUID]
    _exercises_index: dict[UUID, list[tuple[UUID, str]]]
    _get_children: Callable[[UUID], list[LearningUnit]]
    _find_page_range_for_unit: Callable[[UUID, list[PageContext]], tuple[int, int]]

    def _build_unit_card(
        self,
        unit: LearningUnit,
        progress: ProgressContext,
    ) -> UnitCard:
        """Build the top-level UnitCard from a COURSE-level LearningUnit."""
        section_children = self._get_section_children(unit)
        total_lessons = self._count_lessons_recursive(unit.id)
        unit_progress = progress.get_unit_progress(unit.id)
        estimated_minutes = self._calculate_estimated_time(unit)

        return UnitCard(
            unit_id=unit.id,
            title=unit.title,
            description=unit.description,
            difficulty=self.config.difficulty_mapping.map_difficulty(unit.difficulty.value),
            estimated_minutes=estimated_minutes,
            total_sections=len(section_children),
            total_lessons=total_lessons,
            course_id=progress.course_id,
            progress_pct=self._calculate_progress_pct(unit_progress),
        )

    def _get_section_children(self, unit: LearningUnit) -> list[LearningUnit]:
        """Get children that should be treated as sections based on config."""
        children = self._get_children(unit.id)

        if self.config.section.grouping == SectionGroupingStrategy.BY_MODULE_LEVEL:
            return [c for c in children if c.unit_type == UnitType.MODULE]
        elif self.config.section.grouping == SectionGroupingStrategy.FLAT:
            return children
        else:
            return [c for c in children if c.unit_type == UnitType.MODULE]

    def _count_lessons_recursive(self, unit_id: UUID) -> int:
        """Count all lessons recursively under a unit (memoized)."""
        return self._lesson_counts.get(unit_id, 0)

    def _calculate_estimated_time(self, unit: LearningUnit) -> int:
        """Calculate estimated study time based on configuration."""
        strategy = self.config.study_time.strategy

        if strategy.value == "sum_children":
            return unit.estimated_study_time_minutes
        elif strategy.value == "fixed_per_lesson":
            lesson_count = self._count_lessons_recursive(unit.id)
            return lesson_count * self.config.study_time.fixed_minutes_per_lesson
        elif strategy.value == "weighted_average":
            return unit.estimated_study_time_minutes
        else:
            return unit.estimated_study_time_minutes

    def _build_sections(
        self,
        root_unit: LearningUnit,
        pipeline_output: PipelineOutput,
        progress: ProgressContext,
    ) -> list[Section]:
        """Build sections based on configuration."""
        section_children = self._get_section_children(root_unit)

        sections: list[Section] = []
        for order, child in enumerate(section_children):
            section = self._build_single_section(
                child,
                root_unit,
                pipeline_output,
                progress,
                order,
            )
            if (
                self.config.section.min_lessons_per_section > 0
                and section.lesson_count < self.config.section.min_lessons_per_section
            ):
                continue
            sections.append(section)

        return sections

    def _build_single_section(
        self,
        section_unit: LearningUnit,
        root_unit: LearningUnit,
        pipeline_output: PipelineOutput,
        progress: ProgressContext,
        order: int,
    ) -> Section:
        """Build a single Section from a LearningUnit."""
        lesson_count = self._count_lessons_recursive(section_unit.id)
        practice_count = self._count_exercises_recursive(section_unit.id)
        quiz_count = self._count_quizzes_for_section(section_unit, pipeline_output.quizzes)
        completed_count = self._get_section_completed_count(section_unit.id, progress)
        estimated_minutes = self._calculate_estimated_time(section_unit)
        start_page, end_page = self._find_page_range_for_unit(
            section_unit.id,
            pipeline_output.pages,
        )

        return Section(
            section_id=section_unit.id,
            unit_id=root_unit.id,
            title=section_unit.title,
            order=order,
            estimated_minutes=estimated_minutes,
            lesson_count=lesson_count,
            practice_count=practice_count,
            quiz_count=quiz_count,
            completed_count=completed_count,
            start_page=start_page,
            end_page=end_page,
        )

    def _count_exercises_recursive(self, unit_id: UUID) -> int:
        """Count all exercises recursively under a unit (memoized)."""
        return self._exercise_counts.get(unit_id, 0)

    def _count_quizzes_for_section(
        self,
        section_unit: LearningUnit,
        quizzes: list[Quiz],
    ) -> int:
        """Count quizzes that belong to lessons in this section."""
        lesson_ids = self._get_lesson_ids_in_unit(section_unit.id)

        count = 0
        for quiz in quizzes:
            if quiz.lesson_id and quiz.lesson_id in lesson_ids:
                count += 1
        return count

    def _get_lesson_ids_in_unit(self, unit_id: UUID) -> set[UUID]:
        """Get all lesson IDs recursively under a unit (memoized)."""
        return self._lesson_ids.get(unit_id, set())

    def _get_section_completed_count(
        self,
        section_unit_id: UUID,
        progress: ProgressContext,
    ) -> int:
        """Count completed items in a section."""
        lesson_ids = self._get_lesson_ids_in_unit(section_unit_id)
        completed = 0

        for lesson_id in lesson_ids:
            status = progress.get_lesson_status(lesson_id)
            if status in (
                ProgressStatus.COMPLETED,
                ProgressStatus.MASTERED,
            ):
                completed += 1

        return completed

    def _build_lessons(
        self,
        study_plan: StudyPlan,
        progress: ProgressContext,
        pages: list[PageContext] | None = None,
    ) -> list:
        """Build LessonCards from the study plan using configuration."""
        from learning_platform.presentation.mappers.content_mapper import document_nodes_to_content
        from learning_platform.presentation.models import LessonCard

        unit_to_pages: dict[UUID, list[int]] = {}
        if pages:
            for page in pages:
                if page.page_number == 0:
                    continue
                for unit in page.units:
                    unit_to_pages.setdefault(unit.id, []).append(page.page_number)

        lessons: list[LessonCard] = []

        for lesson in study_plan.lessons:
            unit = self._units_by_id.get(lesson.unit_id)
            if unit is None:
                continue

            section_id = self._find_section_id_for_unit(lesson.unit_id)
            objectives = self._map_learning_objectives(lesson.learning_objectives, unit.id)

            lesson_progress = progress.get_lesson_status(lesson.id)
            card_status = self.config.status_mapping.not_started
            if lesson_progress == ProgressStatus.IN_PROGRESS:
                card_status = self.config.status_mapping.in_progress
            elif lesson_progress == ProgressStatus.COMPLETED:
                card_status = self.config.status_mapping.completed
            elif lesson_progress == ProgressStatus.MASTERED:
                card_status = self.config.status_mapping.mastered
            elif lesson_progress == ProgressStatus.PRACTICED:
                card_status = self.config.status_mapping.practiced
            elif lesson_progress == ProgressStatus.ATTEMPTED:
                card_status = self.config.status_mapping.attempted

            completed_at = None
            lesson_progress_data = progress.lesson_progress.get(lesson.id)
            if lesson_progress_data and lesson_progress_data.completed_at:
                completed_at = lesson_progress_data.completed_at.isoformat()

            lesson_pages = unit_to_pages.get(lesson.unit_id, [])
            start_page = min(lesson_pages) if lesson_pages else 0
            end_page = max(lesson_pages) if lesson_pages else 0

            lesson_content = []
            if self._document is not None:
                if start_page > 0:
                    page_nodes = [
                        n for n in self._document.nodes if start_page <= n.page <= end_page
                    ]
                else:
                    page_nodes = list(self._document.nodes)
                lesson_content = document_nodes_to_content(page_nodes)

            lessons.append(
                LessonCard(
                    lesson_id=lesson.id,
                    unit_id=lesson.unit_id,
                    section_id=section_id,
                    title=lesson.title,
                    description=lesson.description,
                    order=lesson.order,
                    duration_minutes=lesson.estimated_minutes,
                    difficulty=self.config.difficulty_mapping.map_difficulty(lesson.difficulty),
                    status=card_status,
                    learning_objectives=objectives,
                    start_page=start_page,
                    end_page=end_page,
                    completed_at=completed_at,
                    content_references=unit.content_references,
                    definitions=unit.definitions,
                    examples=unit.examples,
                    figures=unit.figures,
                    tables=unit.tables,
                    equations=unit.equations,
                    content=lesson_content,
                )
            )

        return self._order_lessons(lessons)

    def _order_lessons(self, lessons: list) -> list:
        """Order lessons based on configuration."""
        ordering = self.config.lesson.ordering

        if ordering.value == "by_study_plan":
            return sorted(lessons, key=lambda x: x.order)
        elif ordering.value == "by_title_alpha":
            return sorted(lessons, key=lambda x: x.title)
        elif ordering.value == "by_difficulty":
            difficulty_order = {
                DifficultyLevel.BEGINNER: 0,
                DifficultyLevel.INTERMEDIATE: 1,
                DifficultyLevel.ADVANCED: 2,
            }
            return sorted(lessons, key=lambda x: difficulty_order.get(x.difficulty, 0))
        elif ordering.value == "by_estimated_time":
            return sorted(lessons, key=lambda x: x.duration_minutes)
        else:
            return sorted(lessons, key=lambda x: x.order)

    def _find_section_id_for_unit(self, unit_id: UUID) -> UUID:
        """Find the section (MODULE) that contains a given unit (memoized)."""
        return self._section_ids.get(unit_id, unit_id)

    def _map_learning_objectives(
        self,
        objective_strings: list[str],
        unit_id: UUID,
    ) -> list[LearningObjective]:
        """Map objective strings to LearningObjective objects with annotation IDs."""
        annotation_ids = self._find_objective_annotation_ids(unit_id)
        return map_learning_objectives(objective_strings, annotation_ids)

    def _find_objective_annotation_ids(self, unit_id: UUID) -> list[UUID]:
        """Find annotation IDs for objective annotations in a unit."""
        unit = self._units_by_id.get(unit_id)
        if unit is None:
            return []

        node_ids = set(unit.source_node_ids)
        return [
            ann.id
            for ann in self._annotations
            if isinstance(ann, ObjectiveAnnotation) and ann.node_id in node_ids
        ]

    def _build_practices(
        self,
        root_unit: LearningUnit,
        sections: list[Section],
        progress: ProgressContext,
    ) -> list[PracticeCard]:
        """Build PracticeCards based on configuration."""
        practices: list[PracticeCard] = []
        order = 0

        if self.config.practice.grouping.value == "by_section":
            for section in sections:
                section_practices = self._build_practices_for_section(
                    section,
                    root_unit,
                    progress,
                    order,
                )
                practices.extend(section_practices)
                order += len(section_practices)
        elif self.config.practice.grouping.value == "flat":
            for section in sections:
                section_unit = self._units_by_id.get(section.section_id)
                if section_unit is None:
                    continue
                exercises = self._get_exercises_in_unit(section_unit.id)
                for exercise_node_id, exercise_title in exercises:
                    practices.append(
                        self._create_practice_card(
                            exercise_node_id,
                            exercise_title,
                            root_unit.id,
                            section.section_id,
                            order,
                            progress,
                        )
                    )
                    order += 1

        return self._order_practices(practices)

    def _build_practices_for_section(
        self,
        section: Section,
        root_unit: LearningUnit,
        progress: ProgressContext,
        start_order: int,
    ) -> list[PracticeCard]:
        """Build practice cards for a specific section."""
        section_unit = self._units_by_id.get(section.section_id)
        if section_unit is None:
            return []

        practices: list[PracticeCard] = []
        order = start_order

        exercises = self._get_exercises_in_unit(section_unit.id)
        for exercise_node_id, exercise_title in exercises:
            practices.append(
                self._create_practice_card(
                    exercise_node_id,
                    exercise_title,
                    root_unit.id,
                    section.section_id,
                    order,
                    progress,
                )
            )
            order += 1

        return practices

    def _resolve_exercise_content(self, node_id: UUID) -> Exercise | None:
        """Look up the Exercise content block for a given document node."""
        if self._document is None:
            return None
        node = self._document.get_node(node_id)
        if node is not None and isinstance(node.content, Exercise):
            return node.content
        return None

    def _create_practice_card(
        self,
        practice_id: UUID,
        title: str,
        unit_id: UUID,
        section_id: UUID,
        order: int,
        progress: ProgressContext,
    ) -> PracticeCard:
        """Create a single PracticeCard."""
        practice_progress = progress.practice_progress.get(practice_id)
        card_status = self.config.status_mapping.not_started
        attempts = 0
        best_score = 0.0

        if practice_progress:
            if practice_progress.status == ProgressStatus.IN_PROGRESS:
                card_status = self.config.status_mapping.in_progress
            elif practice_progress.status == ProgressStatus.COMPLETED:
                card_status = self.config.status_mapping.completed
            elif practice_progress.status == ProgressStatus.MASTERED:
                card_status = self.config.status_mapping.mastered
            elif practice_progress.status == ProgressStatus.PRACTICED:
                card_status = self.config.status_mapping.practiced
            elif practice_progress.status == ProgressStatus.ATTEMPTED:
                card_status = self.config.status_mapping.attempted
            attempts = practice_progress.attempts
            best_score = practice_progress.best_score

        exercise = self._resolve_exercise_content(practice_id)
        question_text = ""
        exercise_type = ""
        options: list[ExerciseOption] = []
        solution = ""
        explanation = ""

        if exercise is not None:
            question_text = exercise.question.plain_text
            exercise_type = str(exercise.exercise_type)
            options = [
                ExerciseOption(
                    label=opt.label,
                    text=opt.text.plain_text,
                    is_correct=opt.is_correct,
                    explanation=opt.explanation,
                )
                for opt in exercise.options
            ]
            solution = exercise.solution
            explanation = exercise.explanation

        return PracticeCard(
            practice_id=practice_id,
            unit_id=unit_id,
            section_id=section_id,
            title=title,
            order=order,
            required_correct=self.config.practice.default_required_correct,
            total_questions=self.config.practice.default_total_questions,
            status=card_status,
            attempts=attempts,
            best_score=best_score,
            question_text=question_text,
            exercise_type=exercise_type,
            options=options,
            solution=solution,
            explanation=explanation,
        )

    def _order_practices(self, practices: list[PracticeCard]) -> list[PracticeCard]:
        """Order practices based on configuration."""
        ordering = self.config.practice.ordering

        if ordering.value == "by_study_plan":
            return sorted(practices, key=lambda x: x.order)
        elif ordering.value == "by_title_alpha":
            return sorted(practices, key=lambda x: x.title)
        else:
            return sorted(practices, key=lambda x: x.order)

    def _get_exercises_in_unit(self, unit_id: UUID) -> list[tuple[UUID, str]]:
        """Get all exercises in a unit as (node_id, title) pairs (memoized)."""
        return self._exercises_index.get(unit_id, [])

    def _build_quizzes(
        self,
        quizzes: list[Quiz],
        progress: ProgressContext,
    ) -> list[QuizCard]:
        """Build QuizCards based on configuration."""
        quiz_cards: list[QuizCard] = []

        for i, quiz in enumerate(quizzes):
            section_id = self._find_section_id_for_quiz(quiz)

            quiz_progress_data = progress.quiz_progress.get(quiz.id)
            card_status = self.config.status_mapping.not_started
            score = None
            completed_at = None

            if quiz_progress_data:
                if quiz_progress_data.status == ProgressStatus.IN_PROGRESS:
                    card_status = self.config.status_mapping.in_progress
                elif quiz_progress_data.status == ProgressStatus.COMPLETED:
                    card_status = self.config.status_mapping.completed
                elif quiz_progress_data.status == ProgressStatus.MASTERED:
                    card_status = self.config.status_mapping.mastered
                elif quiz_progress_data.status == ProgressStatus.ATTEMPTED:
                    card_status = self.config.status_mapping.attempted

                score = quiz_progress_data.score
                if quiz_progress_data.completed_at:
                    completed_at = quiz_progress_data.completed_at.isoformat()

            quiz_cards.append(
                QuizCard(
                    quiz_id=quiz.id,
                    unit_id=quiz.lesson_id or UUID(int=0),
                    section_id=section_id,
                    title=quiz.title,
                    order=i,
                    total_points=quiz.total_points,
                    passing_points=quiz.passing_points,
                    time_limit_minutes=quiz.time_limit_minutes
                    if self.config.quiz.show_time_limit
                    else None,
                    status=card_status,
                    score=score,
                    completed_at=completed_at,
                )
            )

        return self._order_quizzes(quiz_cards)

    def _order_quizzes(self, quizzes: list[QuizCard]) -> list[QuizCard]:
        """Order quizzes based on configuration."""
        ordering = self.config.quiz.ordering

        if ordering.value == "by_study_plan":
            return sorted(quizzes, key=lambda x: x.order)
        elif ordering.value == "by_title_alpha":
            return sorted(quizzes, key=lambda x: x.title)
        else:
            return sorted(quizzes, key=lambda x: x.order)

    def _find_section_id_for_quiz(self, quiz: Quiz) -> UUID:
        """Find the section ID for a quiz based on its lesson."""
        if quiz.lesson_id is None:
            return UUID(int=0)

        return self._find_section_id_for_unit(quiz.lesson_id)

    def _build_milestones(
        self,
        milestones: list[Milestone],
        lessons: list,
        unit_id: UUID,
        progress: ProgressContext,
    ) -> list[MilestoneCard]:
        """Build MilestoneCards based on configuration."""
        milestone_cards: list[MilestoneCard] = []

        for milestone in milestones:
            completed_count = 0
            for lesson_id in milestone.lesson_ids:
                lesson_status = progress.get_lesson_status(lesson_id)
                if lesson_status in (
                    ProgressStatus.COMPLETED,
                    ProgressStatus.MASTERED,
                ):
                    completed_count += 1

            lesson_count = len(milestone.lesson_ids)
            if lesson_count == 0:
                card_status = self.config.status_mapping.not_started
            elif completed_count == lesson_count:
                card_status = self.config.status_mapping.mastered
            elif completed_count > 0:
                card_status = self.config.status_mapping.in_progress
            else:
                card_status = self.config.status_mapping.not_started

            milestone_cards.append(
                MilestoneCard(
                    milestone_id=milestone.id,
                    unit_id=unit_id,
                    title=milestone.title,
                    description=milestone.description,
                    order=milestone.order,
                    estimated_minutes=milestone.estimated_minutes,
                    lesson_count=lesson_count,
                    completed_lesson_count=completed_count
                    if self.config.goal.show_completed_count
                    else 0,
                    status=card_status,
                )
            )

        return sorted(milestone_cards, key=lambda x: x.order)

    def _build_progress_summary(
        self,
        unit: LearningUnit,
        progress: ProgressContext,
    ) -> ProgressSummary:
        """Build ProgressSummary for the unit."""
        unit_progress = progress.get_unit_progress(unit.id)

        total_minutes = self._calculate_estimated_time(unit)
        studied_minutes = unit_progress.total_minutes_studied
        remaining_minutes = max(0, total_minutes - studied_minutes)

        return ProgressSummary(
            total_items=unit_progress.total_items,
            completed_items=unit_progress.completed_items,
            mastery_pct=self._calculate_progress_pct(unit_progress),
            total_minutes_studied=studied_minutes,
            estimated_remaining_minutes=remaining_minutes,
        )

    def _calculate_progress_pct(self, unit_progress: Any) -> float:
        """Calculate progress percentage."""
        if unit_progress.total_items == 0:
            return 0.0
        return round((unit_progress.completed_items / unit_progress.total_items) * 100, 2)
