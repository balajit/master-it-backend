# Plan: Page-Based Pipeline Redesign

## Problem

Currently, the pipeline after the normalizer processes each `DocumentNode` independently:
- **SemanticEnricher** runs detectors across `document.nodes` flat list
- **LearningUnitBuilder** splits on headings, collecting nodes into units
- **ConceptExtractor** scans full document text or per-node annotations
- **KnowledgeGraphBuilder** and **LearningSequenceBuilder** aggregate results

This means a "concept" is extracted from individual document elements. The user wants concepts to emerge from **page-level groupings** — all nodes belonging to the same page are processed together, enabling richer context for extraction.

## Design

### New Model: `PageContext`

A `PageContext` groups all nodes on a single page and carries computed page-level state:

```python
@dataclass
class PageContext:
    page_number: int
    nodes: list[DocumentNode]          # all nodes on this page
    page_text: str                     # concatenated plain text
    heading: str | None                # first heading on the page (title)
    annotations: list[Annotation]      # enriched per-page
    units: list[LearningUnit]          # units originating on this page
    concepts: list[Concept]            # concepts extracted from this page
```

### Pipeline Flow (after normalizer)

```
CanonicalDocument (normalized)
    │
    ▼
GroupNodesByPage ──► list[PageContext]
    │
    ▼ (per page, in parallel or sequential)
    ├── SemanticEnricher.enrich_pages(pages)  ──► pages (annotations populated)
    ├── LearningUnitBuilder.build_pages(pages) ──► pages (units populated)
    ├── ConceptExtractor.extract_pages(pages)  ──► pages (concepts populated)
    │
    ▼ (aggregate across pages)
    ├── KnowledgeGraphBuilder.build(units, concepts)  ──► KnowledgeGraph
    └── LearningSequenceBuilder.build(graph)          ──► StudyPlan
```

Key insight: The first 3 stages operate on `list[PageContext]` (page-based). The last 2 stages aggregate results and don't need page context — they already receive the aggregated products.

### What Changes

#### 1. New file: `learning_platform/src/learning_platform/models/page_context.py`

Create `PageContext` dataclass and a `build_page_contexts(document)` factory function that:
- Groups `document.nodes` by `node.page`
- Concatenates plain text per page
- Extracts first heading as page title
- Returns `list[PageContext]` sorted by page number

#### 2. Update Protocol: `pipeline/base.py`

Add new page-aware protocol methods (keep old ones for backward compat):

```python
class SemanticEnricher(Protocol):
    def enrich(self, document: CanonicalDocument) -> tuple[CanonicalDocument, list[Annotation]]: ...
    def enrich_pages(self, pages: list[PageContext]) -> list[PageContext]: ...

class LearningUnitBuilder(Protocol):
    def build(self, document: CanonicalDocument, annotations: list[Annotation]) -> list[LearningUnit]: ...
    def build_pages(self, pages: list[PageContext]) -> list[LearningUnit]: ...

class ConceptExtractor(Protocol):
    def extract(self, document: CanonicalDocument, annotations: list[Annotation], units: list[LearningUnit]) -> ConceptMap: ...
    def extract_pages(self, pages: list[PageContext], units: list[LearningUnit]) -> ConceptMap: ...
```

#### 3. Update `SemanticEnricher` (`stages/enricher/semantic.py`)

Add `enrich_pages()` method:
- For each `PageContext`, create a temporary `CanonicalDocument` containing only that page's nodes
- Run `self._engine.enrich(page_doc)` on it
- Store annotations in `page_context.annotations`
- Return updated `list[PageContext]`

#### 4. Update `LearningUnitBuilder` (`stages/unit_builder/builder.py`)

Add `build_pages()` method:
- Iterate over `list[PageContext]` in page order
- Within each page, run the existing heading-split logic on the page's nodes
- Units get `source_node_ids` from the page's nodes
- Use the page's annotations to populate objectives/definitions/examples
- Return flat `list[LearningUnit]` (across all pages)

#### 5. Update `ConceptExtractor` (`stages/concept_extractor/extractor.py`)

Add `extract_pages()` method:
- For each `PageContext`, run strategies with the page's nodes, annotations, and page-level units
- Aggregate concepts across all pages
- Deduplicate by name (existing logic)
- Score importance and detect relationships across pages
- Return `ConceptMap`

Update strategies to accept page-level text (not full document):
- `TextPatternStrategy.extract()` already calls `all_text(document)` — change to accept page text
- `AnnotationStrategy.extract()` already works per-annotation — no change needed

#### 6. Update `EnrichmentEngine` (`stages/enricher/engine.py`)

No structural changes needed — detectors already accept `CanonicalDocument`. The enricher creates a per-page document to pass to the engine.

#### 7. Update `PipelineOrchestrator` (`pipeline/orchestrator.py`)

```python
def run(self, source: str) -> PipelineResult:
    document = self._parser.parse(source)
    document = self._normalizer.normalize(document)

    # Build page contexts from normalized document
    pages = build_page_contexts(document)

    # Page-aware stages
    pages = self._enricher.enrich_pages(pages)
    units = self._unit_builder.build_pages(pages)
    concepts = self._concept_extractor.extract_pages(pages, units)

    # Aggregate stages (unchanged)
    graph = self._graph_builder.build(units, concepts)
    study_plan = self._sequence_builder.build(graph)

    # Reconstruct document-level annotations from pages
    annotations = [ann for p in pages for ann in p.annotations]

    return PipelineResult(...)
```

#### 8. Update `PipelineResult`

Add `pages: list[PageContext]` field to capture page-level results.

### Files to Create
- `learning_platform/src/learning_platform/models/page_context.py`

### Files to Modify
- `learning_platform/src/learning_platform/pipeline/base.py` — add page-aware protocol methods
- `learning_platform/src/learning_platform/pipeline/orchestrator.py` — use page contexts
- `learning_platform/src/learning_platform/stages/enricher/semantic.py` — add `enrich_pages()`
- `learning_platform/src/learning_platform/stages/unit_builder/builder.py` — add `build_pages()`
- `learning_platform/src/learning_platform/stages/concept_extractor/extractor.py` — add `extract_pages()`
- `learning_platform/src/learning_platform/stages/concept_extractor/text_strategy.py` — accept page text
- `learning_platform/src/learning_platform/stages/concept_extractor/strategy.py` — update protocol
- `learning_platform/src/learning_platform/models/__init__.py` — export PageContext

### Files to Update (Tests)
- `learning_platform/tests/unit/test_unit_builder.py` — add page-based tests
- `learning_platform/tests/unit/test_concept_extractor.py` — add page-based tests
- `learning_platform/tests/unit/test_enrichment.py` — add page-based tests
- `learning_platform/tests/unit/test_graph_builder.py` — verify no breakage
- `learning_platform/tests/unit/test_sequence_builder.py` — verify no breakage

### What Does NOT Change
- **Parser/Adapter** — still produces `CanonicalDocument`
- **Normalizer** — still normalizes the document tree
- **Enrichment detectors** — still accept `CanonicalDocument` (we create per-page docs)
- **KnowledgeGraphBuilder** — still takes `units + concepts` (aggregated)
- **LearningSequenceBuilder** — still takes `KnowledgeGraph` (aggregated)
- **All existing single-doc APIs** — old methods remain for backward compatibility

## Implementation Order

1. Create `PageContext` model and `build_page_contexts()` factory
2. Update `pipeline/base.py` protocols
3. Implement `enrich_pages()` in `SemanticEnricher`
4. Implement `build_pages()` in `LearningUnitBuilder`
5. Implement `extract_pages()` in `ConceptExtractor` + update `TextPatternStrategy`
6. Update `PipelineOrchestrator` to use page-based flow
7. Update `PipelineResult` to include pages
8. Write/update tests
9. Run full test suite + lint
