"""Annotation models — detector output that enriches a CanonicalDocument.

An annotation is a structured finding produced by a ``Detector``.  It
never modifies the document directly; the ``EnrichmentEngine`` merges
annotations into a final enrichment layer.

Every annotation carries:

- **id** — unique UUID.
- **type** — discriminator matching the ``Literal`` tag on each variant.
- **node_id** — the ``DocumentNode.id`` this annotation relates to.
- **confidence** — ``[0.0, 1.0]`` score from the detector.
- **detector** — name of the detector that produced the annotation.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

# ──────────────────────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────────────────────


class _AnnotationBase(BaseModel):
    """Shared fields for every annotation variant."""

    id: UUID = Field(default_factory=uuid4)
    node_id: UUID
    confidence: float = 1.0
    detector: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Specific annotation types
# ──────────────────────────────────────────────────────────────────────────────


class DefinitionAnnotation(_AnnotationBase):
    """A term and its definition detected in the text."""

    type: Literal["definition"] = "definition"
    term: str = ""
    definition_text: str = ""


class ExampleAnnotation(_AnnotationBase):
    """An example or non-example block."""

    type: Literal["example"] = "example"
    is_positive: bool = True
    title: str = ""
    body_text: str = ""


class ExerciseAnnotation(_AnnotationBase):
    """An exercise, question, or problem."""

    type: Literal["exercise"] = "exercise"
    exercise_type: str = "multiple_choice"
    question_text: str = ""
    options: list[str] = Field(default_factory=list)
    solution: str = ""


class ObjectiveAnnotation(_AnnotationBase):
    """A learning objective or learning outcome statement."""

    type: Literal["objective"] = "objective"
    objective_text: str = ""


class SummaryAnnotation(_AnnotationBase):
    """A summary, recap, or chapter review block."""

    type: Literal["summary"] = "summary"
    summary_text: str = ""


class CalloutAnnotation(_AnnotationBase):
    """A callout, tip, note, or warning block."""

    type: Literal["callout"] = "callout"
    callout_type: str = "example"
    title: str = ""
    body_text: str = ""


class KeyTermAnnotation(_AnnotationBase):
    """An important term that should be highlighted or glossed."""

    type: Literal["key_term"] = "key_term"
    term: str = ""
    context_text: str = ""


class CrossReferenceAnnotation(_AnnotationBase):
    """A cross-reference to another section, equation, or figure."""

    type: Literal["cross_reference"] = "cross_reference"
    label: str = ""
    target_description: str = ""


class FigureAssociationAnnotation(_AnnotationBase):
    """An association between a figure and its caption or surrounding text."""

    type: Literal["figure_association"] = "figure_association"
    figure_node_id: UUID | None = None
    caption_text: str = ""


class EquationAssociationAnnotation(_AnnotationBase):
    """An association between an equation and its label or surrounding text."""

    type: Literal["equation_association"] = "equation_association"
    equation_node_id: UUID | None = None
    label: str = ""
    description_text: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Discriminated union
# ──────────────────────────────────────────────────────────────────────────────

Annotation = Annotated[
    DefinitionAnnotation
    | ExampleAnnotation
    | ExerciseAnnotation
    | ObjectiveAnnotation
    | SummaryAnnotation
    | CalloutAnnotation
    | KeyTermAnnotation
    | CrossReferenceAnnotation
    | FigureAssociationAnnotation
    | EquationAssociationAnnotation,
    Field(discriminator="type"),
]
