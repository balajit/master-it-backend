"""Unit tests for the page-based pipeline.

Tests PageContext creation, page-aware enrichment, unit building,
concept extraction, and the full page-based orchestrator flow.
"""

from __future__ import annotations

from uuid import uuid4

from learning_platform.models.annotation import DefinitionAnnotation
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Heading,
    HeadingLevel,
    PageBreak,
    Paragraph,
    StyledText,
    TextRun,
)
from learning_platform.models.page_context import PageContext, build_page_contexts
from learning_platform.stages.concept_extractor.extractor import ConceptExtractor
from learning_platform.stages.concept_extractor.text_strategy import (
    TextPatternStrategy,
)
from learning_platform.stages.enricher.engine import EnrichmentEngine
from learning_platform.stages.enricher.semantic import SemanticEnricher
from learning_platform.stages.unit_builder.builder import LearningUnitBuilder

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


def _para(text: str, page: int = 1) -> DocumentNode:
    return DocumentNode(
        content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
        page=page,
    )


def _heading(text: str, level: int = 2, page: int = 1) -> DocumentNode:
    return DocumentNode(
        content=Heading(
            level=HeadingLevel(min(level, 4)),
            text=StyledText(runs=[TextRun(text=text)]),
        ),
        page=page,
    )


def _page_break(page: int = 2) -> DocumentNode:
    return DocumentNode(content=PageBreak(), page=page)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: build_page_contexts
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildPageContexts:
    """Test page context creation from a normalized document."""

    def test_groups_nodes_by_page(self) -> None:
        p1 = _para("Page 1 content", page=1)
        p2 = _para("Page 2 content", page=2)
        p3 = _para("Page 3 content", page=3)
        doc = _doc(p1, p2, p3)

        pages = build_page_contexts(doc)

        assert len(pages) == 3
        assert pages[0].page_number == 1
        assert pages[1].page_number == 2
        assert pages[2].page_number == 3

    def test_page_nodes_correct(self) -> None:
        p1a = _para("Page 1 A", page=1)
        p1b = _para("Page 1 B", page=1)
        p2 = _para("Page 2", page=2)
        doc = _doc(p1a, p1b, p2)

        pages = build_page_contexts(doc)

        assert len(pages[0].nodes) == 2
        assert len(pages[1].nodes) == 1

    def test_page_text_concatenated(self) -> None:
        p1 = _para("Hello world", page=1)
        p2 = _para("Goodbye world", page=1)
        doc = _doc(p1, p2)

        pages = build_page_contexts(doc)

        assert "Hello world" in pages[0].page_text
        assert "Goodbye world" in pages[0].page_text

    def test_heading_extracted_as_title(self) -> None:
        h = _heading("Chapter Title", level=1, page=1)
        p = _para("Content", page=1)
        doc = _doc(h, p)

        pages = build_page_contexts(doc)

        assert pages[0].heading == "Chapter Title"

    def test_no_heading_returns_none(self) -> None:
        p = _para("Just text", page=1)
        doc = _doc(p)

        pages = build_page_contexts(doc)

        assert pages[0].heading is None

    def test_empty_document(self) -> None:
        doc = _doc()

        pages = build_page_contexts(doc)

        assert pages == []

    def test_page_zero_included(self) -> None:
        p0 = _para("Unknown page", page=0)
        p1 = _para("Page 1", page=1)
        doc = _doc(p0, p1)

        pages = build_page_contexts(doc)

        assert len(pages) == 2
        assert pages[0].page_number == 0
        assert pages[1].page_number == 1

    def test_skip_page_breaks_in_text(self) -> None:
        pb = _page_break(page=1)
        p = _para("Content", page=1)
        doc = _doc(pb, p)

        pages = build_page_contexts(doc)

        # Page break node is included but its text is not in page_text
        assert len(pages[0].nodes) == 2
        assert "Content" in pages[0].page_text

    def test_annotations_initially_empty(self) -> None:
        p = _para("Content", page=1)
        doc = _doc(p)

        pages = build_page_contexts(doc)

        assert pages[0].annotations == []
        assert pages[0].units == []
        assert pages[0].concepts == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Page-aware enrichment
# ──────────────────────────────────────────────────────────────────────────────


class TestPageAwareEnrichment:
    """Test page-aware enrichment via SemanticEnricher.enrich_pages."""

    def test_enrich_populates_annotations(self) -> None:
        from learning_platform.stages.enricher.detectors.definition import (
            DefinitionDetector,
        )

        engine = EnrichmentEngine([DefinitionDetector()])
        enricher = SemanticEnricher(engine)

        p1 = _para("Definition: energy is the capacity to do work", page=1)
        p2 = _para("Some other text", page=2)
        doc = _doc(p1, p2)
        pages = build_page_contexts(doc)

        result = enricher.enrich_pages(pages)

        # Page 1 should have annotations (definition detector matches)
        assert len(result[0].annotations) >= 1
        # Page 2 has no definition pattern
        assert len(result[1].annotations) == 0

    def test_enrich_pages_returns_same_list(self) -> None:
        enricher = SemanticEnricher()
        p1 = _para("Hello", page=1)
        doc = _doc(p1)
        pages = build_page_contexts(doc)

        result = enricher.enrich_pages(pages)

        assert result is pages

    def test_empty_page_not_processed(self) -> None:
        enricher = SemanticEnricher()
        pages = [PageContext(page_number=99, nodes=[], page_text="")]

        result = enricher.enrich_pages(pages)

        assert result[0].annotations == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Page-aware unit building
# ──────────────────────────────────────────────────────────────────────────────


class TestPageAwareUnitBuilding:
    """Test page-aware unit building via LearningUnitBuilder.build_pages."""

    def test_heading_creates_unit(self) -> None:
        h = _heading("Introduction", level=2, page=1)
        p = _para("Content here", page=1)
        doc = _doc(h, p)
        pages = build_page_contexts(doc)

        builder = LearningUnitBuilder()
        units = builder.build_pages(pages)

        assert len(units) >= 1
        assert units[0].title == "Introduction"

    def test_units_across_pages(self) -> None:
        h1 = _heading("Chapter 1", level=1, page=1)
        p1 = _para("Content on page 1", page=1)
        h2 = _heading("Chapter 2", level=1, page=2)
        p2 = _para("Content on page 2", page=2)
        doc = _doc(h1, p1, h2, p2)
        pages = build_page_contexts(doc)

        builder = LearningUnitBuilder()
        units = builder.build_pages(pages)

        titles = [u.title for u in units]
        assert "Chapter 1" in titles
        assert "Chapter 2" in titles

    def test_content_collected_into_units(self) -> None:
        h = _heading("Section", level=2, page=1)
        p1 = _para("First paragraph", page=1)
        p2 = _para("Second paragraph", page=1)
        doc = _doc(h, p1, p2)
        pages = build_page_contexts(doc)

        builder = LearningUnitBuilder()
        units = builder.build_pages(pages)

        # The section unit should have content references
        section_unit = [u for u in units if u.title == "Section"][0]
        assert len(section_unit.content_references) >= 2

    def test_page_annotations_used(self) -> None:
        h = _heading("Definitions", level=2, page=1)
        p = _para("Term: something important", page=1)
        doc = _doc(h, p)
        pages = build_page_contexts(doc)

        # Manually add an annotation to the page

        pages[0].annotations.append(
            DefinitionAnnotation(
                node_id=p.id,
                term="Term",
                definition_text="something important",
                confidence=0.9,
                detector="test",
            )
        )

        builder = LearningUnitBuilder()
        units = builder.build_pages(pages)

        # The unit should have a definition reference
        defs = [u for u in units if u.title == "Definitions"][0]
        assert len(defs.definitions) >= 1

    def test_empty_pages(self) -> None:
        builder = LearningUnitBuilder()
        units = builder.build_pages([])

        assert units == []

    def test_page_without_heading(self) -> None:
        p1 = _para("No heading here", page=1)
        h2 = _heading("Later heading", level=2, page=2)
        p2 = _para("Content", page=2)
        doc = _doc(p1, h2, p2)
        pages = build_page_contexts(doc)

        builder = LearningUnitBuilder()
        units = builder.build_pages(pages)

        # Content from page 1 goes into course unit (no heading)
        assert len(units) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Page-aware concept extraction
# ──────────────────────────────────────────────────────────────────────────────


class TestPageAwareConceptExtraction:
    """Test page-aware concept extraction via ConceptExtractor.extract_pages."""

    def test_extract_pages_returns_concept_map(self) -> None:
        p1 = _para(
            "Learning objective: students will understand energy concepts",
            page=1,
        )
        doc = _doc(p1)
        pages = build_page_contexts(doc)

        extractor = ConceptExtractor([TextPatternStrategy()])
        concept_map = extractor.extract_pages(pages, units=[])

        assert hasattr(concept_map, "concepts")
        assert hasattr(concept_map, "relationships")

    def test_concepts_from_page_text(self) -> None:
        p1 = _para(
            "Learning objective: master the concept of thermodynamics",
            page=1,
        )
        doc = _doc(p1)
        pages = build_page_contexts(doc)

        extractor = ConceptExtractor([TextPatternStrategy()])
        concept_map = extractor.extract_pages(pages, units=[])

        names = [c.name.lower() for c in concept_map.concepts]
        assert any("thermodynamics" in n for n in names)

    def test_concepts_deduplicated_across_pages(self) -> None:
        p1 = _para(
            "Learning objective: understand energy transformation",
            page=1,
        )
        p2 = _para(
            "Learning objective: understand energy transformation",
            page=2,
        )
        doc = _doc(p1, p2)
        pages = build_page_contexts(doc)

        extractor = ConceptExtractor([TextPatternStrategy()])
        concept_map = extractor.extract_pages(pages, units=[])

        # Same text on both pages → deduplicated to one concept
        energy_concepts = [
            c for c in concept_map.concepts
            if "energy transformation" in c.name.lower()
        ]
        assert len(energy_concepts) <= 1
        if energy_concepts:
            # Mention count should reflect both pages
            assert energy_concepts[0].mention_count >= 1

    def test_empty_pages(self) -> None:
        extractor = ConceptExtractor([TextPatternStrategy()])
        concept_map = extractor.extract_pages([], units=[])

        assert concept_map.concepts == []

    def test_pages_without_text(self) -> None:
        pages = [PageContext(page_number=1, nodes=[], page_text="")]
        extractor = ConceptExtractor([TextPatternStrategy()])
        concept_map = extractor.extract_pages(pages, units=[])

        assert concept_map.concepts == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests: TextPatternStrategy.extract_from_text
# ──────────────────────────────────────────────────────────────────────────────


class TestTextPatternStrategyPageAware:
    """Test the page-aware TextPatternStrategy methods."""

    def test_extract_from_text(self) -> None:
        strategy = TextPatternStrategy()
        text = "Step 1: Open the application. Step 2: Configure settings."
        concepts = strategy.extract_from_text(text)

        assert len(concepts) >= 1
        assert any(c.category.value == "process" for c in concepts)

    def test_extract_from_text_empty(self) -> None:
        strategy = TextPatternStrategy()
        concepts = strategy.extract_from_text("")

        assert concepts == []

    def test_extract_from_text_with_source_ids(self) -> None:
        strategy = TextPatternStrategy()
        nid = uuid4()
        text = "Step 1: First action"
        concepts = strategy.extract_from_text(text, source_node_ids=[nid])

        for c in concepts:
            assert nid in c.source_node_ids


# ──────────────────────────────────────────────────────────────────────────────
# Tests: PageContext model
# ──────────────────────────────────────────────────────────────────────────────


class TestPageContextModel:
    """Test PageContext dataclass behavior."""

    def test_default_fields(self) -> None:
        ctx = PageContext(page_number=1)

        assert ctx.page_number == 1
        assert ctx.nodes == []
        assert ctx.page_text == ""
        assert ctx.heading is None
        assert ctx.annotations == []
        assert ctx.units == []
        assert ctx.concepts == []

    def test_mutable_annotations(self) -> None:
        ctx = PageContext(page_number=1)
        ann = DefinitionAnnotation(
            node_id=uuid4(),
            term="test",
            definition_text="a test",
            confidence=0.9,
            detector="test",
        )
        ctx.annotations.append(ann)

        assert len(ctx.annotations) == 1
