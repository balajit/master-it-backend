"""CalloutDetector — finds callout, tip, note, and warning blocks."""

from __future__ import annotations

import re

from learning_platform.models.annotation import CalloutAnnotation
from learning_platform.models.document import (
    Callout,
    CanonicalDocument,
    Note,
    Paragraph,
)

from ._helpers import plain_text

_CALLOUT_PATTERN = re.compile(
    r"(?:Note|Tip|Warning|Caution|Important|Remember|Info|Danger"
    r"|Key Point|Did you know)\s*"
    r"(?:\d+[\.:)])?\s*"
    r"[:\-–—]?\s*(.*)",
    re.IGNORECASE,
)

_TYPE_MAP = {
    "note": "info",
    "info": "info",
    "tip": "example",
    "did you know": "example",
    "important": "reminder",
    "remember": "reminder",
    "key point": "reminder",
    "warning": "non_example",
    "caution": "non_example",
    "danger": "non_example",
}


class CalloutDetector:
    """Detects callout, tip, note, and warning blocks."""

    def detect(self, document: CanonicalDocument) -> list[CalloutAnnotation]:
        annotations: list[CalloutAnnotation] = []

        for node in document.nodes:
            if isinstance(node.content, Note):
                callout_type = _TYPE_MAP.get(node.content.note_type.value, "info")
                annotations.append(
                    CalloutAnnotation(
                        node_id=node.id,
                        callout_type=callout_type,
                        title=node.content.note_type.value.title(),
                        body_text=node.content.text.plain_text,
                        confidence=1.0,
                        detector="CalloutDetector",
                    )
                )
                continue

            if isinstance(node.content, Callout):
                annotations.append(
                    CalloutAnnotation(
                        node_id=node.id,
                        callout_type=node.content.callout_type.value,
                        title=node.content.title,
                        body_text=node.content.text.plain_text,
                        confidence=1.0,
                        detector="CalloutDetector",
                    )
                )
                continue

            if isinstance(node.content, Paragraph):
                text = plain_text(node)
                match = _CALLOUT_PATTERN.search(text)
                if match:
                    keyword = match.group(0).split(":")[0].split(".")[0].strip().lower()
                    callout_type = _TYPE_MAP.get(keyword, "info")
                    annotations.append(
                        CalloutAnnotation(
                            node_id=node.id,
                            callout_type=callout_type,
                            title=keyword.title(),
                            body_text=text,
                            confidence=0.8,
                            detector="CalloutDetector",
                        )
                    )

        return annotations
