"""Learning Unit models — discrete units of learning content.

A ``LearningUnit`` is a self-contained chunk of educational material
(a topic, lesson, or module) composed of references back into the
canonical document.  Content is *never* duplicated — every reference
is a ``NodeRef`` UUID that points to the source ``DocumentNode``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class UnitType(StrEnum):
    """Hierarchy of learning unit granularity."""

    COURSE = "course"
    MODULE = "module"
    LESSON = "lesson"
    TOPIC = "topic"


class Difficulty(StrEnum):
    """Estimated difficulty level for a learning unit."""

    BASIC = "basic"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


# ──────────────────────────────────────────────────────────────────────────────
# Node Reference
# ──────────────────────────────────────────────────────────────────────────────


class NodeRef(BaseModel):
    """A reference to a ``DocumentNode`` in the canonical document.

    Carries only the UUID of the referenced node plus a human-readable
    summary.  The actual content lives exclusively in the canonical
    document — never duplicated here.
    """

    node_id: UUID
    summary: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Learning Unit
# ──────────────────────────────────────────────────────────────────────────────


class LearningUnit(BaseModel):
    """A single discrete unit of learning content.

    Units form a tree: COURSE → MODULE → LESSON → TOPIC.

    Every list field (``content_references``, ``definitions``, …) holds
    ``NodeRef`` instances that point back to the canonical document.
    Content is never stored inside the unit itself.

    Attributes
    ----------
    id : UUID
        Globally unique identifier.
    unit_type : UnitType
        Granularity level within the hierarchy.
    title : str
        Human-readable title derived from the section heading.
    learning_objectives : list[str]
        Strings extracted from ``ObjectiveAnnotation`` instances scoped
        to this unit's content nodes.
    content_references : list[NodeRef]
        Paragraphs, lists, notes, and callouts that make up the body.
    definitions : list[NodeRef]
        Key term–definition pairs scoped to this unit.
    examples : list[NodeRef]
        Example callouts or example-annotated paragraphs.
    figures : list[NodeRef]
        Figures (images, diagrams) that appear in this unit.
    tables : list[NodeRef]
        Table blocks that appear in this unit.
    equations : list[NodeRef]
        Equations that appear in this unit.
    exercises : list[NodeRef]
        Exercises or problems scoped to this unit.
    estimated_study_time_minutes : int
        Rough estimate based on word count and exercise count.
    difficulty : Difficulty
        Estimated difficulty derived from content and exercise analysis.
    parent_id : UUID | None
        ``None`` only for the root COURSE unit.
    children_ids : list[UUID]
        Ordered child unit IDs (reading order).
    prerequisite_ids : list[UUID]
        Other unit IDs this unit depends on (set by sequence builder).
    metadata : dict[str, Any]
        Open key-value store for stage-specific data.
    """

    id: UUID = Field(default_factory=uuid4)
    unit_type: UnitType
    title: str
    description: str = ""

    # ── learning objectives (plain strings, not node refs) ──
    learning_objectives: list[str] = Field(default_factory=list)

    # ── node references — all point into the canonical document ──
    content_references: list[NodeRef] = Field(default_factory=list)
    definitions: list[NodeRef] = Field(default_factory=list)
    examples: list[NodeRef] = Field(default_factory=list)
    figures: list[NodeRef] = Field(default_factory=list)
    tables: list[NodeRef] = Field(default_factory=list)
    equations: list[NodeRef] = Field(default_factory=list)
    exercises: list[NodeRef] = Field(default_factory=list)

    # ── study metadata ──
    estimated_study_time_minutes: int = 0
    difficulty: Difficulty = Difficulty.BASIC

    # ── hierarchy ──
    parent_id: UUID | None = None
    children_ids: list[UUID] = Field(default_factory=list)
    prerequisite_ids: list[UUID] = Field(default_factory=list)

    # ── internal: tracks all document node IDs belonging to this unit ──
    source_node_ids: list[UUID] = Field(default_factory=list)

    # ── open metadata ──
    metadata: dict[str, Any] = Field(default_factory=dict)
