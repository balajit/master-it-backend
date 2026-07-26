"""Learning Experience Mapper — transforms pipeline output to StudyExperience.

This module implements the concrete mapper that transforms canonical domain
models (Document, Learning Units, Annotations, Concept Map, Knowledge Graph,
Study Plan) into the presentation model shown on the study screen.

Design Principles
-----------------
- **No side effects**: Only transforms data, never mutates inputs.
- **Pure composition**: Assembles presentation models from domain objects.
- **Configurable**: Layout rules are controlled by MappingConfiguration.
- **Extensible**: Additional mappers can be added for different formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from learning_platform.models.annotation import Annotation, ObjectiveAnnotation
from learning_platform.models.concept import ConceptMap
from learning_platform.models.document import CanonicalDocument, Exercise
from learning_platform.models.knowledge_graph import KnowledgeGraph
from learning_platform.models.learning_unit import LearningUnit, UnitType
from learning_platform.models.page_context import PageContext
from learning_platform.models.quiz import Quiz
from learning_platform.models.sequence import (
    Milestone,
    StudyPlan,
)
from learning_platform.presentation.mappers.configuration import (
    MappingConfiguration,
    SectionGroupingStrategy,
    create_default_config,
)
from learning_platform.presentation.mappers.context import (
    ProgressContext,
    ProgressStatus,
)
from learning_platform.presentation.mappers.protocols import map_learning_objectives
from learning_platform.presentation.models import (
    CardStatus,
    DifficultyLevel,
    ExerciseOption,
    LearningObjective,
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

# ──────────────────────────────────────────────────────────────────────────────
# Input Data Structure
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineOutput:
    """Aggregated output from the learning pipeline.

    This is the input to the mapper. It contains all the domain objects
    produced by the pipeline stages.
    """

    document: CanonicalDocument
    learning_units: list[LearningUnit]
    annotations: list[Annotation]
    concept_map: ConceptMap
    knowledge_graph: KnowledgeGraph
    study_plan: StudyPlan
    quizzes: list[Quiz]
    pages: list[PageContext] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Status Legend Builder
# ──────────────────────────────────────────────────────────────────────────────


def _build_status_legend_from_config(
    config: MappingConfiguration,
) -> list[StatusLegend]:
    """Build status legend from configuration."""
    if not config.status_legend.show_legend:
        return []

    # Use custom legend if provided
    if config.status_legend.custom_legend is not None:
        return [
            StatusLegend(
                status=CardStatus(item.get("status", "not_started")),
                label=item.get("label", ""),
                description=item.get("description", ""),
                icon_name=item.get("icon_name", ""),
                color_hex=item.get("color_hex", ""),
            )
            for item in config.status_legend.custom_legend
        ]

    # Default legend
    return [
        StatusLegend(
            status=CardStatus.NOT_STARTED,
            label="Not Started",
            description="You haven't begun this lesson yet",
            icon_name="circle-outline",
            color_hex="#E5E7EB",
        ),
        StatusLegend(
            status=CardStatus.IN_PROGRESS,
            label="In Progress",
            description="You're currently working on this",
            icon_name="circle-half",
            color_hex="#FCD34D",
        ),
        StatusLegend(
            status=CardStatus.COMPLETED,
            label="Completed",
            description="You've finished this lesson",
            icon_name="check-circle",
            color_hex="#34D399",
        ),
        StatusLegend(
            status=CardStatus.MASTERED,
            label="Mastered",
            description="You've demonstrated mastery",
            icon_name="star",
            color_hex="#10B981",
        ),
        StatusLegend(
            status=CardStatus.LOCKED,
            label="Locked",
            description="Complete prerequisites to unlock",
            icon_name="lock",
            color_hex="#9CA3AF",
        ),
        StatusLegend(
            status=CardStatus.PRACTICED,
            label="Practiced",
            description="You've practiced this material",
            icon_name="repeat",
            color_hex="#60A5FA",
        ),
        StatusLegend(
            status=CardStatus.ATTEMPTED,
            label="Attempted",
            description="You've attempted this assessment",
            icon_name="pencil",
            color_hex="#A78BFA",
        ),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Learning Experience Mapper
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class LearningExperienceMapper:
    """Transforms pipeline output into a StudyExperience.

    This mapper takes all the domain objects produced by the pipeline
    and composes the presentation model shown on the study screen.
    It does not modify any domain objects — only creates new presentation
    models from them.

    The mapper reads layout rules from MappingConfiguration, allowing
    different learning platform layouts without changing code.
    """

    # ── Configuration ──
    config: MappingConfiguration = field(default_factory=create_default_config)

    # ── Internal indices (built once, used across all mapping methods) ──
    _units_by_id: dict[UUID, LearningUnit] = field(default_factory=dict)
    _unit_ids_by_type: dict[UnitType, list[UUID]] = field(default_factory=dict)
    _annotations: list[Annotation] = field(default_factory=list)
    _document: CanonicalDocument | None = None

    # ── Memoized tree indices (single-pass bottom-up, O(1) lookups) ──
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
        """Transform pipeline output into a StudyExperience.

        Parameters
        ----------
        pipeline_output : PipelineOutput
            All domain objects from the pipeline.
        progress : ProgressContext
            User progress data from the database.

        Returns
        -------
        StudyExperience
            The complete presentation model for the study screen.
        """
        # Build internal indices for efficient lookup
        self._build_indices(pipeline_output.learning_units)
        self._annotations = pipeline_output.annotations
        self._document = pipeline_output.document
        self._compute_memoized_indices(pipeline_output.pages)

        # Find the root unit (COURSE level)
        root_unit = self._find_root_unit(pipeline_output.learning_units)
        if root_unit is None:
            raise ValueError("No root COURSE unit found in learning units")

        # Build all presentation components using configuration
        unit_card = self._build_unit_card(root_unit, progress)
        sections = self._build_sections(root_unit, pipeline_output, progress)
        lessons = self._build_lessons(pipeline_output.study_plan, progress, pipeline_output.pages)
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

    # ── Index Building ───────────────────────────────────────────────────

    def _build_indices(self, units: list[LearningUnit]) -> None:
        """Build internal lookup indices from the list of units."""
        self._units_by_id = {unit.id: unit for unit in units}
        self._unit_ids_by_type = {}
        for unit in units:
            self._unit_ids_by_type.setdefault(unit.unit_type, []).append(unit.id)

    def _compute_memoized_indices(self, pages: list[PageContext]) -> None:
        """Single bottom-up pass to pre-compute all recursive tree lookups.

        Populates ``_descendant_ids``, ``_lesson_counts``, ``_exercise_counts``,
        ``_lesson_ids``, ``_page_ranges``, ``_section_ids``, and ``_exercises_index``
        so that every downstream method can do O(1) dict lookups instead of
        re-walking the tree per section / lesson / practice.
        """
        # ── 1. Leaf initialization ───────────────────────────────────────
        #    For each unit, seed values from its own data.
        unit_ids = list(self._units_by_id.keys())
        for uid in unit_ids:
            unit = self._units_by_id[uid]
            self._descendant_ids[uid] = {uid}
            self._lesson_counts[uid] = 1 if unit.unit_type == UnitType.LESSON else 0
            self._exercise_counts[uid] = len(unit.exercises)
            self._lesson_ids[uid] = {uid} if unit.unit_type == UnitType.LESSON else set()
            self._exercises_index[uid] = [
                (ref.node_id, ref.summary or f"Practice {str(ref.node_id)[:8]}")
                for ref in unit.exercises
            ]

        # ── 2. Page ranges from PageContext (before bottom-up) ──────────
        #    Seed each unit that appears on a page with its page number.
        for page in pages:
            if page.page_number == 0:
                continue
            for page_unit in page.units:
                uid = page_unit.id
                if uid not in self._units_by_id:
                    continue
                cur_s, cur_e = self._page_ranges.get(uid, (0, 0))
                if cur_s == 0:
                    self._page_ranges[uid] = (
                        page.page_number, page.page_number,
                    )
                else:
                    self._page_ranges[uid] = (
                        min(cur_s, page.page_number),
                        max(cur_e, page.page_number),
                    )

        # ── 3. Bottom-up aggregation (children → parent) ─────────────────
        #    Process leaves first so children are computed before parents.
        children_done: set[UUID] = set()
        remaining = set(unit_ids)
        order: list[UUID] = []

        # Units with no children are leaves — they go first
        for uid in unit_ids:
            unit = self._units_by_id[uid]
            if not unit.children_ids or all(
                c not in self._units_by_id for c in unit.children_ids
            ):
                order.append(uid)
                children_done.add(uid)
                remaining.discard(uid)

        # Iteratively add units whose children are all already processed
        while remaining:
            progress_made = False
            for uid in list(remaining):
                unit = self._units_by_id[uid]
                if all(
                    c in children_done or c not in self._units_by_id
                    for c in unit.children_ids
                ):
                    order.append(uid)
                    children_done.add(uid)
                    remaining.discard(uid)
                    progress_made = True
            if not progress_made:
                order.extend(remaining)
                break

        for uid in order:
            unit = self._units_by_id.get(uid)
            if unit is None:
                continue
            for child_id in unit.children_ids:
                if child_id not in self._units_by_id:
                    continue
                self._descendant_ids[uid].update(
                    self._descendant_ids[child_id],
                )
                self._lesson_counts[uid] += self._lesson_counts[child_id]
                self._exercise_counts[uid] += self._exercise_counts[
                    child_id
                ]
                self._lesson_ids[uid].update(self._lesson_ids[child_id])
                self._exercises_index[uid].extend(
                    self._exercises_index[child_id],
                )

                # Page range: merge child ranges into parent
                child_range = self._page_ranges.get(child_id)
                if child_range is not None:
                    s, e = child_range
                    if s > 0:
                        cur_s, cur_e = self._page_ranges.get(uid, (0, 0))
                        if cur_s == 0:
                            self._page_ranges[uid] = (s, e)
                        else:
                            self._page_ranges[uid] = (
                                min(cur_s, s), max(cur_e, e),
                            )

        # ── 4. Section IDs (top-down) ───────────────────────────────────
        #    Walk from root downward: MODULEs set their own ID; others
        #    inherit their parent's section ID.
        root = self._find_root_unit(list(self._units_by_id.values()))
        if root is not None:
            self._section_ids[root.id] = root.id
            queue = list(root.children_ids)
            while queue:
                cid = queue.pop(0)
                unit = self._units_by_id.get(cid)
                if unit is None:
                    continue
                if unit.unit_type == UnitType.MODULE:
                    self._section_ids[cid] = cid
                else:
                    self._section_ids[cid] = self._section_ids.get(
                        unit.parent_id, cid,
                    )
                queue.extend(unit.children_ids)

    def _find_root_unit(self, units: list[LearningUnit]) -> LearningUnit | None:
        """Find the root COURSE-level unit."""
        for unit in units:
            if unit.unit_type == UnitType.COURSE and unit.parent_id is None:
                return unit
        return None

    def _get_children(self, unit_id: UUID) -> list[LearningUnit]:
        """Get child units for a given unit, in order."""
        unit = self._units_by_id.get(unit_id)
        if unit is None:
            return []
        return [
            self._units_by_id[child_id]
            for child_id in unit.children_ids
            if child_id in self._units_by_id
        ]

    # ── Unit Card ────────────────────────────────────────────────────────

    def _build_unit_card(
        self,
        unit: LearningUnit,
        progress: ProgressContext,
    ) -> UnitCard:
        """Build the top-level UnitCard from a COURSE-level LearningUnit."""
        # Count sections based on configuration
        section_children = self._get_section_children(unit)

        # Count all lessons recursively
        total_lessons = self._count_lessons_recursive(unit.id)

        # Get progress
        unit_progress = progress.get_unit_progress(unit.id)

        # Calculate estimated time using configuration
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
            # In flat mode, all children are treated as sections
            return children
        else:
            # For other strategies, group by MODULE level by default
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
            # Placeholder for weighted average calculation
            return unit.estimated_study_time_minutes
        else:
            return unit.estimated_study_time_minutes

    # ── Sections ─────────────────────────────────────────────────────────

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
                child, root_unit, pipeline_output, progress, order
            )
            # Apply minimum lessons filter if configured
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
        # Count lessons in this section
        lesson_count = self._count_lessons_recursive(section_unit.id)

        # Count practices (exercises in child units)
        practice_count = self._count_exercises_recursive(section_unit.id)

        # Count quizzes for lessons in this section
        quiz_count = self._count_quizzes_for_section(section_unit, pipeline_output.quizzes)

        # Get completed count from progress
        completed_count = self._get_section_completed_count(section_unit.id, progress)

        # Calculate estimated time
        estimated_minutes = self._calculate_estimated_time(section_unit)

        # Resolve page range: first and last pages containing any child unit's content
        start_page, end_page = self._find_page_range_for_unit(
            section_unit.id, pipeline_output.pages,
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

    # ── Lessons ──────────────────────────────────────────────────────────

    def _build_lessons(
        self,
        study_plan: StudyPlan,
        progress: ProgressContext,
        pages: list[PageContext] | None = None,
    ) -> list:
        """Build LessonCards from the study plan using configuration."""
        from learning_platform.presentation.models import LessonCard

        # Build a unit_id → list[page_number] lookup from page contexts
        unit_to_pages: dict[UUID, list[int]] = {}
        if pages:
            for page in pages:
                if page.page_number == 0:
                    continue
                for unit in page.units:
                    unit_to_pages.setdefault(unit.id, []).append(page.page_number)

        lessons: list[LessonCard] = []

        for lesson in study_plan.lessons:
            # Find the corresponding LearningUnit
            unit = self._units_by_id.get(lesson.unit_id)
            if unit is None:
                continue

            # Determine section_id (parent MODULE)
            section_id = self._find_section_id_for_unit(lesson.unit_id)

            # Get learning objectives with annotation IDs
            objectives = self._map_learning_objectives(lesson.learning_objectives, unit.id)

            # Get progress status using configured mapping
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

            # Get completion timestamp
            completed_at = None
            lesson_progress_data = progress.lesson_progress.get(lesson.id)
            if lesson_progress_data and lesson_progress_data.completed_at:
                completed_at = lesson_progress_data.completed_at.isoformat()

            # Resolve page range from page contexts
            lesson_pages = unit_to_pages.get(lesson.unit_id, [])
            start_page = min(lesson_pages) if lesson_pages else 0
            end_page = max(lesson_pages) if lesson_pages else 0

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
                )
            )

        # Apply ordering based on configuration
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
        """Find annotation IDs for objective annotations in a unit.

        Iterates the annotations list in the same order the unit builder
        did when populating ``learning_objectives``, so each returned ID
        aligns positionally with the corresponding objective string.
        """
        unit = self._units_by_id.get(unit_id)
        if unit is None:
            return []

        node_ids = set(unit.source_node_ids)
        return [
            ann.id
            for ann in self._annotations
            if isinstance(ann, ObjectiveAnnotation)
            and ann.node_id in node_ids
        ]

    # ── Practices ────────────────────────────────────────────────────────

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
            # Group practices by section
            for section in sections:
                section_practices = self._build_practices_for_section(
                    section, root_unit, progress, order
                )
                practices.extend(section_practices)
                order += len(section_practices)
        elif self.config.practice.grouping.value == "flat":
            # All practices in a flat list
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

        # Apply ordering
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
        # Get progress
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

        # Resolve exercise content from the canonical document
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

    # ── Quizzes ──────────────────────────────────────────────────────────

    def _build_quizzes(
        self,
        quizzes: list[Quiz],
        progress: ProgressContext,
    ) -> list[QuizCard]:
        """Build QuizCards based on configuration."""
        quiz_cards: list[QuizCard] = []

        for i, quiz in enumerate(quizzes):
            section_id = self._find_section_id_for_quiz(quiz)

            # Get progress using configured mapping
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

        # Apply ordering
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

    # ── Milestones ───────────────────────────────────────────────────────

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

        # Order milestones based on configuration
        return sorted(milestone_cards, key=lambda x: x.order)

    # ── Pages ────────────────────────────────────────────────────────────

    def _build_pages(
        self,
        pages: list[PageContext],
        units: list[LearningUnit],
    ) -> list[PageView]:
        """Build PageView objects from pipeline page contexts.

        Skips page 0 (unknown page) and pages that only contain
        structural nodes (page groups, headers, footers).
        """
        # Build unit_id → unit lookup for title resolution
        unit_lookup = {u.id: u for u in units}

        page_views: list[PageView] = []
        for page in pages:
            # Skip the synthetic page 0
            if page.page_number == 0:
                continue

            # Collect unit IDs from page context, resolving titles
            unit_ids: list[UUID] = []
            for unit in page.units:
                if unit.id not in unit_lookup:
                    continue
                unit_ids.append(unit.id)

            # Collect annotation IDs
            annotation_ids: list[UUID] = [ann.id for ann in page.annotations]

            # Collect concept IDs
            concept_ids: list[UUID] = [concept.id for concept in page.concepts]

            # Use page heading as title, fall back to empty
            title = page.heading or ""

            # Truncate text preview to 280 chars for display
            text_preview = page.page_text[:280]

            page_views.append(
                PageView(
                    page_number=page.page_number,
                    title=title,
                    text_preview=text_preview,
                    full_text=page.page_text,
                    unit_ids=unit_ids,
                    annotation_ids=annotation_ids,
                    concept_ids=concept_ids,
                )
            )

        return page_views

    # ── Progress Summary ─────────────────────────────────────────────────

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

    # ── Navigation ───────────────────────────────────────────────────────

    def _build_navigation(
        self,
        root_unit: LearningUnit,
        progress: ProgressContext,
    ) -> list[NavigationNode]:
        """Build navigation hierarchy based on configuration."""
        nodes: list[NavigationNode] = []
        self._build_navigation_recursive(root_unit, None, nodes, progress, 0)
        return nodes

    def _build_navigation_recursive(
        self,
        unit: LearningUnit,
        parent_id: UUID | None,
        nodes: list[NavigationNode],
        progress: ProgressContext,
        depth: int,
    ) -> None:
        """Recursively build navigation nodes."""
        # Check max depth
        if (
            self.config.navigation.max_depth is not None
            and depth >= self.config.navigation.max_depth
        ):
            return

        # Map unit type to navigation node type
        node_type = self._map_unit_type_to_navigation_type(unit.unit_type)

        # Get status
        unit_progress = progress.get_unit_progress(unit.id)
        if self.config.navigation.show_status:
            card_status = (
                self.config.status_mapping.mastered
                if unit_progress.completed_items > 0
                else self.config.status_mapping.not_started
            )
        else:
            card_status = CardStatus.NOT_STARTED

        # Check if this is the current node
        is_current = (
            self.config.navigation.highlight_current and progress.current_node_id == unit.id
        )

        node = NavigationNode(
            node_id=unit.id,
            node_type=node_type,
            title=unit.title,
            parent_id=parent_id,
            children_ids=unit.children_ids,
            unit_id=unit.id,
            order=len(nodes),
            is_current=is_current,
            is_accessible=True,
            status=card_status,
        )
        nodes.append(node)

        # Recurse into children
        for child_id in unit.children_ids:
            child_unit = self._units_by_id.get(child_id)
            if child_unit:
                self._build_navigation_recursive(child_unit, unit.id, nodes, progress, depth + 1)

    # ── Helper Methods ───────────────────────────────────────────────────

    def _find_start_page_for_unit(
        self,
        unit_id: UUID,
        pages: list[PageContext],
    ) -> int:
        """Find the first page number where this unit or any of its children have content."""
        start, _end = self._find_page_range_for_unit(unit_id, pages)
        return start

    def _find_page_range_for_unit(
        self,
        unit_id: UUID,
        pages: list[PageContext],
    ) -> tuple[int, int]:
        """Find (start, end) page range for a unit (memoized)."""
        return self._page_ranges.get(unit_id, (0, 0))

    def _collect_descendant_ids(self, unit_id: UUID) -> set[UUID]:
        """Collect the IDs of a unit and all its descendants (memoized)."""
        return self._descendant_ids.get(unit_id, set())

    def _map_unit_type_to_navigation_type(self, unit_type: UnitType) -> NavigationNodeType:
        """Map UnitType to NavigationNodeType."""
        type_map = {
            UnitType.COURSE: NavigationNodeType.COURSE,
            UnitType.MODULE: NavigationNodeType.MODULE,
            UnitType.LESSON: NavigationNodeType.LESSON,
            UnitType.TOPIC: NavigationNodeType.TOPIC,
        }
        return type_map.get(unit_type, NavigationNodeType.TOPIC)


# ──────────────────────────────────────────────────────────────────────────────
# Public Factory Functions
# ──────────────────────────────────────────────────────────────────────────────


def create_learning_experience(
    pipeline_output: PipelineOutput,
    progress: ProgressContext,
    config: MappingConfiguration | None = None,
) -> StudyExperience:
    """Create a StudyExperience from pipeline output and user progress.

    This is the main entry point for the presentation mapping layer.

    Parameters
    ----------
    pipeline_output : PipelineOutput
        All domain objects from the pipeline.
    progress : ProgressContext
        User progress data from the database.
    config : MappingConfiguration | None
        Optional configuration. If None, uses default configuration.

    Returns
    -------
    StudyExperience
        The complete presentation model for the study screen.

    Example
    -------
    ::

        from learning_platform.presentation.mappers import (
            PipelineOutput,
            ProgressContext,
            MappingConfiguration,
            create_learning_experience,
        )

        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=units,
            annotations=annotations,
            concept_map=concept_map,
            knowledge_graph=kg,
            study_plan=plan,
            quizzes=quizzes,
        )

        progress = ProgressContext(
            user_id=123,
            course_id=456,
            lesson_progress={...},
        )

        # Use default config
        experience = create_learning_experience(pipeline_output, progress)

        # Or use custom config
        config = MappingConfiguration(
            section=SectionConfig(
                grouping=SectionGroupingStrategy.FLAT,
            ),
        )
        experience = create_learning_experience(pipeline_output, progress, config)
    """
    if config is None:
        config = create_default_config()

    mapper = LearningExperienceMapper(config=config)
    return mapper.map(pipeline_output, progress)
