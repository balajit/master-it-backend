"""Concept Extractor — orchestrates strategies to build a ConceptMap.

The extractor runs every registered ``ConceptExtractionStrategy``,
merges the raw concept lists, deduplicates by name, scores importance,
and discovers relationships between concepts.

Design Principles
-----------------
- **Strategy pattern**: New extraction backends (LLM, knowledge base
  lookups, etc.) are added by registering a new strategy — zero
  changes to the orchestrator.
- **No content duplication**: Concepts carry ``source_node_ids`` and
  ``source_unit_ids`` that point back to the canonical document.
- **Composable**: The orchestrator is a plain class, not a singleton.
  Callers inject strategies via the constructor.
- **Page-aware**: ``extract_pages`` processes each page's text and
  annotations together, enabling page-level concept grouping.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from learning_platform.models.annotation import Annotation
from learning_platform.models.concept import (
    Concept,
    ConceptMap,
    ConceptRelationship,
    RelationType,
)
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.learning_unit import LearningUnit

from .strategy import ConceptExtractionStrategy

if TYPE_CHECKING:
    from learning_platform.models.page_context import PageContext

_LOG = logging.getLogger(__name__)


class ConceptExtractor:
    """Orchestrates concept extraction from multiple strategies.

    Parameters
    ----------
    strategies : Sequence[ConceptExtractionStrategy] | None
        Ordered list of strategies to execute.  When ``None`` the
        extractor starts empty and strategies must be added via
        ``add_strategy()``.
    """

    def __init__(self, strategies: Sequence[ConceptExtractionStrategy] | None = None) -> None:
        self._strategies: list[ConceptExtractionStrategy] = (
            list(strategies) if strategies is not None else []
        )

    @property
    def strategies(self) -> list[ConceptExtractionStrategy]:
        """Return a copy of the current strategy list."""
        return list(self._strategies)

    def add_strategy(self, strategy: ConceptExtractionStrategy) -> None:
        """Register a strategy for future ``extract()`` calls."""
        self._strategies.append(strategy)

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> ConceptMap:
        """Run all strategies and produce a deduplicated ``ConceptMap``.

        Steps
        -----
        1. Collect raw concepts from every strategy.
        2. Deduplicate by canonical name (case-insensitive).
        3. Aggregate mention counts and source references.
        4. Compute final importance scores.
        5. Discover relationships between concepts.
        6. Map concepts to their source learning units.
        """
        _LOG.info(
            "Extracting concepts from '%s' with %d strategies",
            document.title,
            len(self._strategies),
        )

        raw_concepts: list[Concept] = []
        for strategy in self._strategies:
            name = type(strategy).__name__
            _LOG.debug("Running strategy: %s", name)
            try:
                found = strategy.extract(document, annotations, units)
                _LOG.debug("  → %d concepts from %s", len(found), name)
                raw_concepts.extend(found)
            except Exception:
                _LOG.exception("Strategy %s failed", name)

        merged = self._deduplicate(raw_concepts)
        self._score_importance(merged)
        relationships = self._detect_relationships(merged, document)
        self._map_to_units(merged, units)

        _LOG.info(
            "Concept extraction complete: %d raw → %d merged, %d relationships",
            len(raw_concepts),
            len(merged),
            len(relationships),
        )

        return ConceptMap(concepts=merged, relationships=relationships)

    def extract_pages(
        self,
        pages: list[PageContext],
        units: list[LearningUnit],
    ) -> ConceptMap:
        """Extract concepts from page-grouped nodes.

        For each page, creates a temporary ``CanonicalDocument`` with
        that page's nodes and runs strategies against it.  The page's
        annotations and pre-built units are passed to strategies.

        After per-page extraction, concepts are deduplicated, scored,
        and relationships are detected across all pages.
        """
        from learning_platform.models.document import (
            DocumentMetadata,
        )

        _LOG.info(
            "Extracting concepts from %d pages with %d strategies",
            len(pages),
            len(self._strategies),
        )

        raw_concepts: list[Concept] = []

        for page in pages:
            if not page.nodes:
                continue

            page_doc = CanonicalDocument(
                source=f"page_{page.page_number}",
                title=page.heading or f"Page {page.page_number}",
                metadata=DocumentMetadata(
                    title=page.heading or f"Page {page.page_number}",
                ),
                nodes=page.nodes,
            )

            # Find units that overlap with this page's nodes
            page_node_ids = {n.id for n in page.nodes}
            page_units = [
                u for u in units if any(nid in page_node_ids for nid in u.source_node_ids)
            ]

            for strategy in self._strategies:
                name = type(strategy).__name__
                _LOG.debug("Running strategy on page %d: %s", page.page_number, name)
                try:
                    found = strategy.extract(page_doc, page.annotations, page_units)
                    _LOG.debug(
                        "  → %d concepts from %s on page %d",
                        len(found),
                        name,
                        page.page_number,
                    )
                    raw_concepts.extend(found)
                except Exception:
                    _LOG.exception("Strategy %s failed on page %d", name, page.page_number)

        merged = self._deduplicate(raw_concepts)
        self._score_importance(merged)

        # Build a full document snapshot for relationship detection
        all_nodes = [n for p in pages for n in p.nodes]
        full_doc = CanonicalDocument(
            source="aggregated",
            title="Aggregated",
            metadata=DocumentMetadata(title="Aggregated"),
            nodes=all_nodes,
        )
        relationships = self._detect_relationships(merged, full_doc)
        self._map_to_units(merged, units)

        _LOG.info(
            "Page-aware concept extraction complete: %d raw → %d merged, %d relationships",
            len(raw_concepts),
            len(merged),
            len(relationships),
        )

        return ConceptMap(concepts=merged, relationships=relationships)

    # ──────────────────────────────────────────────────────────────────────
    # Deduplication
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _deduplicate(concepts: list[Concept]) -> list[Concept]:
        """Merge concepts with the same canonical name.

        When two concepts share a name (case-insensitive), the merged
        result keeps the higher importance, sums mention counts, and
        unions source references and aliases.
        """
        best: dict[str, Concept] = {}

        for c in concepts:
            key = c.name.lower()
            existing = best.get(key)
            if existing is None:
                best[key] = c
            else:
                # Merge into existing
                existing.mention_count += c.mention_count
                existing.importance = max(existing.importance, c.importance)
                for nid in c.source_node_ids:
                    if nid not in existing.source_node_ids:
                        existing.source_node_ids.append(nid)
                for uid in c.source_unit_ids:
                    if uid not in existing.source_unit_ids:
                        existing.source_unit_ids.append(uid)
                for alias in c.aliases:
                    if alias not in existing.aliases:
                        existing.aliases.append(alias)

        return list(best.values())

    # ──────────────────────────────────────────────────────────────────────
    # Importance scoring
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _score_importance(concepts: list[Concept]) -> None:
        """Recompute importance based on mention frequency.

        Importance is normalised to ``[0.0, 1.0]`` using a log scale
        so that very frequent terms don't dominate.
        """
        if not concepts:
            return

        max_mentions = max(c.mention_count for c in concepts) or 1
        for c in concepts:
            # Logarithmic scaling:  log(1 + mentions) / log(1 + max)
            import math

            c.importance = round(
                math.log(1 + c.mention_count) / math.log(1 + max_mentions),
                3,
            )

    # ──────────────────────────────────────────────────────────────────────
    # Relationship detection
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_relationships(
        concepts: list[Concept],
        document: CanonicalDocument,
    ) -> list[ConceptRelationship]:
        """Discover relationships between concepts.

        Rules:
        - DEFINITION concepts that appear in the same node as a
          VOCABULARY concept get a ``RELATES_TO`` edge.
        - Any two concepts sharing ≥ 2 source nodes get a
          ``RELATES_TO`` edge.
        """
        relationships: list[ConceptRelationship] = []
        seen_edges: set[tuple[str, str, str]] = set()

        node_index: dict[str, list[Concept]] = {}
        for c in concepts:
            for nid in c.source_node_ids:
                key = str(nid)
                node_index.setdefault(key, []).append(c)

        for _node_id, co_occurring in node_index.items():
            for i in range(len(co_occurring)):
                for j in range(i + 1, len(co_occurring)):
                    a = co_occurring[i]
                    b = co_occurring[j]

                    if a.id == b.id:
                        continue

                    # Ensure consistent ordering for dedup
                    src, tgt = (a.id, b.id) if str(a.id) < str(b.id) else (b.id, a.id)
                    edge_key = (str(src), str(tgt), RelationType.RELATES_TO)
                    if edge_key in seen_edges:
                        continue
                    seen_edges.add(edge_key)

                    # Determine weight from shared node count
                    shared = len(set(a.source_node_ids) & set(b.source_node_ids))
                    weight = min(1.0, shared * 0.25)

                    relationships.append(
                        ConceptRelationship(
                            source_id=src,
                            target_id=tgt,
                            relation_type=RelationType.RELATES_TO,
                            weight=weight,
                        )
                    )

        # DEF → VOCAB "relates_to" edges
        definitions = [c for c in concepts if c.category.value == "definition"]
        vocab = [c for c in concepts if c.category.value == "vocab"]
        for d in definitions:
            for v in vocab:
                if d.name.lower() == v.name.lower():
                    edge_key = (str(d.id), str(v.id), RelationType.RELATES_TO)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        relationships.append(
                            ConceptRelationship(
                                source_id=d.id,
                                target_id=v.id,
                                relation_type=RelationType.RELATES_TO,
                                weight=1.0,
                            )
                        )

        return relationships

    # ──────────────────────────────────────────────────────────────────────
    # Unit mapping
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _map_to_units(
        concepts: list[Concept],
        units: list[LearningUnit],
    ) -> None:
        """Populate ``source_unit_ids`` for each concept.

        A concept belongs to a unit if any of its ``source_node_ids``
        appears in that unit's ``source_node_ids``.
        """
        unit_node_index: dict[str, str] = {}
        for unit in units:
            for nid in unit.source_node_ids:
                unit_node_index[str(nid)] = str(unit.id)

        for c in concepts:
            seen_units: set[str] = set()
            for nid in c.source_node_ids:
                uid = unit_node_index.get(str(nid))
                if uid and uid not in seen_units:
                    seen_units.add(uid)
                    from uuid import UUID

                    c.source_unit_ids.append(UUID(uid))
