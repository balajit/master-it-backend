"""Bridge tree -> canonical DocumentNode mapper for parser2."""

from __future__ import annotations

import logging
from uuid import uuid4

from learning_platform.models.document import (
    BlockStyle,
    BoundingBox,
    CodeBlock,
    DocumentNode,
    Equation,
    Figure,
    FontInfo,
    FormAreaBlock,
    Heading,
    HeadingLevel,
    InlineStyle,
    ListBlock,
    ListItem,
    ListStyle,
    Paragraph,
    SourceLocation,
    StyledText,
    TableBlock,
    TextItem,
    TextRun,
)
from learning_platform.stages.parser2.docling_pymupdf_merger import BridgeDocument, BridgeNode

_LOG = logging.getLogger(__name__)


def build_document_tree(bridge: BridgeDocument, source: str) -> DocumentNode:
    """Build canonical document tree from bridge tree."""
    root = _map_bridge_node(bridge.root, source)
    id_map: dict[str, DocumentNode] = {bridge.root.id: root}
    _build_children(bridge.root, root, source, id_map)
    _assign_global_dfs_sequence(root)
    _hydrate_list_groups(root)
    return root


def _build_children(
    bridge_parent: BridgeNode,
    parent_node: DocumentNode,
    source: str,
    id_map: dict[str, DocumentNode],
) -> None:
    for child in bridge_parent.children:
        mapped_child = _map_bridge_node(child, source)
        mapped_child.parent_id = parent_node.id
        parent_node.children.append(mapped_child)
        id_map[child.id] = mapped_child
        _build_children(child, mapped_child, source, id_map)


def _map_bridge_node(node: BridgeNode, source: str) -> DocumentNode:
    role = str(node.metadata.get("role", ""))

    if role == "AI-table_row":
        mapped = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={
                "role": "AI-table_row",
                "table_row_index": node.metadata.get("table_row_index", 0),
            },
        )
    elif role == "AI-table_cell":
        mapped = _make_text_node(node)
        mapped.metadata["role"] = "AI-table_cell"
        mapped.metadata["table_row_index"] = node.metadata.get("table_row_index", 0)
        mapped.metadata["table_col_index"] = node.metadata.get("table_col_index", 0)
        mapped.metadata["row_span"] = node.metadata.get("row_span", 1)
        mapped.metadata["col_span"] = node.metadata.get("col_span", 1)
        mapped.metadata["is_header"] = bool(node.metadata.get("is_header", False))
    elif node.label in {"AI-BODY"}:
        mapped = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={"role": "document_root", "label": "AI-BODY"},
        )
    elif node.is_synthetic:
        mapped = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={
                "role": "AI-synthetic_container",
                "label": node.label or "AI-CONTAINER",
            },
        )
    else:
        mapped = _map_content_node(node)

    _apply_common_attributes(mapped, node, source)
    return mapped


def _map_content_node(node: BridgeNode) -> DocumentNode:
    lowered = node.label.lower()
    name = node.name

    if lowered == "page_header":
        return _make_text_node(node, role="page_header")
    if lowered == "page_footer":
        return _make_text_node(node, role="page_footer")

    if name == "TitleItem" or lowered == "title":
        return _make_heading_node(node, HeadingLevel.CHAPTER)
    if name == "SectionHeaderItem" or lowered in {"section_header", "subtitle"}:
        level = _map_heading_level(int(node.level or 1))
        return _make_heading_node(node, level)
    if lowered == "form_area":
        return DocumentNode(id=uuid4(), content=FormAreaBlock())
    if name == "ListItem" or lowered == "list_item":
        return _make_list_item_node(node)
    if lowered == "list":
        return _make_list_group_node(node)
    if name == "TableItem" or lowered == "table":
        return DocumentNode(
            id=uuid4(),
            content=TableBlock(
                rows=[],
                headers=[],
                row_count=0,
                column_count=0,
            ),
        )
    if name == "FormulaItem" or lowered in {"formula", "equation"}:
        return DocumentNode(id=uuid4(), content=Equation(latex=node.text, is_block=True))
    if name == "CodeItem" or lowered in {"code", "code_block"}:
        language = str(node.metadata.get("language", "") or "")
        return DocumentNode(id=uuid4(), content=CodeBlock(code=node.text, language=language))
    if name == "PictureItem" or lowered in {"picture", "figure", "image"}:
        return DocumentNode(id=uuid4(), content=Figure(caption_text=node.text))
    if name == "TextItem" or lowered in {"text", "paragraph", "caption"}:
        return _make_text_node(node)

    return DocumentNode(
        id=uuid4(),
        content=Paragraph(
            text=StyledText(
                runs=[TextRun(text=f"***Error*** Unmapped item type: {name}, label: {node.label}")]
            )
        ),
    )


def _make_heading_node(node: BridgeNode, level: HeadingLevel) -> DocumentNode:
    text = node.text
    number = ""

    import re

    heading_re = re.compile(r"^((?:\d+\.)*\d+|[A-Z]\.|Appendix\s+[A-Z])\s+(.*)$")
    match = heading_re.match(text)
    if match:
        number = match.group(1)
        text = match.group(2)

    return DocumentNode(
        id=uuid4(),
        content=Heading(
            level=level,
            text=StyledText(runs=[TextRun(text=text, style=_inline_style(node))]),
            number=number,
        ),
    )


def _make_text_node(node: BridgeNode, role: str | None = None) -> DocumentNode:
    mapped = DocumentNode(
        id=uuid4(),
        content=TextItem(
            text=StyledText(runs=[TextRun(text=node.text, style=_inline_style(node))])
        ),
    )
    if role:
        mapped.metadata["role"] = role
    return mapped


def _make_list_item_node(node: BridgeNode) -> DocumentNode:
    style = _infer_list_style(node.text, node.label)
    return DocumentNode(
        id=uuid4(),
        content=ListBlock(
            style=style,
            items=[
                ListItem(
                    text=StyledText(runs=[TextRun(text=node.text, style=_inline_style(node))])
                )
            ],
        ),
    )


def _make_list_group_node(node: BridgeNode) -> DocumentNode:
    style = _infer_list_style(node.text, node.label)
    return DocumentNode(
        id=uuid4(),
        content=ListBlock(
            style=style,
            items=[],
        ),
    )


def _apply_common_attributes(mapped: DocumentNode, node: BridgeNode, source: str) -> None:
    mapped.page = node.page_no
    mapped.level = node.level
    mapped.source = SourceLocation(
        file=source,
        page=node.page_no,
        element_ref=node.self_ref or "",
    )

    bbox = _bbox_from_bridge(node)
    if bbox is not None:
        mapped.bbox = bbox

    if node.font_name or node.font_size:
        mapped.style = BlockStyle(
            font=FontInfo(
                name=node.font_name or "",
                size=node.font_size or 0.0,
                is_bold=node.is_bold,
                is_italic=node.is_italic,
                color=node.color_hex or "",
            )
        )

    mapped.metadata.setdefault("label", node.label)
    if node.self_ref:
        mapped.metadata["docling_self_ref"] = node.self_ref
    if node.parent_cref:
        mapped.metadata["docling_parent_ref"] = node.parent_cref
    if node.is_synthetic:
        mapped.metadata["AI-synthetic"] = True
    if node.fitz_text:
        mapped.metadata["fitz_text"] = node.fitz_text


def _bbox_from_bridge(node: BridgeNode) -> BoundingBox | None:
    if node.norm_top == float("inf") or node.norm_left == float("inf"):
        return None

    page_width, page_height = _page_size_from_item(node.docling_item)
    x = node.norm_left * page_width if page_width > 0.0 else node.norm_left
    y = node.norm_top * page_height if page_height > 0.0 else node.norm_top
    right = node.norm_right * page_width if page_width > 0.0 else node.norm_right
    bottom = node.norm_bottom * page_height if page_height > 0.0 else node.norm_bottom

    return BoundingBox(
        x=x,
        y=y,
        width=max(0.0, right - x),
        height=max(0.0, bottom - y),
        page_width=page_width,
        page_height=page_height,
    )


def _page_size_from_item(docling_item: object | None) -> tuple[float, float]:
    prov_list = getattr(docling_item, "prov", None) if docling_item is not None else None
    if not prov_list:
        return (0.0, 0.0)
    bbox = getattr(prov_list[0], "bbox", None)
    if bbox is None:
        return (0.0, 0.0)

    width = float(getattr(bbox, "r", 0.0) or 0.0) - float(getattr(bbox, "l", 0.0) or 0.0)
    height = float(getattr(bbox, "b", 0.0) or 0.0) - float(getattr(bbox, "t", 0.0) or 0.0)
    return (max(width, 0.0), max(height, 0.0))


def _inline_style(node: BridgeNode) -> InlineStyle:
    if not (node.font_name or node.font_size or node.is_bold or node.is_italic):
        return InlineStyle()
    return InlineStyle(
        font=FontInfo(
            name=node.font_name or "",
            size=node.font_size or 0.0,
            is_bold=node.is_bold,
            is_italic=node.is_italic,
            color=node.color_hex or "",
        )
    )


def _map_heading_level(docling_level: int) -> HeadingLevel:
    if docling_level <= 1:
        return HeadingLevel.CHAPTER
    if docling_level == 2:
        return HeadingLevel.SECTION
    if docling_level == 3:
        return HeadingLevel.SUBSECTION
    return HeadingLevel.SUBSUBSECTION


def _infer_list_style(text: str, label: str) -> ListStyle:
    import re

    lowered = label.lower()
    if "checkbox" in lowered:
        return ListStyle.CHECKBOX
    if re.match(r"^\s*(?:\[[xX ]\]|☐|☑|✓)\s+", text):
        return ListStyle.CHECKBOX
    if re.match(r"^\s*\d+[.)]\s+", text):
        return ListStyle.NUMBERED
    if re.match(r"^\s*(?=[IVXLCDMivxlcdm]{2,}[.)])[IVXLCDMivxlcdm]+[.)]\s+", text):
        return ListStyle.ROMAN
    if re.match(r"^\s*[A-Za-z][.)]\s+", text):
        return ListStyle.ALPHA
    return ListStyle.BULLET


def _assign_global_dfs_sequence(root: DocumentNode) -> None:
    next_seq = 0

    def walk(node: DocumentNode) -> None:
        nonlocal next_seq
        node.seq = next_seq
        next_seq += 1
        for child in node.children:
            walk(child)

    walk(root)


def _hydrate_list_groups(root: DocumentNode) -> None:
    def process(node: DocumentNode) -> None:
        if isinstance(node.content, ListBlock):
            kept: list[DocumentNode] = []
            for child in node.children:
                if isinstance(child.content, ListBlock) and len(child.content.items) == 1:
                    if not node.content.items and node.content.style != child.content.style:
                        node.content = node.content.model_copy(
                            update={"style": child.content.style}
                        )

                    if node.style is None and child.style is not None:
                        node.style = child.style.model_copy(deep=True)

                    node.content.items.append(child.content.items[0])
                else:
                    kept.append(child)
            node.children = kept

        for child in node.children:
            process(child)

    process(root)


def map_correlated_item(*_args: object, **_kwargs: object) -> DocumentNode:
    """Compatibility stub retained for external imports/tests.

    The parser2 pipeline now uses bridge-tree mapping instead of direct
    item-level mapping.
    """
    raise RuntimeError("map_correlated_item is no longer used; build via BridgeDocument")
