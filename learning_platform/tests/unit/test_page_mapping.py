"""Tests for page-aware presentation mapping.

Verifies that ``LearningExperienceMapper`` correctly maps pipeline
``PageContext`` objects into ``PageView`` presentation models, populates
``start_page`` on ``LessonCard`` and ``Section``, and includes pages
in ``StudyExperience``.
"""

from __future__ import annotations

from uuid import uuid4

from learning_platform.models.annotation import DefinitionAnnotation
from learning_platform.models.concept import Concept, ConceptCategory
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Heading,
    HeadingLevel,
    Paragraph,
    SourceLocation,
    StyledText,
    TextRun,
)
from learning_platform.models.knowledge_graph import KnowledgeGraph
from learning_platform.models.learning_unit import LearningUnit, NodeRef, UnitType
from learning_platform.models.page_context import PageContext, build_page_contexts
from learning_platform.models.sequence import Lesson, StudyPlan
from learning_platform.presentation.mappers.configuration import (
    create_default_config,
)
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.mappers.learning_experience import (
    LearningExperienceMapper,
    PipelineOutput,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

DOC_ID = uuid4()


def _node(text: str, page: int, node_id: uuid4 | None = None) -> DocumentNode:
    """Create a DocumentNode with a Paragraph on a given page."""
    return DocumentNode(
        id=node_id or uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
        page=page,
        seq=0,
        level=0,
        source=SourceLocation(element_ref=f"p{page}"),
    )


def _heading_node(text: str, page: int, level: int = 1) -> DocumentNode:
    """Create a DocumentNode with a Heading on a given page."""
    return DocumentNode(
        id=uuid4(),
        content=Heading(
            text=StyledText(runs=[TextRun(text=text)]),
            level=HeadingLevel(level),
        ),
        page=page,
        seq=0,
        level=level,
        source=SourceLocation(element_ref=f"h{page}"),
    )


def _unit(title: str, unit_type: UnitType, parent_id: uuid4 | None = None) -> LearningUnit:
    """Create a minimal LearningUnit."""
    uid = uuid4()
    return LearningUnit(
        id=uid,
        title=title,
        description=f"Desc for {title}",
        unit_type=unit_type,
        parent_id=parent_id,
    )


def _make_document(nodes: list[DocumentNode]) -> CanonicalDocument:
    return CanonicalDocument(
        id=DOC_ID,
        source_path="test.pdf",
        metadata=DocumentMetadata(title="Test Doc"),
        nodes=nodes,
    )


def _empty_progress() -> ProgressContext:
    return ProgressContext(user_id=1, course_id=1)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: PageView in StudyExperience
# ──────────────────────────────────────────────────────────────────────────────


class TestPageViewInStudyExperience:
    """StudyExperience.pages is populated from pipeline PageContext."""

    def test_study_experience_has_pages(self) -> None:
        """Pages from pipeline output appear in StudyExperience."""
        n1 = _heading_node("Chapter 1", page=1)
        n2 = _node("Hello world", page=1)
        n3 = _heading_node("Chapter 2", page=2)
        n4 = _node("More content", page=2)

        doc = _make_document([n1, n2, n3, n4])
        pages = build_page_contexts(doc)

        root = _unit("Root", UnitType.COURSE)
        child = _unit("Module 1", UnitType.MODULE, parent_id=root.id)
        root.children_ids = [child.id]

        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root, child],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        # page 0 (synthetic) is skipped; pages 1 and 2 remain
        assert len(experience.pages) == 2
        assert experience.pages[0].page_number == 1
        assert experience.pages[1].page_number == 2

    def test_page_view_title_from_heading(self) -> None:
        """PageView.title is set from the first heading on the page."""
        n1 = _heading_node("Introduction", page=1)
        n2 = _node("Some text", page=1)

        doc = _make_document([n1, n2])
        pages = build_page_contexts(doc)

        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.pages) == 1
        assert experience.pages[0].title == "Introduction"

    def test_page_view_text_preview_truncated(self) -> None:
        """PageView.text_preview is truncated to 280 chars."""
        long_text = "word " * 100  # 500 chars
        n1 = _node(long_text, page=1)

        doc = _make_document([n1])
        pages = build_page_contexts(doc)

        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.pages) == 1
        assert len(experience.pages[0].text_preview) <= 280

    def test_page_view_skips_page_zero(self) -> None:
        """Page 0 (unknown page) is excluded from presentation."""
        n1 = _node("Content with no page", page=0)
        n2 = _node("Page 1 content", page=1)

        doc = _make_document([n1, n2])
        pages = build_page_contexts(doc)

        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.pages) == 1
        assert experience.pages[0].page_number == 1

    def test_page_view_empty_when_no_pages(self) -> None:
        """When pages list is empty, StudyExperience.pages is empty."""
        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=_make_document([]),
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=[],
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert experience.pages == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests: start_page on LessonCard
# ──────────────────────────────────────────────────────────────────────────────


class TestLessonStartPage:
    """LessonCard.start_page is resolved from page contexts."""

    def test_lesson_start_page_from_page_context(self) -> None:
        """A lesson's start_page matches the page containing its unit."""
        unit1 = _unit("Lesson A", UnitType.LESSON)
        unit2 = _unit("Lesson B", UnitType.LESSON)
        root = _unit("Root", UnitType.COURSE)
        root.children_ids = [unit1.id, unit2.id]

        n1 = _node("Content A", page=3)
        n1.id = unit1.id  # Link node to unit via ID
        n2 = _node("Content B", page=7)
        n2.id = unit2.id

        doc = _make_document([n1, n2])
        page_ctx = PageContext(page_number=3, nodes=[n1], page_text="Content A", units=[unit1])
        page_ctx2 = PageContext(page_number=7, nodes=[n2], page_text="Content B", units=[unit2])

        from learning_platform.models.sequence import Lesson

        lesson1 = Lesson(
            id=unit1.id,
            unit_id=unit1.id,
            title="Lesson A",
            order=0,
        )
        lesson2 = Lesson(
            id=unit2.id,
            unit_id=unit2.id,
            title="Lesson B",
            order=1,
        )

        study_plan = StudyPlan(lessons=[lesson1, lesson2])

        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root, unit1, unit2],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=study_plan,
            quizzes=[],
            pages=[page_ctx, page_ctx2],
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        lesson_cards = {l.lesson_id: l for l in experience.lessons}
        assert lesson_cards[unit1.id].start_page == 3
        assert lesson_cards[unit2.id].start_page == 7

    def test_lesson_start_page_zero_when_no_page_match(self) -> None:
        """start_page defaults to 0 when no page context contains the unit."""
        unit1 = _unit("Lesson A", UnitType.LESSON)
        root = _unit("Root", UnitType.COURSE)
        root.children_ids = [unit1.id]

        from learning_platform.models.sequence import Lesson

        lesson1 = Lesson(id=unit1.id, unit_id=unit1.id, title="Lesson A", order=0)
        study_plan = StudyPlan(lessons=[lesson1])

        pipeline_output = PipelineOutput(
            document=_make_document([]),
            learning_units=[root, unit1],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=study_plan,
            quizzes=[],
            pages=[],  # No pages at all
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.lessons) == 1
        assert experience.lessons[0].start_page == 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests: start_page on Section
# ──────────────────────────────────────────────────────────────────────────────


class TestSectionStartPage:
    """Section.start_page is resolved from child unit pages."""

    def test_section_start_page_from_first_child(self) -> None:
        """Section's start_page is the first page of its first child unit."""
        root = _unit("Root", UnitType.COURSE)
        mod = _unit("Module 1", UnitType.MODULE, parent_id=root.id)
        lesson = _unit("Lesson 1", UnitType.LESSON, parent_id=mod.id)
        root.children_ids = [mod.id]
        mod.children_ids = [lesson.id]

        n1 = _node("Lesson content", page=5)
        page_ctx = PageContext(
            page_number=5,
            nodes=[n1],
            page_text="Lesson content",
            units=[lesson],
        )

        pipeline_output = PipelineOutput(
            document=_make_document([n1]),
            learning_units=[root, mod, lesson],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=[page_ctx],
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.sections) == 1
        assert experience.sections[0].start_page == 5

    def test_section_start_page_zero_when_no_pages(self) -> None:
        """Section's start_page defaults to 0 when no pages are available."""
        root = _unit("Root", UnitType.COURSE)
        mod = _unit("Module 1", UnitType.MODULE, parent_id=root.id)
        root.children_ids = [mod.id]

        pipeline_output = PipelineOutput(
            document=_make_document([]),
            learning_units=[root, mod],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=[],
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.sections) == 1
        assert experience.sections[0].start_page == 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests: PageView annotation and concept IDs
# ──────────────────────────────────────────────────────────────────────────────


class TestPageViewReferences:
    """PageView includes annotation and concept IDs from page contexts."""

    def test_page_view_annotation_ids(self) -> None:
        """PageView.annotation_ids are populated from page annotations."""
        ann = DefinitionAnnotation(
            node_id=uuid4(),
            term="H2O",
            definition="Water",
        )

        n1 = _node("H2O is water", page=1)
        doc = _make_document([n1])
        pages = build_page_contexts(doc)
        pages[0].annotations = [ann]

        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[ann],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.pages) == 1
        assert experience.pages[0].annotation_ids == [ann.id]

    def test_page_view_concept_ids(self) -> None:
        """PageView.concept_ids are populated from page concepts."""
        concept = Concept(
            id=uuid4(),
            name="Chemistry",
            category=ConceptCategory.CONCEPT,
        )

        n1 = _node("Chemistry content", page=1)
        doc = _make_document([n1])
        pages = build_page_contexts(doc)
        pages[0].concepts = [concept]

        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.pages) == 1
        assert experience.pages[0].concept_ids == [concept.id]


# ──────────────────────────────────────────────────────────────────────────────
# Tests: LessonCard content references
# ──────────────────────────────────────────────────────────────────────────────


class TestLessonCardContent:
    """Verify LessonCard carries content references from LearningUnit."""

    def test_lesson_card_has_content_references(self) -> None:
        """Content references from LearningUnit are passed to LessonCard."""
        n1 = _heading_node("Introduction", page=1)
        n2 = _node("Some content", page=1)
        doc = _make_document([n1, n2])
        pages = build_page_contexts(doc)

        root = _unit("Root", UnitType.COURSE)
        child = _unit("Module 1", UnitType.MODULE, parent_id=root.id)
        root.children_ids = [child.id]

        # Attach content references to the child unit
        child.content_references = [
            NodeRef(node_id=n2.id, summary="Some content"),
        ]
        child.definitions = [
            NodeRef(node_id=uuid4(), summary="term: definition"),
        ]
        child.figures = [
            NodeRef(node_id=uuid4(), summary="Figure 1"),
        ]

        # Create a study plan with a lesson referencing the child unit
        lesson = Lesson(unit_id=child.id, title="Module 1 Lesson")
        study_plan = StudyPlan(lessons=[lesson])

        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root, child],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=study_plan,
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        # Find the lesson card for child unit
        lesson_cards = [l for l in experience.lessons if l.unit_id == child.id]
        assert len(lesson_cards) == 1
        card = lesson_cards[0]

        assert len(card.content_references) == 1
        assert card.content_references[0].node_id == n2.id
        assert len(card.definitions) == 1
        assert card.definitions[0].summary == "term: definition"
        assert len(card.figures) == 1
        assert card.figures[0].summary == "Figure 1"
        assert card.tables == []
        assert card.equations == []
        assert card.examples == []

    def test_lesson_card_content_fields_default_empty(self) -> None:
        """LessonCard content fields default to empty lists."""
        n1 = _heading_node("Intro", page=1)
        doc = _make_document([n1])
        pages = build_page_contexts(doc)

        root = _unit("Root", UnitType.COURSE)

        lesson = Lesson(unit_id=root.id, title="Root Lesson")
        study_plan = StudyPlan(lessons=[lesson])

        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=study_plan,
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        for lesson in experience.lessons:
            assert lesson.content_references == []
            assert lesson.definitions == []
            assert lesson.examples == []
            assert lesson.figures == []
            assert lesson.tables == []
            assert lesson.equations == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests: PageView full_text
# ──────────────────────────────────────────────────────────────────────────────


class TestPageViewFullText:
    """Verify PageView.full_text is populated from PageContext.page_text."""

    def test_page_view_has_full_text(self) -> None:
        """PageView.full_text contains the complete page text."""
        n1 = _heading_node("Chapter 1", page=1)
        n2 = _node("Full content here that is much longer than 280 chars " * 10, page=1)
        doc = _make_document([n1, n2])
        pages = build_page_contexts(doc)

        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert len(experience.pages) == 1
        page = experience.pages[0]
        assert page.full_text != ""
        assert len(page.full_text) > 280
        assert page.text_preview == page.full_text[:280]

    def test_page_view_full_text_matches_page_text(self) -> None:
        """PageView.full_text exactly matches PageContext.page_text."""
        n1 = _node("Exact text match", page=1)
        doc = _make_document([n1])
        pages = build_page_contexts(doc)
        original_text = pages[0].page_text

        root = _unit("Root", UnitType.COURSE)
        pipeline_output = PipelineOutput(
            document=doc,
            learning_units=[root],
            annotations=[],
            concept_map=None,
            knowledge_graph=KnowledgeGraph(),
            study_plan=StudyPlan(),
            quizzes=[],
            pages=pages,
        )

        mapper = LearningExperienceMapper(config=create_default_config())
        experience = mapper.map(pipeline_output, _empty_progress())

        assert experience.pages[0].full_text == original_text
