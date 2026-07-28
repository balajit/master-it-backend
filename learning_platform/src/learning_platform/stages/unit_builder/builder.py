"""Learning Unit Builder — decomposes a CanonicalDocument into LearningUnits.

The builder walks the document tree in reading order, splits on headings
to create unit boundaries, then populates each unit with node references
and annotation-derived metadata (objectives, definitions, examples, etc.).

Content is *never* duplicated — every reference is a ``NodeRef`` pointing
back to the canonical document.

Page-aware: ``build_pages`` processes each page's nodes together,
using page-level annotations for richer unit metadata.
"""

from __future__ import annotations

import logging
import textwrap
from typing import TYPE_CHECKING

from learning_platform.models.annotation import (
    Annotation,
    CalloutAnnotation,
    DefinitionAnnotation,
    ExampleAnnotation,
    ObjectiveAnnotation,
)
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentNode,
    Heading,
    HeadingLevel,
    Paragraph,
)
from learning_platform.models.learning_unit import (
    Difficulty,
    LearningUnit,
    NodeRef,
    UnitType,
)

if TYPE_CHECKING:
    from learning_platform.models.page_context import PageContext

_LOG = logging.getLogger(__name__)

# Reading speed assumption (words per minute)
_WPM: int = 250

# Minutes to spend examining a non-text element
_FIGURE_MINUTES: int = 1
_TABLE_MINUTES: int = 1
_EQUATION_MINUTES: int = 1

# Minutes per exercise
_EXERCISE_MINUTES: int = 3


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _plain_text(node: DocumentNode) -> str:
    """Extract plain text from any content block."""
    from learning_platform.models.document import (
        Callout,
        CodeBlock,
        Definition,
        Equation,
        Exercise,
        Figure,
        ListBlock,
        Note,
        Reference,
        TableBlock,
    )

    content = node.content
    if isinstance(content, (Paragraph, Heading)):
        return content.text.plain_text
    if isinstance(content, ListBlock):
        return "\n".join(item.text.plain_text for item in content.items)
    if isinstance(content, (Note, Callout)):
        return content.text.plain_text
    if isinstance(content, CodeBlock):
        return content.code
    if isinstance(content, TableBlock):
        return " | ".join(content.headers) if content.headers else ""
    if isinstance(content, Figure):
        return content.alt_text or content.caption_text
    if isinstance(content, Equation):
        return content.latex
    if isinstance(content, Exercise):
        return content.question.plain_text
    if isinstance(content, Definition):
        return f"{content.term}: {content.definition}"
    if isinstance(content, Reference):
        return content.text
    return ""


def _word_count(text: str) -> int:
    """Count words in a text string."""
    return len(text.split())


_SKIP_KINDS: frozenset[str] = frozenset(
    {"PageBreak", "PageHeader", "PageFooter", "TableOfContents", "MetadataBlock"}
)


# Chapter keywords (case-insensitive, matched as whole words at start of heading)
_CHAPTER_KEYWORDS: frozenset[str] = frozenset({"chapter", "unit", "module", "part"})

# Lesson keywords (case-insensitive, matched as whole words at start of heading)
_LESSON_KEYWORDS: frozenset[str] = frozenset({"lesson", "section", "topic", "lab"})


def _unit_type_for_heading(level: int, title: str = "") -> UnitType:
    """Map a heading to the appropriate unit type.

    Keyword detection takes priority over heading level:
    - Headings starting with chapter/unit/module/part → MODULE
    - Headings starting with lesson/section/topic/lab → LESSON
    - Fallback: heading level (CHAPTER→MODULE, SECTION→LESSON, deeper→TOPIC)
    """
    if title:
        first_word = title.strip().split()[0].lower().rstrip(".:") if title.strip() else ""
        if first_word in _CHAPTER_KEYWORDS:
            return UnitType.MODULE
        if first_word in _LESSON_KEYWORDS:
            return UnitType.LESSON
    # Fallback to heading level
    if level <= HeadingLevel.CHAPTER:
        return UnitType.MODULE
    if level <= HeadingLevel.SECTION:
        return UnitType.LESSON
    return UnitType.TOPIC


def _node_ref(node: DocumentNode, summary: str = "") -> NodeRef:
    """Create a NodeRef from a DocumentNode."""
    if not summary:
        summary = textwrap.shorten(_plain_text(node), width=120, placeholder="…")
    return NodeRef(node_id=node.id, summary=summary)


# ──────────────────────────────────────────────────────────────────────────────
# Difficulty estimation
# ──────────────────────────────────────────────────────────────────────────────


def _estimate_difficulty(
    text_nodes: list[DocumentNode],
    exercises: list[DocumentNode],
    equations: list[DocumentNode],
) -> Difficulty:
    """Estimate difficulty from content characteristics.

    Scoring:
    - Equations: 2 points each
    - Exercises: 3 points each
    - Average word count per paragraph: >30 words = +2, >50 words = +4
    - Total score: ≤3 → BASIC, ≤8 → INTERMEDIATE, else ADVANCED
    """
    score: int = 0

    score += len(equations) * 2
    score += len(exercises) * 3

    if text_nodes:
        avg_words = sum(_word_count(_plain_text(n)) for n in text_nodes) / len(text_nodes)
        if avg_words > 50:
            score += 4
        elif avg_words > 30:
            score += 2

    if score <= 3:
        return Difficulty.BASIC
    if score <= 8:
        return Difficulty.INTERMEDIATE
    return Difficulty.ADVANCED


# ──────────────────────────────────────────────────────────────────────────────
# Study time estimation
# ──────────────────────────────────────────────────────────────────────────────


def _estimate_study_time(
    text_nodes: list[DocumentNode],
    exercises: list[DocumentNode],
    figures: list[DocumentNode],
    tables: list[DocumentNode],
    equations: list[DocumentNode],
) -> int:
    """Estimate study time in minutes.

    Reading: word_count / WPM
    Exercises: _EXERCISE_MINUTES each
    Figures/Tables/Equations: fixed minutes each
    """
    total_words = sum(_word_count(_plain_text(n)) for n in text_nodes)
    reading_minutes = max(1, round(total_words / _WPM))

    exercise_minutes = len(exercises) * _EXERCISE_MINUTES
    visual_minutes = (len(figures) + len(tables) + len(equations)) * _FIGURE_MINUTES

    return reading_minutes + exercise_minutes + visual_minutes


# ──────────────────────────────────────────────────────────────────────────────
# Flush helper
# ──────────────────────────────────────────────────────────────────────────────


def _flush_unit(
    unit: LearningUnit | None,
    text_nodes: list[DocumentNode],
    exercise_nodes: list[DocumentNode],
    figure_nodes: list[DocumentNode],
    table_nodes: list[DocumentNode],
    equation_nodes: list[DocumentNode],
    annotations: list[Annotation],
) -> None:
    """Populate a unit's fields from collected nodes and annotations."""
    if unit is None:
        return

    unit_node_ids: set = set(unit.source_node_ids)

    unit.content_references = [_node_ref(n) for n in text_nodes]
    unit.figures = [_node_ref(n) for n in figure_nodes]
    unit.tables = [_node_ref(n) for n in table_nodes]
    unit.equations = [_node_ref(n) for n in equation_nodes]
    unit.exercises = [_node_ref(n) for n in exercise_nodes]

    objectives: list[str] = []
    definitions: list[NodeRef] = []
    examples: list[NodeRef] = []

    for ann in annotations:
        if ann.node_id not in unit_node_ids:
            continue

        if isinstance(ann, ObjectiveAnnotation) and ann.objective_text:
            objectives.append(ann.objective_text)
        elif isinstance(ann, DefinitionAnnotation):
            definitions.append(
                NodeRef(
                    node_id=ann.node_id,
                    summary=f"{ann.term}: {ann.definition_text}",
                )
            )
        elif isinstance(ann, ExampleAnnotation) or (
            isinstance(ann, CalloutAnnotation) and ann.callout_type == "example"
        ):
            examples.append(
                NodeRef(
                    node_id=ann.node_id,
                    summary=ann.title or ann.body_text[:120],
                )
            )

    unit.learning_objectives = objectives
    unit.definitions = definitions
    unit.examples = examples

    unit.estimated_study_time_minutes = _estimate_study_time(
        text_nodes,
        exercise_nodes,
        figure_nodes,
        table_nodes,
        equation_nodes,
    )

    unit.difficulty = _estimate_difficulty(
        text_nodes,
        exercise_nodes,
        equation_nodes,
    )

    if text_nodes:
        unit.description = textwrap.shorten(
            _plain_text(text_nodes[0]),
            width=200,
            placeholder="…",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────


class LearningUnitBuilder:
    """Splits a normalized document into a hierarchy of LearningUnits.

    The builder is stateless — all state is derived from the document and
    annotations passed to ``build()``.

    Page-aware: ``build_pages`` processes each page's nodes together,
    creating units from page-level heading structure.
    """

    def build(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation] | None = None,
    ) -> list[LearningUnit]:
        """Map document nodes to LearningUnit hierarchy.

        Parameters
        ----------
        document : CanonicalDocument
            The normalized, enriched document.
        annotations : list[Annotation] | None
            Annotations produced by the enrichment stage.  When ``None``
            the unit will have empty objectives, definitions, etc.

        Returns
        -------
        list[LearningUnit]
            Units in reading order.  The first unit is always
            ``COURSE``-type.
        """
        anns: list[Annotation] = list(annotations) if annotations is not None else []
        _LOG.info(
            "Building learning units from %d nodes, %d annotations",
            len(document.nodes),
            len(anns),
        )

        units: list[LearningUnit] = []
        course_unit: LearningUnit | None = None
        current_unit: LearningUnit | None = None
        current_text_nodes: list[DocumentNode] = []
        current_exercise_nodes: list[DocumentNode] = []
        current_figure_nodes: list[DocumentNode] = []
        current_table_nodes: list[DocumentNode] = []
        current_equation_nodes: list[DocumentNode] = []
        heading_stack: list[LearningUnit] = []

        for node in document.nodes:
            content = node.content

            # ── HEADING → create unit ──
            if isinstance(content, Heading):
                _flush_unit(
                    current_unit,
                    current_text_nodes,
                    current_exercise_nodes,
                    current_figure_nodes,
                    current_table_nodes,
                    current_equation_nodes,
                    anns,
                )
                current_text_nodes = []
                current_exercise_nodes = []
                current_figure_nodes = []
                current_table_nodes = []
                current_equation_nodes = []

                is_root = content.level == HeadingLevel.CHAPTER and node.parent_id is None

                if is_root and course_unit is None:
                    unit_type = UnitType.COURSE
                else:
                    unit_type = _unit_type_for_heading(content.level, content.text.plain_text)

                new_unit = LearningUnit(
                    unit_type=unit_type,
                    title=content.text.plain_text,
                    source_node_ids=[node.id],
                )

                if unit_type == UnitType.COURSE:
                    course_unit = new_unit
                    heading_stack = [new_unit]
                else:
                    while heading_stack and heading_stack[-1].unit_type.value >= unit_type.value:
                        heading_stack.pop()
                    if heading_stack:
                        parent = heading_stack[-1]
                        new_unit.parent_id = parent.id
                        parent.children_ids.append(new_unit.id)
                    heading_stack.append(new_unit)

                current_unit = new_unit
                units.append(new_unit)
                continue

            # ── Skip non-content node types ──
            kind = type(content).__name__
            if kind in _SKIP_KINDS:
                continue

            # ── Collect content into current unit ──
            if current_unit is None:
                if course_unit is not None:
                    course_unit.source_node_ids.append(node.id)
                continue

            current_unit.source_node_ids.append(node.id)

            from learning_platform.models.document import (
                Equation,
                Exercise,
                Figure,
                TableBlock,
            )

            if isinstance(content, Figure):
                current_figure_nodes.append(node)
            elif isinstance(content, TableBlock):
                current_table_nodes.append(node)
            elif isinstance(content, Equation):
                current_equation_nodes.append(node)
            elif isinstance(content, Exercise):
                current_exercise_nodes.append(node)
            else:
                current_text_nodes.append(node)

        # Flush the last unit
        _flush_unit(
            current_unit,
            current_text_nodes,
            current_exercise_nodes,
            current_figure_nodes,
            current_table_nodes,
            current_equation_nodes,
            anns,
        )

        _LOG.info("Built %d learning units", len(units))
        return units

    def build_pages(self, pages: list[PageContext]) -> list[LearningUnit]:
        """Build learning units from page-grouped nodes.

        Iterates pages in order.  Within each page, headings create
        unit boundaries.  Page-level annotations are used to populate
        unit metadata (objectives, definitions, examples).

        Pages without headings contribute content to the most recent
        unit from a previous page (cross-page content flow).
        """
        _LOG.info("Building learning units from %d pages", len(pages))

        units: list[LearningUnit] = []
        course_unit: LearningUnit | None = None
        current_unit: LearningUnit | None = None
        current_text_nodes: list[DocumentNode] = []
        current_exercise_nodes: list[DocumentNode] = []
        current_figure_nodes: list[DocumentNode] = []
        current_table_nodes: list[DocumentNode] = []
        current_equation_nodes: list[DocumentNode] = []
        heading_stack: list[LearningUnit] = []

        for page in pages:
            # Collect all annotations from this page
            page_anns: list[Annotation] = list(page.annotations)

            for node in page.nodes:
                content = node.content

                # ── HEADING → create unit ──
                if isinstance(content, Heading):
                    _flush_unit(
                        current_unit,
                        current_text_nodes,
                        current_exercise_nodes,
                        current_figure_nodes,
                        current_table_nodes,
                        current_equation_nodes,
                        page_anns,
                    )
                    current_text_nodes = []
                    current_exercise_nodes = []
                    current_figure_nodes = []
                    current_table_nodes = []
                    current_equation_nodes = []

                    is_root = content.level == HeadingLevel.CHAPTER and course_unit is None

                    if is_root and course_unit is None:
                        unit_type = UnitType.COURSE
                    else:
                        unit_type = _unit_type_for_heading(content.level, content.text.plain_text)

                    new_unit = LearningUnit(
                        unit_type=unit_type,
                        title=content.text.plain_text,
                        source_node_ids=[node.id],
                    )

                    if unit_type == UnitType.COURSE:
                        course_unit = new_unit
                        heading_stack = [new_unit]
                    else:
                        while (
                            heading_stack and heading_stack[-1].unit_type.value >= unit_type.value
                        ):
                            heading_stack.pop()
                        if heading_stack:
                            parent = heading_stack[-1]
                            new_unit.parent_id = parent.id
                            parent.children_ids.append(new_unit.id)
                        heading_stack.append(new_unit)

                    current_unit = new_unit
                    units.append(new_unit)
                    continue

                # ── Skip non-content node types ──
                kind = type(content).__name__
                if kind in _SKIP_KINDS:
                    continue

                # ── Collect content into current unit ──
                if current_unit is None:
                    if course_unit is not None:
                        course_unit.source_node_ids.append(node.id)
                    continue

                current_unit.source_node_ids.append(node.id)

                from learning_platform.models.document import (
                    Equation,
                    Exercise,
                    Figure,
                    TableBlock,
                )

                if isinstance(content, Figure):
                    current_figure_nodes.append(node)
                elif isinstance(content, TableBlock):
                    current_table_nodes.append(node)
                elif isinstance(content, Equation):
                    current_equation_nodes.append(node)
                elif isinstance(content, Exercise):
                    current_exercise_nodes.append(node)
                else:
                    current_text_nodes.append(node)

            # Flush accumulated nodes at page boundary if unit exists
            # (but keep current_unit alive for cross-page flow)
            if current_unit is not None and (
                current_text_nodes
                or current_figure_nodes
                or current_table_nodes
                or current_equation_nodes
                or current_exercise_nodes
            ):
                _flush_unit(
                    current_unit,
                    current_text_nodes,
                    current_exercise_nodes,
                    current_figure_nodes,
                    current_table_nodes,
                    current_equation_nodes,
                    page_anns,
                )
                current_text_nodes = []
                current_exercise_nodes = []
                current_figure_nodes = []
                current_table_nodes = []
                current_equation_nodes = []

        # Flush the last unit only if there are unflushed nodes
        # (page boundary may have already flushed)
        if current_unit is not None and (
            current_text_nodes
            or current_figure_nodes
            or current_table_nodes
            or current_equation_nodes
            or current_exercise_nodes
        ):
            _flush_unit(
                current_unit,
                current_text_nodes,
                current_exercise_nodes,
                current_figure_nodes,
                current_table_nodes,
                current_equation_nodes,
                page.annotations if pages else [],
            )

        _LOG.info("Built %d learning units from pages", len(units))
        return units
