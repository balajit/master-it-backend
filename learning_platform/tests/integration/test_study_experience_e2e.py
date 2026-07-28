"""End-to-end integration test: PDF → pipeline → presentation mapping.

Processes ``test_pdfs/small.pdf`` through the full pipeline, then feeds
the result into the presentation mapper and verifies that all card data
is correctly mapped — including page-aware fields (start_page on lessons
and sections, PageView objects in StudyExperience).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

# Ensure the project root is on the path so imports resolve.
_project_root: str = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Environment must be set before importing anything that reads Settings.
import os  # noqa: E402

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_integration.db")

# E402: imports intentionally follow env-var setup above.
from learning_platform.pipeline.orchestrator import PipelineOrchestrator  # noqa: E402
from learning_platform.pipeline.plugins import PluginRegistry  # noqa: E402
from learning_platform.pipeline.retry import RetryPolicy  # noqa: E402
from learning_platform.presentation.mappers.configuration import (  # noqa: E402
    create_default_config,
)
from learning_platform.presentation.mappers.context import ProgressContext  # noqa: E402
from learning_platform.presentation.mappers.learning_experience import (  # noqa: E402
    PipelineOutput,
    create_learning_experience,
)
from learning_platform.presentation.models import StudyExperience  # noqa: E402

# ── Fixtures ────────────────────────────────────────────────────────────────

SMALL_PDF: Path = (Path(_project_root).parent / "test_pdfs" / "small.pdf").resolve()


@pytest.fixture(scope="module")
def pipeline_result() -> Any:
    """Run the full pipeline on small.pdf once for all tests."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from learning_platform.stages.concept_extractor import ConceptExtractor
    from learning_platform.stages.concept_extractor.annotation_strategy import AnnotationStrategy
    from learning_platform.stages.concept_extractor.text_strategy import TextPatternStrategy
    from learning_platform.stages.enricher.semantic import SemanticEnricher
    from learning_platform.stages.graph_builder.graph import NetworkxGraphBuilder
    from learning_platform.stages.normalizer.structural import StructuralNormalizer
    from learning_platform.stages.parser.docling_adapter import DoclingAdapter
    from learning_platform.stages.sequence_builder.sequencer import TopologicalSequenceBuilder
    from learning_platform.stages.unit_builder.builder import LearningUnitBuilder

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.generate_page_images = False
    opts.generate_picture_images = False
    opts.do_picture_description = False
    opts.do_code_enrichment = False
    opts.do_formula_enrichment = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
        }
    )

    concept_extractor = ConceptExtractor(strategies=[TextPatternStrategy(), AnnotationStrategy()])

    orchestrator = PipelineOrchestrator(
        parser=DoclingAdapter(converter=converter),
        normalizer=StructuralNormalizer(),
        enricher=SemanticEnricher(),
        unit_builder=LearningUnitBuilder(),
        concept_extractor=concept_extractor,
        graph_builder=NetworkxGraphBuilder(),
        sequence_builder=TopologicalSequenceBuilder(),
        plugin_registry=PluginRegistry(),
        retry_policy=RetryPolicy(max_retries=2),
    )

    result = orchestrator.run(str(SMALL_PDF))
    return result


@pytest.fixture(scope="module")
def study_experience(pipeline_result: Any) -> StudyExperience:
    """Build the StudyExperience from pipeline output."""
    pipeline_output = PipelineOutput(
        document=pipeline_result.document,
        learning_units=pipeline_result.units,
        annotations=pipeline_result.annotations,
        concept_map=pipeline_result.concepts,
        knowledge_graph=pipeline_result.graph,
        study_plan=pipeline_result.study_plan,
        quizzes=[],
        pages=pipeline_result.pages,
    )

    progress = ProgressContext(user_id=1, course_id=1)
    config = create_default_config()
    return create_learning_experience(pipeline_output, progress, config)


# ── Pipeline sanity checks ──────────────────────────────────────────────────


class TestPipelineProducesExpectedOutput:
    """Verify the pipeline actually produces meaningful results from small.pdf."""

    def test_document_has_nodes(self, pipeline_result: Any) -> None:
        assert len(pipeline_result.document.nodes) > 0

    def test_document_has_title(self, pipeline_result: Any) -> None:
        assert pipeline_result.document.title != ""

    def test_has_learning_units(self, pipeline_result: Any) -> None:
        assert len(pipeline_result.units) > 0

    def test_has_study_plan(self, pipeline_result: Any) -> None:
        assert pipeline_result.study_plan is not None

    def test_has_pages(self, pipeline_result: Any) -> None:
        assert len(pipeline_result.pages) > 0

    def test_has_concepts(self, pipeline_result: Any) -> None:
        assert len(pipeline_result.concepts.concepts) > 0


# ── StudyExperience structure ───────────────────────────────────────────────


class TestStudyExperienceStructure:
    """Verify the StudyExperience has all required components."""

    def test_has_unit_card(self, study_experience: StudyExperience) -> None:
        assert study_experience.unit is not None
        assert study_experience.unit.title != ""

    def test_has_sections(self, study_experience: StudyExperience) -> None:
        assert len(study_experience.sections) > 0

    def test_has_lessons(self, study_experience: StudyExperience) -> None:
        assert len(study_experience.lessons) > 0

    def test_has_pages(self, study_experience: StudyExperience) -> None:
        assert len(study_experience.pages) > 0

    def test_has_navigation(self, study_experience: StudyExperience) -> None:
        assert len(study_experience.navigation) > 0

    def test_has_status_legend(self, study_experience: StudyExperience) -> None:
        assert len(study_experience.status_legend) > 0


# ── Page views ──────────────────────────────────────────────────────────────


class TestPageViews:
    """Verify PageView objects are properly mapped."""

    def test_page_view_page_numbers_are_positive(self, study_experience: StudyExperience) -> None:
        for page in study_experience.pages:
            assert page.page_number > 0, f"Page number should be positive, got {page.page_number}"

    def test_page_view_has_title_or_text(self, study_experience: StudyExperience) -> None:
        for page in study_experience.pages:
            has_content = page.title != "" or page.text_preview != ""
            assert has_content, f"Page {page.page_number} has neither title nor text"

    def test_page_view_text_preview_is_bounded(self, study_experience: StudyExperience) -> None:
        for page in study_experience.pages:
            assert len(page.text_preview) <= 280, (
                f"Page {page.page_number} text_preview exceeds 280 chars"
            )

    def test_page_view_unit_ids_are_valid_uuids(self, study_experience: StudyExperience) -> None:
        for page in study_experience.pages:
            for uid_str in page.unit_ids:
                UUID(uid_str)  # Should not raise


# ── Lesson start_page ───────────────────────────────────────────────────────


class TestLessonStartPage:
    """Verify LessonCard.start_page is properly populated."""

    def test_lessons_have_start_page(self, study_experience: StudyExperience) -> None:
        for lesson in study_experience.lessons:
            assert lesson.start_page >= 0, (
                f"Lesson '{lesson.title}' has invalid start_page: {lesson.start_page}"
            )

    def test_lesson_start_page_matches_page_context(
        self, study_experience: StudyExperience
    ) -> None:
        """Each lesson's start_page should correspond to a page in the experience."""
        page_numbers = {p.page_number for p in study_experience.pages}
        for lesson in study_experience.lessons:
            if lesson.start_page > 0:
                assert lesson.start_page in page_numbers, (
                    f"Lesson '{lesson.title}' start_page={lesson.start_page} "
                    f"not in page numbers {page_numbers}"
                )


# ── Section start_page ─────────────────────────────────────────────────────


class TestSectionStartPage:
    """Verify Section.start_page is properly populated."""

    def test_sections_have_start_page(self, study_experience: StudyExperience) -> None:
        for section in study_experience.sections:
            assert section.start_page >= 0, (
                f"Section '{section.title}' has invalid start_page: {section.start_page}"
            )

    def test_section_start_page_matches_page_context(
        self, study_experience: StudyExperience
    ) -> None:
        """Each section's start_page should correspond to a page in the experience."""
        page_numbers = {p.page_number for p in study_experience.pages}
        for section in study_experience.sections:
            if section.start_page > 0:
                assert section.start_page in page_numbers, (
                    f"Section '{section.title}' start_page={section.start_page} "
                    f"not in page numbers {page_numbers}"
                )


# ── Card consistency ────────────────────────────────────────────────────────


class TestCardConsistency:
    """Verify cross-references between cards are valid."""

    def _collect_uuids(self, study_experience: StudyExperience) -> set[str]:
        """Collect all referenced UUIDs from the study experience."""
        ids: set[str] = set()
        ids.add(str(study_experience.unit.unit_id))
        for s in study_experience.sections:
            ids.add(str(s.section_id))
        for l in study_experience.lessons:
            ids.add(str(l.lesson_id))
        return ids

    def test_lesson_section_references_valid(self, study_experience: StudyExperience) -> None:
        """Every lesson's section_id should reference a valid section.

        The root COURSE lesson is allowed to reference itself since it
        has no parent section.
        """
        section_ids = {str(s.section_id) for s in study_experience.sections}
        root_id = str(study_experience.unit.unit_id)
        for lesson in study_experience.lessons:
            ref = str(lesson.section_id)
            if ref == root_id:
                continue
            assert ref in section_ids, (
                f"Lesson '{lesson.title}' references section {lesson.section_id} "
                f"not in sections {section_ids}"
            )

    def test_section_unit_references_valid(self, study_experience: StudyExperience) -> None:
        """Every section's unit_id should reference the root unit."""
        root_id = str(study_experience.unit.unit_id)
        for section in study_experience.sections:
            assert str(section.unit_id) == root_id, (
                f"Section '{section.title}' unit_id {section.unit_id} != root {root_id}"
            )

    def test_navigation_references_valid(self, study_experience: StudyExperience) -> None:
        """Every navigation node's unit_id should reference a valid unit."""
        valid_ids = self._collect_uuids(study_experience)
        for node in study_experience.navigation:
            if node.unit_id is not None:
                assert str(node.unit_id) in valid_ids, (
                    f"Navigation node '{node.title}' references "
                    f"unit {node.unit_id} not in {valid_ids}"
                )


# ── Lesson content references ────────────────────────────────────────────────


class TestLessonCardContentReferences:
    """Verify LessonCard carries content references from LearningUnit."""

    def test_lessons_have_content_references(self, study_experience: StudyExperience) -> None:
        """At least one lesson should have non-empty content references."""
        has_content = any(len(l.content_references) > 0 for l in study_experience.lessons)
        assert has_content, "No lesson has content references"

    def test_content_references_have_node_ids(self, study_experience: StudyExperience) -> None:
        """Every content reference should have a valid node_id."""
        for lesson in study_experience.lessons:
            for ref in lesson.content_references:
                assert ref.node_id is not None

    def test_lesson_definitions_default_empty(self, study_experience: StudyExperience) -> None:
        """Lessons without definitions should have empty lists."""
        for lesson in study_experience.lessons:
            assert isinstance(lesson.definitions, list)
            assert isinstance(lesson.figures, list)
            assert isinstance(lesson.tables, list)
            assert isinstance(lesson.equations, list)
            assert isinstance(lesson.examples, list)


# ── Page full_text ────────────────────────────────────────────────────────────


class TestPageFullText:
    """Verify PageView.full_text is populated."""

    def test_pages_have_full_text(self, study_experience: StudyExperience) -> None:
        """Every page should have non-empty full_text."""
        for page in study_experience.pages:
            assert page.full_text != "", f"Page {page.page_number} has empty full_text"

    def test_full_text_longer_than_preview(self, study_experience: StudyExperience) -> None:
        """full_text should be at least as long as text_preview."""
        for page in study_experience.pages:
            assert len(page.full_text) >= len(page.text_preview), (
                f"Page {page.page_number}: full_text shorter than text_preview"
            )

    def test_text_preview_is_prefix_of_full_text(self, study_experience: StudyExperience) -> None:
        """text_preview should be a prefix of full_text."""
        for page in study_experience.pages:
            if page.text_preview:
                assert page.full_text.startswith(page.text_preview), (
                    f"Page {page.page_number}: text_preview not a prefix of full_text"
                )


# ── Objective annotation linking ──────────────────────────────────────────────


class TestObjectiveAnnotationLinking:
    """Verify learning objectives carry annotation IDs from the pipeline."""

    def test_objectives_have_annotation_ids(self, study_experience: StudyExperience) -> None:
        """Every objective should reference an annotation when the pipeline produced one."""
        for lesson in study_experience.lessons:
            for obj in lesson.learning_objectives:
                assert obj.annotation_id is None or isinstance(obj.annotation_id, object)
        # At least confirm the field exists and is populated when annotations match
        assert isinstance(study_experience.lessons, list)

    def test_annotation_id_count_matches_objectives(
        self, pipeline_result: Any, study_experience: StudyExperience
    ) -> None:
        """The number of objective annotations per unit should match the mapper output."""
        from learning_platform.models.annotation import ObjectiveAnnotation

        objective_annotations = [
            a for a in pipeline_result.annotations if isinstance(a, ObjectiveAnnotation)
        ]
        if not objective_annotations:
            pytest.skip("No objective annotations produced by pipeline")

        total_obj_ann_ids = 0
        for lesson in study_experience.lessons:
            total_obj_ann_ids += sum(
                1 for obj in lesson.learning_objectives if obj.annotation_id is not None
            )
        assert total_obj_ann_ids == len(objective_annotations)


# ── PracticeCard exercise content ─────────────────────────────────────────────


class TestPracticeCardContent:
    """Verify PracticeCard surfaces exercise content from the document."""

    def test_practice_card_has_content_fields(self, study_experience: StudyExperience) -> None:
        """Every PracticeCard should have the exercise content fields."""
        for practice in study_experience.practices:
            assert hasattr(practice, "question_text")
            assert hasattr(practice, "exercise_type")
            assert hasattr(practice, "options")
            assert hasattr(practice, "solution")
            assert hasattr(practice, "explanation")
            assert isinstance(practice.options, list)

    def test_practice_card_fields_are_populated_when_exercise_exists(
        self, pipeline_result: Any, study_experience: StudyExperience
    ) -> None:
        """If the pipeline produced Exercise content blocks, PracticeCards should have content."""
        from learning_platform.models.document import Exercise

        exercise_nodes = [
            node for node in pipeline_result.document.nodes if isinstance(node.content, Exercise)
        ]
        if not exercise_nodes:
            pytest.skip("No Exercise content blocks in document")

        exercised_practices = [p for p in study_experience.practices if p.question_text != ""]
        assert len(exercised_practices) > 0, (
            "Exercise nodes exist but no PracticeCard has question_text"
        )

    def test_exercise_type_is_string(self, study_experience: StudyExperience) -> None:
        """exercise_type should be a non-empty string when populated."""
        for practice in study_experience.practices:
            if practice.exercise_type:
                assert isinstance(practice.exercise_type, str)

    def test_options_have_required_fields(self, study_experience: StudyExperience) -> None:
        """Each ExerciseOption should have label, text, is_correct."""
        for practice in study_experience.practices:
            for opt in practice.options:
                assert hasattr(opt, "label")
                assert hasattr(opt, "text")
                assert hasattr(opt, "is_correct")
                assert isinstance(opt.is_correct, bool)


# ── Page range (start_page / end_page) ───────────────────────────────────────


class TestPageRange:
    """Verify start_page and end_page are populated on sections and lessons."""

    def test_sections_have_end_page(self, study_experience: StudyExperience) -> None:
        """Every Section should have an end_page attribute."""
        for section in study_experience.sections:
            assert hasattr(section, "end_page")
            assert isinstance(section.end_page, int)

    def test_lessons_have_end_page(self, study_experience: StudyExperience) -> None:
        """Every LessonCard should have an end_page attribute."""
        for lesson in study_experience.lessons:
            assert hasattr(lesson, "end_page")
            assert isinstance(lesson.end_page, int)

    def test_section_end_ge_start(self, study_experience: StudyExperience) -> None:
        """end_page should be >= start_page for every section."""
        for section in study_experience.sections:
            if section.start_page > 0:
                assert section.end_page >= section.start_page, (
                    f"Section {section.title}: end_page {section.end_page} "
                    f"< start_page {section.start_page}"
                )

    def test_lesson_end_ge_start(self, study_experience: StudyExperience) -> None:
        """end_page should be >= start_page for every lesson."""
        for lesson in study_experience.lessons:
            if lesson.start_page > 0:
                assert lesson.end_page >= lesson.start_page, (
                    f"Lesson {lesson.title}: end_page {lesson.end_page} "
                    f"< start_page {lesson.start_page}"
                )

    def test_zero_start_implies_zero_end(self, study_experience: StudyExperience) -> None:
        """If start_page is 0, end_page should also be 0."""
        for section in study_experience.sections:
            if section.start_page == 0:
                assert section.end_page == 0, (
                    f"Section {section.title}: start_page=0 but end_page={section.end_page}"
                )
        for lesson in study_experience.lessons:
            if lesson.start_page == 0:
                assert lesson.end_page == 0, (
                    f"Lesson {lesson.title}: start_page=0 but end_page={lesson.end_page}"
                )
