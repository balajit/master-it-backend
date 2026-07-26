"""TextPatternStrategy — rule-based concept extraction via text patterns.

Scans the document text for patterns that indicate concepts, skills,
processes, facts, rules, and formulas.  Each pattern produces a
``Concept`` with a ``ConceptCategory`` tag.

This strategy does *not* use an LLM — it relies entirely on regex
heuristics.  An LLM-based strategy can be swapped in later via the
``ConceptExtractionStrategy`` protocol.
"""

from __future__ import annotations

import re

from learning_platform.models.annotation import Annotation
from learning_platform.models.concept import Concept, ConceptCategory
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.learning_unit import LearningUnit

from ._helpers import all_text, count_mentions

# ──────────────────────────────────────────────────────────────────────────────
# Pattern definitions — each maps to a ConceptCategory
# ──────────────────────────────────────────────────────────────────────────────

_SKILL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:learning\s+objective|you\s+will|students?\s+will|"
        r"by\s+the\s+end|able\s+to)\s*[:\-]?\s*(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:skill|competency|ability\s+to)\s*[:\-]\s*(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
]

_PROCESS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:step\s+\d+|first|second|third|then|next|finally)\s*"
        r"[:\-–—]\s*(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:process|procedure|method|algorithm)\s+(?:of|for|to)\s+"
        r"(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
]

_FACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:fact|key\s+point|important|note\s+that)\s*"
        r"[:\-–—]\s*(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(.+?)\s+is\s+(?:always|never|defined\s+as)\s+(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
]

_RULE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:rule|law|principle|theorem|axiom)\s*"
        r"[:\-–—]\s*(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:must|shall|always|required\s+to)\s+(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
]

_FORMULA_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:formula|equation|expression)\s*"
        r"[:\-–—]\s*(.+?)(?:\.|;|\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([A-Za-z]\s*=\s*[A-Za-z0-9\s\+\-\*/\^\(\)]+)",
        re.IGNORECASE,
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Strategy
# ──────────────────────────────────────────────────────────────────────────────


class TextPatternStrategy:
    """Rule-based concept extraction using regex patterns.

    Each category of concept has its own set of patterns.  The strategy
    scans the full document text once per pattern set and creates a
    ``Concept`` for each match.

    Also supports ``extract_from_text`` for page-level extraction where
    the caller provides the text directly.
    """

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> list[Concept]:
        text = all_text(document)
        if not text.strip():
            return []

        return self._extract_from_text(text)

    def extract_from_text(
        self,
        text: str,
        source_node_ids: list | None = None,
    ) -> list[Concept]:
        """Extract concepts from pre-computed text (e.g. page-level text).

        Parameters
        ----------
        text : str
            The text to scan for concept patterns.
        source_node_ids : list | None
            Optional node IDs to associate with extracted concepts.
        """
        if not text.strip():
            return []

        concepts = self._extract_from_text(text)
        if source_node_ids:
            for c in concepts:
                c.source_node_ids = list(source_node_ids)
        return concepts

    @staticmethod
    def _extract_from_text(text: str) -> list[Concept]:
        """Run all pattern sets against the given text."""
        concepts: list[Concept] = []
        cats = [
            (ConceptCategory.SKILL, _SKILL_PATTERNS),
            (ConceptCategory.PROCESS, _PROCESS_PATTERNS),
            (ConceptCategory.FACT, _FACT_PATTERNS),
            (ConceptCategory.RULE, _RULE_PATTERNS),
            (ConceptCategory.FORMULA, _FORMULA_PATTERNS),
        ]
        for cat, patterns in cats:
            concepts.extend(
                TextPatternStrategy._extract_category(text, cat, patterns)
            )
        return concepts

    @staticmethod
    def _extract_category(
        text: str,
        category: ConceptCategory,
        patterns: list[re.Pattern[str]],
    ) -> list[Concept]:
        """Run a set of patterns and produce one Concept per unique match."""
        concepts: list[Concept] = []
        seen: set[str] = set()

        for pattern in patterns:
            for match in pattern.finditer(text):
                name = match.group(1).strip() if match.lastindex else match.group(0).strip()
                name = name[:120]  # cap length
                key = name.lower()

                if key in seen or len(name) < 3:
                    continue
                seen.add(key)

                mentions = count_mentions(text, name, [])
                concepts.append(
                    Concept(
                        name=name,
                        category=category,
                        aliases=[],
                        importance=min(1.0, mentions * 0.15),
                        mention_count=mentions,
                        source_node_ids=[],
                    )
                )

        return concepts
