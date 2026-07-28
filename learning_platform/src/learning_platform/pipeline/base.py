"""Pipeline stage interfaces.

Every stage in the processing pipeline implements a Protocol from this module.
Stages are composed by the Orchestrator — dependencies flow inward via
constructor injection (Dependency Inversion).

Core pipeline (page-based):
    AbstractParser → CanonicalDocument
    StructuralNormalizer → CanonicalDocument
    build_page_contexts → list[PageContext]
    SemanticEnricher.enrich_pages → list[PageContext]  (annotations populated)
    LearningUnitBuilder.build_pages → list[LearningUnit]
    ConceptExtractor.extract_pages → ConceptMap
    KnowledgeGraphBuilder → KnowledgeGraph
    LearningSequenceBuilder → StudyPlan

Plugin-provided stages:
    QuizGenerator → list[Quiz]
    DocumentSummarizer → list[Summary]
    SearchIndex → list[SearchResult]
    VectorIndexer → VectorStore
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from learning_platform.models.annotation import Annotation
    from learning_platform.models.concept import ConceptMap
    from learning_platform.models.document import CanonicalDocument
    from learning_platform.models.knowledge_graph import KnowledgeGraph
    from learning_platform.models.learning_unit import LearningUnit
    from learning_platform.models.page_context import PageContext
    from learning_platform.models.quiz import Quiz
    from learning_platform.models.search import SearchQuery, SearchResult
    from learning_platform.models.sequence import StudyPlan
    from learning_platform.models.summary import Summary
    from learning_platform.models.vector import VectorDocument, VectorStore


# ──────────────────────────────────────────────────────────────────────────────
# Abstract Parser
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class AbstractParser(Protocol):
    """Defines the contract every parser adapter must satisfy.

    A parser adapter wraps a third-party document conversion library
    (Docling, MinerU, Marker, etc.) and converts its output into the
    ``CanonicalDocument`` model. The caller never depends on the
    underlying library — only on this Protocol.

    Methods
    -------
    parse(source)
        Convert a file at *source* into a ``CanonicalDocument``.

    supports(source)
        Return ``True`` if this adapter can handle the file (by
        extension, MIME type, or other heuristic).

    confidence(source)
        Return a score in ``[0.0, 1.0]`` indicating how confidently
        this adapter can parse the file. The ``ParserSelector`` uses
        this to pick the best adapter when multiple claim support.
    """

    def parse(self, source: str) -> CanonicalDocument: ...

    def supports(self, source: str) -> bool: ...

    def confidence(self, source: str) -> float: ...


# ──────────────────────────────────────────────────────────────────────────────
# Downstream Stages
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class StructuralNormalizer(Protocol):
    """Normalizes heading levels, merges fragmented sections, resolves TOC."""

    def normalize(self, document: CanonicalDocument) -> CanonicalDocument: ...


@runtime_checkable
class Detector(Protocol):
    """Scans a CanonicalDocument and returns Annotations.

    A detector never modifies the document.  It inspects nodes and
    produces structured ``Annotation`` findings that the
    ``EnrichmentEngine`` merges into a final enrichment layer.
    """

    def detect(self, document: CanonicalDocument) -> list: ...


@runtime_checkable
class SemanticEnricher(Protocol):
    """Enriches a document and returns both the document and annotations.

    The enriched document may carry metadata derived from annotations.
    The annotations list is passed downstream to the unit builder.

    Page-aware: ``enrich_pages`` processes all nodes on each page
    together, enabling cross-node annotation discovery.
    """

    def enrich(
        self, document: CanonicalDocument
    ) -> tuple[CanonicalDocument, list[Annotation]]: ...

    def enrich_pages(self, pages: list[PageContext]) -> list[PageContext]: ...


@runtime_checkable
class LearningUnitBuilder(Protocol):
    """Decomposes a CanonicalDocument + Annotations into discrete LearningUnits.

    Page-aware: ``build_pages`` creates units from page-level node
    groupings, using page context for richer unit metadata.
    """

    def build(
        self, document: CanonicalDocument, annotations: list[Annotation]
    ) -> list[LearningUnit]: ...

    def build_pages(self, pages: list[PageContext]) -> list[LearningUnit]: ...


@runtime_checkable
class ConceptExtractor(Protocol):
    """Extracts domain concepts from a document, annotations, and learning units.

    The extractor identifies concepts, skills, vocabulary, processes,
    facts, rules, formulas, and definitions.  It computes importance
    scores, tracks mentions, and discovers relationships between
    concepts.  The underlying implementation can be rule-based or
    LLM-based — callers depend only on this Protocol.

    Page-aware: ``extract_pages`` processes each page's text and
    annotations together, enabling page-level concept grouping.
    """

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> ConceptMap: ...

    def extract_pages(
        self,
        pages: list[PageContext],
        units: list[LearningUnit],
    ) -> ConceptMap: ...


@runtime_checkable
class KnowledgeGraphBuilder(Protocol):
    """Constructs a KnowledgeGraph from LearningUnits and Concepts."""

    def build(
        self,
        units: list[LearningUnit],
        concepts: ConceptMap,
    ) -> KnowledgeGraph: ...


@runtime_checkable
class LearningSequenceBuilder(Protocol):
    """Derives an ordered StudyPlan from a KnowledgeGraph."""

    def build(self, graph: KnowledgeGraph) -> StudyPlan: ...


# ──────────────────────────────────────────────────────────────────────────────
# Plugin-Provided Stages
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class QuizGenerator(Protocol):
    """Generates quizzes from a StudyPlan, learning units, and concepts."""

    def generate(
        self,
        plan: StudyPlan,
        units: list[LearningUnit],
        concepts: ConceptMap,
    ) -> list[Quiz]: ...


@runtime_checkable
class DocumentSummarizer(Protocol):
    """Produces summaries of a document and its learning units."""

    def summarize(
        self,
        document: CanonicalDocument,
        units: list[LearningUnit],
    ) -> list[Summary]: ...


@runtime_checkable
class SearchIndex(Protocol):
    """Indexes content and supports filtered text search."""

    def search(self, query: SearchQuery) -> list[SearchResult]: ...

    def add(self, documents: list[VectorDocument]) -> None: ...

    def remove(self, ids: list[str]) -> None: ...


@runtime_checkable
class VectorIndexer(Protocol):
    """Embeds and indexes documents for similarity-based retrieval."""

    def index(self, documents: list[VectorDocument]) -> VectorStore: ...

    def similarity_search(self, query: str, k: int = 5) -> list[SearchResult]: ...
