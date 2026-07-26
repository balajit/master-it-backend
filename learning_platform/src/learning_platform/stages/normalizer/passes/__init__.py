"""Normalization passes — each addresses one structural concern."""

from learning_platform.stages.normalizer.passes.base import NormalizationPass
from learning_platform.stages.normalizer.passes.caption import CaptionAssociationPass
from learning_platform.stages.normalizer.passes.heading import HeadingNormalizationPass
from learning_platform.stages.normalizer.passes.heading_section import HeadingSectionPass
from learning_platform.stages.normalizer.passes.list_norm import ListNormalizationPass
from learning_platform.stages.normalizer.passes.page_grouping import PageGroupingPass
from learning_platform.stages.normalizer.passes.paragraph import ParagraphMergePass
from learning_platform.stages.normalizer.passes.parent_child import ParentChildRepairPass
from learning_platform.stages.normalizer.passes.reading_order import ReadingOrderPass
from learning_platform.stages.normalizer.passes.table import TableNormalizationPass

__all__ = [
    "CaptionAssociationPass",
    "HeadingNormalizationPass",
    "HeadingSectionPass",
    "ListNormalizationPass",
    "NormalizationPass",
    "PageGroupingPass",
    "ParagraphMergePass",
    "ParentChildRepairPass",
    "ReadingOrderPass",
    "TableNormalizationPass",
]
