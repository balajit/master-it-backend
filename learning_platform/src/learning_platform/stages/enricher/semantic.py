"""Semantic Enricher — runs detectors and applies annotations to the document.

Wraps ``EnrichmentEngine`` to conform to the ``SemanticEnricher`` Protocol
defined in ``pipeline/base.py``.  The engine runs all detectors; the enricher
then attaches a summary of annotations as metadata on the document so
downstream stages can access it without re-running detectors.

Page-aware: ``enrich_pages`` processes each page's nodes together,
creating a per-page CanonicalDocument snapshot for the detectors.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from learning_platform.stages.enricher.engine import EnrichmentEngine

if TYPE_CHECKING:
    from learning_platform.models.annotation import Annotation
    from learning_platform.models.document import CanonicalDocument
    from learning_platform.models.page_context import PageContext

_LOG = logging.getLogger(__name__)


class SemanticEnricher:
    """Adapter that wraps ``EnrichmentEngine`` to satisfy the Protocol.

    Parameters
    ----------
    engine : EnrichmentEngine | None
        Pre-configured engine.  When ``None`` a default engine with no
        detectors is created (callers should inject via
        ``engine.add_detector()``).
    """

    def __init__(self, engine: EnrichmentEngine | None = None) -> None:
        self._engine = engine or EnrichmentEngine()

    @property
    def engine(self) -> EnrichmentEngine:
        """Expose the underlying engine for detector registration."""
        return self._engine

    def enrich(self, document: CanonicalDocument) -> tuple[CanonicalDocument, list[Annotation]]:
        """Run detectors and return the enriched document plus annotations.

        Annotations are stored in ``document.metadata["annotations"]`` as a
        serialisable list of dicts, while the full typed list is returned
        separately for direct consumption by the unit builder.
        """
        _LOG.info("Running enrichment on document: %s", document.title)
        annotations = self._engine.enrich(document)

        annotation_records: list[dict[str, object]] = []
        for ann in annotations:
            annotation_records.append(
                {
                    "type": ann.type,
                    "node_id": str(ann.node_id),
                    "confidence": ann.confidence,
                    "detector": ann.detector,
                }
            )

        enriched_metadata = {
            **document.metadata.custom,
            "annotations": annotation_records,
        }
        enriched_metadata_obj = document.metadata.model_copy(update={"custom": enriched_metadata})
        enriched_doc = document.model_copy(update={"metadata": enriched_metadata_obj})

        _LOG.info(
            "Enrichment complete: %d annotations applied to document",
            len(annotations),
        )
        return enriched_doc, annotations

    def enrich_pages(self, pages: list[PageContext]) -> list[PageContext]:
        """Run detectors on each page's nodes and populate page annotations.

        For each ``PageContext``, a temporary ``CanonicalDocument`` is
        created containing only that page's nodes.  Detectors run on
        this per-page document, and the resulting annotations are stored
        in ``page_context.annotations``.
        """
        from learning_platform.models.document import (
            CanonicalDocument,
            DocumentMetadata,
        )

        _LOG.info("Running page-aware enrichment on %d pages", len(pages))

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

            annotations = self._engine.enrich(page_doc)
            page.annotations = list(annotations)

        total_annotations = sum(len(p.annotations) for p in pages)
        _LOG.info(
            "Page enrichment complete: %d annotations across %d pages",
            total_annotations,
            len(pages),
        )
        return pages
