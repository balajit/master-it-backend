"""HeadingNormalizationPass — fix heading level gaps and enforce hierarchy.

Rules:
- Heading levels must be sequential (no H1 → H3).
- A gap is filled by demoting the jumped-over level.
- The first heading encountered is anchored at level 1 if it is > 1.
"""

from __future__ import annotations

from learning_platform.models.document import DocumentNode, Heading, HeadingLevel

from . import _helpers


class HeadingNormalizationPass:
    """Normalize heading levels so they form a strict hierarchy."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        result: list[DocumentNode] = []
        expected_level = 0

        for node in nodes:
            if not _helpers.is_heading(node):
                result.append(node)
                continue

            current_level = int(node.content.level)

            if expected_level == 0:
                current_level = 1

            if current_level > expected_level + 1:
                current_level = expected_level + 1

            if current_level != int(node.content.level):
                safe_level = min(current_level, 4)
                new_content = Heading(
                    level=HeadingLevel(safe_level),
                    text=node.content.text,
                    metadata=node.content.metadata,
                )
                node = node.model_copy(update={"content": new_content, "level": safe_level})

            expected_level = int(node.content.level)
            result.append(node)

        return result
