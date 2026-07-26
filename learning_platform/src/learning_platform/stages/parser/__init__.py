"""Parser adapters — wrap third-party conversion libraries for the AbstractParser protocol."""

from learning_platform.stages.parser.docling_adapter import DoclingAdapter
from learning_platform.stages.parser.marker_adapter import MarkerAdapter
from learning_platform.stages.parser.mineru_adapter import MinerUAdapter

__all__ = ["DoclingAdapter", "MarkerAdapter", "MinerUAdapter"]
