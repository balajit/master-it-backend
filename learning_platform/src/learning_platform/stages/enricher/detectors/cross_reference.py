"""CrossReferenceDetector — finds cross-references to sections, equations, figures."""

from __future__ import annotations

import re

from learning_platform.models.annotation import CrossReferenceAnnotation
from learning_platform.models.document import CanonicalDocument, Paragraph

from ._helpers import find_pattern, plain_text

_CROSS_REF_PATTERN = re.compile(
    r"(?:see|refer to|as shown in|as discussed in|from|in)"
    r"\s+"
    r"(?:Section|Chapter|Figure|Fig\.?|Table|Equation|Eq\.?|Appendix)"
    r"\s*"
    r"(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)

_LABEL_PATTERN = re.compile(
    r"(?:Section|Chapter|Figure|Fig\.?|Table|Equation|Eq\.?|Appendix)"
    r"\s*"
    r"(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)


class CrossReferenceDetector:
    """Detects cross-references to other parts of the document."""

    def detect(self, document: CanonicalDocument) -> list[CrossReferenceAnnotation]:
        annotations: list[CrossReferenceAnnotation] = []

        for node, match in find_pattern(document, _CROSS_REF_PATTERN):
            label = match.group(0).strip()
            annotations.append(
                CrossReferenceAnnotation(
                    node_id=node.id,
                    label=label,
                    target_description=match.group(1).strip() if match.lastindex else "",
                    confidence=0.85,
                    detector="CrossReferenceDetector",
                )
            )

        for node in document.nodes:
            if not isinstance(node.content, Paragraph):
                continue
            text = plain_text(node)
            for match in _LABEL_PATTERN.finditer(text):
                full = match.group(0).strip()
                if not any(a.label == full for a in annotations if a.node_id == node.id):
                    annotations.append(
                        CrossReferenceAnnotation(
                            node_id=node.id,
                            label=full,
                            target_description=match.group(1).strip() if match.lastindex else "",
                            confidence=0.6,
                            detector="CrossReferenceDetector",
                        )
                    )

        return annotations
