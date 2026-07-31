"""ExerciseDetector — finds exercises, questions, and problems."""

from __future__ import annotations

import re

from learning_platform.models.annotation import ExerciseAnnotation
from learning_platform.models.document import (
    CanonicalDocument,
    Exercise,
    Heading,
    Paragraph,
    Question,
)

from ._helpers import plain_text

_EXERCISE_PATTERN = re.compile(
    r"\b(?:Exercise|Problem|Question|Practice|Quiz)"
    r"(?:\s+\d+)?\s*"
    r"[:\-–—]\s*(.*)",
    re.IGNORECASE,
)


class ExerciseDetector:
    """Detects exercises and questions in the document."""

    def detect(self, document: CanonicalDocument) -> list[ExerciseAnnotation]:
        annotations: list[ExerciseAnnotation] = []

        for node in document.nodes:
            if isinstance(node.content, Exercise):
                options = [opt.text.plain_text for opt in node.content.options]
                annotations.append(
                    ExerciseAnnotation(
                        node_id=node.id,
                        exercise_type=node.content.exercise_type.value,
                        question_text=node.content.question.plain_text,
                        options=options,
                        solution=node.content.solution,
                        confidence=1.0,
                        detector="ExerciseDetector",
                    )
                )
                continue

            if isinstance(node.content, Question):
                question_text = node.content.text.plain_text
                if not question_text and node.content.statements:
                    question_text = " ".join(
                        statement.text.plain_text for statement in node.content.statements
                    )
                options = [option.text.plain_text for option in node.content.options]
                annotations.append(
                    ExerciseAnnotation(
                        node_id=node.id,
                        exercise_type=node.content.question_type.value,
                        question_text=question_text,
                        options=options,
                        solution=node.content.solution,
                        confidence=1.0,
                        detector="ExerciseDetector",
                    )
                )
                continue

            if isinstance(node.content, (Paragraph, Heading)):
                text = plain_text(node)
                match = _EXERCISE_PATTERN.search(text)
                if match:
                    annotations.append(
                        ExerciseAnnotation(
                            node_id=node.id,
                            exercise_type="unknown",
                            question_text=text,
                            confidence=0.75,
                            detector="ExerciseDetector",
                        )
                    )

        return annotations
