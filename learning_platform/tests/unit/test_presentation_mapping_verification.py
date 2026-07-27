"""Unit tests verifying document text to presentation mapping in LearningExperienceMapper."""

from __future__ import annotations

from uuid import uuid4

from learning_platform.models.annotation import ObjectiveAnnotation
from learning_platform.models.concept import ConceptMap
from learning_platform.models.document import (
    AnswerOption,
    CanonicalDocument,
    DocumentNode,
    Exercise,
    Paragraph,
    StyledText,
    TextRun,
)
from learning_platform.models.knowledge_graph import KnowledgeGraph
from learning_platform.models.learning_unit import LearningUnit, NodeRef, UnitType
from learning_platform.models.page_context import PageContext
from learning_platform.models.sequence import Lesson, StudyPlan
from learning_platform.presentation.mappers.configuration import create_default_config
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.mappers.learning_experience import (
    LearningExperienceMapper,
    PipelineOutput,
)


def test_lesson_card_content_references_and_page_range():
    """Verify LessonCard carries content references and calculated start/end pages."""
    node_p1 = DocumentNode(
        id=uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text="Lesson text on page 1")])),
        page=1,
    )
    node_p2 = DocumentNode(
        id=uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text="Lesson text on page 3")])),
        page=3,
    )
    doc = CanonicalDocument(source="test.pdf", title="Test Doc", nodes=[node_p1, node_p2])

    ref1 = NodeRef(node_id=node_p1.id, summary="Ref 1")
    ref2 = NodeRef(node_id=node_p2.id, summary="Ref 2")

    course_unit = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.COURSE,
        title="Test Course",
    )
    module_unit = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.MODULE,
        title="Module 1",
        parent_id=course_unit.id,
    )
    lesson_unit = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.LESSON,
        title="Lesson 1",
        parent_id=module_unit.id,
        content_references=[ref1, ref2],
        source_node_ids=[node_p1.id, node_p2.id],
    )
    course_unit.children_ids = [module_unit.id]
    module_unit.children_ids = [lesson_unit.id]

    lesson = Lesson(
        id=uuid4(),
        unit_id=lesson_unit.id,
        title="Lesson 1",
        description="Description",
        learning_objectives=["Understand mapping"],
    )
    study_plan = StudyPlan(title="Plan", lessons=[lesson])

    page1 = PageContext(page_number=1, heading="Header 1", page_text="Page 1 full text content", units=[lesson_unit])
    page3 = PageContext(page_number=3, heading="Header 3", page_text="Page 3 full text content", units=[lesson_unit])

    output = PipelineOutput(
        document=doc,
        learning_units=[course_unit, module_unit, lesson_unit],
        annotations=[],
        concept_map=ConceptMap(),
        knowledge_graph=KnowledgeGraph(),
        study_plan=study_plan,
        quizzes=[],
        pages=[page1, page3],
    )

    mapper = LearningExperienceMapper(config=create_default_config())
    experience = mapper.map(output, ProgressContext(user_id=1, course_id=100))

    assert len(experience.lessons) == 1
    card = experience.lessons[0]
    assert card.start_page == 1
    assert card.end_page == 3
    assert len(card.content_references) == 2
    assert card.content_references[0].summary == "Ref 1"
    assert card.content_references[1].summary == "Ref 2"


def test_page_view_full_text():
    """Verify PageView contains both text_preview and full_text."""
    page_text = "A" * 500
    page = PageContext(page_number=2, heading="Chapter 1", page_text=page_text)

    course_unit = LearningUnit(id=uuid4(), unit_type=UnitType.COURSE, title="Course")
    doc = CanonicalDocument(source="test.pdf", title="Doc", nodes=[])
    output = PipelineOutput(
        document=doc,
        learning_units=[course_unit],
        annotations=[],
        concept_map=ConceptMap(),
        knowledge_graph=KnowledgeGraph(),
        study_plan=StudyPlan(),
        quizzes=[],
        pages=[page],
    )

    mapper = LearningExperienceMapper(config=create_default_config())
    experience = mapper.map(output, ProgressContext(user_id=1, course_id=100))

    assert len(experience.pages) == 1
    pv = experience.pages[0]
    assert len(pv.text_preview) == 280
    assert pv.full_text == page_text


def test_objective_annotation_tracing():
    """Verify objective annotations are positional-aligned with objective strings."""
    node_id = uuid4()
    ann1 = ObjectiveAnnotation(id=uuid4(), node_id=node_id, objective_text="Objective 1")

    course_unit = LearningUnit(id=uuid4(), unit_type=UnitType.COURSE, title="Course")
    module_unit = LearningUnit(id=uuid4(), unit_type=UnitType.MODULE, title="Module", parent_id=course_unit.id)
    lesson_unit = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.LESSON,
        title="Lesson",
        parent_id=module_unit.id,
        source_node_ids=[node_id],
    )
    course_unit.children_ids = [module_unit.id]
    module_unit.children_ids = [lesson_unit.id]

    lesson = Lesson(id=uuid4(), unit_id=lesson_unit.id, title="Lesson", learning_objectives=["Objective 1"])
    doc = CanonicalDocument(source="test.pdf", title="Doc", nodes=[])
    output = PipelineOutput(
        document=doc,
        learning_units=[course_unit, module_unit, lesson_unit],
        annotations=[ann1],
        concept_map=ConceptMap(),
        knowledge_graph=KnowledgeGraph(),
        study_plan=StudyPlan(lessons=[lesson]),
        quizzes=[],
    )

    mapper = LearningExperienceMapper(config=create_default_config())
    experience = mapper.map(output, ProgressContext(user_id=1, course_id=100))

    card = experience.lessons[0]
    assert len(card.learning_objectives) == 1
    assert card.learning_objectives[0].text == "Objective 1"
    assert card.learning_objectives[0].annotation_id == ann1.id


def test_practice_card_exercise_details_resolution():
    """Verify PracticeCard resolves question text, options, and solution from Exercise DocumentNode."""
    exercise_id = uuid4()
    ex_content = Exercise(
        question=StyledText(runs=[TextRun(text="What is 2 + 2?")]),
        exercise_type="multiple_choice",
        options=[
            AnswerOption(label="A", text=StyledText(runs=[TextRun(text="3")]), is_correct=False),
            AnswerOption(label="B", text=StyledText(runs=[TextRun(text="4")]), is_correct=True),
        ],
        solution="4",
        explanation="2 plus 2 equals 4",
    )
    ex_node = DocumentNode(id=exercise_id, content=ex_content, page=1)

    doc = CanonicalDocument(source="test.pdf", title="Doc", nodes=[ex_node])
    doc.rebuild_index()

    ref = NodeRef(node_id=exercise_id, summary="Math Practice")

    course_unit = LearningUnit(id=uuid4(), unit_type=UnitType.COURSE, title="Course")
    module_unit = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.MODULE,
        title="Module",
        parent_id=course_unit.id,
        exercises=[ref],
    )
    course_unit.children_ids = [module_unit.id]

    output = PipelineOutput(
        document=doc,
        learning_units=[course_unit, module_unit],
        annotations=[],
        concept_map=ConceptMap(),
        knowledge_graph=KnowledgeGraph(),
        study_plan=StudyPlan(),
        quizzes=[],
    )

    mapper = LearningExperienceMapper(config=create_default_config())
    experience = mapper.map(output, ProgressContext(user_id=1, course_id=100))

    assert len(experience.practices) == 1
    practice = experience.practices[0]
    assert practice.question_text == "What is 2 + 2?"
    assert practice.exercise_type == "multiple_choice"
    assert len(practice.options) == 2
    assert practice.options[1].label == "B"
    assert practice.options[1].is_correct is True
    assert practice.solution == "4"
    assert practice.explanation == "2 plus 2 equals 4"
