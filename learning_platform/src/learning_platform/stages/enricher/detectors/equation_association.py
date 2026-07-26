"""EquationAssociationDetector — associates equations with labels and surrounding text."""

from __future__ import annotations

from learning_platform.models.annotation import EquationAssociationAnnotation
from learning_platform.models.document import (
    CanonicalDocument,
    Equation,
    Paragraph,
)

from ._helpers import plain_text


class EquationAssociationDetector:
    """Detects equations and associates them with labels or nearby text."""

    def detect(self, document: CanonicalDocument) -> list[EquationAssociationAnnotation]:
        annotations: list[EquationAssociationAnnotation] = []
        nodes = document.nodes

        for i, node in enumerate(nodes):
            if not isinstance(node.content, Equation):
                continue

            label = node.content.label
            description = node.content.metadata.get("caption", "")
            nearby_text = ""

            if not description and i + 1 < len(nodes):
                next_node = nodes[i + 1]
                if isinstance(next_node.content, Paragraph):
                    nearby_text = plain_text(next_node)

            if not label:
                label = f"Eq. {node.id}"

            annotations.append(
                EquationAssociationAnnotation(
                    node_id=node.id,
                    equation_node_id=node.id,
                    label=label,
                    description_text=description or nearby_text,
                    confidence=0.9 if label else 0.5,
                    detector="EquationAssociationDetector",
                )
            )

        return annotations
