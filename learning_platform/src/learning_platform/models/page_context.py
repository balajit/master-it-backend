"""Page Context — groups document nodes by page for page-level processing.

After normalization, the pipeline partitions nodes by page number into
``PageContext`` objects. Each page-aware stage receives a list of
``PageContext`` instances and processes all nodes on a page together,
enabling richer context for concept extraction and learning unit creation.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from learning_platform.models.annotation import Annotation
    from learning_platform.models.concept import Concept
    from learning_platform.models.document import CanonicalDocument, DocumentNode
    from learning_platform.models.learning_unit import LearningUnit

_LOG = logging.getLogger(__name__)


def _plain_text(node: DocumentNode) -> str:
    """Extract plain text from any content block."""
    from learning_platform.models.document import (
        Callout,
        CodeBlock,
        Definition,
        Equation,
        Exercise,
        Figure,
        Heading,
        ListBlock,
        Note,
        Paragraph,
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


_SKIP_KINDS: frozenset[str] = frozenset(
    {"PageBreak", "PageHeader", "PageFooter", "TableOfContents", "MetadataBlock"}
)


@dataclass
class PageContext:
    """All document nodes and computed state for a single page.

    Page contexts are created by ``build_page_contexts()`` and passed
    through the page-aware pipeline stages. Each stage populates its
    own field (annotations, units, concepts) as it processes the page.
    """

    page_number: int
    nodes: list[DocumentNode] = field(default_factory=list)
    page_text: str = ""
    heading: str | None = None
    annotations: list[Annotation] = field(default_factory=list)
    units: list[LearningUnit] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)


def build_page_contexts(document: CanonicalDocument) -> list[PageContext]:
    """Partition a normalized document's nodes into per-page contexts.

    Nodes are grouped by their ``page`` attribute (1-indexed).
    Nodes with ``page == 0`` (unknown page) are placed in a synthetic
    page 0 context at the beginning.

    For each page, the factory computes:
    - ``page_text``: concatenated plain text of all content nodes
    - ``heading``: the first heading on the page (used as page title)
    """
    from learning_platform.models.document import Heading
    from learning_platform.stages.normalizer.passes._helpers import tree_to_flat

    all_nodes: list[DocumentNode] = []
    for node in document.nodes:
        all_nodes.extend(tree_to_flat(node))

    buckets: dict[int, list[DocumentNode]] = defaultdict(list)

    for node in all_nodes:
        page_num = node.page if node.page >= 0 else 0
        buckets[page_num].append(node)

    pages: list[PageContext] = []
    for page_num in sorted(buckets.keys()):
        nodes = buckets[page_num]

        text_parts: list[str] = []
        heading: str | None = None

        for node in nodes:
            kind = type(node.content).__name__
            if kind in _SKIP_KINDS:
                continue

            text = _plain_text(node)
            if text:
                text_parts.append(text)

            if heading is None and isinstance(node.content, Heading):
                heading = node.content.text.plain_text

        pages.append(
            PageContext(
                page_number=page_num,
                nodes=nodes,
                page_text="\n".join(text_parts),
                heading=heading,
            )
        )

    _LOG.info(
        "Built %d page contexts from document with %d nodes",
        len(pages),
        len(document.nodes),
    )
    return pages
