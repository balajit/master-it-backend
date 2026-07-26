"""AnnotationStrategy — extracts concepts from enrichment annotations.

This strategy reads ``DefinitionAnnotation``, ``KeyTermAnnotation``,
and ``ObjectiveAnnotation`` objects and converts them into ``Concept``
instances with appropriate categories.
"""

from __future__ import annotations

from learning_platform.models.annotation import Annotation
from learning_platform.models.concept import Concept
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.learning_unit import LearningUnit

from ._helpers import concepts_from_annotations


class AnnotationStrategy:
    """Derives concepts from pre-existing annotation data.

    This is the simplest strategy — it converts structured annotation
    output into the concept model without any additional text analysis.
    """

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> list[Concept]:
        return concepts_from_annotations(annotations)
