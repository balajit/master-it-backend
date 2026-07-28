"""Content Mapper — transforms DocumentNode tree into ContentNode presentation objects.

This module is the bridge between the pipeline's internal CanonicalDocument
representation and the typed, ordered ContentNode array consumed by client
applications.

Design Principles
-----------------
- **No side effects**: Pure transformation, no I/O, no DB access.
- **Stays inside learning_platform**: CanonicalDocument never leaks to the web layer.
- **Graceful degradation**: Unknown or structural node types (page breaks, TOC, etc.)
  are silently skipped rather than raising.
"""

from __future__ import annotations

from learning_platform.models.document import (
    Callout,
    CalloutType,
    CodeBlock,
    Definition,
    DocumentNode,
    Equation,
    Figure,
    Heading,
    ListBlock,
    ListStyle,
    Note,
    NoteType,
    Paragraph,
    TableBlock,
    TextRun,
)
from learning_platform.presentation.models import (
    BoldRun,
    CalloutNode,
    CodeBlockNode,
    ContentNode,
    DefinitionNode,
    EquationNode,
    FigureNode,
    HeadingNode,
    InlineRun,
    ItalicRun,
    LinkRun,
    ListItemNode,
    ListNode,
    NoteNode,
    ParagraphNode,
    PlainRun,
    TableCellNode,
    TableNode,
    TableRowNode,
)

_LIST_STYLE_MAP: dict[str, str] = {
    ListStyle.BULLET: "bullet",
    ListStyle.NUMBERED: "numbered",
    ListStyle.ALPHA: "alpha",
    ListStyle.ROMAN: "roman",
    ListStyle.CHECKBOX: "checkbox",
}

# ── Note variant mapping ──────────────────────────────────────────────────────

_NOTE_VARIANT_MAP: dict[NoteType, str] = {
    NoteType.INFO: "info",
    NoteType.TIP: "tip",
    NoteType.WARNING: "warning",
    NoteType.DANGER: "danger",
}

# ── Callout variant mapping ───────────────────────────────────────────────────

_CALLOUT_VARIANT_MAP: dict[CalloutType, str] = {
    CalloutType.EXAMPLE: "example",
    CalloutType.NON_EXAMPLE: "non_example",
    CalloutType.REMINDER: "reminder",
}


# ── Internal helpers ─────────────────────────────────────────────────────────


def _text_run_to_inline(run: TextRun) -> InlineRun:
    """Convert a single pipeline TextRun to the appropriate InlineRun variant."""
    font = run.style.font if run.style else None

    if run.link_target:
        return LinkRun(text=run.text, href=run.link_target)
    if font and font.is_bold:
        return BoldRun(text=run.text)
    if font and font.is_italic:
        return ItalicRun(text=run.text)
    return PlainRun(text=run.text)


def _styled_text_to_runs(st: object) -> list[InlineRun]:
    """Convert a StyledText object to a list of InlineRun objects.

    Falls back to a single empty PlainRun when there are no runs.
    """
    runs: list[InlineRun] = [_text_run_to_inline(run) for run in getattr(st, "runs", [])]
    return runs or [PlainRun(text="")]


# ── Public API ────────────────────────────────────────────────────────────────


def canonical_node_to_content_node(node: DocumentNode) -> ContentNode | None:
    """Map a single DocumentNode to a ContentNode presentation object.

    Returns ``None`` for node types that have no presentation representation
    (page breaks, headers, footers, TOC entries, metadata blocks, exercises).
    """
    c = node.content

    if isinstance(c, Heading):
        return HeadingNode(
            level=int(c.level),
            number=c.number or "",
            text=c.text.plain_text,
        )

    if isinstance(c, Paragraph):
        return ParagraphNode(runs=_styled_text_to_runs(c.text))

    if isinstance(c, ListBlock):
        items: list[ListItemNode] = [
            ListItemNode(runs=_styled_text_to_runs(li.text)) for li in c.items
        ]
        # Also collect child DocumentNodes — the normaliser stores list items as
        # Paragraph or ListBlock children rather than in c.items.
        for child in node.children:
            child_content = child.content
            if isinstance(child_content, Paragraph):
                items.append(ListItemNode(runs=_styled_text_to_runs(child_content.text)))
            elif isinstance(child_content, ListBlock) and child_content.items:
                for li in child_content.items:
                    items.append(ListItemNode(runs=_styled_text_to_runs(li.text)))
        return ListNode(
            style=_LIST_STYLE_MAP.get(str(c.style), "bullet"),  # type: ignore[arg-type]
            items=items,
        )

    if isinstance(c, Equation):
        return EquationNode(latex=c.latex, label=c.label or "")

    if isinstance(c, CodeBlock):
        return CodeBlockNode(language=c.language or "", code=c.code)

    if isinstance(c, TableBlock):
        rows = [
            TableRowNode(
                cells=[
                    TableCellNode(
                        header=cell.header,
                        text="".join(r.text for r in cell.content),
                        col_span=cell.col_span,
                        row_span=cell.row_span,
                    )
                    for cell in row.cells
                ],
                is_header=row.is_header,
            )
            for row in c.rows
        ]
        return TableNode(caption=c.caption, rows=rows)

    if isinstance(c, Note):
        return NoteNode(
            variant=_NOTE_VARIANT_MAP.get(c.note_type, "info"),  # type: ignore[arg-type]
            runs=_styled_text_to_runs(c.text),
        )

    if isinstance(c, Callout):
        return CalloutNode(
            variant=_CALLOUT_VARIANT_MAP.get(c.callout_type, "example"),  # type: ignore[arg-type]
            title=c.title or "",
            runs=_styled_text_to_runs(c.text),
        )

    if isinstance(c, Definition):
        return DefinitionNode(term=c.term, definition=c.definition)

    if isinstance(c, Figure):
        return FigureNode(
            image_url=c.image_uri or "",
            alt_text=c.alt_text or "",
            caption=c.caption_text or "",
        )

    # PageBreak, PageHeader, PageFooter, TOC, MetadataBlock, Exercise — skip
    return None


def document_nodes_to_content(nodes: list[DocumentNode]) -> list[ContentNode]:
    """Convert a list of DocumentNodes to a ContentNode list, skipping unmapped types.

    Walks the full node tree (including children) to produce a flat, ordered list.
    Top-level container nodes (page groups with empty paragraphs) are skipped if
    they produce no content themselves, but their children are always descended.
    """
    result: list[ContentNode] = []
    _walk_nodes(nodes, result)
    return result


def _walk_nodes(nodes: list[DocumentNode], result: list[ContentNode]) -> None:
    """Recursively walk DocumentNodes, appending mapped content to result."""
    for node in nodes:
        mapped = canonical_node_to_content_node(node)
        if mapped is not None:
            # Skip empty paragraphs (page group markers produced by the normaliser)
            if isinstance(mapped, ParagraphNode):
                text = "".join(getattr(r, "text", "") for r in mapped.runs).strip()
                if not text:
                    # Still descend into children
                    _walk_nodes(node.children, result)
                    continue
            result.append(mapped)
            # ListNodes already absorbed their paragraph children — don't recurse
            if isinstance(mapped, ListNode):
                continue
        # Always descend into children regardless of whether the parent mapped
        _walk_nodes(node.children, result)
