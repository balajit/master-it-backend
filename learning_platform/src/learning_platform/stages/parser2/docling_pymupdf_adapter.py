"""Parser2 adapter — simplified Docling + PyMuPDF parser implementing AbstractParser.

This adapter uses the ``DoclingPyMuPDFMerger`` pattern to parse documents:
1. Run Docling conversion for semantic structure
2. For PDFs, correlate with PyMuPDF for font/vector-line enrichment
3. Direct-map Docling items to canonical DocumentNode types (no synthetics)
4. Build tree from parent-child relationships

The adapter implements the ``AbstractParser`` protocol and can be used
interchangeably with ``DoclingAdapter``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
)
from learning_platform.stages.parser2.docling_node_mapper import build_document_tree
from learning_platform.stages.parser2.docling_pymupdf_merger import DoclingPyMuPDFMerger

_LOG = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".doc",
        ".xls",
        ".ppt",
        ".odt",
        ".ods",
        ".odp",
        ".epub",
        ".md",
        ".asciidoc",
        ".adoc",
        ".html",
        ".htm",
        ".xhtml",
        ".csv",
        ".txt",
        ".xml",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".webp",
    }
)


class Parser2Adapter:
    """Simplified parser using DoclingPyMuPDFMerger pattern.

    This adapter implements the ``AbstractParser`` protocol with:
    - Zero configuration (no OCR strategy, no multi-pass, no hybrid merge)
    - Direct type mapping (paragraph→paragraph, heading→heading, etc.)
    - No synthetic inference (no question promotion, no TOC generation)
    - PyMuPDF enrichment for PDFs (fonts, vector lines)

    The adapter is interchangeable with ``DoclingAdapter`` via the
    ``AbstractParser`` protocol.
    """

    def parse(self, source: str) -> CanonicalDocument:
        """Convert *source* into a ``CanonicalDocument``.

        Parameters
        ----------
        source : str
            Path to the source file.

        Returns
        -------
        CanonicalDocument
            The parsed document with canonical node structure.
        """
        _LOG.info("Parser2Adapter.parse: %s", source)

        # Use context manager to ensure proper cleanup
        with DoclingPyMuPDFMerger(source) as merger:
            # Get correlated items (Docling + PyMuPDF enrichment for PDFs)
            correlated_items = merger.correlate()

            # Build document tree using direct mapping
            root_node = build_document_tree(
                items=correlated_items,
                source=source,
                docling_doc=merger.docling_doc,
            )

            # Extract document metadata
            title = merger.title or Path(source).stem
            page_count = merger.page_count

        return CanonicalDocument(
            source=str(source),
            title=title,
            metadata=DocumentMetadata(
                title=title,
                file_type=Path(source).suffix.lstrip("."),
                page_count=page_count,
                custom={"parser": "parser2"},
            ),
            nodes=[root_node],
        )

    def supports(self, source: str) -> bool:
        """Return ``True`` if *source* has a supported extension.

        Parameters
        ----------
        source : str
            Path to the source file.

        Returns
        -------
        bool
            True if the file extension is supported.
        """
        return Path(source).suffix.lower() in _SUPPORTED_EXTENSIONS

    def confidence(self, source: str) -> float:
        """Return a confidence score for parsing the source.

        Parameters
        ----------
        source : str
            Path to the source file.

        Returns
        -------
        float
            Confidence score between 0.0 and 1.0.
        """
        ext = Path(source).suffix.lower()
        if ext in {".pdf", ".docx"}:
            return 0.95
        if ext in {".pptx", ".xlsx"}:
            return 0.85
        if ext in {".html", ".htm", ".md"}:
            return 0.70
        if ext in {".txt", ".csv", ".xml"}:
            return 0.40
        return 0.0
