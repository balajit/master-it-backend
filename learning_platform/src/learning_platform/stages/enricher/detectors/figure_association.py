"""FigureAssociationDetector — associates figures with captions and surrounding text."""

from __future__ import annotations

from learning_platform.models.annotation import FigureAssociationAnnotation
from learning_platform.models.document import (
    CanonicalDocument,
    Figure,
    Paragraph,
)

from ._helpers import plain_text


class FigureAssociationDetector:
    """Detects figures and associates them with captions or nearby text."""

    def detect(self, document: CanonicalDocument) -> list[FigureAssociationAnnotation]:
        annotations: list[FigureAssociationAnnotation] = []
        nodes = document.nodes

        for i, node in enumerate(nodes):
            if not isinstance(node.content, Figure):
                continue

            caption = node.content.caption_text
            nearby_text = ""

            if i + 1 < len(nodes):
                next_node = nodes[i + 1]
                if isinstance(next_node.content, Paragraph):
                    nearby_text = plain_text(next_node)

            if not caption and node.content.caption_node_id:
                caption_node = document.get_node(node.content.caption_node_id)
                if caption_node is not None:
                    caption = plain_text(caption_node)

            annotations.append(
                FigureAssociationAnnotation(
                    node_id=node.id,
                    figure_node_id=node.id,
                    caption_text=caption or nearby_text,
                    confidence=0.9 if caption else 0.5,
                    detector="FigureAssociationDetector",
                )
            )

        return annotations
