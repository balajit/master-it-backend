"""Unit tests for enrichment detectors and EnrichmentEngine."""

from __future__ import annotations

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
    Note,
    NoteType,
    Paragraph,
    StyledText,
    TextRun,
)
from learning_platform.stages.enricher.detectors.callout import CalloutDetector
from learning_platform.stages.enricher.detectors.cross_reference import CrossReferenceDetector
from learning_platform.stages.enricher.detectors.definition import DefinitionDetector
from learning_platform.stages.enricher.detectors.equation_association import (
    EquationAssociationDetector,
)
from learning_platform.stages.enricher.detectors.example import ExampleDetector
from learning_platform.stages.enricher.detectors.exercise import ExerciseDetector
from learning_platform.stages.enricher.detectors.figure_association import (
    FigureAssociationDetector,
)
from learning_platform.stages.enricher.detectors.key_term import KeyTermDetector
from learning_platform.stages.enricher.detectors.objective import ObjectiveDetector
from learning_platform.stages.enricher.detectors.summary import SummaryDetector
from learning_platform.stages.enricher.engine import EnrichmentEngine

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _doc(*nodes: DocumentNode) -> CanonicalDocument:
    return CanonicalDocument(
        source="test.pdf",
        title="Test",
        metadata=DocumentMetadata(title="Test"),
        nodes=list(nodes),
    )


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


def _note(text: str, note_type: NoteType = NoteType.INFO) -> DocumentNode:
    return DocumentNode(
        content=Note(
            note_type=note_type,
            text=StyledText(runs=[TextRun(text=text)]),
        ),
    )


def _figure(caption: str = "") -> DocumentNode:
    return DocumentNode(content=Figure(caption_text=caption))


def _equation(latex: str = "E=mc^2", label: str = "") -> DocumentNode:
    return DocumentNode(content=Equation(latex=latex, label=label))


# ──────────────────────────────────────────────────────────────────────────────
# DefinitionDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestDefinitionDetector:
    def test_explicit_definition(self) -> None:
        doc = _doc(_para("Definition: A function is a relation."))
        anns = DefinitionDetector().detect(doc)
        assert len(anns) >= 1
        assert anns[0].term

    def test_inline_definition(self) -> None:
        doc = _doc(_para("A polygon is a closed shape."))
        anns = DefinitionDetector().detect(doc)
        assert len(anns) >= 1
        assert "polygon" in anns[0].term.lower() or "Polygon" in anns[0].term

    def test_no_definitions(self) -> None:
        doc = _doc(_para("Hello world."))
        anns = DefinitionDetector().detect(doc)
        assert len(anns) == 0

    def test_empty_document(self) -> None:
        anns = DefinitionDetector().detect(_doc())
        assert anns == []


# ──────────────────────────────────────────────────────────────────────────────
# ExampleDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestExampleDetector:
    def test_positive_example(self) -> None:
        doc = _doc(_para("Example: Consider a triangle."))
        anns = ExampleDetector().detect(doc)
        assert len(anns) >= 1
        assert anns[0].is_positive is True

    def test_non_example(self) -> None:
        doc = _doc(_para("Non-example: A circle is not a polygon."))
        anns = ExampleDetector().detect(doc)
        assert len(anns) >= 1
        assert anns[0].is_positive is False

    def test_no_examples(self) -> None:
        doc = _doc(_para("Plain text."))
        anns = ExampleDetector().detect(doc)
        assert len(anns) == 0


# ──────────────────────────────────────────────────────────────────────────────
# ExerciseDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestExerciseDetector:
    def test_explicit_exercise_node(self) -> None:
        node = DocumentNode(
            content=Exercise(
                exercise_type=ExerciseType.MULTIPLE_CHOICE,
                question=StyledText(runs=[TextRun(text="What is 2+2?")]),
                options=[],
                solution="4",
            ),
        )
        doc = _doc(node)
        anns = ExerciseDetector().detect(doc)
        assert len(anns) == 1
        assert anns[0].exercise_type == "multiple_choice"
        assert anns[0].solution == "4"

    def test_text_exercise(self) -> None:
        doc = _doc(_para("Exercise 1: Solve for x."))
        anns = ExerciseDetector().detect(doc)
        assert len(anns) >= 1

    def test_no_exercises(self) -> None:
        doc = _doc(_para("No exercises here."))
        anns = ExerciseDetector().detect(doc)
        assert len(anns) == 0


# ──────────────────────────────────────────────────────────────────────────────
# ObjectiveDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestObjectiveDetector:
    def test_learning_objective(self) -> None:
        doc = _doc(_para("Learning Objective: Understand derivatives."))
        anns = ObjectiveDetector().detect(doc)
        assert len(anns) >= 1
        assert "derivatives" in anns[0].objective_text.lower()

    def test_you_will_pattern(self) -> None:
        doc = _doc(_para("You will learn to integrate."))
        anns = ObjectiveDetector().detect(doc)
        assert len(anns) >= 1

    def test_no_objectives(self) -> None:
        doc = _doc(_para("Random text."))
        anns = ObjectiveDetector().detect(doc)
        assert len(anns) == 0


# ──────────────────────────────────────────────────────────────────────────────
# SummaryDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestSummaryDetector:
    def test_summary_heading(self) -> None:
        doc = _doc(_heading("Summary"))
        anns = SummaryDetector().detect(doc)
        assert len(anns) >= 1
        assert anns[0].summary_text

    def test_in_summary_text(self) -> None:
        doc = _doc(_para("In summary, calculus is important."))
        anns = SummaryDetector().detect(doc)
        assert len(anns) >= 1

    def test_no_summary(self) -> None:
        doc = _doc(_para("No summary here."))
        anns = SummaryDetector().detect(doc)
        assert len(anns) == 0


# ──────────────────────────────────────────────────────────────────────────────
# CalloutDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestCalloutDetector:
    def test_note_node(self) -> None:
        doc = _doc(_note("Remember to check units.", NoteType.TIP))
        anns = CalloutDetector().detect(doc)
        assert len(anns) >= 1
        assert anns[0].callout_type == "example"

    def test_text_callout(self) -> None:
        doc = _doc(_para("Warning: Do not divide by zero."))
        anns = CalloutDetector().detect(doc)
        assert len(anns) >= 1
        assert anns[0].callout_type == "non_example"

    def test_no_callouts(self) -> None:
        doc = _doc(_para("Plain text."))
        anns = CalloutDetector().detect(doc)
        assert len(anns) == 0


# ──────────────────────────────────────────────────────────────────────────────
# KeyTermDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestKeyTermDetector:
    def test_bold_term(self) -> None:
        doc = _doc(_para("The **derivative** measures rate of change."))
        anns = KeyTermDetector().detect(doc)
        assert len(anns) >= 1
        assert anns[0].term == "derivative"

    def test_definition_site_term(self) -> None:
        doc = _doc(_para("Matrix is a rectangular array."))
        anns = KeyTermDetector().detect(doc)
        assert len(anns) >= 1

    def test_no_key_terms(self) -> None:
        doc = _doc(_para("No bold or definitions here."))
        anns = KeyTermDetector().detect(doc)
        assert len(anns) == 0


# ──────────────────────────────────────────────────────────────────────────────
# CrossReferenceDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestCrossReferenceDetector:
    def test_see_section(self) -> None:
        doc = _doc(_para("See Section 3.2 for details."))
        anns = CrossReferenceDetector().detect(doc)
        assert len(anns) >= 1
        assert "3.2" in anns[0].label

    def test_as_shown_in_figure(self) -> None:
        doc = _doc(_para("As shown in Figure 1."))
        anns = CrossReferenceDetector().detect(doc)
        assert len(anns) >= 1

    def test_no_cross_refs(self) -> None:
        doc = _doc(_para("No references here."))
        anns = CrossReferenceDetector().detect(doc)
        assert len(anns) == 0


# ──────────────────────────────────────────────────────────────────────────────
# FigureAssociationDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestFigureAssociationDetector:
    def test_figure_with_caption(self) -> None:
        fig = _figure(caption="Figure 1: A chart")
        doc = _doc(fig)
        anns = FigureAssociationDetector().detect(doc)
        assert len(anns) == 1
        assert "chart" in anns[0].caption_text.lower()

    def test_figure_without_caption_uses_next_para(self) -> None:
        fig = _figure()
        para = _para("This describes the figure.")
        doc = _doc(fig, para)
        anns = FigureAssociationDetector().detect(doc)
        assert len(anns) == 1
        assert "describes" in anns[0].caption_text.lower()

    def test_no_figures(self) -> None:
        doc = _doc(_para("No figures."))
        anns = FigureAssociationDetector().detect(doc)
        assert anns == []


# ──────────────────────────────────────────────────────────────────────────────
# EquationAssociationDetector
# ──────────────────────────────────────────────────────────────────────────────


class TestEquationAssociationDetector:
    def test_equation_with_label(self) -> None:
        eq = _equation(label="Eq. 3")
        doc = _doc(eq)
        anns = EquationAssociationDetector().detect(doc)
        assert len(anns) == 1
        assert anns[0].label == "Eq. 3"

    def test_equation_without_label(self) -> None:
        eq = _equation()
        doc = _doc(eq)
        anns = EquationAssociationDetector().detect(doc)
        assert len(anns) == 1
        assert "Eq." in anns[0].label

    def test_no_equations(self) -> None:
        doc = _doc(_para("No equations."))
        anns = EquationAssociationDetector().detect(doc)
        assert anns == []


# ──────────────────────────────────────────────────────────────────────────────
# EnrichmentEngine
# ──────────────────────────────────────────────────────────────────────────────


class TestEnrichmentEngine:
    def test_single_detector(self) -> None:
        doc = _doc(_para("Definition: A set is a collection."))
        engine = EnrichmentEngine(detectors=[DefinitionDetector()])
        anns = engine.enrich(doc)
        assert len(anns) >= 1
        assert anns[0].detector == "DefinitionDetector"

    def test_multiple_detectors(self) -> None:
        doc = _doc(
            _para("Definition: A group is a set."),
            _para("See Section 1 for context."),
        )
        engine = EnrichmentEngine(detectors=[DefinitionDetector(), CrossReferenceDetector()])
        anns = engine.enrich(doc)
        types = {a.type for a in anns}
        assert "definition" in types
        assert "cross_reference" in types

    def test_deduplication_keeps_highest_confidence(self) -> None:
        node = _para("Definition: A ring is a set.")
        doc = _doc(node)
        engine = EnrichmentEngine(detectors=[DefinitionDetector(), DefinitionDetector()])
        anns = engine.enrich(doc)
        by_type_node = [(a.type, str(a.node_id)) for a in anns]
        assert len(by_type_node) == len(set(by_type_node))

    def test_empty_detectors(self) -> None:
        engine = EnrichmentEngine()
        anns = engine.enrich(_doc())
        assert anns == []

    def test_add_detector(self) -> None:
        engine = EnrichmentEngine()
        engine.add_detector(DefinitionDetector())
        assert len(engine.detectors) == 1

    def test_detector_failure_handled(self) -> None:
        class BrokenDetector:
            def detect(self, document: CanonicalDocument) -> list:
                raise RuntimeError("boom")

        doc = _doc(_para("Hello"))
        engine = EnrichmentEngine(detectors=[BrokenDetector()])
        anns = engine.enrich(doc)
        assert anns == []

    def test_returns_annotation_types(self) -> None:
        doc = _doc(
            _para("Definition: A field is a set."),
            _para("Example: The integers form a field."),
            _para("Learning Objective: Understand fields."),
        )
        engine = EnrichmentEngine(
            detectors=[
                DefinitionDetector(),
                ExampleDetector(),
                ObjectiveDetector(),
            ]
        )
        anns = engine.enrich(doc)
        types = {a.type for a in anns}
        assert "definition" in types
        assert "example" in types
        assert "objective" in types
