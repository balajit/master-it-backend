"""ExampleDetector — finds example and non-example blocks."""

from __future__ import annotations

import re

from learning_platform.models.annotation import ExampleAnnotation
from learning_platform.models.document import CanonicalDocument, Heading, Note, Paragraph

from ._helpers import plain_text

_POSITIVE_PATTERN = re.compile(
    r"\b(?:Example|Ex\.|For instance|Consider|Observe)\s*"
    r"(?:\d+[\.:)])?\s*"
    r"[:\-–—]?\s*(.*)",
    re.IGNORECASE,
)

_NEGATIVE_PATTERN = re.compile(
    r"\b(?:Non-?example|Counterexample|Incorrect|Wrong)\s*"
    r"(?:\d+[\.:)])?\s*"
    r"[:\-–—]?\s*(.*)",
    re.IGNORECASE,
)


class ExampleDetector:
    """Detects example and non-example blocks in the document."""

    def detect(self, document: CanonicalDocument) -> list[ExampleAnnotation]:
        annotations: list[ExampleAnnotation] = []

        for node in document.nodes:
            if not isinstance(node.content, (Paragraph, Heading, Note)):
                continue

            text = plain_text(node)
            if not text:
                continue

            neg_match = _NEGATIVE_PATTERN.search(text)
            if neg_match:
                annotations.append(
                    ExampleAnnotation(
                        node_id=node.id,
                        is_positive=False,
                        title="Non-example",
                        body_text=text,
                        confidence=0.85,
                        detector="ExampleDetector",
                    )
                )
                continue

            pos_match = _POSITIVE_PATTERN.search(text)
            if pos_match:
                raw = pos_match.group(0)
                title = raw.split(":")[0].strip() if ":" in raw else "Example"
                annotations.append(
                    ExampleAnnotation(
                        node_id=node.id,
                        is_positive=True,
                        title=title,
                        body_text=text,
                        confidence=0.85,
                        detector="ExampleDetector",
                    )
                )

        return annotations
