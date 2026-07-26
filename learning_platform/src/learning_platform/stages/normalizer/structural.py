"""Structural Normalizer — composes normalization passes into a pipeline.

The normalizer is a thin orchestrator: it holds an ordered list of
``NormalizationPass`` instances and applies them sequentially to the
document's flat node list.  Passes can be injected via the constructor
(Dependency Inversion) or replaced with custom implementations.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from learning_platform.models.document import CanonicalDocument

from .passes import (
    CaptionAssociationPass,
    HeadingNormalizationPass,
    HeadingSectionPass,
    ListNormalizationPass,
    NormalizationPass,
    PageGroupingPass,
    ParagraphMergePass,
    ParentChildRepairPass,
    ReadingOrderPass,
    TableNormalizationPass,
)
from .passes._helpers import flat_to_tree, tree_to_flat

_LOG = logging.getLogger(__name__)


def _default_passes() -> list[NormalizationPass]:
    """Return the standard normalization pipeline in execution order."""
    return [
        HeadingNormalizationPass(),
        ParagraphMergePass(),
        CaptionAssociationPass(),
        ListNormalizationPass(),
        TableNormalizationPass(),
        HeadingSectionPass(),
        PageGroupingPass(),
        ParentChildRepairPass(),
        ReadingOrderPass(),
    ]


class StructuralNormalizer:
    """Normalizes document structure via a composable pass pipeline.

    Parameters
    ----------
    passes : Sequence[NormalizationPass] | None
        An explicit list of passes.  When ``None`` the default pipeline
        is used.  Passes are executed in list order.
    """

    def __init__(self, passes: Sequence[NormalizationPass] | None = None) -> None:
        if passes is not None:
            self._passes: list[NormalizationPass] = list(passes)
        else:
            self._passes = _default_passes()

    @property
    def passes(self) -> list[NormalizationPass]:
        """Return a copy of the current pass list."""
        return list(self._passes)

    def normalize(self, document: CanonicalDocument) -> CanonicalDocument:
        """Apply every normalization pass and return the repaired document.

        The input document is not mutated.

        The document tree is flattened into a node list before passes run,
        so every pass sees all content nodes (not just the root). After
        all passes, the tree is rebuilt from ``parent_id`` references.
        """
        _LOG.info(
            "Normalizing document '%s' with %d nodes across %d passes",
            document.title,
            len(document.nodes),
            len(self._passes),
        )

        # Flatten the tree so passes see every node, not just the root.
        nodes = tree_to_flat(document.nodes[0]) if document.nodes else []

        _LOG.debug("Flattened tree: %d nodes", len(nodes))

        for i, p in enumerate(self._passes):
            before = len(nodes)
            nodes = p(nodes)
            after = len(nodes)
            _LOG.debug(
                "Pass %d/%d (%s): %d → %d nodes",
                i + 1,
                len(self._passes),
                type(p).__name__,
                before,
                after,
            )

        # Rebuild tree from parent_id references.
        if not nodes:
            return document.model_copy(update={"nodes": []})
        root = flat_to_tree(nodes)
        return document.model_copy(update={"nodes": [root]})
