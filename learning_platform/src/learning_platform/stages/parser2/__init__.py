"""Parser2 — simplified Docling + PyMuPDF parser with direct type mapping.

This package provides a streamlined parser that:
- Uses Docling for semantic structure extraction
- Enriches PDFs with PyMuPDF font/vector-line data
- Maps Docling types directly to canonical types (no synthetics)
- Captures page furniture (headers, footers)

Usage
-----
>>> from learning_platform.stages.parser2 import Parser2Adapter
>>> parser = Parser2Adapter()
>>> doc = parser.parse("document.pdf")
"""

from learning_platform.stages.parser2.docling_node_mapper import (
    build_document_tree,
    map_correlated_item,
)
from learning_platform.stages.parser2.docling_pymupdf_adapter import Parser2Adapter
from learning_platform.stages.parser2.docling_pymupdf_merger import (
    CorrelatedItem,
    DoclingPyMuPDFMerger,
    compute_bbox_overlap_ratio,
)

__all__ = [
    "Parser2Adapter",
    "DoclingPyMuPDFMerger",
    "CorrelatedItem",
    "compute_bbox_overlap_ratio",
    "map_correlated_item",
    "build_document_tree",
]
