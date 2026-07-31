"""Parser adapters — wrap third-party conversion libraries for the AbstractParser protocol."""

from learning_platform.stages.parser.docling_adapter import DoclingAdapter
from learning_platform.stages.parser.hybrid_merge import HybridMergeEngine, HybridMergeSettings
from learning_platform.stages.parser.marker_adapter import MarkerAdapter
from learning_platform.stages.parser.mineru_adapter import MinerUAdapter
from learning_platform.stages.parser.pymupdf_layout import PyMuPDFLayoutExtractor

__all__ = [
    "DoclingAdapter",
    "HybridMergeEngine",
    "HybridMergeSettings",
    "MarkerAdapter",
    "MinerUAdapter",
    "PyMuPDFLayoutExtractor",
]
