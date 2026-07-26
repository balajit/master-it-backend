"""LlmConceptStrategy — placeholder for LLM-based concept extraction.

This strategy is a stub that returns no results.  When an LLM backend
is available, this class should be extended to send the document text
to the model and parse the response into ``Concept`` objects.

To implement:

1. Inject an LLM client (e.g. ``langchain_ollama.ChatOllama``).
2. Build a prompt that asks the model to identify concepts, skills,
   vocabulary, processes, facts, rules, formulas, and definitions.
3. Parse the structured response into ``Concept`` instances.
4. Set ``confidence`` and ``importance`` based on model output.
"""

from __future__ import annotations

from learning_platform.models.annotation import Annotation
from learning_platform.models.concept import Concept
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.learning_unit import LearningUnit


class LlmConceptStrategy:
    """LLM-based concept extraction (stub).

    Currently returns an empty list.  This is the extension point for
    future LLM integration — the ``ConceptExtractor`` orchestrator
    accepts any ``ConceptExtractionStrategy`` implementation, so
    dropping in a real LLM backend requires zero changes to the
    orchestrator.
    """

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> list[Concept]:
        # TODO: implement LLM-based extraction
        return []
