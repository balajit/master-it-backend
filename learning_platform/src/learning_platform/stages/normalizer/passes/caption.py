"""CaptionAssociationPass — associate orphan captions with their figures/equations.

Heuristic: a ``Paragraph`` whose text starts with "Figure N:", "Fig. N:",
"Table N:", or "Equation N:" immediately following a ``Figure`` or
``Equation`` node is treated as that element's caption.  The caption text
is moved into the element's caption field and the paragraph is removed.
"""

from __future__ import annotations

import re

from learning_platform.models.document import (
    DocumentNode,
    Equation,
    Figure,
)

from . import _helpers

_CAPTION_PATTERN = re.compile(
    r"^(?:Figure|Fig\.?|Table|Equation|Eq\.?)\s*\d+",
    re.IGNORECASE,
)


class CaptionAssociationPass:
    """Attach caption paragraphs to the preceding figure or equation."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        result: list[DocumentNode] = []
        prev_element: DocumentNode | None = None

        for node in nodes:
            is_caption = _helpers.is_paragraph(node) and _CAPTION_PATTERN.match(
                _helpers.plain_text(node)
            )

            if is_caption and prev_element is not None:
                caption_text = _helpers.plain_text(node)
                content = prev_element.content

                if isinstance(content, Figure):
                    new_content = Figure(
                        caption_text=caption_text,
                        image_uri=content.image_uri,
                        alt_text=content.alt_text,
                        caption_node_id=content.caption_node_id,
                        width=content.width,
                        height=content.height,
                        format=content.format,
                        mimetype=content.mimetype,
                        storage_key=content.storage_key,
                        size_bytes=content.size_bytes,
                        metadata=content.metadata,
                    )
                    prev_element = prev_element.model_copy(update={"content": new_content})
                    result[-1] = prev_element
                    continue

                if isinstance(content, Equation):
                    new_content = Equation(
                        latex=content.latex,
                        mathml=content.mathml,
                        label=content.label,
                        is_block=content.is_block,
                        metadata={**content.metadata, "caption": caption_text},
                    )
                    prev_element = prev_element.model_copy(update={"content": new_content})
                    result[-1] = prev_element
                    continue

            if _helpers.is_heading(node) or (isinstance(node.content, (Figure, Equation))):
                prev_element = node
            else:
                prev_element = None

            result.append(node)

        return result
