"""Docling to canonical node mapper — direct type mapping with no synthetics.

This module provides functions to map Docling items (via ``CorrelatedItem``)
directly to canonical ``DocumentNode`` types. The mapping is 1:1 with no
synthetic question promotion, TOC generation, or other inference.

Mapping Table
-------------
| Docling Type/Label        | Canonical Type              |
|---------------------------|------------------------------|
| TitleItem                 | Heading(level=CHAPTER)       |
| SectionHeaderItem         | Heading(level=...)           |
| TextItem (any label)      | TextItem                     |
| ListItem                  | ListBlock (single item)      |
| GroupItem (label="list")  | ListBlock (container)        |
| GroupItem (label="form_area") | FormAreaBlock            |
| TableItem                 | TableBlock                   |
| FormulaItem               | Equation                     |
| CodeItem                  | CodeBlock                    |
| PictureItem               | Figure                       |
| label="page_header"       | PageHeader                   |
| label="page_footer"       | PageFooter                   |
| Others (unmapped)         | Paragraph with error text    |
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from uuid import UUID, uuid4

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
    PageFooter,
    PageHeader,
    Paragraph,
    SourceLocation,
    StyledText,
    TableBlock,
    TableCell,
    TableRow,
    TextItem,
    TextRun,
)
from learning_platform.stages.parser2.docling_pymupdf_merger import CorrelatedItem

_LOG = logging.getLogger(__name__)

_SPATIAL_PAGE_SENTINEL: int = 10**9


@dataclass
class _SpatialOrder:
    """Internal spatial sort key components for a node."""

    page: int = _SPATIAL_PAGE_SENTINEL
    norm_top: float = float("inf")
    norm_left: float = float("inf")


def map_correlated_item(
    item: CorrelatedItem,
    source: str,
    docling_doc: object,
) -> DocumentNode:
    """Map a single CorrelatedItem to a DocumentNode.

    This function performs direct type mapping with no synthetic inference.
    Unmapped items become Paragraph nodes with error text prefix.

    Parameters
    ----------
    item : CorrelatedItem
        The correlated item to map.
    source : str
        Source file path.
    docling_doc : object
        The Docling document (for page size lookups).

    Returns
    -------
    DocumentNode
        The mapped canonical node.
    """
    # Import Docling types dynamically to handle optional dependency
    try:
        from docling_core.types.doc import (  # noqa: PLC0415
            CodeItem,
            FormulaItem,
            GroupItem,
            PictureItem,
            SectionHeaderItem,
            TableItem,
            TitleItem,
        )
        from docling_core.types.doc import (
            ListItem as DoclingListItem,
        )
        from docling_core.types.doc import (
            TextItem as DoclingTextItem,
        )
    except ImportError:
        _LOG.warning("docling_core not available; using fallback label-based mapping")
        return _map_by_label_only(item, source, docling_doc)

    docling_item = item.docling_item
    label = item.label

    # Check for furniture items first (by label)
    if label == "page_header":
        node = _make_page_header(item, source)
    elif label == "page_footer":
        node = _make_page_footer(item, source)
    # Map by Docling item type
    elif isinstance(docling_item, TitleItem):
        node = _make_heading(item, HeadingLevel.CHAPTER, source)
    elif isinstance(docling_item, SectionHeaderItem):
        level = _map_heading_level(getattr(docling_item, "level", 1))
        node = _make_heading(item, level, source)
    elif isinstance(docling_item, DoclingTextItem):
        node = _make_text_item(item, source)
    elif isinstance(docling_item, DoclingListItem):
        node = _make_list_item(item, source)
    elif isinstance(docling_item, GroupItem) and label == "list":
        node = _make_list_group(item, source)
    elif isinstance(docling_item, GroupItem) and label == "form_area":
        node = _make_form_area(item, source)
    elif isinstance(docling_item, GroupItem):
        # Other GroupItem types → Paragraph (preserve text content)
        node = _make_paragraph(item, source)
    elif isinstance(docling_item, TableItem):
        node = _make_table(item, source, docling_doc)
    elif isinstance(docling_item, FormulaItem):
        node = _make_equation(item, source)
    elif isinstance(docling_item, CodeItem):
        node = _make_code_block(item, source)
    elif isinstance(docling_item, PictureItem):
        node = _make_figure(item, source, docling_doc)
    else:
        # Unmapped item → Paragraph with error prefix
        node = _make_error_paragraph(item, source)

    # Apply common attributes
    _apply_common_attributes(node, item, source, docling_doc)

    return node


def _map_by_label_only(
    item: CorrelatedItem,
    source: str,
    docling_doc: object,
) -> DocumentNode:
    """Fallback mapping when docling_core types are not available."""
    label = item.label.lower()

    if label == "page_header":
        node = _make_page_header(item, source)
    elif label == "page_footer":
        node = _make_page_footer(item, source)
    elif label in ("title",):
        node = _make_heading(item, HeadingLevel.CHAPTER, source)
    elif label in ("section_header", "subtitle"):
        node = _make_heading(item, HeadingLevel.SECTION, source)
    elif label == "form_area":
        node = _make_form_area(item, source)
    elif label in ("paragraph", "text", "caption"):
        node = _make_text_item(item, source)
    elif label == "list_item":
        node = _make_list_item(item, source)
    elif label == "list":
        node = _make_list_group(item, source)
    elif label == "table":
        node = _make_table(item, source, docling_doc)
    elif label in ("formula", "equation"):
        node = _make_equation(item, source)
    elif label in ("code", "code_block"):
        node = _make_code_block(item, source)
    elif label in ("picture", "figure", "image"):
        node = _make_figure(item, source, docling_doc)
    else:
        node = _make_error_paragraph(item, source)

    _apply_common_attributes(node, item, source, docling_doc)
    return node


def _apply_common_attributes(
    node: DocumentNode,
    item: CorrelatedItem,
    source: str,
    docling_doc: object,
) -> None:
    """Apply common attributes to a node from a CorrelatedItem."""
    node.page = item.page_no
    node.level = item.level

    # Source location
    node.source = SourceLocation(
        file=source,
        page=item.page_no,
        element_ref=item.self_ref or "",
    )

    # Bounding box (normalized to top-left origin)
    normalized_bbox = _normalized_bbox_extents(item, docling_doc)
    if normalized_bbox is not None:
        left, top, right, bottom, page_width, page_height = normalized_bbox
        node.bbox = BoundingBox(
            x=left,
            y=top,
            width=max(0.0, right - left),
            height=max(0.0, bottom - top),
            page_width=page_width,
            page_height=page_height,
        )

    # Block style from PyMuPDF font data
    if item.primary_font_name or item.primary_font_size:
        node.style = BlockStyle(
            font=FontInfo(
                name=item.primary_font_name or "",
                size=item.primary_font_size or 0.0,
                is_bold=item.is_bold,
                is_italic=item.is_italic,
                color=item.primary_color_hex or "",
            )
        )

    # Metadata
    node.metadata["label"] = item.label
    if item.self_ref:
        node.metadata["docling_self_ref"] = item.self_ref
    if item.parent_cref:
        node.metadata["docling_parent_ref"] = item.parent_cref
    if item.fonts:
        node.metadata["pymupdf_font"] = {
            "name": item.primary_font_name,
            "size": item.primary_font_size,
            "color": item.primary_color_hex,
            "bold": item.is_bold,
            "italic": item.is_italic,
        }
    if item.vector_lines:
        node.metadata["vector_lines"] = [
            {"length": float(vl["length"]), "top": float(vl["top"])} for vl in item.vector_lines
        ]


# ── Node Factory Functions ────────────────────────────────────────────────────


def _make_heading(
    item: CorrelatedItem,
    level: HeadingLevel,
    source: str,
) -> DocumentNode:
    """Create a Heading node."""
    text = item.text
    number = ""

    # Try to split heading number (e.g., "1.2 Introduction" -> "1.2", "Introduction")
    import re

    heading_re = re.compile(r"^((?:\d+\.)*\d+|[A-Z]\.|Appendix\s+[A-Z])\s+(.*)$")
    match = heading_re.match(text)
    if match:
        number = match.group(1)
        text = match.group(2)

    inline_style = _make_inline_style(item)

    return DocumentNode(
        id=uuid4(),
        content=Heading(
            level=level,
            text=StyledText(runs=[TextRun(text=text, style=inline_style)]),
            number=number,
        ),
    )


def _make_paragraph(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a Paragraph node."""
    inline_style = _make_inline_style(item)

    return DocumentNode(
        id=uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text=item.text, style=inline_style)])),
    )


def _make_text_item(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a TextItem node.

    TextItem represents discrete text elements like word-bank choices,
    form field labels, or answer options. Unlike Paragraph (flowing prose),
    each TextItem is a distinct selectable/fillable unit.
    """
    inline_style = _make_inline_style(item)

    return DocumentNode(
        id=uuid4(),
        content=TextItem(text=StyledText(runs=[TextRun(text=item.text, style=inline_style)])),
    )


def _make_form_area(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a FormAreaBlock node.

    FormAreaBlock represents word banks, answer boxes, option groups, and similar
    interactive regions. Children (TextItem nodes) are attached as
    DocumentNode.children during tree building.
    """
    return DocumentNode(
        id=uuid4(),
        content=FormAreaBlock(),
    )


def _make_page_header(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a PageHeader node."""
    inline_style = _make_inline_style(item)

    return DocumentNode(
        id=uuid4(),
        content=PageHeader(text=StyledText(runs=[TextRun(text=item.text, style=inline_style)])),
    )


def _make_page_footer(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a PageFooter node."""
    inline_style = _make_inline_style(item)

    return DocumentNode(
        id=uuid4(),
        content=PageFooter(
            text=StyledText(runs=[TextRun(text=item.text, style=inline_style)]),
            page_number=item.page_no,
        ),
    )


def _make_list_item(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a ListBlock node containing a single list item."""
    inline_style = _make_inline_style(item)
    list_style = _infer_list_style(item.text, item.label)

    return DocumentNode(
        id=uuid4(),
        content=ListBlock(
            style=list_style,
            items=[ListItem(text=StyledText(runs=[TextRun(text=item.text, style=inline_style)]))],
        ),
    )


def _make_list_group(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create an empty ListBlock container (children added during tree building)."""
    list_style = _infer_list_style(item.text, item.label)

    return DocumentNode(
        id=uuid4(),
        content=ListBlock(
            style=list_style,
            items=[],
        ),
    )


def _make_table(
    item: CorrelatedItem,
    source: str,
    docling_doc: object,
) -> DocumentNode:
    """Create a TableBlock node from a Docling TableItem."""
    docling_item = item.docling_item
    rows: list[TableRow] = []
    headers: list[str] = []

    # Try to extract table data from Docling item
    data = getattr(docling_item, "data", None)
    if data is not None:
        table_cells = getattr(data, "table_cells", None)
        if table_cells:
            # Build rows from table_cells
            rows_dict: dict[int, list[TableCell]] = {}
            for cell in table_cells:
                row_idx = getattr(cell, "row", 0)
                cell_text = getattr(cell, "text", "") or ""
                is_header = getattr(cell, "is_header", False)
                row_span = getattr(cell, "row_span", 1) or 1
                col_span = getattr(cell, "col_span", 1) or 1

                if row_idx not in rows_dict:
                    rows_dict[row_idx] = []

                rows_dict[row_idx].append(
                    TableCell(
                        content=[TextRun(text=cell_text)],
                        row_span=row_span,
                        col_span=col_span,
                        header=is_header,
                    )
                )

                if is_header and row_idx == 0:
                    headers.append(cell_text)

            for row_idx in sorted(rows_dict.keys()):
                cells = rows_dict[row_idx]
                is_header_row = all(c.header for c in cells)
                rows.append(TableRow(cells=cells, is_header=is_header_row))

    return DocumentNode(
        id=uuid4(),
        content=TableBlock(
            rows=rows,
            headers=headers,
            row_count=len(rows),
            column_count=len(headers) if headers else (len(rows[0].cells) if rows else 0),
        ),
    )


def _make_equation(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create an Equation node."""
    docling_item = item.docling_item
    latex = getattr(docling_item, "text", "") or item.text
    # Some Docling items have a 'latex' attribute
    latex = getattr(docling_item, "latex", latex) or latex

    return DocumentNode(
        id=uuid4(),
        content=Equation(
            latex=latex,
            is_block=True,
        ),
    )


def _make_code_block(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a CodeBlock node."""
    docling_item = item.docling_item
    code = getattr(docling_item, "text", "") or item.text
    language = getattr(docling_item, "language", "") or ""

    return DocumentNode(
        id=uuid4(),
        content=CodeBlock(
            code=code,
            language=language,
        ),
    )


def _make_figure(
    item: CorrelatedItem,
    source: str,
    docling_doc: object,
) -> DocumentNode:
    """Create a Figure node."""
    docling_item = item.docling_item

    # Try to extract image data from Docling
    image_uri = ""
    alt_text = ""
    caption_text = ""

    # Docling PictureItem may have various attributes
    if hasattr(docling_item, "image"):
        image = docling_item.image
        if hasattr(image, "uri"):
            image_uri = image.uri or ""
    if hasattr(docling_item, "caption"):
        caption_text = str(docling_item.caption or "")
    if hasattr(docling_item, "alt_text"):
        alt_text = str(docling_item.alt_text or "")

    return DocumentNode(
        id=uuid4(),
        content=Figure(
            image_uri=image_uri,
            alt_text=alt_text,
            caption_text=caption_text,
        ),
    )


def _make_error_paragraph(item: CorrelatedItem, source: str) -> DocumentNode:
    """Create a Paragraph node for unmapped items with error prefix."""
    type_name = type(item.docling_item).__name__
    error_text = f"***Error*** Unmapped item type: {type_name}, label: {item.label}"

    # Include original text if available
    if item.text:
        error_text += f"\nOriginal text: {item.text}"

    return DocumentNode(
        id=uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text=error_text)])),
    )


# ── Helper Functions ──────────────────────────────────────────────────────────


def _make_inline_style(item: CorrelatedItem) -> InlineStyle:
    """Create InlineStyle from CorrelatedItem's PyMuPDF font data."""
    if not (item.primary_font_name or item.primary_font_size or item.is_bold or item.is_italic):
        return InlineStyle()

    return InlineStyle(
        font=FontInfo(
            name=item.primary_font_name or "",
            size=item.primary_font_size or 0.0,
            is_bold=item.is_bold,
            is_italic=item.is_italic,
            color=item.primary_color_hex or "",
        )
    )


def _map_heading_level(docling_level: int) -> HeadingLevel:
    """Map Docling heading level to canonical HeadingLevel."""
    if docling_level <= 1:
        return HeadingLevel.CHAPTER
    if docling_level == 2:
        return HeadingLevel.SECTION
    if docling_level == 3:
        return HeadingLevel.SUBSECTION
    return HeadingLevel.SUBSUBSECTION


def _infer_list_style(text: str, label: str) -> ListStyle:
    """Infer list style from text patterns and label."""
    import re

    # Check label for checkbox hints
    label_lower = label.lower()
    if "checkbox" in label_lower:
        return ListStyle.CHECKBOX

    # Check text patterns
    if re.match(r"^\s*(?:\[[xX ]\]|☐|☑|✓)\s+", text):
        return ListStyle.CHECKBOX
    if re.match(r"^\s*\d+[.)]\s+", text):
        return ListStyle.NUMBERED
    if re.match(r"^\s*(?=[IVXLCDMivxlcdm]{2,}[.)])[IVXLCDMivxlcdm]+[.)]\s+", text):
        return ListStyle.ROMAN
    if re.match(r"^\s*[A-Za-z][.)]\s+", text):
        return ListStyle.ALPHA

    return ListStyle.BULLET


def _get_page_size(docling_doc: object, page_no: int) -> tuple[float, float]:
    """Get page dimensions from Docling document."""
    try:
        pages = getattr(docling_doc, "pages", None)
        if pages and page_no in pages:
            page = pages[page_no]
            size = getattr(page, "size", None)
            if size:
                return (
                    float(getattr(size, "width", 0.0) or 0.0),
                    float(getattr(size, "height", 0.0) or 0.0),
                )
    except Exception:
        pass
    return (0.0, 0.0)


def _normalized_bbox_extents(
    item: CorrelatedItem,
    docling_doc: object,
) -> tuple[float, float, float, float, float, float] | None:
    """Return bbox extents normalized to top-left origin.

    Returns ``(left, top, right, bottom, page_width, page_height)`` or
    ``None`` when the item has no bbox.
    """
    if item.bbox is None:
        return None

    left_raw = float(item.bbox[0])
    top_raw = float(item.bbox[1])
    right_raw = float(item.bbox[2])
    bottom_raw = float(item.bbox[3])

    left = min(left_raw, right_raw)
    right = max(left_raw, right_raw)
    top_value = min(top_raw, bottom_raw)
    bottom_value = max(top_raw, bottom_raw)

    page_width, page_height = _get_page_size(docling_doc, item.page_no)
    coord_origin = _extract_coord_origin(item.docling_item)
    if "BOTTOM" in coord_origin.upper() and page_height > 0.0:
        top = page_height - bottom_value
        bottom = page_height - top_value
    else:
        top = top_value
        bottom = bottom_value

    return (left, top, right, bottom, page_width, page_height)


def build_document_tree(
    items: list[CorrelatedItem],
    source: str,
    docling_doc: object,
) -> DocumentNode:
    """Build a document tree from correlated items using parent references.

    Parent refs that do not map to a real Docling item are represented by
    AI-prefixed synthetic container nodes so hierarchy is preserved instead of
    flattening orphaned items to the root.

    Parameters
    ----------
    items : list[CorrelatedItem]
        List of correlated items from the merger.
    source : str
        Source file path.
    docling_doc : object
        The Docling document.

    Returns
    -------
    DocumentNode
        The root node with children organized by parent-child relationships.
    """
    # Step 1: Create root and map all items to canonical nodes.
    body_ref = _extract_body_self_ref(docling_doc)
    root = DocumentNode(
        id=uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
        metadata={
            "role": "document_root",
            "label": "AI-BODY",
            "docling_self_ref": body_ref,
        },
    )

    ref_to_node: dict[str, DocumentNode] = {}
    ref_to_node[body_ref] = root
    all_nodes: list[tuple[CorrelatedItem, DocumentNode]] = []
    spatial_by_node_id: dict[UUID, _SpatialOrder] = {}
    spatial_by_node_id[root.id] = _SpatialOrder(page=0, norm_top=0.0, norm_left=0.0)

    for item in items:
        node = map_correlated_item(item, source, docling_doc)

        spatial_by_node_id[node.id] = _spatial_from_correlated_item(item, docling_doc)

        if item.self_ref:
            ref_to_node[item.self_ref] = node

        all_nodes.append((item, node))

    # Step 2: Build tree with synthetic AI-prefixed containers for missing refs.
    for item, node in all_nodes:
        parent_ref = item.parent_cref or body_ref
        parent_node = _get_or_create_parent_node(
            parent_ref=parent_ref,
            body_ref=body_ref,
            source=source,
            ref_to_node=ref_to_node,
            spatial_by_node_id=spatial_by_node_id,
        )
        node.parent_id = parent_node.id
        parent_node.children.append(node)

    # Step 3: Hydrate list groups (move list items into parent list containers).
    _hydrate_list_groups(root)

    # Step 4: Propagate child-derived spatial bounds to containers.
    _propagate_spatial_keys(root, spatial_by_node_id)

    # Step 5: Sort full hierarchy spatially (page -> y -> x) at every level.
    _sort_tree_spatially(root, spatial_by_node_id)

    # Step 6: Assign global DFS sequence numbers after final ordering.
    _assign_global_dfs_sequence(root)

    return root


def _extract_body_self_ref(docling_doc: object) -> str:
    """Return the Docling body self_ref, defaulting to ``#/body``."""
    body = getattr(docling_doc, "body", None)
    body_ref = getattr(body, "self_ref", None)
    if isinstance(body_ref, str) and body_ref.strip():
        return body_ref
    return "#/body"


def _extract_parent_ref_from_cref(cref: str) -> str | None:
    """Return the parent cref for a Docling cref-like path."""
    cleaned = cref.strip()
    if not cleaned:
        return None
    if not cleaned.startswith("#/"):
        return None
    parts = [part for part in cleaned[2:].split("/") if part]
    if len(parts) <= 1:
        return None
    return "#/" + "/".join(parts[:-1])


def _infer_ai_container_label(self_ref: str) -> str:
    """Infer an AI-prefixed container label from a Docling self-ref."""
    cleaned = self_ref.strip()
    if not cleaned.startswith("#/"):
        return "AI-CONTAINER"
    parts = [part for part in cleaned[2:].split("/") if part]
    if not parts:
        return "AI-CONTAINER"
    return f"AI-{parts[0].rstrip('s').upper()}"


def _create_synthetic_container_node(self_ref: str, source: str) -> DocumentNode:
    """Create a synthetic AI-prefixed container node for unresolved refs."""
    label = _infer_ai_container_label(self_ref)
    return DocumentNode(
        id=uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
        source=SourceLocation(file=source, element_ref=self_ref),
        metadata={
            "role": "AI-synthetic_container",
            "label": label,
            "docling_self_ref": self_ref,
            "AI-synthetic": True,
        },
    )


def _get_or_create_parent_node(
    parent_ref: str,
    body_ref: str,
    source: str,
    ref_to_node: dict[str, DocumentNode],
    spatial_by_node_id: dict[UUID, _SpatialOrder],
) -> DocumentNode:
    """Resolve a parent ref to a node, creating AI containers as needed."""
    normalized_ref = parent_ref.strip() or body_ref

    existing = ref_to_node.get(normalized_ref)
    if existing is not None:
        return existing

    container = _create_synthetic_container_node(normalized_ref, source)
    ref_to_node[normalized_ref] = container
    spatial_by_node_id[container.id] = _SpatialOrder()

    parent_container_ref = _extract_parent_ref_from_cref(normalized_ref)
    if parent_container_ref is None or parent_container_ref == normalized_ref:
        parent_container_ref = body_ref

    parent_node = _get_or_create_parent_node(
        parent_ref=parent_container_ref,
        body_ref=body_ref,
        source=source,
        ref_to_node=ref_to_node,
        spatial_by_node_id=spatial_by_node_id,
    )
    container.parent_id = parent_node.id
    if container not in parent_node.children:
        parent_node.children.append(container)

    return container


def _spatial_from_correlated_item(item: CorrelatedItem, docling_doc: object) -> _SpatialOrder:
    """Compute normalized top-left spatial position for a CorrelatedItem."""
    page_no = item.page_no if item.page_no > 0 else _SPATIAL_PAGE_SENTINEL
    normalized_bbox = _normalized_bbox_extents(item, docling_doc)
    if normalized_bbox is None:
        return _SpatialOrder(page=page_no)

    left, top, _, _, page_width, page_height = normalized_bbox

    norm_top = top / page_height if page_height > 0.0 else top
    norm_left = left / page_width if page_width > 0.0 else left

    return _SpatialOrder(page=page_no, norm_top=norm_top, norm_left=norm_left)


def _extract_coord_origin(docling_item: object) -> str:
    """Extract bbox coordinate origin string from a Docling item."""
    prov_list = getattr(docling_item, "prov", None)
    if not prov_list:
        return "TOP_LEFT"

    bbox = getattr(prov_list[0], "bbox", None)
    if bbox is None:
        return "TOP_LEFT"

    coord_origin = getattr(bbox, "coord_origin", "TOP_LEFT")
    return str(coord_origin)


def _merge_spatial(current: _SpatialOrder, candidate: _SpatialOrder) -> _SpatialOrder:
    """Return the top-left-most spatial position across two keys."""
    return _SpatialOrder(
        page=min(current.page, candidate.page),
        norm_top=min(current.norm_top, candidate.norm_top),
        norm_left=min(current.norm_left, candidate.norm_left),
    )


def _propagate_spatial_keys(
    node: DocumentNode,
    spatial_by_node_id: dict[UUID, _SpatialOrder],
) -> _SpatialOrder:
    """Propagate leaf-derived spatial keys up through container nodes."""
    current = spatial_by_node_id.get(node.id, _SpatialOrder())
    aggregated = current

    for child in node.children:
        child_spatial = _propagate_spatial_keys(child, spatial_by_node_id)
        aggregated = _merge_spatial(aggregated, child_spatial)

    spatial_by_node_id[node.id] = aggregated

    if node.page <= 0 and aggregated.page < _SPATIAL_PAGE_SENTINEL:
        node.page = aggregated.page

    return aggregated


def _spatial_sort_key(
    node: DocumentNode, spatial_by_node_id: dict[UUID, _SpatialOrder]
) -> tuple[int, float, float]:
    """Return sortable key tuple: page, normalized-top, normalized-left."""
    spatial = spatial_by_node_id.get(node.id, _SpatialOrder())

    page = node.page if node.page > 0 else spatial.page
    if page <= 0:
        page = _SPATIAL_PAGE_SENTINEL

    norm_top = (
        spatial.norm_top if math.isfinite(spatial.norm_top) else float(_SPATIAL_PAGE_SENTINEL)
    )
    norm_left = (
        spatial.norm_left if math.isfinite(spatial.norm_left) else float(_SPATIAL_PAGE_SENTINEL)
    )

    return (page, round(norm_top, 2), norm_left)


def _sort_tree_spatially(
    node: DocumentNode, spatial_by_node_id: dict[UUID, _SpatialOrder]
) -> None:
    """Sort each sibling list recursively by spatial reading order."""
    node.children.sort(key=lambda child: _spatial_sort_key(child, spatial_by_node_id))

    for child in node.children:
        _sort_tree_spatially(child, spatial_by_node_id)


def _assign_global_dfs_sequence(root: DocumentNode) -> None:
    """Assign global depth-first sequence numbers across the entire tree."""
    next_seq = 0

    def _walk(node: DocumentNode) -> None:
        nonlocal next_seq
        node.seq = next_seq
        next_seq += 1
        for child in node.children:
            _walk(child)

    _walk(root)


def _hydrate_list_groups(root: DocumentNode) -> None:
    """Move ListBlock single-item nodes into their parent ListBlock containers.

    When a ListBlock container (from GroupItem) has ListBlock children (from
    ListItem), extract the items from children and add them to the parent's
    items list.
    """

    def process_node(node: DocumentNode) -> None:
        if isinstance(node.content, ListBlock):
            # Check if this is a container with ListBlock children
            new_children: list[DocumentNode] = []
            for child in node.children:
                if isinstance(child.content, ListBlock) and len(child.content.items) == 1:
                    # Move the item to parent's items list
                    node.content.items.append(child.content.items[0])
                else:
                    new_children.append(child)
            node.children = new_children

        # Recurse into children
        for child in node.children:
            process_node(child)

    process_node(root)
