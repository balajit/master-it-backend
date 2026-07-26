"""Concept models — structured representations of domain knowledge.

A ``Concept`` is an atomic unit of domain knowledge extracted from a
document.  Concepts carry metadata (aliases, importance, mention count)
and are linked by ``ConceptRelationship`` edges inside a ``ConceptMap``.

Concept categories cover the full range of educational content types:
CONCEPT, SKILL, VOCABULARY, PROCESS, FACT, RULE, FORMULA, DEFINITION.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class ConceptCategory(StrEnum):
    """Categories of domain knowledge."""

    CONCEPT = "concept"
    SKILL = "skill"
    VOCABULARY = "vocab"
    PROCESS = "process"
    FACT = "fact"
    RULE = "rule"
    FORMULA = "formula"
    DEFINITION = "definition"


class RelationType(StrEnum):
    """Types of relationships between concepts."""

    PREREQUISITE = "prerequisite"
    RELATES_TO = "relates_to"
    CONTAINS = "contains"
    USED_IN = "used_in"
    DERIVED_FROM = "derived_from"
    EXAMPLE_OF = "example_of"


# ──────────────────────────────────────────────────────────────────────────────
# Concept
# ──────────────────────────────────────────────────────────────────────────────


class Concept(BaseModel):
    """An atomic unit of domain knowledge.

    Attributes
    ----------
    id : UUID
        Globally unique identifier.
    name : str
        Canonical name of the concept.
    category : ConceptCategory
        What kind of knowledge this represents.
    aliases : list[str]
        Alternative names or spellings for the same concept.
    importance : float
        Score in ``[0.0, 1.0]`` reflecting how central this concept is.
    mention_count : int
        How many times the concept (or its aliases) appeared in the text.
    source_node_ids : list[UUID]
        ``DocumentNode.id`` values where this concept was found.
    source_unit_ids : list[UUID]
        ``LearningUnit.id`` values this concept belongs to.
    metadata : dict[str, Any]
        Open key-value store for strategy-specific data.
    """

    id: UUID = Field(default_factory=uuid4)
    name: str
    category: ConceptCategory
    aliases: list[str] = Field(default_factory=list)
    importance: float = 0.0
    mention_count: int = 0
    source_node_ids: list[UUID] = Field(default_factory=list)
    source_unit_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Relationships
# ──────────────────────────────────────────────────────────────────────────────


class ConceptRelationship(BaseModel):
    """A directed relationship between two concepts.

    ``source_id`` depends on / relates to ``target_id`` according to
    ``relation_type``.
    """

    source_id: UUID
    target_id: UUID
    relation_type: RelationType
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Concept Map
# ──────────────────────────────────────────────────────────────────────────────


class ConceptMap(BaseModel):
    """A collection of concepts and their relationships.

    Produced by the ``ConceptExtractor`` stage and consumed by the
    ``KnowledgeGraphBuilder``.
    """

    concepts: list[Concept] = Field(default_factory=list)
    relationships: list[ConceptRelationship] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def concept_by_name(self, name: str) -> Concept | None:
        """Look up a concept by canonical name (case-insensitive)."""
        lower = name.lower()
        for c in self.concepts:
            if c.name.lower() == lower:
                return c
        return None

    def concepts_in_category(self, category: ConceptCategory) -> list[Concept]:
        """Return all concepts in a given category."""
        return [c for c in self.concepts if c.category == category]
