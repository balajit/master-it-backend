"""Flashcard Seed Generator — Phase 1 (Stateless, definition/equation-based).

Extracts ``FlashcardSeed`` objects from cached ``PipelineResult`` data.
Called by the main app's ``services/flashcards.py`` when a user requests
AI-generated flashcards for a unit or lesson.

Phase 1 sources (no LLM required):
  - Definition blocks from the document (term → definition)
  - Equation blocks from the document (label → latex)

Phase 2 (future):
  - CuratorAgent.aanalyze() key_terms + question extraction (LLM path)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FlashcardSeed:
    """A minimal flashcard front/back pair ready for persistence."""

    front: str
    back: str
    source_type: str  # "definition" | "equation"
    source_node_id: str | None = None


def _seeds_from_pipeline_result(result: object) -> list[FlashcardSeed]:
    """Extract FlashcardSeed list from a PipelineResult.

    Iterates all nodes in the canonical document and produces one seed per:
      - Definition node  → front=term, back=definition
      - Equation node    → front=label (or "Equation"), back=latex
    """
    seeds: list[FlashcardSeed] = []

    try:
        document = getattr(result, "document", None)
        if document is None:
            return seeds

        nodes = getattr(document, "nodes", [])
        for node in nodes:
            content = getattr(node, "content", None)
            if content is None:
                continue
            block_type = getattr(content, "type", None)
            node_id = str(getattr(node, "id", ""))

            if block_type == "definition":
                term: str = getattr(content, "term", "").strip()
                definition: str = getattr(content, "definition", "").strip()
                if term and definition:
                    seeds.append(
                        FlashcardSeed(
                            front=term,
                            back=definition,
                            source_type="definition",
                            source_node_id=node_id,
                        )
                    )

            elif block_type == "equation":
                latex: str = getattr(content, "latex", "").strip()
                label: str = getattr(content, "label", "").strip()
                if latex:
                    front = label if label else "Equation"
                    seeds.append(
                        FlashcardSeed(
                            front=front,
                            back=latex,
                            source_type="equation",
                            source_node_id=node_id,
                        )
                    )
    except Exception as exc:
        logger.warning("FlashcardSeed extraction failed: %s", exc)

    return seeds


async def generate_seeds_for_unit(unit_id: int) -> list[FlashcardSeed]:
    """Generate flashcard seeds for a main-app unit.

    Phase 1: resolves the unit → course → document(s) via the learning platform
    cache and extracts seeds from all associated documents.

    Returns an empty list if no cached pipeline results are available.
    """
    from learning_platform.service import get_service

    service = get_service()
    seeds: list[FlashcardSeed] = []

    for doc_id in service.list_processed():
        result = service.get_cached(doc_id)
        if result is None:
            continue
        seeds.extend(_seeds_from_pipeline_result(result))

    # Deduplicate by (front, back) to avoid identical cards from multiple docs
    seen: set[tuple[str, str]] = set()
    deduped: list[FlashcardSeed] = []
    for seed in seeds:
        key = (seed.front, seed.back)
        if key not in seen:
            seen.add(key)
            deduped.append(seed)

    return deduped


async def generate_seeds_for_lesson(lesson_id: int) -> list[FlashcardSeed]:
    """Generate flashcard seeds for a main-app lesson.

    Phase 1 uses the same document-level extraction as the unit path.
    Fine-grained lesson-to-LP-unit mapping is a Phase 2 concern.
    """
    return await generate_seeds_for_unit(lesson_id)
