"""SummaryDetector — finds summary and recap blocks."""

from __future__ import annotations

import re

from learning_platform.models.annotation import SummaryAnnotation
from learning_platform.models.document import CanonicalDocument, Heading, Paragraph

from ._helpers import plain_text

_SUMMARY_PATTERN = re.compile(
    r"^(?:\s*)\b(?:Summary|Recap|Review|Key Takeaways?|Chapter Summary"
    r"|Section Summary|In summary|To summarize|In conclusion|Conclusion)"
    r"(?:\s+\d+[\.:)])?\s*"
    r"[:\-–—]?\s*(.*)",
    re.IGNORECASE | re.MULTILINE,
)


class SummaryDetector:
    """Detects summary and recap blocks."""

    def detect(self, document: CanonicalDocument) -> list[SummaryAnnotation]:
        annotations: list[SummaryAnnotation] = []

        for node in document.nodes:
            if not isinstance(node.content, (Heading, Paragraph)):
                continue

            text = plain_text(node)
            if not text:
                continue

            match = _SUMMARY_PATTERN.search(text)
            if match:
                annotations.append(
                    SummaryAnnotation(
                        node_id=node.id,
                        summary_text=text,
                        confidence=0.85,
                        detector="SummaryDetector",
                    )
                )

        return annotations
