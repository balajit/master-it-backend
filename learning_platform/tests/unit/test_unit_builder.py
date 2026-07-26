"""Unit tests for LearningUnitBuilder."""

from __future__ import annotations

from learning_platform.models.annotation import (
    DefinitionAnnotation,
    ExampleAnnotation,
    ObjectiveAnnotation,
)
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Equation,
    Exercise,
    ExerciseType,
    Figure,
    Heading,
    HeadingLevel,
    PageBreak,
    Paragraph,
    StyledText,
    TableBlock,
    TextRun,
)
from learning_platform.models.learning_unit import Difficulty, NodeRef, UnitType
from learning_platform.stages.unit_builder.builder import LearningUnitBuilder

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _doc(*nodes: DocumentNode) -> CanonicalDocument:
    doc = CanonicalDocument(
        source="test.pdf",
        title="Test",
        metadata=DocumentMetadata(title="Test"),
        nodes=list(nodes),
    )
    return doc


def _para(text: str) -> DocumentNode:
    return DocumentNode(
        content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
    )


def _heading(text: str, level: int = 1) -> DocumentNode:
    return DocumentNode(
        content=Heading(
            level=HeadingLevel(min(level, 4)),
            text=StyledText(runs=[TextRun(text=text)]),
        ),
    )


def _figure(caption: str = "") -> DocumentNode:
    return DocumentNode(content=Figure(caption_text=caption))


def _equation(latex: str = "E=mc^2") -> DocumentNode:
    return DocumentNode(content=Equation(latex=latex))


def _exercise(question: str = "Solve x+1=2") -> DocumentNode:
    return DocumentNode(
        content=Exercise(
            exercise_type=ExerciseType.MULTIPLE_CHOICE,
            question=StyledText(runs=[TextRun(text=question)]),
        )
    )


def _table(headers: list[str] | None = None) -> DocumentNode:
    return DocumentNode(content=TableBlock(headers=headers or ["A", "B"]))


def _obj_ann(node_id, text: str = "Learn to code") -> ObjectiveAnnotation:
    return ObjectiveAnnotation(node_id=node_id, objective_text=text, detector="test")


def _def_ann(node_id, term: str = "var", definition: str = "a thing") -> DefinitionAnnotation:
    return DefinitionAnnotation(
        node_id=node_id, term=term, definition_text=definition, detector="test"
    )


def _ex_ann(node_id, title: str = "Example 1") -> ExampleAnnotation:
    return ExampleAnnotation(node_id=node_id, title=title, body_text="body", detector="test")


# ──────────────────────────────────────────────────────────────────────────────
# Basic construction
# ──────────────────────────────────────────────────────────────────────────────


class TestBasicConstruction:
    def test_empty_document(self) -> None:
        doc = _doc()
        units = LearningUnitBuilder().build(doc)
        assert units == []

    def test_title_only(self) -> None:
        title = _heading("Intro to Math", level=1)
        doc = _doc(title)
        units = LearningUnitBuilder().build(doc)
        assert len(units) == 1
        assert units[0].unit_type == UnitType.COURSE
        assert units[0].title == "Intro to Math"

    def test_single_section(self) -> None:
        title = _heading("Math 101", level=1)
        sec = _heading("Algebra", level=2)
        para = _para("Algebra is the study of symbols.")
        doc = _doc(title, sec, para)
        units = LearningUnitBuilder().build(doc)
        assert len(units) == 2
        assert units[0].unit_type == UnitType.COURSE
        assert units[1].unit_type == UnitType.LESSON
        assert units[1].title == "Algebra"
        assert len(units[1].content_references) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Hierarchy mapping
# ──────────────────────────────────────────────────────────────────────────────


class TestHierarchyMapping:
    def test_chapter_heading_maps_to_module(self) -> None:
        title = _heading("Book", level=1)
        ch = _heading("Ch1", level=1)
        doc = _doc(title, ch)
        units = LearningUnitBuilder().build(doc)
        assert units[1].unit_type == UnitType.MODULE

    def test_section_heading_maps_to_lesson(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Sec1", level=2)
        doc = _doc(title, sec)
        units = LearningUnitBuilder().build(doc)
        assert units[1].unit_type == UnitType.LESSON

    def test_subsection_heading_maps_to_topic(self) -> None:
        title = _heading("Book", level=1)
        sub = _heading("Sub1", level=3)
        doc = _doc(title, sub)
        units = LearningUnitBuilder().build(doc)
        assert units[1].unit_type == UnitType.TOPIC

    def test_sub_subsection_heading_maps_to_topic(self) -> None:
        title = _heading("Book", level=1)
        subsub = _heading("Deep", level=4)
        doc = _doc(title, subsub)
        units = LearningUnitBuilder().build(doc)
        assert units[1].unit_type == UnitType.TOPIC

    def test_multiple_sections(self) -> None:
        title = _heading("Book", level=1)
        sec1 = _heading("Ch1", level=2)
        p1 = _para("First chapter content.")
        sec2 = _heading("Ch2", level=2)
        p2 = _para("Second chapter content.")
        doc = _doc(title, sec1, p1, sec2, p2)
        units = LearningUnitBuilder().build(doc)
        assert len(units) == 3
        assert units[1].title == "Ch1"
        assert units[2].title == "Ch2"


# ──────────────────────────────────────────────────────────────────────────────
# Parent-child relationships
# ──────────────────────────────────────────────────────────────────────────────


class TestParentChild:
    def test_section_parent_is_course(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        doc = _doc(title, sec)
        units = LearningUnitBuilder().build(doc)
        course = units[0]
        lesson = units[1]
        assert lesson.parent_id == course.id
        assert lesson.id in course.children_ids

    def test_topic_parent_is_lesson(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        sub = _heading("Sub1", level=3)
        doc = _doc(title, sec, sub)
        units = LearningUnitBuilder().build(doc)
        lesson = units[1]
        topic = units[2]
        assert topic.parent_id == lesson.id
        assert topic.id in lesson.children_ids


# ──────────────────────────────────────────────────────────────────────────────
# Content references — node refs, not content
# ──────────────────────────────────────────────────────────────────────────────


class TestContentReferences:
    def test_paragraphs_become_content_references(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p1 = _para("Hello world.")
        p2 = _para("Goodbye world.")
        doc = _doc(title, sec, p1, p2)
        units = LearningUnitBuilder().build(doc)
        lesson = units[1]
        assert len(lesson.content_references) == 2
        assert all(isinstance(ref, NodeRef) for ref in lesson.content_references)
        assert lesson.content_references[0].node_id == p1.id
        assert lesson.content_references[1].node_id == p2.id

    def test_node_refs_have_summary_not_content(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("A" * 500)
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc)
        ref = units[1].content_references[0]
        assert ref.node_id == p.id
        assert len(ref.summary) <= 120

    def test_figures_collected_separately(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        fig = _figure(caption="Figure 1: A cat")
        doc = _doc(title, sec, fig)
        units = LearningUnitBuilder().build(doc)
        assert len(units[1].figures) == 1
        assert units[1].figures[0].node_id == fig.id
        assert "cat" in units[1].figures[0].summary

    def test_tables_collected_separately(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        tbl = _table(headers=["Name", "Age"])
        doc = _doc(title, sec, tbl)
        units = LearningUnitBuilder().build(doc)
        assert len(units[1].tables) == 1
        assert units[1].tables[0].node_id == tbl.id

    def test_equations_collected_separately(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        eq = _equation(latex="E=mc^2")
        doc = _doc(title, sec, eq)
        units = LearningUnitBuilder().build(doc)
        assert len(units[1].equations) == 1
        assert units[1].equations[0].node_id == eq.id

    def test_exercises_collected_separately(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        ex = _exercise(question="What is 2+2?")
        doc = _doc(title, sec, ex)
        units = LearningUnitBuilder().build(doc)
        assert len(units[1].exercises) == 1
        assert units[1].exercises[0].node_id == ex.id


# ──────────────────────────────────────────────────────────────────────────────
# Annotation scoping
# ──────────────────────────────────────────────────────────────────────────────


class TestAnnotationScoping:
    def test_objectives_scoped_to_correct_unit(self) -> None:
        title = _heading("Book", level=1)
        sec1 = _heading("Ch1", level=2)
        p1 = _para("Content 1.")
        sec2 = _heading("Ch2", level=2)
        p2 = _para("Content 2.")
        doc = _doc(title, sec1, p1, sec2, p2)

        anns = [
            _obj_ann(p1.id, "Learn basics"),
            _obj_ann(p2.id, "Learn advanced"),
        ]
        units = LearningUnitBuilder().build(doc, anns)
        lesson1 = units[1]
        lesson2 = units[2]
        assert "Learn basics" in lesson1.learning_objectives
        assert "Learn advanced" in lesson2.learning_objectives
        assert "Learn advanced" not in lesson1.learning_objectives

    def test_definitions_scoped_to_correct_unit(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("Some content.")
        doc = _doc(title, sec, p)

        anns = [_def_ann(p.id, "var", "a variable")]
        units = LearningUnitBuilder().build(doc, anns)
        lesson = units[1]
        assert len(lesson.definitions) == 1
        assert lesson.definitions[0].node_id == p.id
        assert "var" in lesson.definitions[0].summary

    def test_examples_scoped_to_correct_unit(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("Some content.")
        doc = _doc(title, sec, p)

        anns = [_ex_ann(p.id, "Example: x=1")]
        units = LearningUnitBuilder().build(doc, anns)
        lesson = units[1]
        assert len(lesson.examples) == 1
        assert lesson.examples[0].node_id == p.id

    def test_annotations_outside_scope_ignored(self) -> None:
        title = _heading("Book", level=1)
        orphan = _para("This is before any section.")
        sec = _heading("Ch1", level=2)
        p = _para("Content.")
        doc = _doc(title, orphan, sec, p)

        anns = [_obj_ann(orphan.id, "Should be ignored")]
        units = LearningUnitBuilder().build(doc, anns)
        lesson = units[1]
        assert lesson.learning_objectives == []

    def test_none_annotations_handled(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("Content.")
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc, None)
        assert units[1].learning_objectives == []
        assert units[1].definitions == []
        assert units[1].examples == []


# ──────────────────────────────────────────────────────────────────────────────
# Study time estimation
# ──────────────────────────────────────────────────────────────────────────────


class TestStudyTimeEstimation:
    def test_short_text_minimum_one_minute(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("Hi.")
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc)
        assert units[1].estimated_study_time_minutes >= 1

    def test_longer_text_higher_time(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para(" ".join(["word"] * 250))
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc)
        assert units[1].estimated_study_time_minutes >= 1

    def test_exercises_add_time(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        ex1 = _exercise("Q1?")
        ex2 = _exercise("Q2?")
        doc = _doc(title, sec, ex1, ex2)
        units = LearningUnitBuilder().build(doc)
        assert units[1].estimated_study_time_minutes >= 6

    def test_figures_add_time(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        fig = _figure()
        doc = _doc(title, sec, fig)
        units = LearningUnitBuilder().build(doc)
        assert units[1].estimated_study_time_minutes >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Difficulty estimation
# ──────────────────────────────────────────────────────────────────────────────


class TestDifficultyEstimation:
    def test_simple_text_is_basic(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("Simple content.")
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc)
        assert units[1].difficulty == Difficulty.BASIC

    def test_many_equations_increases_difficulty(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        nodes = [_equation(f"E_{i}=mc^{i}") for i in range(5)]
        doc = _doc(title, sec, *nodes)
        units = LearningUnitBuilder().build(doc)
        assert units[1].difficulty in {Difficulty.INTERMEDIATE, Difficulty.ADVANCED}

    def test_exercises_increases_difficulty(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        exs = [_exercise(f"Q{i}?") for i in range(4)]
        doc = _doc(title, sec, *exs)
        units = LearningUnitBuilder().build(doc)
        assert units[1].difficulty in {Difficulty.INTERMEDIATE, Difficulty.ADVANCED}

    def test_many_equations_and_exercises_is_advanced(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        eqs = [_equation(f"E_{i}") for i in range(3)]
        exs = [_exercise(f"Q{i}?") for i in range(3)]
        doc = _doc(title, sec, *eqs, *exs)
        units = LearningUnitBuilder().build(doc)
        assert units[1].difficulty == Difficulty.ADVANCED


# ──────────────────────────────────────────────────────────────────────────────
# Source node IDs
# ──────────────────────────────────────────────────────────────────────────────


class TestSourceNodeIds:
    def test_heading_and_content_both_recorded(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("Content.")
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc)
        lesson = units[1]
        assert sec.id in lesson.source_node_ids
        assert p.id in lesson.source_node_ids

    def test_figures_recorded_in_source(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        fig = _figure()
        doc = _doc(title, sec, fig)
        units = LearningUnitBuilder().build(doc)
        assert fig.id in units[1].source_node_ids


# ──────────────────────────────────────────────────────────────────────────────
# Non-content nodes
# ──────────────────────────────────────────────────────────────────────────────


class TestNonContentNodes:
    def test_page_break_skipped(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        pb = DocumentNode(content=PageBreak(page_number=2))
        p = _para("After break.")
        doc = _doc(title, sec, pb, p)
        units = LearningUnitBuilder().build(doc)
        lesson = units[1]
        assert len(lesson.content_references) == 1
        assert lesson.content_references[0].node_id == p.id


# ──────────────────────────────────────────────────────────────────────────────
# Description from first paragraph
# ──────────────────────────────────────────────────────────────────────────────


class TestDescription:
    def test_description_from_first_paragraph(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        p = _para("This is the first paragraph which becomes the description.")
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc)
        assert units[1].description.startswith("This is the first paragraph")

    def test_description_truncated_to_200_chars(self) -> None:
        title = _heading("Book", level=1)
        sec = _heading("Ch1", level=2)
        long_text = "word " * 60
        p = _para(long_text)
        doc = _doc(title, sec, p)
        units = LearningUnitBuilder().build(doc)
        assert len(units[1].description) <= 200


# ──────────────────────────────────────────────────────────────────────────────
# Multiple units with mixed content
# ──────────────────────────────────────────────────────────────────────────────


class TestMixedContent:
    def test_multi_section_with_annotations_and_media(self) -> None:
        title = _heading("Science", level=1)
        sec1 = _heading("Physics", level=2)
        p1 = _para("Newton's laws of motion.")
        fig1 = _figure(caption="F=ma diagram")
        sec2 = _heading("Chemistry", level=2)
        p2 = _para("The periodic table.")
        tbl = _table(headers=["Element", "Symbol"])
        eq = _equation(latex="PV=nRT")

        doc = _doc(title, sec1, p1, fig1, sec2, p2, tbl, eq)

        anns = [
            _obj_ann(p1.id, "Understand Newton's laws"),
            _obj_ann(p2.id, "Know the periodic table"),
            _def_ann(p1.id, "force", "mass times acceleration"),
            _ex_ann(p2.id, "Example: noble gases"),
        ]

        units = LearningUnitBuilder().build(doc, anns)

        assert len(units) == 3

        physics = units[1]
        chemistry = units[2]

        assert physics.title == "Physics"
        assert len(physics.content_references) == 1
        assert len(physics.figures) == 1
        assert "Understand Newton's laws" in physics.learning_objectives
        assert len(physics.definitions) == 1
        assert physics.examples == []

        assert chemistry.title == "Chemistry"
        assert len(chemistry.content_references) == 1
        assert len(chemistry.tables) == 1
        assert len(chemistry.equations) == 1
        assert "Know the periodic table" in chemistry.learning_objectives
        assert len(chemistry.examples) == 1


# ──────────────────────────────────────────────────────────────────────────────
# No content before first heading
# ──────────────────────────────────────────────────────────────────────────────


class TestContentBeforeHeading:
    def test_content_before_first_heading_goes_to_course(self) -> None:
        title = _heading("Book", level=1)
        orphan = _para("This is before any section.")
        sec = _heading("Ch1", level=2)
        p = _para("Section content.")
        doc = _doc(title, orphan, sec, p)
        units = LearningUnitBuilder().build(doc)
        course = units[0]
        assert orphan.id in course.source_node_ids
