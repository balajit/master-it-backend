"""Unit tests for ConceptExtractor and extraction strategies."""

from __future__ import annotations

from uuid import uuid4

import pytest

from learning_platform.models.annotation import (
    DefinitionAnnotation,
    KeyTermAnnotation,
    ObjectiveAnnotation,
)
from learning_platform.models.concept import Concept, ConceptCategory, ConceptMap, RelationType
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Heading,
    HeadingLevel,
    Paragraph,
    StyledText,
    TextRun,
)
from learning_platform.models.learning_unit import LearningUnit, UnitType
from learning_platform.stages.concept_extractor.annotation_strategy import AnnotationStrategy
from learning_platform.stages.concept_extractor.extractor import ConceptExtractor
from learning_platform.stages.concept_extractor.llm_strategy import LlmConceptStrategy
from learning_platform.stages.concept_extractor.text_strategy import TextPatternStrategy

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
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


def _heading(text: str, level: int = 2) -> DocumentNode:
    return DocumentNode(
        content=Heading(
            level=HeadingLevel(min(level, 4)),
            text=StyledText(runs=[TextRun(text=text)]),
        ),
    )


def _unit(
    title: str,
    unit_type: UnitType = UnitType.LESSON,
    node_ids: list | None = None,
) -> LearningUnit:
    return LearningUnit(
        unit_type=unit_type,
        title=title,
        source_node_ids=node_ids or [],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Concept model
# ──────────────────────────────────────────────────────────────────────────────


class TestConceptModel:
    def test_concept_by_name(self) -> None:
        c = Concept(name="gravity", category=ConceptCategory.CONCEPT)
        cmap = ConceptMap(concepts=[c])
        assert cmap.concept_by_name("gravity") is c
        assert cmap.concept_by_name("Gravity") is c
        assert cmap.concept_by_name("missing") is None

    def test_concepts_in_category(self) -> None:
        c1 = Concept(name="A", category=ConceptCategory.SKILL)
        c2 = Concept(name="B", category=ConceptCategory.FACT)
        c3 = Concept(name="C", category=ConceptCategory.SKILL)
        cmap = ConceptMap(concepts=[c1, c2, c3])
        skills = cmap.concepts_in_category(ConceptCategory.SKILL)
        assert len(skills) == 2


# ──────────────────────────────────────────────────────────────────────────────
# AnnotationStrategy
# ──────────────────────────────────────────────────────────────────────────────


class TestAnnotationStrategy:
    def test_definition_becomes_concept(self) -> None:
        ann = DefinitionAnnotation(
            node_id=uuid4(), term="photosynthesis", definition_text="converting light"
        )
        doc = _doc(_para("Photosynthesis is important."))
        concepts = AnnotationStrategy().extract(doc, [ann], [])
        assert len(concepts) == 1
        assert concepts[0].name == "photosynthesis"
        assert concepts[0].category == ConceptCategory.DEFINITION

    def test_key_term_becomes_concept(self) -> None:
        ann = KeyTermAnnotation(node_id=uuid4(), term="algorithm")
        doc = _doc(_para("An algorithm is a procedure."))
        concepts = AnnotationStrategy().extract(doc, [ann], [])
        assert len(concepts) == 1
        assert concepts[0].category == ConceptCategory.VOCABULARY

    def test_objective_becomes_skill(self) -> None:
        ann = ObjectiveAnnotation(node_id=uuid4(), objective_text="Understand Newton's laws")
        doc = _doc(_para("Some text."))
        concepts = AnnotationStrategy().extract(doc, [ann], [])
        assert len(concepts) == 1
        assert concepts[0].category == ConceptCategory.SKILL
        assert "Newton" in concepts[0].name

    def test_empty_annotations(self) -> None:
        doc = _doc(_para("Nothing special."))
        concepts = AnnotationStrategy().extract(doc, [], [])
        assert concepts == []


# ──────────────────────────────────────────────────────────────────────────────
# TextPatternStrategy
# ──────────────────────────────────────────────────────────────────────────────


class TestTextPatternStrategy:
    def test_skill_detected(self) -> None:
        doc = _doc(_para("Learning objective: Understand photosynthesis."))
        concepts = TextPatternStrategy().extract(doc, [], [])
        skills = [c for c in concepts if c.category == ConceptCategory.SKILL]
        assert len(skills) >= 1
        assert any("photosynthesis" in c.name.lower() for c in skills)

    def test_process_detected(self) -> None:
        doc = _doc(_para("Step 1: Heat the oven to 350 degrees."))
        concepts = TextPatternStrategy().extract(doc, [], [])
        processes = [c for c in concepts if c.category == ConceptCategory.PROCESS]
        assert len(processes) >= 1

    def test_rule_detected(self) -> None:
        doc = _doc(_para("Rule: Always check your work."))
        concepts = TextPatternStrategy().extract(doc, [], [])
        rules = [c for c in concepts if c.category == ConceptCategory.RULE]
        assert len(rules) >= 1

    def test_formula_detected(self) -> None:
        doc = _doc(_para("The formula: F = ma"))
        concepts = TextPatternStrategy().extract(doc, [], [])
        formulas = [c for c in concepts if c.category == ConceptCategory.FORMULA]
        assert len(formulas) >= 1

    def test_fact_detected(self) -> None:
        doc = _doc(_para("Fact: Water boils at 100 degrees Celsius."))
        concepts = TextPatternStrategy().extract(doc, [], [])
        facts = [c for c in concepts if c.category == ConceptCategory.FACT]
        assert len(facts) >= 1

    def test_empty_document(self) -> None:
        doc = _doc()
        concepts = TextPatternStrategy().extract(doc, [], [])
        assert concepts == []

    def test_mention_count_increases(self) -> None:
        doc = _doc(
            _para("Learning objective: Master calculus."),
            _para("Learning objective: Master calculus in practice."),
        )
        concepts = TextPatternStrategy().extract(doc, [], [])
        skills = [c for c in concepts if c.category == ConceptCategory.SKILL]
        assert len(skills) >= 1
        assert skills[0].mention_count >= 2


# ──────────────────────────────────────────────────────────────────────────────
# LlmConceptStrategy (stub)
# ──────────────────────────────────────────────────────────────────────────────


class TestLlmConceptStrategy:
    def test_returns_empty(self) -> None:
        doc = _doc(_para("Some text."))
        concepts = LlmConceptStrategy().extract(doc, [], [])
        assert concepts == []


# ──────────────────────────────────────────────────────────────────────────────
# ConceptExtractor orchestrator
# ──────────────────────────────────────────────────────────────────────────────


class TestConceptExtractor:
    def test_empty_strategies(self) -> None:
        doc = _doc(_para("Text."))
        cmap = ConceptExtractor().extract(doc, [], [])
        assert cmap.concepts == []
        assert cmap.relationships == []

    def test_deduplication(self) -> None:
        doc = _doc(_para("Definition: gravity is a force."))

        ann = DefinitionAnnotation(node_id=uuid4(), term="gravity", definition_text="a force")
        strategies = [AnnotationStrategy()]
        cmap = ConceptExtractor(strategies).extract(doc, [ann], [])
        gravity = [c for c in cmap.concepts if c.name.lower() == "gravity"]
        assert len(gravity) == 1

    def test_importance_scored(self) -> None:
        doc = _doc(
            _para("Key term: algorithm appears often."),
            _para("The algorithm is used here."),
            _para("Another algorithm reference."),
        )
        anns = [
            KeyTermAnnotation(node_id=doc.nodes[0].id, term="algorithm"),
        ]
        cmap = ConceptExtractor([AnnotationStrategy()]).extract(doc, anns, [])
        assert len(cmap.concepts) >= 1
        assert cmap.concepts[0].importance > 0

    def test_relationships_detected(self) -> None:
        nid1 = uuid4()
        nid2 = uuid4()
        c1 = Concept(
            name="force",
            category=ConceptCategory.DEFINITION,
            source_node_ids=[nid1, nid2],
        )
        c2 = Concept(
            name="acceleration",
            category=ConceptCategory.CONCEPT,
            source_node_ids=[nid1, nid2],
        )
        extractor = ConceptExtractor()

        merged = extractor._deduplicate([c1, c2])
        rels = extractor._detect_relationships(merged, _doc())
        relate_to = [r for r in rels if r.relation_type == RelationType.RELATES_TO]
        assert len(relate_to) >= 1

    def test_unit_mapping(self) -> None:
        nid = uuid4()
        c = Concept(
            name="gravity",
            category=ConceptCategory.CONCEPT,
            source_node_ids=[nid],
        )
        u = _unit("Physics", node_ids=[nid])
        extractor = ConceptExtractor()
        merged = extractor._deduplicate([c])
        extractor._map_to_units(merged, [u])
        assert u.id in merged[0].source_unit_ids

    def test_multiple_strategies_composed(self) -> None:
        doc = _doc(
            _para("Definition: entropy is disorder."),
            _para("Learning objective: Calculate entropy."),
        )
        ann = DefinitionAnnotation(
            node_id=doc.nodes[0].id, term="entropy", definition_text="disorder"
        )
        strategies = [AnnotationStrategy(), TextPatternStrategy()]
        cmap = ConceptExtractor(strategies).extract(doc, [ann], [])
        categories = {c.category for c in cmap.concepts}
        assert ConceptCategory.DEFINITION in categories
        assert ConceptCategory.SKILL in categories

    def test_concept_map_has_relationships(self) -> None:
        doc = _doc(
            _para("Definition: force causes motion."),
            _para("Key term: motion."),
        )
        anns = [
            DefinitionAnnotation(
                node_id=doc.nodes[0].id, term="force", definition_text="causes motion"
            ),
            KeyTermAnnotation(node_id=doc.nodes[1].id, term="motion"),
        ]
        cmap = ConceptExtractor([AnnotationStrategy()]).extract(doc, anns, [])
        # Both concepts share no nodes, so no relationship
        # But they exist as separate concepts
        assert len(cmap.concepts) == 2


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_strategy_failure_handled(self) -> None:
        class FailingStrategy:
            def extract(self, document, annotations, units):
                raise RuntimeError("boom")

        doc = _doc(_para("Text."))
        extractor = ConceptExtractor([FailingStrategy()], fail_fast=False)  # type: ignore[arg-type]
        cmap = extractor.extract(doc, [], [])
        assert cmap.concepts == []

    def test_strategy_failure_fail_fast_raises(self) -> None:
        class FailingStrategy:
            def extract(self, document, annotations, units):
                raise RuntimeError("boom")

        doc = _doc(_para("Text."))
        extractor = ConceptExtractor([FailingStrategy()], fail_fast=True)  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match="Strategy FailingStrategy failed"):
            extractor.extract(doc, [], [])

    def test_concept_aliases_preserved(self) -> None:
        c = Concept(
            name="AI",
            category=ConceptCategory.VOCABULARY,
            aliases=["artificial intelligence"],
        )
        extractor = ConceptExtractor()
        merged = extractor._deduplicate([c])
        assert merged[0].aliases == ["artificial intelligence"]

    def test_dedup_merges_aliases(self) -> None:
        c1 = Concept(
            name="ML",
            category=ConceptCategory.VOCABULARY,
            aliases=["machine learning"],
        )
        c2 = Concept(
            name="ML",
            category=ConceptCategory.VOCABULARY,
            aliases=["statistical learning"],
        )
        extractor = ConceptExtractor()
        merged = extractor._deduplicate([c1, c2])
        assert len(merged) == 1
        assert "machine learning" in merged[0].aliases
        assert "statistical learning" in merged[0].aliases
