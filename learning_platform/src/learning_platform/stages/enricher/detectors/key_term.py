"""KeyTermDetector — finds important terms that should be highlighted."""

from __future__ import annotations

import re

from learning_platform.models.annotation import KeyTermAnnotation
from learning_platform.models.document import CanonicalDocument, Heading, Paragraph

from ._helpers import plain_text

_BOLD_PATTERN = re.compile(r"\*\*(.+?)\b\*\*")
_DEFINITION_SITE_PATTERN = re.compile(
    r"(\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s+"
    r"(?:is|are|refers to|means|denotes|is defined as)\s+",
    re.IGNORECASE,
)


class KeyTermDetector:
    """Detects key terms marked bold or appearing at definition sites."""

    def detect(self, document: CanonicalDocument) -> list[KeyTermAnnotation]:
        annotations: list[KeyTermAnnotation] = []
        seen_terms: set[str] = set()

        for node in document.nodes:
            if not isinstance(node.content, (Paragraph, Heading)):
                continue

            text = plain_text(node)
            if not text:
                continue

            for match in _BOLD_PATTERN.finditer(text):
                term = match.group(1).strip()
                if term and term.lower() not in seen_terms:
                    seen_terms.add(term.lower())
                    annotations.append(
                        KeyTermAnnotation(
                            node_id=node.id,
                            term=term,
                            context_text=text,
                            confidence=0.9,
                            detector="KeyTermDetector",
                        )
                    )

            for match in _DEFINITION_SITE_PATTERN.finditer(text):
                term = match.group(1).strip()
                if term and term.lower() not in seen_terms:
                    seen_terms.add(term.lower())
                    annotations.append(
                        KeyTermAnnotation(
                            node_id=node.id,
                            term=term,
                            context_text=text,
                            confidence=0.7,
                            detector="KeyTermDetector",
                        )
                    )

        return annotations
