"""Docling adapter — wraps IBM Docling and converts output to CanonicalDocument.

This adapter does NOT implement parsing internals. It delegates to
``docling.document_converter.DocumentConverter`` and maps the resulting
``DoclingDocument`` DOM into the canonical tree of ``DocumentNode`` instances.

The adapter preserves Docling's tree structure by:
1. Capturing parent-child relationships via ``parent.cref`` and ``self_ref``
2. Building a proper tree instead of flattening everything
3. Mapping groups (lists) as container nodes with list items as children
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from learning_platform.models.document import (
    BoundingBox,
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Equation,
    Heading,
    HeadingLevel,
    ListBlock,
    ListItem,
    ListStyle,
    Paragraph,
    SourceLocation,
    StyledText,
    TableBlock,
    TableCell,
    TableOfContents,
    TableOfContentsEntry,
    TableOfContentsType,
    TableRow,
    TextRun,
)

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

_LOG = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".csv", ".xml"}
)

HEADING_RE = re.compile(r"^((?:\d+\.)*\d+|[A-Z]\.|Appendix\s+[A-Z])\s+(.*)$")

TOC_ENTRY_RE = re.compile(r"^(.+?)\s*[.\-–—]{2,}\s*(\d+)\s*$")


class DoclingAdapter:
    """Adapter wrapping IBM Docling for use as an ``AbstractParser``.

    Parameters
    ----------
    converter : DocumentConverter | None
        An optional pre-configured ``DocumentConverter`` instance. When
        ``None`` the adapter creates one with default settings. This
        allows callers to inject a custom converter (Dependency Inversion).
    """

    def __init__(self, converter: DocumentConverter | None = None) -> None:
        self._converter = converter

    # ── AbstractParser Protocol ───────────────────────────────────────────

    def parse(self, source: str) -> CanonicalDocument:
        """Convert *source* into a ``CanonicalDocument`` via Docling."""
        _LOG.info("DoclingAdapter.parse: %s", source)
        converter = self._get_converter()
        result = converter.convert(source)
        docling_doc = result.document

        root_node = self._build_tree(docling_doc, source)
        self._auto_generate_toc(root_node)

        return CanonicalDocument(
            source=str(source),
            title=docling_doc.name or Path(source).stem,
            metadata=DocumentMetadata(
                title=docling_doc.name or "",
                file_type=Path(source).suffix.lstrip("."),
                page_count=len(docling_doc.pages) if hasattr(docling_doc, "pages") else 0,
            ),
            nodes=[root_node],
        )

    def supports(self, source: str) -> bool:
        """Return ``True`` if *source* has a Docling-supported extension."""
        return Path(source).suffix.lower() in _SUPPORTED_EXTENSIONS

    def confidence(self, source: str) -> float:
        """Return a confidence score for Docling parsing.

        Docling has highest confidence for PDF and DOCX, moderate for
        HTML/Markdown, and low for plain text.
        """
        ext = Path(source).suffix.lower()
        if ext in {".pdf", ".docx"}:
            return 0.95
        if ext in {".pptx", ".xlsx"}:
            return 0.85
        if ext in {".html", ".htm", ".md"}:
            return 0.70
        if ext in {".txt", ".csv", ".xml"}:
            return 0.40
        return 0.0

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_converter(self) -> DocumentConverter:
        """Return the Docling ``DocumentConverter``, creating one if needed."""
        if self._converter is not None:
            return self._converter

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import CodeFormulaVlmOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        opts = PdfPipelineOptions()

        opts.do_ocr = True
        opts.generate_page_images = True
        opts.generate_picture_images = True
        opts.do_picture_description = True

        opts.do_code_enrichment = True
        opts.do_formula_enrichment = True

        opts.code_formula_options = CodeFormulaVlmOptions.from_preset("codeformulav2")

        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
            }
        )

        return self._converter

    def _build_tree(self, docling_doc: object, source: str) -> DocumentNode:
        """Walk the Docling DOM and produce a canonical ``DocumentNode`` tree.

        The returned node is a synthetic root whose children represent the
        document's top-level reading order. This method preserves Docling's
        parent-child relationships instead of flattening everything.
        """
        # Step 1: Map all Docling items to DocumentNodes
        ref_to_node: dict[str, DocumentNode] = {}
        page_seq: dict[int, int] = {}
        # Track docling_ref -> DocumentNode.id mapping
        docling_ref_to_node_id: dict[str, uuid4] = {}

        for item, depth in self._iterate_items(docling_doc):
            prov_list = getattr(item, "prov", None)
            page = 0
            if prov_list:
                p = prov_list[0] if prov_list else None
                if p is not None:
                    page = getattr(p, "page_no", 0) or 0

            seq = page_seq.get(page, 0)
            page_seq[page] = seq + 1

            node = self._map_item(item, source, docling_doc, depth=depth, seq=seq, page=page)
            if node is not None:
                # Store the docling self_ref for tree building
                self_ref = getattr(item, "self_ref", "") or ""
                if self_ref:
                    ref_to_node[self_ref] = node
                    docling_ref_to_node_id[self_ref] = node.id

        # Step 2: Build tree using parent references
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={"role": "document_root"},
        )

        # Group nodes by their parent reference
        children_by_parent: dict[str, list[DocumentNode]] = defaultdict(list)

        for item, _depth in self._iterate_items(docling_doc):
            self_ref = getattr(item, "self_ref", "") or ""
            parent = getattr(item, "parent", None)
            parent_ref = getattr(parent, "cref", "") if parent else ""

            if self_ref and self_ref in ref_to_node:
                node = ref_to_node[self_ref]
                if parent_ref and parent_ref in ref_to_node:
                    # Attach to parent node
                    children_by_parent[parent_ref].append(node)
                else:
                    # Top-level node (parent is body or not found)
                    root.children.append(node)

        # Step 3: Set children on parent nodes
        for parent_ref, children in children_by_parent.items():
            if parent_ref in ref_to_node:
                parent_node = ref_to_node[parent_ref]
                parent_node.children = children
                # Set parent_id on children
                for child in children:
                    child.parent_id = parent_node.id

        return root

    def _iterate_items(self, docling_doc: object) -> list[tuple[object, int]]:
        """Safely iterate Docling items with groups. Returns an empty list on failure."""
        try:
            return list(docling_doc.iterate_items(with_groups=True))  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            _LOG.warning("DoclingDocument does not support iterate_items")
            return []

    def _map_item(
        self,
        item: object,
        source: str,
        docling_doc: object,
        *,
        depth: int = 0,
        seq: int = 0,
        page: int = 0,
    ) -> DocumentNode | None:
        """Map a single Docling item to a ``DocumentNode``."""
        from docling_core.types.doc import (
            CodeItem,
            FormulaItem,
            GroupItem,
            ListItem,
            PictureItem,
            SectionHeaderItem,
            TableItem,
            TextItem,
            TitleItem,
        )

        label = getattr(item, "label", None)
        label_value = getattr(label, "value", str(label)) if label is not None else ""
        prov_list = getattr(item, "prov", None)
        prov = prov_list[0] if prov_list else None

        bbox = BoundingBox()
        if prov is not None:
            raw_bbox = getattr(prov, "bbox", None)
            if raw_bbox is not None:
                bbox = BoundingBox(
                    x=getattr(raw_bbox, "l", 0.0),
                    y=getattr(raw_bbox, "t", 0.0),
                    width=getattr(raw_bbox, "r", 0.0) - getattr(raw_bbox, "l", 0.0),
                    height=getattr(raw_bbox, "b", 0.0) - getattr(raw_bbox, "t", 0.0),
                )

        src = SourceLocation(
            file=source,
            page=page,
            element_ref=getattr(item, "self_ref", "") or "",
        )

        # Store docling parent ref for tree building
        parent = getattr(item, "parent", None)
        parent_ref = getattr(parent, "cref", "") if parent else ""

        if label_value == "document_index":
            node = self._make_toc(item, source)
        elif isinstance(item, GroupItem) and label_value == "list":
            # Groups (lists) become ListBlock container nodes
            node = self._make_list_group(item, source)
        elif isinstance(item, TitleItem):
            node = self._make_heading(item, HeadingLevel.CHAPTER, source)
        elif isinstance(item, SectionHeaderItem):
            level = self._map_heading_level(getattr(item, "level", 1))
            node = self._make_heading(item, level, source)
        elif isinstance(item, TextItem):
            node = self._make_paragraph(item, source)
        elif isinstance(item, ListItem):
            node = self._make_list_item(item, source)
        elif isinstance(item, TableItem):
            node = self._make_table(item, source, docling_doc)
        elif isinstance(item, FormulaItem):
            node = self._make_equation(item, source)
        elif isinstance(item, CodeItem):
            node = self._make_code_block(item, source)
        elif isinstance(item, PictureItem):
            node = self._make_figure(item, source, docling_doc)
        else:
            _LOG.debug("Skipping unmapped Docling item type: %s", type(item).__name__)
            return None

        node.page = page
        node.seq = seq
        node.level = depth
        node.source = src
        node.bbox = bbox
        if label is not None:
            node.metadata["label"] = label_value
        if parent_ref:
            node.metadata["docling_parent_ref"] = parent_ref
        return node

    # ── Node factories ────────────────────────────────────────────────────

    def _make_heading(self, item: object, level: HeadingLevel, source: str) -> DocumentNode:
        text = getattr(item, "text", "") or ""
        (number, text) = self.split_heading(text)

        return DocumentNode(
            id=uuid4(),
            content=Heading(
                level=level,
                text=StyledText(runs=[TextRun(text=text)]),
                number=number,
            ),
            source=SourceLocation(file=source),
        )

    def _make_paragraph(self, item: object, source: str) -> DocumentNode:
        text = getattr(item, "text", "") or ""
        return DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
            source=SourceLocation(file=source),
        )

    def _make_list_group(self, item: object, source: str) -> DocumentNode:
        """Create a ListBlock container node for a Docling group (list).

        The group itself becomes a ListBlock, and its children (list items)
        will be attached as DocumentNode children during tree building.
        """
        # Determine list style from label or metadata
        style = ListStyle.BULLET
        # TODO: Detect numbered lists from Docling metadata

        return DocumentNode(
            id=uuid4(),
            content=ListBlock(
                style=style,
                items=[],  # Items will be attached as children
            ),
            source=SourceLocation(file=source),
        )

    def _make_list_item(self, item: object, source: str) -> DocumentNode:
        text = getattr(item, "text", "") or ""
        return DocumentNode(
            id=uuid4(),
            content=ListBlock(
                style=ListStyle.BULLET,
                items=[ListItem(text=StyledText(runs=[TextRun(text=text)]))],
            ),
            source=SourceLocation(file=source),
        )

    def _make_table(self, item: object, source: str, docling_doc: object) -> DocumentNode:
        markdown = ""
        try:
            markdown = item.export_to_markdown(doc=docling_doc)  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            _LOG.debug("TableItem.export_to_markdown failed")

        rows = self._parse_markdown_table(markdown)
        headers = [cell.strip() for cell in rows[0]] if rows else []

        return DocumentNode(
            id=uuid4(),
            content=TableBlock(
                rows=[
                    TableRow(
                        cells=[TableCell(content=[TextRun(text=c)]) for c in row],
                        is_header=(i == 0),
                    )
                    for i, row in enumerate(rows)
                ],
                headers=headers,
                row_count=len(rows),
                column_count=len(headers),
            ),
            source=SourceLocation(file=source),
        )

    def _make_equation(self, item: object, source: str) -> DocumentNode:
        latex = getattr(item, "text", "") or ""
        return DocumentNode(
            id=uuid4(),
            content=Equation(latex=latex),
            source=SourceLocation(file=source),
        )

    def _make_code_block(self, item: object, source: str) -> DocumentNode:
        from learning_platform.models.document import CodeBlock

        code = getattr(item, "text", "") or ""
        language = getattr(item, "language", "") or ""
        return DocumentNode(
            id=uuid4(),
            content=CodeBlock(code=code, language=language),
            source=SourceLocation(file=source),
        )

    def _make_figure(self, item: object, source: str, docling_doc: object) -> DocumentNode:
        """Create a Figure node from a Docling PictureItem.

        Extracts image metadata including:
        - Image URI from ImageRef
        - Caption text from captions
        - Dimensions from ImageRef.size
        - Mimetype from ImageRef
        """
        from learning_platform.models.document import Figure

        # Extract caption text
        caption = ""
        try:
            caption = item.caption_text(doc=docling_doc)  # type: ignore[union-attr]
        except (AttributeError, TypeError):
            _LOG.debug("PictureItem.caption_text failed, trying fallback")
            caption = getattr(item, "caption", "") or ""

        # Extract image metadata
        image_uri = ""
        mimetype = ""
        width = 0.0
        height = 0.0

        image_ref = getattr(item, "image", None)
        if image_ref is not None:
            # Get URI from ImageRef
            uri = getattr(image_ref, "uri", None)
            if uri is not None:
                image_uri = str(uri)

            # Get mimetype
            mimetype = getattr(image_ref, "mimetype", "") or ""

            # Get dimensions
            size = getattr(image_ref, "size", None)
            if size is not None:
                width = getattr(size, "width", 0.0) or 0.0
                height = getattr(size, "height", 0.0) or 0.0

        # Try to get alt text from metadata
        alt_text = ""
        meta = getattr(item, "meta", None)
        if meta is not None:
            description = getattr(meta, "description", None)
            if description is not None:
                alt_text = getattr(description, "text", "") or ""

        return DocumentNode(
            id=uuid4(),
            content=Figure(
                caption_text=caption,
                image_uri=image_uri,
                alt_text=alt_text,
                mimetype=mimetype,
                width=width,
                height=height,
            ),
            source=SourceLocation(file=source),
        )

    def _make_toc(self, item: object, source: str) -> DocumentNode:
        """Build a TableOfContents node from a Docling document_index item."""
        raw_text = getattr(item, "text", "") or ""
        entries: list[TableOfContentsEntry] = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = TOC_ENTRY_RE.match(line)
            if m:
                entries.append(
                    TableOfContentsEntry(
                        label=m.group(1).strip(),
                        page_number=int(m.group(2)),
                    )
                )
            else:
                entries.append(TableOfContentsEntry(label=line))

        return DocumentNode(
            id=uuid4(),
            content=TableOfContents(
                toc_type=TableOfContentsType.MANUAL,
                entries=entries,
            ),
            source=SourceLocation(file=source),
        )

    def _auto_generate_toc(self, root: DocumentNode) -> None:
        """If *root* has no TableOfContents child, build one from headings."""
        for child in root.children:
            if isinstance(child.content, TableOfContents):
                return

        heading_nodes = self._collect_headings(root)
        if not heading_nodes:
            return

        entries: list[TableOfContentsEntry] = []
        for hn in heading_nodes:
            heading = hn.content
            text = heading.text.plain_text if hasattr(heading, "text") else ""
            number = getattr(heading, "number", "") or ""
            label = f"{number} {text}".strip() if number else text
            entries.append(
                TableOfContentsEntry(
                    label=label,
                    page_number=hn.page,
                    node_id=hn.id,
                    indent_level=getattr(hn.content, "level", HeadingLevel.SECTION).value
                    if hasattr(hn.content, "level")
                    else 1,
                )
            )

        toc_node = DocumentNode(
            id=uuid4(),
            content=TableOfContents(
                toc_type=TableOfContentsType.AUTO,
                entries=entries,
            ),
        )
        root.children.insert(0, toc_node)

    def _collect_headings(self, node: DocumentNode) -> list[DocumentNode]:
        """Collect all heading nodes in document order (depth-first)."""
        result: list[DocumentNode] = []
        for child in node.children:
            if isinstance(child.content, Heading):
                result.append(child)
            result.extend(self._collect_headings(child))
        return result

    # ── Utilities ─────────────────────────────────────────────────────────

    @staticmethod
    def _map_heading_level(raw_level: int) -> HeadingLevel:
        """Map a Docling heading level integer to a ``HeadingLevel`` enum."""
        mapping = {
            1: HeadingLevel.CHAPTER,
            2: HeadingLevel.SECTION,
            3: HeadingLevel.SUBSECTION,
        }
        return mapping.get(raw_level, HeadingLevel.SUBSUBSECTION)

    @staticmethod
    def _parse_markdown_table(markdown: str) -> list[list[str]]:
        """Parse a markdown table string into a list of rows (list of cells)."""
        rows: list[list[str]] = []
        for line in markdown.strip().splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [c.strip() for c in stripped.split("|")]
            cells = [c for c in cells if c]
            if cells and all(set(c) <= {"-", ":", " "} for c in cells):
                continue
            rows.append(cells)
        return rows

    @staticmethod
    def split_heading(text: str) -> tuple[str, str]:
        m = HEADING_RE.match(text.strip())
        if not m:
            return "", text

        return m.group(1), m.group(2)
