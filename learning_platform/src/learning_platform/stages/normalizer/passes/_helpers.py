"""Shared helpers for normalization passes.

These utilities are pure functions — no state, no side effects.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from learning_platform.models.document import (
    DocumentNode,
    Heading,
    Paragraph,
    StyledText,
    TextRun,
)

# ──────────────────────────────────────────────────────────────────────────────
# Node type inspection
# ──────────────────────────────────────────────────────────────────────────────


def node_type(node: DocumentNode) -> str:
    """Return the ``type`` discriminator string for a node's content."""
    return node.content.type


def is_heading(node: DocumentNode) -> bool:
    """Return ``True`` if *node* carries ``Heading`` content."""
    return isinstance(node.content, Heading)


def is_paragraph(node: DocumentNode) -> bool:
    """Return ``True`` if *node* carries ``Paragraph`` content."""
    return isinstance(node.content, Paragraph)


def heading_level(node: DocumentNode) -> int:
    """Return the heading level, or 0 if *node* is not a heading."""
    if isinstance(node.content, Heading):
        return int(node.content.level)
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Text extraction
# ──────────────────────────────────────────────────────────────────────────────


def plain_text(node: DocumentNode) -> str:
    """Extract the plain-text content of a node, regardless of its type.

    Handles all content block types by extracting the textual representation.
    """
    from learning_platform.models.document import (
        CodeBlock,
        Equation,
        Figure,
        ListBlock,
        TableBlock,
    )

    content = node.content
    if hasattr(content, "text") and isinstance(content.text, StyledText):
        return content.text.plain_text
    if hasattr(content, "question") and isinstance(content.question, StyledText):
        return content.question.plain_text
    if isinstance(content, Equation):
        return content.latex
    if isinstance(content, CodeBlock):
        return content.code
    if isinstance(content, Figure):
        return content.caption_text or content.alt_text
    if isinstance(content, ListBlock):
        return " ".join(item.text.plain_text for item in content.items if item.text)
    if isinstance(content, TableBlock):
        return content.caption or " ".join(content.headers)
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Tree ↔ flat conversions
# ──────────────────────────────────────────────────────────────────────────────


def flat_to_tree(nodes: list[DocumentNode]) -> DocumentNode:
    """Convert a flat node list into a tree rooted at a synthetic root.

    Nodes whose ``parent_id`` is ``None`` become children of the root.
    Nodes with a ``parent_id`` are attached to their parent if found;
    otherwise they also become root children.

    Returns a synthetic root ``DocumentNode`` — never ``None``.
    """
    by_id: dict[UUID, DocumentNode] = {n.id: n for n in nodes}

    # Clear any pre-existing children before rebuilding the tree.
    for node in by_id.values():
        node.children.clear()

    root_children: list[DocumentNode] = []
    attached: set[UUID] = set()

    for node in nodes:
        if node.parent_id is not None and node.parent_id in by_id:
            parent = by_id[node.parent_id]
            parent.children.append(node)
            attached.add(node.id)

    for node in nodes:
        if node.id not in attached:
            root_children.append(node)

    return DocumentNode(
        content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
        metadata={"role": "normalizer_root"},
        children=root_children,
    )


def tree_to_flat(root: DocumentNode) -> list[DocumentNode]:
    """Flatten a tree into a pre-order list, excluding synthetic roots."""
    result: list[DocumentNode] = []
    _collect(root, result)
    return result


def _collect(node: DocumentNode, accumulator: list[DocumentNode]) -> None:
    """Recursively collect nodes in pre-order, skipping synthetic roots."""
    if node.metadata.get("role") not in {"normalizer_root", "document_root"}:
        accumulator.append(node)
    for child in node.children:
        _collect(child, accumulator)


# ──────────────────────────────────────────────────────────────────────────────
# Node creation helpers
# ──────────────────────────────────────────────────────────────────────────────


def make_paragraph(text: str, source_node: DocumentNode | None = None) -> DocumentNode:
    """Create a new ``DocumentNode`` carrying a ``Paragraph``."""
    from uuid import uuid4

    return DocumentNode(
        id=uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
        page=source_node.page if source_node else 0,
        source=source_node.source.model_copy() if source_node else Any,
    )


def make_heading(
    text: str, level: int = 1, source_node: DocumentNode | None = None
) -> DocumentNode:
    """Create a new ``DocumentNode`` carrying a ``Heading``."""
    from uuid import uuid4

    from learning_platform.models.document import HeadingLevel

    safe = min(level, 4)
    heading_level_enum = HeadingLevel(safe) if safe in (1, 2, 3, 4) else HeadingLevel.SUBSUBSECTION
    return DocumentNode(
        id=uuid4(),
        content=Heading(level=heading_level_enum, text=StyledText(runs=[TextRun(text=text)])),
        level=level,
        page=source_node.page if source_node else 0,
        source=source_node.source.model_copy() if source_node else Any,
    )
