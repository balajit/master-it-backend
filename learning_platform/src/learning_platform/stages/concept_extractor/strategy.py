"""Concept Extraction Strategy — interface for pluggable extraction backends.

A strategy scans the document, annotations, and learning units to
produce a list of raw ``Concept`` objects.  The ``ConceptExtractor``
orchestrator deduplicates, scores, and links the results from one or
more strategies into a final ``ConceptMap``.

Strategies are stateless — all input arrives via the ``extract()``
method.  Implementations may be rule-based, regex-based, or LLM-based.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from learning_platform.models.annotation import Annotation
    from learning_platform.models.concept import Concept
    from learning_platform.models.document import CanonicalDocument
    from learning_platform.models.learning_unit import LearningUnit


@runtime_checkable
class ConceptExtractionStrategy(Protocol):
    """Interface for a single concept extraction strategy.

    Each implementation knows how to find one or more categories of
    concepts using a specific technique (regex patterns, annotation
    analysis, LLM calls, etc.).

    The orchestrator calls ``extract()`` on every registered strategy,
    merges the results, and builds the final ``ConceptMap``.
    """

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> list[Concept]: ...
