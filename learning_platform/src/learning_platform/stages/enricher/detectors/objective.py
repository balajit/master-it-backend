"""ObjectiveDetector — finds learning objectives and outcomes."""

from __future__ import annotations

import re

from learning_platform.models.annotation import ObjectiveAnnotation
from learning_platform.models.document import CanonicalDocument

from ._helpers import find_pattern

_OBJECTIVE_PATTERN = re.compile(
    r"(?:Learning Objective|Objective|Outcome|After completing|By the end"
    r"|Students will|You will|Aim|Goal)\s*"
    r"(?:\d+[\.:)])?\s*"
    r"[:\-–—]?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)


class ObjectiveDetector:
    """Detects learning objective statements."""

    def detect(self, document: CanonicalDocument) -> list[ObjectiveAnnotation]:
        annotations: list[ObjectiveAnnotation] = []

        for node, match in find_pattern(document, _OBJECTIVE_PATTERN):
            annotations.append(
                ObjectiveAnnotation(
                    node_id=node.id,
                    objective_text=match.group(1).strip() or match.group(0).strip(),
                    confidence=0.85,
                    detector="ObjectiveDetector",
                )
            )

        return annotations
