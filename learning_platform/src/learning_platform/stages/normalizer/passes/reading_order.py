"""ReadingOrderPass — sort nodes into canonical reading order.

Nodes are sorted by:
1. ``page`` (ascending)
2. ``bbox.y`` (top-to-bottom on the page)
3. ``bbox.x`` (left-to-right on the page)
4. ``seq`` (parser-assigned sequence within the page, ascending)
5. Original insertion order (stable sort preserves the existing order
   when all other keys are identical or zero).
"""

from __future__ import annotations

from learning_platform.models.document import DocumentNode


class ReadingOrderPass:
    """Sort the flat node list into reading order."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        indexed = list(enumerate(nodes))
        indexed.sort(key=lambda pair: self._sort_key(pair[1]))
        return [node for _, node in indexed]

    @staticmethod
    def _sort_key(node: DocumentNode) -> tuple[int, float, float, int, int]:
        """Return a sort key ``(page, y, x, seq, original_order)``."""
        return (
            node.page,
            node.bbox.y,
            node.bbox.x,
            node.seq,
            0,
        )
