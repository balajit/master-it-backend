"""DefinitionDetector — finds term-definition pairs in the text."""

from __future__ import annotations

import re

from learning_platform.models.annotation import DefinitionAnnotation
from learning_platform.models.document import CanonicalDocument

from ._helpers import find_pattern

_DEFINITION_PATTERN = re.compile(
    r"(?:Definition|Def\.?|Define)\s*"
    r"(?:\d+[\.:)])?\s*"
    r"[:\-–—]\s*"
    r"(.+?)(?:\n|$)",
    re.IGNORECASE,
)

_INLINE_PATTERN = re.compile(
    r"(\b[A-Za-z][a-zA-Z]+(?:\s[A-Za-z][a-zA-Z]+)*)\s+"
    r"(?:is|are|refers to|means|denotes)\s+"
    r"(.+?)(?:\.|;|,|\n|$)",
)


class DefinitionDetector:
    """Detects definition patterns in document text."""

    def detect(self, document: CanonicalDocument) -> list[DefinitionAnnotation]:
        annotations: list[DefinitionAnnotation] = []

        for node, match in find_pattern(document, _DEFINITION_PATTERN):
            raw = match.group(0)
            term = raw.split(":", 1)[0].strip() if ":" in raw else "Definition"
            annotations.append(
                DefinitionAnnotation(
                    node_id=node.id,
                    term=term,
                    definition_text=match.group(1).strip(),
                    confidence=0.9,
                    detector="DefinitionDetector",
                )
            )

        for node, match in find_pattern(document, _INLINE_PATTERN):
            annotations.append(
                DefinitionAnnotation(
                    node_id=node.id,
                    term=match.group(1).strip(),
                    definition_text=match.group(2).strip(),
                    confidence=0.7,
                    detector="DefinitionDetector",
                )
            )

        return annotations
