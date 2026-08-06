"""Docling + PyMuPDF bridge merger for parser2.

This module builds a bridge tree from Docling items and enriches it with
PyMuPDF style/span data. The bridge tree is then mapped to canonical
``DocumentNode`` objects by ``docling_node_mapper``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from docling.datamodel.pipeline_options import TableFormerMode, TableStructureOptions

_LOG = logging.getLogger(__name__)


@dataclass
class BridgeNode:
    """Internal bridge node used before canonical mapping."""

    id: str = field(default_factory=lambda: str(uuid4()))
    docling_item: Any | None = None
    self_ref: str | None = None
    parent_cref: str | None = None
    level: int = 0
    label: str = ""
    name: str = ""
    text: str = ""
    page_no: int = 0
    norm_top: float = float("inf")
    norm_left: float = float("inf")
    norm_bottom: float = 0.0
    norm_right: float = 0.0
    parent_id: str | None = None
    children: list[BridgeNode] = field(default_factory=list)
    is_synthetic: bool = False
    font_name: str | None = None
    font_size: float | None = None
    color_hex: str | None = None
    is_bold: bool = False
    is_italic: bool = False
    fitz_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    column_no: int = 0  # dynamic column assignment (0-based, set per-page after geometry pass)

    # Image fields — populated only for picture/figure/image nodes
    is_image: bool = False
    image_pil: Any | None = None  # raw PIL.Image, discarded after mapper conversion
    image_format: str | None = None
    image_width: int | None = None
    image_height: int | None = None

    @property
    def center_x(self) -> float:
        """Normalized horizontal center of the node's bounding box."""
        if self.norm_left == float("inf") or self.norm_right == 0.0:
            return 0.0
        return (self.norm_left + self.norm_right) / 2.0

    @property
    def center_y(self) -> float:
        """Normalized vertical center of the node's bounding box."""
        if self.norm_top == float("inf") or self.norm_bottom == 0.0:
            return 0.0
        return (self.norm_top + self.norm_bottom) / 2.0


@dataclass
class BridgeDocument:
    """Bridge output returned by the merger."""

    root: BridgeNode
    source: str
    title: str
    page_count: int


@dataclass
class CorrelatedItem:
    """Legacy compatibility shim.

    Parser2 now operates on ``BridgeNode``/``BridgeDocument``. This class is
    retained only so imports continue to resolve.
    """

    docling_item: Any
    level: int = 0


@dataclass(frozen=True)
class CachedLine:
    """PyMuPDF text line with dominant style metadata."""

    block_index: int
    line_index: int
    bbox: tuple[float, float, float, float]
    text: str
    font_name: str | None
    font_size: float | None
    color_hex: str | None
    is_bold: bool
    is_italic: bool


class PageStyleCache:
    """Pre-index PyMuPDF spans for fast spatial/text style lookup."""

    def __init__(self, page: Any) -> None:
        self.page_no = int(page.number) + 1
        self.page_w = float(page.rect.width)
        self.page_h = float(page.rect.height)
        self.spans: list[tuple[Any, dict[str, Any]]] = []
        self.lines: list[CachedLine] = []
        self._build_index(page)

    def _build_index(self, page: Any) -> None:
        import fitz  # noqa: PLC0415

        page_dict = page.get_text("dict")
        for block_index, block in enumerate(page_dict.get("blocks", [])):
            if "lines" not in block:
                continue
            for line_index, line in enumerate(block["lines"]):
                line_spans: list[dict[str, Any]] = []
                line_text_parts: list[str] = []

                for span in line.get("spans", []):
                    raw_text = str(span.get("text", ""))
                    if raw_text:
                        line_text_parts.append(raw_text)

                    stripped_text = raw_text.strip()
                    if not stripped_text:
                        continue

                    bbox = fitz.Rect(span["bbox"])
                    self.spans.append((bbox, span))
                    line_spans.append(span)

                line_text = "".join(line_text_parts).strip()
                if not line_text or "bbox" not in line:
                    continue

                style_span = self._pick_style_span(line_spans)
                (
                    font_name,
                    font_size,
                    color_hex,
                    is_bold,
                    is_italic,
                ) = self._style_from_span(style_span)

                line_bbox = fitz.Rect(line["bbox"])
                self.lines.append(
                    CachedLine(
                        block_index=block_index,
                        line_index=line_index,
                        bbox=(line_bbox.x0, line_bbox.y0, line_bbox.x1, line_bbox.y1),
                        text=line_text,
                        font_name=font_name,
                        font_size=font_size,
                        color_hex=color_hex,
                        is_bold=is_bold,
                        is_italic=is_italic,
                    )
                )

        self.spans.sort(key=lambda item: (item[0].y0, item[0].x0))
        self.lines.sort(
            key=lambda line: (line.bbox[1], line.bbox[0], line.block_index, line.line_index)
        )

    @staticmethod
    def _pick_style_span(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not spans:
            return None
        return max(spans, key=lambda span: len(str(span.get("text", "")).strip()))

    @staticmethod
    def _style_from_span(
        span: dict[str, Any] | None,
    ) -> tuple[str | None, float | None, str | None, bool, bool]:
        if span is None:
            return (None, None, None, False, False)

        font_name = str(span.get("font", "") or "").strip() or None
        flags = int(span.get("flags", 0) or 0)
        color_int = int(span.get("color", 0) or 0)

        font_size_raw = span.get("size", None)
        font_size = None
        if font_size_raw is not None:
            font_size = round(float(font_size_raw), 2)

        color_hex = f"#{color_int:06x}"
        lowered_font = (font_name or "").lower()
        is_italic = bool(flags & 2) or ("italic" in lowered_font) or ("oblique" in lowered_font)
        is_bold = bool(flags & 16) or ("bold" in lowered_font)

        return (font_name, font_size, color_hex, is_bold, is_italic)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().lower()

    @staticmethod
    def _intersects(
        source: tuple[float, float, float, float],
        target: tuple[float, float, float, float],
        *,
        padding: float = 0.0,
    ) -> bool:
        sx0, sy0, sx1, sy1 = source
        tx0, ty0, tx1, ty1 = target

        tx0 -= padding
        ty0 -= padding
        tx1 += padding
        ty1 += padding

        return not (sx1 < tx0 or tx1 < sx0 or sy1 < ty0 or ty1 < sy0)

    @staticmethod
    def _is_monospace(font_name: str | None) -> bool:
        lowered = (font_name or "").lower()
        return "courier" in lowered or "mono" in lowered

    def _should_split_line_group(self, lines: list[CachedLine]) -> bool:
        if len(lines) <= 1:
            return False

        if all(self._is_monospace(line.font_name) for line in lines):
            return True

        signatures = [
            (
                line.font_name or "",
                round(line.font_size or 0.0, 2),
                line.is_bold,
                line.is_italic,
            )
            for line in lines
        ]
        transitions = sum(
            1
            for previous, current in zip(signatures, signatures[1:], strict=False)
            if previous != current
        )
        return transitions >= max(1, len(lines) - 1)

    def _segment_from_lines(self, lines: list[CachedLine]) -> dict[str, Any]:
        text_parts = [line.text.strip() for line in lines if line.text.strip()]
        segment_text = " ".join(text_parts).strip()
        if not segment_text:
            segment_text = lines[0].text.strip()

        left = min(line.bbox[0] for line in lines)
        top = min(line.bbox[1] for line in lines)
        right = max(line.bbox[2] for line in lines)
        bottom = max(line.bbox[3] for line in lines)

        style_line = max(lines, key=lambda line: len(line.text.strip()))

        return {
            "text": segment_text,
            "norm_left": (left / self.page_w) if self.page_w > 0.0 else 0.0,
            "norm_top": (top / self.page_h) if self.page_h > 0.0 else 0.0,
            "norm_right": (right / self.page_w) if self.page_w > 0.0 else 0.0,
            "norm_bottom": (bottom / self.page_h) if self.page_h > 0.0 else 0.0,
            "font_name": style_line.font_name,
            "font_size": style_line.font_size,
            "color_hex": style_line.color_hex,
            "is_bold": style_line.is_bold,
            "is_italic": style_line.is_italic,
            "fitz_text": segment_text,
        }

    def query_text_segments(
        self,
        *,
        norm_left: float,
        norm_top: float,
        norm_right: float,
        norm_bottom: float,
        node_text: str,
    ) -> list[dict[str, Any]]:
        """Split merged text nodes into line/block-based segments when reliable."""
        if len(self.lines) < 2:
            return []

        normalized_node_text = self._normalize_text(node_text)
        if not normalized_node_text:
            return []

        if norm_right <= norm_left:
            norm_right = norm_left + 0.05
        if norm_bottom <= norm_top:
            norm_bottom = norm_top + 0.02

        target_bbox = (
            norm_left * self.page_w,
            norm_top * self.page_h,
            norm_right * self.page_w,
            norm_bottom * self.page_h,
        )

        candidate_lines = [
            line for line in self.lines if self._intersects(line.bbox, target_bbox, padding=3.0)
        ]
        if len(candidate_lines) < 2:
            return []

        matched_lines: list[CachedLine] = []
        cursor = 0

        for line in candidate_lines:
            normalized_line = self._normalize_text(line.text)
            if not normalized_line:
                continue

            position = normalized_node_text.find(normalized_line, cursor)
            if position < 0:
                position = normalized_node_text.find(normalized_line)
                if position < 0:
                    continue

            cursor = position + len(normalized_line)
            matched_lines.append(line)

        if len(matched_lines) < 2:
            return []

        grouped_by_block: list[list[CachedLine]] = []
        for line in matched_lines:
            if not grouped_by_block or grouped_by_block[-1][-1].block_index != line.block_index:
                grouped_by_block.append([line])
            else:
                grouped_by_block[-1].append(line)

        grouped_segments: list[list[CachedLine]] = []
        for group in grouped_by_block:
            if self._should_split_line_group(group):
                grouped_segments.extend([[line] for line in group])
            else:
                grouped_segments.append(group)

        if len(grouped_segments) < 2:
            return []

        return [self._segment_from_lines(group) for group in grouped_segments]

    def query_style(
        self,
        *,
        norm_left: float,
        norm_top: float,
        norm_right: float,
        norm_bottom: float,
        node_text: str,
    ) -> dict[str, Any]:
        """Query style by spatial overlap with text fallback."""
        import fitz  # noqa: PLC0415

        style_info: dict[str, Any] = {
            "font_name": None,
            "font_size": None,
            "color_hex": None,
            "is_bold": False,
            "is_italic": False,
            "fitz_text": None,
        }

        clean_node_text = node_text.strip().lower()
        best_span: dict[str, Any] | None = None

        if norm_top != float("inf") and norm_left != float("inf"):
            if norm_right <= norm_left:
                norm_right = norm_left + 0.05
            if norm_bottom <= norm_top:
                norm_bottom = norm_top + 0.02

            target_rect = fitz.Rect(
                norm_left * self.page_w,
                norm_top * self.page_h,
                norm_right * self.page_w,
                norm_bottom * self.page_h,
            )
            search_rect = target_rect + (-3, -3, 3, 3)
            max_overlap_area = 0.0

            for span_rect, span in self.spans:
                intersection = search_rect & span_rect
                if intersection.is_empty:
                    continue

                overlap_area = float(intersection.width * intersection.height)
                span_text = str(span.get("text", "")).strip().lower()
                if clean_node_text and (
                    span_text in clean_node_text or clean_node_text in span_text
                ):
                    best_span = span
                    break
                if overlap_area > max_overlap_area:
                    max_overlap_area = overlap_area
                    best_span = span

        if best_span is None and clean_node_text:
            for _, span in self.spans:
                span_text = str(span.get("text", "")).strip().lower()
                if span_text and (
                    span_text == clean_node_text
                    or span_text in clean_node_text
                    or clean_node_text in span_text
                ):
                    best_span = span
                    break

        if best_span is None:
            return style_info

        font_name = str(best_span.get("font", ""))
        color_int = int(best_span.get("color", 0))
        flags = int(best_span.get("flags", 0))

        style_info["font_name"] = font_name
        style_info["font_size"] = round(float(best_span.get("size", 0.0)), 2)
        style_info["fitz_text"] = str(best_span.get("text", "")).strip()
        style_info["color_hex"] = f"#{color_int:06x}"
        style_info["is_italic"] = bool(flags & 2) or ("italic" in font_name.lower())
        style_info["is_bold"] = bool(flags & 16) or ("bold" in font_name.lower())
        return style_info


def _extract_label(docling_item: Any) -> str:
    label = getattr(docling_item, "label", None)
    if label is None:
        return type(docling_item).__name__
    return str(getattr(label, "value", str(label)))


def _extract_parent_cref(docling_item: Any) -> str | None:
    parent = getattr(docling_item, "parent", None)
    if parent is None:
        return None
    cref = getattr(parent, "cref", None)
    if isinstance(cref, str) and cref.strip():
        return cref.strip()
    as_text = str(parent).strip()
    return as_text or None


def _extract_self_ref(docling_item: Any) -> str | None:
    self_ref = getattr(docling_item, "self_ref", None)
    if isinstance(self_ref, str) and self_ref.strip():
        return self_ref.strip()
    return None


def _normalize_docling_bbox(
    prov: Any,
    page_height: float,
    page_width: float,
) -> tuple[float, float, float, float]:
    """Convert Docling bbox to normalized top-left coordinates."""
    bbox = prov.bbox
    left_raw = float(getattr(bbox, "l", 0.0))
    top_raw = float(getattr(bbox, "t", 0.0))
    right_raw = float(getattr(bbox, "r", 0.0))
    bottom_raw = float(getattr(bbox, "b", 0.0))
    coord_origin = str(getattr(bbox, "coord_origin", "TOP_LEFT")).upper()

    left_val = min(left_raw, right_raw)
    right_val = max(left_raw, right_raw)
    top_val = min(top_raw, bottom_raw)
    bottom_val = max(top_raw, bottom_raw)

    if "BOTTOM" in coord_origin:
        actual_top = page_height - bottom_val
        actual_bottom = page_height - top_val
    else:
        actual_top = top_val
        actual_bottom = bottom_val

    norm_top = actual_top / page_height if actual_top > 1.0 and page_height > 0.0 else actual_top
    norm_left = left_val / page_width if left_val > 1.0 and page_width > 0.0 else left_val
    norm_bottom = (
        actual_bottom / page_height if actual_bottom > 1.0 and page_height > 0.0 else actual_bottom
    )
    norm_right = right_val / page_width if right_val > 1.0 and page_width > 0.0 else right_val

    return (norm_top, norm_left, norm_bottom, norm_right)


def _canonicalize_ref(ref: str | None, body_ref: str) -> str:
    if not isinstance(ref, str):
        return body_ref
    cleaned = ref.strip()
    if not cleaned:
        return body_ref
    if cleaned == "#" or cleaned.lower() == "body":
        return body_ref
    if cleaned.startswith("/"):
        return f"#{cleaned}"
    if not cleaned.startswith("#"):
        if "/" in cleaned:
            return f"#/{cleaned.lstrip('/')}"
        return cleaned
    return cleaned


def _parent_ref_of(ref: str, body_ref: str) -> str:
    if ref == body_ref:
        return body_ref
    if not ref.startswith("#/"):
        return body_ref
    parts = [part for part in ref[2:].split("/") if part]
    if len(parts) <= 1:
        return body_ref
    return "#/" + "/".join(parts[:-1])


def _infer_container_label(ref: str) -> str:
    if not ref.startswith("#/"):
        return "AI-CONTAINER"
    parts = [part for part in ref[2:].split("/") if part]
    if not parts:
        return "AI-CONTAINER"
    return f"AI-{parts[0].rstrip('s').upper()}"


class DoclingPyMuPDFMerger:
    """Build a correlated Docling/PyMuPDF bridge tree."""

    def __init__(self, source: str) -> None:
        self.source = source
        self._is_pdf = source.lower().endswith(".pdf")

        _LOG.info("DoclingPyMuPDFMerger: Running Docling conversion for %s", source)
        from docling.datamodel.base_models import InputFormat  # noqa: PLC0415
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # noqa: PLC0415
        from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: PLC0415

        pdf_options = PdfPipelineOptions()
        pdf_options.do_table_structure = True
        pdf_options.generate_picture_images = True  # populate PictureItem.image for extraction
        # --- ESSENTIAL ADDITIONS FOR VISUAL/GRID DOCUMENTS ---
        pdf_options.generate_page_images = True
        pdf_options.generate_picture_images = True
        pdf_options.generate_table_images = True

        # Helps detect complex visual table structures and grids
        pdf_options.table_structure_options = TableStructureOptions(
            mode=TableFormerMode.ACCURATE,  # Uses ACCURATE instead of FAST
            do_cell_matching=True,  # Strict cell matching to drawn/implicit grid lines
        )

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            }
        )
        result = converter.convert(source)
        self.docling_doc = result.document

        self.fitz_doc: Any = None
        self.page_style_caches: dict[int, PageStyleCache] = {}
        if self._is_pdf:
            try:
                import fitz  # noqa: PLC0415

                self.fitz_doc = fitz.open(source)
                self.page_style_caches = {
                    int(page.number) + 1: PageStyleCache(page) for page in self.fitz_doc
                }
            except Exception as exc:
                _LOG.warning("Failed to open PDF with PyMuPDF: %s", exc)

        body = getattr(self.docling_doc, "body", None)
        body_ref = getattr(body, "self_ref", None)
        self.body_ref = body_ref if isinstance(body_ref, str) and body_ref.strip() else "#/body"

        self.ref_to_node: dict[str, BridgeNode] = {}
        self.nodes_by_id: dict[str, BridgeNode] = {}

    def close(self) -> None:
        if self.fitz_doc is not None:
            import contextlib

            with contextlib.suppress(Exception):
                self.fitz_doc.close()
            self.fitz_doc = None

    def __enter__(self) -> DoclingPyMuPDFMerger:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    @property
    def title(self) -> str:
        return str(getattr(self.docling_doc, "name", "") or "")

    @property
    def page_count(self) -> int:
        pages = getattr(self.docling_doc, "pages", None)
        return len(pages) if pages is not None else 0

    def build_bridge_tree(self) -> BridgeDocument:
        root = BridgeNode(
            docling_item=getattr(self.docling_doc, "body", None),
            self_ref=self.body_ref,
            label="AI-BODY",
            name="Body",
            is_synthetic=False,
        )
        self.ref_to_node[self.body_ref] = root
        self.nodes_by_id[root.id] = root

        all_nodes: list[BridgeNode] = []
        self._extract_docling_nodes(all_nodes)
        self._extract_fitz_fallback_images(all_nodes)

        # Assign column numbers per page based on dynamic horizontal distribution.
        # Must happen after geometry is set but before sorting/parent-child linking.
        nodes_by_page: dict[int, list[BridgeNode]] = {}
        for node in all_nodes:
            if node.page_no > 0:
                nodes_by_page.setdefault(node.page_no, []).append(node)
        for page_nodes in nodes_by_page.values():
            self._assign_page_columns(page_nodes)

        self._extract_table_cell_nodes(root)
        self._attach_parent_child(all_nodes, root)
        self._propagate_bounds(root)
        self._sort_tree_spatially(root)

        return BridgeDocument(
            root=root,
            source=self.source,
            title=self.title,
            page_count=self.page_count,
        )

    def _extract_docling_nodes(self, all_nodes: list[BridgeNode]) -> None:
        try:
            items_with_levels = list(self.docling_doc.iterate_items(with_groups=True))
        except TypeError:
            items_with_levels = list(self.docling_doc.iterate_items())

        for doc_item, level in items_with_levels:
            node = BridgeNode(
                docling_item=doc_item,
                self_ref=_extract_self_ref(doc_item),
                parent_cref=_extract_parent_cref(doc_item),
                level=int(level),
                label=_extract_label(doc_item),
                name=type(doc_item).__name__,
                text=str(getattr(doc_item, "text", "") or "").strip(),
            )
            self._extract_geometry_and_style(node)

            for expanded_node in self._expand_docling_text_node(node):
                self.nodes_by_id[expanded_node.id] = expanded_node
                all_nodes.append(expanded_node)
                if expanded_node.self_ref:
                    self.ref_to_node[expanded_node.self_ref] = expanded_node

            # Extract PIL image for picture/figure/image nodes
            if node.label.upper() in {"PICTURE", "IMAGE", "FIGURE"}:
                self._process_image_item(node, doc_item)

    @staticmethod
    def _is_text_item_node(node: BridgeNode) -> bool:
        return node.name == "TextItem" or node.label.lower() in {"text", "paragraph", "caption"}

    @staticmethod
    def _float_or_fallback(value: Any, fallback: float | None) -> float | None:
        if value is None:
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _expand_docling_text_node(self, node: BridgeNode) -> list[BridgeNode]:
        if not self._is_text_item_node(node):
            return [node]

        if not node.text or node.page_no <= 0:
            return [node]

        if node.norm_top == float("inf") or node.norm_left == float("inf"):
            return [node]

        cache = self.page_style_caches.get(node.page_no)
        if cache is None:
            return [node]

        segments = cache.query_text_segments(
            norm_left=node.norm_left,
            norm_top=node.norm_top,
            norm_right=node.norm_right,
            norm_bottom=node.norm_bottom,
            node_text=node.text,
        )
        if len(segments) < 2:
            return [node]

        expanded_nodes: list[BridgeNode] = []
        segment_count = len(segments)

        for segment_index, segment in enumerate(segments):
            segment_text = str(segment.get("text", "") or "").strip()
            if not segment_text:
                continue

            if node.self_ref and segment_index > 0:
                segment_self_ref = f"{node.self_ref}/segments/{segment_index}"
            else:
                segment_self_ref = node.self_ref

            metadata = dict(node.metadata)
            metadata["docling_split_segment_index"] = segment_index
            metadata["docling_split_segment_count"] = segment_count
            if node.self_ref:
                metadata["docling_split_source_ref"] = node.self_ref

            expanded_nodes.append(
                BridgeNode(
                    docling_item=node.docling_item,
                    self_ref=segment_self_ref,
                    parent_cref=node.parent_cref,
                    level=node.level,
                    label=node.label,
                    name=node.name,
                    text=segment_text,
                    page_no=node.page_no,
                    norm_top=float(segment.get("norm_top", node.norm_top)),
                    norm_left=float(segment.get("norm_left", node.norm_left)),
                    norm_bottom=float(segment.get("norm_bottom", node.norm_bottom)),
                    norm_right=float(segment.get("norm_right", node.norm_right)),
                    is_synthetic=node.is_synthetic,
                    font_name=(str(segment.get("font_name") or "").strip() or node.font_name),
                    font_size=self._float_or_fallback(segment.get("font_size"), node.font_size),
                    color_hex=(str(segment.get("color_hex") or "").strip() or node.color_hex),
                    is_bold=bool(segment.get("is_bold", node.is_bold)),
                    is_italic=bool(segment.get("is_italic", node.is_italic)),
                    fitz_text=str(segment.get("fitz_text") or segment_text),
                    metadata=metadata,
                )
            )

        if len(expanded_nodes) < 2:
            return [node]

        return expanded_nodes

    def _extract_geometry_and_style(self, node: BridgeNode) -> None:
        doc_item = node.docling_item
        prov_list = getattr(doc_item, "prov", None)
        if not prov_list:
            return

        prov = prov_list[0]
        page_no = int(getattr(prov, "page_no", 0) or 0)
        if page_no <= 0:
            return
        node.page_no = page_no

        if self.fitz_doc is None:
            return

        pdf_page = self.fitz_doc[page_no - 1]
        node.norm_top, node.norm_left, node.norm_bottom, node.norm_right = _normalize_docling_bbox(
            prov,
            float(pdf_page.rect.height),
            float(pdf_page.rect.width),
        )

        self._apply_style_from_cache(node)

    def _apply_style_from_cache(self, node: BridgeNode) -> None:
        cache = self.page_style_caches.get(node.page_no)
        if cache is None:
            return

        style = cache.query_style(
            norm_left=node.norm_left,
            norm_top=node.norm_top,
            norm_right=node.norm_right,
            norm_bottom=node.norm_bottom,
            node_text=node.text,
        )
        node.font_name = style["font_name"]
        node.font_size = style["font_size"]
        node.color_hex = style["color_hex"]
        node.is_bold = bool(style["is_bold"])
        node.is_italic = bool(style["is_italic"])
        node.fitz_text = style["fitz_text"]

    def _get_or_create_ref_node(self, ref: str, root: BridgeNode) -> BridgeNode:
        canonical_ref = _canonicalize_ref(ref, self.body_ref)
        existing = self.ref_to_node.get(canonical_ref)
        if existing is not None:
            return existing

        container = BridgeNode(
            self_ref=canonical_ref,
            level=1,
            label=_infer_container_label(canonical_ref),
            name="SyntheticContainer",
            is_synthetic=True,
            metadata={
                "role": "AI-synthetic_container",
                "docling_self_ref": canonical_ref,
            },
        )
        self.ref_to_node[canonical_ref] = container
        self.nodes_by_id[container.id] = container

        parent_ref = _parent_ref_of(canonical_ref, self.body_ref)
        if parent_ref == canonical_ref:
            parent_ref = self.body_ref
        parent_node = (
            root if parent_ref == self.body_ref else self._get_or_create_ref_node(parent_ref, root)
        )
        container.parent_id = parent_node.id
        if container not in parent_node.children:
            parent_node.children.append(container)

        return container

    def _assign_page_columns(
        self,
        page_nodes: list[BridgeNode],
        num_columns: int = 2,
        gap_threshold: float = 0.05,
    ) -> None:
        """Dynamically assign column numbers based on horizontal distribution.

        Columns are detected from real horizontal gaps between node bounding
        boxes, not from bucket-splitting the page width.  A single-column page
        (where lines span overlapping x-intervals) stays in column 0, so wide
        headings and paragraphs are not misclassified as a second column.
        The result is stored as ``BridgeNode.column_no`` (0-based).

        Only nodes with valid bounding boxes are assigned; nodes without
        geometry keep ``column_no = 0``.
        """
        valid = [n for n in page_nodes if n.norm_left != float("inf") and n.norm_right > 0.0]
        if not valid:
            return

        ordered = sorted(valid, key=lambda n: (n.norm_left, n.norm_top))
        current_max_right = -float("inf")
        column_starts: list[float] = [ordered[0].norm_left]
        for node in ordered:
            if current_max_right != -float("inf") and (
                node.norm_left - current_max_right > gap_threshold
            ):
                column_starts.append(node.norm_left)
            current_max_right = max(current_max_right, node.norm_right)

        for node in valid:
            column_no = 0
            for start in column_starts[1:]:
                if node.norm_left >= start - 1e-9:
                    column_no += 1
            node.column_no = min(column_no, num_columns - 1)

    def _process_image_item(self, node: BridgeNode, doc_item: Any) -> None:
        """Extract a raw PIL.Image from a Docling picture/figure item and attach it to the node."""
        image_obj: Any = None

        if hasattr(doc_item, "get_image"):
            try:
                image_obj = doc_item.get_image(self.docling_doc)
            except Exception:  # noqa: BLE001
                image_obj = getattr(doc_item, "image", None)
        else:
            image_obj = getattr(doc_item, "image", None)

        if image_obj is not None:
            node.is_image = True
            node.image_pil = image_obj
            node.image_width = int(getattr(image_obj, "width", 0) or 0)
            node.image_height = int(getattr(image_obj, "height", 0) or 0)
            fmt = str(getattr(image_obj, "format", None) or "PNG").upper()
            node.image_format = fmt if fmt in {"JPEG", "PNG", "WEBP"} else "PNG"

    def _extract_fitz_fallback_images(self, all_nodes: list[BridgeNode]) -> None:
        """Recover embedded raster images PyMuPDF sees that Docling's layout
        model failed to classify as picture regions.

        Only image rects not already covered by a Docling picture node are
        emitted, so normal detections are never duplicated.
        """
        if self.fitz_doc is None:
            return

        import fitz  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        existing_pictures = [
            node for node in all_nodes if node.label.lower() in {"picture", "figure", "image"}
        ]

        for page_no, pdf_page in enumerate(self.fitz_doc, start=1):
            page_w = float(pdf_page.rect.width)
            page_h = float(pdf_page.rect.height)
            if page_w <= 0.0 or page_h <= 0.0:
                continue

            for image_info in pdf_page.get_images(full=True):
                xref = int(image_info[0])
                for raw_rect in pdf_page.get_image_rects(xref):
                    rect = fitz.Rect(raw_rect)
                    norm = (
                        rect.x0 / page_w,
                        rect.y0 / page_h,
                        rect.x1 / page_w,
                        rect.y1 / page_h,
                    )
                    if (norm[2] - norm[0]) * (norm[3] - norm[1]) <= 0.0:
                        continue
                    if self._covered_by_picture(norm, existing_pictures):
                        continue

                    try:
                        pix = pdf_page.get_pixmap(clip=rect)
                        pil_image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    except Exception:  # noqa: BLE001 - skip undecodable raster
                        continue
                    pil_image.format = "PNG"

                    node = BridgeNode(
                        self_ref=None,
                        parent_cref=None,
                        level=1,
                        label="picture",
                        name="PictureItem",
                        text="",
                        page_no=page_no,
                        norm_top=norm[1],
                        norm_left=norm[0],
                        norm_bottom=norm[3],
                        norm_right=norm[2],
                        is_synthetic=True,
                        is_image=True,
                        image_pil=pil_image,
                        image_format="PNG",
                        image_width=pix.width,
                        image_height=pix.height,
                        metadata={
                            "role": "AI-synthetic_picture",
                            "image_source": "fitz_fallback",
                            "xref": xref,
                        },
                    )
                    self.nodes_by_id[node.id] = node
                    all_nodes.append(node)
                    existing_pictures.append(node)

    @staticmethod
    def _covered_by_picture(
        norm_rect: tuple[float, float, float, float],
        picture_nodes: list[BridgeNode],
        overlap_threshold: float = 0.5,
    ) -> bool:
        """Return True when an existing picture node covers most of ``norm_rect``."""
        left, top, right, bottom = norm_rect
        rect_area = (right - left) * (bottom - top)
        if rect_area <= 0.0:
            return True
        for picture in picture_nodes:
            p_left = picture.norm_left
            p_top = picture.norm_top
            p_right = picture.norm_right
            p_bottom = picture.norm_bottom
            if p_left == float("inf") or p_right == 0.0:
                continue
            inter_left = max(left, p_left)
            inter_top = max(top, p_top)
            inter_right = min(right, p_right)
            inter_bottom = min(bottom, p_bottom)
            if inter_right <= inter_left or inter_bottom <= inter_top:
                continue
            inter_area = (inter_right - inter_left) * (inter_bottom - inter_top)
            if inter_area / rect_area >= overlap_threshold:
                return True
        return False

    def _extract_table_cell_nodes(self, root: BridgeNode) -> None:
        tables = getattr(self.docling_doc, "tables", None)
        if not tables:
            return

        for idx, table in enumerate(tables):
            table_ref_raw = getattr(table, "self_ref", None) or f"#/tables/{idx}"
            table_ref = _canonicalize_ref(str(table_ref_raw), self.body_ref)
            table_node = self._get_or_create_ref_node(table_ref, root)

            if not (hasattr(table, "data") and hasattr(table.data, "table_cells")):
                continue
            table_cells = table.data.table_cells
            if not table_cells:
                continue

            rows_dict: dict[int, list[Any]] = {}
            for cell in table_cells:
                # Docling table cells expose row_offset_idx (or fall back to
                # start_row_offset_idx)
                row_idx = int(
                    getattr(
                        cell,
                        "row_offset_idx",
                        getattr(cell, "start_row_offset_idx", 0),
                    )
                    or 0
                )
                rows_dict.setdefault(row_idx, []).append(cell)

            for row_idx in sorted(rows_dict.keys()):
                row_cells = rows_dict[row_idx]
                # Sort cells within the row left-to-right by column index
                row_cells.sort(
                    key=lambda cell: int(
                        getattr(
                            cell,
                            "col_offset_idx",
                            getattr(cell, "start_col_offset_idx", 0),
                        )
                        or 0
                    )
                )

                row_ref = f"{table_ref}/rows/{row_idx}"
                row_node = BridgeNode(
                    self_ref=row_ref,
                    parent_cref=table_ref,
                    level=table_node.level + 1,
                    label="AI-TABLE_ROW",
                    name="TableRowContainer",
                    is_synthetic=True,
                    metadata={
                        "role": "AI-table_row",
                        "table_row_index": row_idx,
                        "docling_self_ref": row_ref,
                    },
                )
                row_node.parent_id = table_node.id
                self.nodes_by_id[row_node.id] = row_node
                self.ref_to_node[row_ref] = row_node
                table_node.children.append(row_node)

                for cell in row_cells:
                    col_idx = int(
                        getattr(
                            cell,
                            "col_offset_idx",
                            getattr(cell, "start_col_offset_idx", 0),
                        )
                        or 0
                    )
                    cell_ref = f"{row_ref}/cells/{col_idx}"
                    cell_text = str(getattr(cell, "text", "") or "").strip()
                    cell_node = BridgeNode(
                        docling_item=cell,
                        self_ref=cell_ref,
                        parent_cref=row_ref,
                        level=row_node.level + 1,
                        label="AI-TABLE_CELL",
                        name="TableCell",
                        text=cell_text,
                        metadata={
                            "role": "AI-table_cell",
                            "table_row_index": row_idx,
                            "table_col_index": col_idx,
                            "row_span": int(getattr(cell, "row_span", 1) or 1),
                            "col_span": int(getattr(cell, "col_span", 1) or 1),
                            "is_header": bool(getattr(cell, "column_header", False)),
                            "docling_self_ref": cell_ref,
                        },
                    )
                    cell_node.column_no = col_idx

                    if hasattr(cell, "prov") and cell.prov:
                        prov = cell.prov[0]
                        cell_node.page_no = int(getattr(prov, "page_no", 0) or 0)
                    elif hasattr(cell, "bbox"):
                        prov = cell
                        cell_node.page_no = int(getattr(cell, "page_no", 0) or 0)
                    else:
                        prov = None

                    if prov is not None:
                        if cell_node.page_no <= 0:
                            cell_node.page_no = table_node.page_no or 1
                        if self.fitz_doc is not None and cell_node.page_no > 0:
                            pdf_page = self.fitz_doc[cell_node.page_no - 1]
                            (
                                cell_node.norm_top,
                                cell_node.norm_left,
                                cell_node.norm_bottom,
                                cell_node.norm_right,
                            ) = _normalize_docling_bbox(
                                prov,
                                float(pdf_page.rect.height),
                                float(pdf_page.rect.width),
                            )

                    if cell_node.page_no <= 0:
                        cell_node.page_no = table_node.page_no or 1

                    self._apply_style_from_cache(cell_node)

                    cell_node.parent_id = row_node.id
                    row_node.children.append(cell_node)
                    self.nodes_by_id[cell_node.id] = cell_node
                    self.ref_to_node[cell_ref] = cell_node

    def _attach_parent_child(self, all_nodes: list[BridgeNode], root: BridgeNode) -> None:
        for node in all_nodes:
            parent_ref_raw = node.parent_cref or self.body_ref
            parent_ref = _canonicalize_ref(parent_ref_raw, self.body_ref)

            if node.self_ref is not None:
                self_ref = _canonicalize_ref(node.self_ref, self.body_ref)
                if self_ref == parent_ref:
                    parent_ref = self.body_ref

            parent_node = (
                root
                if parent_ref == self.body_ref
                else self._get_or_create_ref_node(parent_ref, root)
            )
            if parent_node.id == node.id:
                parent_node = root

            node.parent_id = parent_node.id
            if node not in parent_node.children:
                parent_node.children.append(node)

    def _propagate_bounds(self, node: BridgeNode) -> None:
        if not node.children:
            return

        for child in node.children:
            self._propagate_bounds(child)
            if child.page_no > 0:
                node.page_no = (
                    child.page_no if node.page_no == 0 else min(node.page_no, child.page_no)
                )
                node.norm_top = min(node.norm_top, child.norm_top)
                node.norm_left = min(node.norm_left, child.norm_left)
                node.norm_bottom = max(node.norm_bottom, child.norm_bottom)
                node.norm_right = max(node.norm_right, child.norm_right)

    def _sort_tree_spatially(self, node: BridgeNode) -> None:
        """Sort children by reading order: page → column → y-top → x-left.

        Uses the dynamically assigned ``column_no`` field rather than a
        fixed column-tolerance bucket.  This avoids the misplacement of
        figures that occurred when ``norm_left`` varied slightly across
        columns causing nodes to fall into the wrong rigid bucket.
        """
        if not node.children:
            return

        def sort_key(child: BridgeNode) -> tuple[int, int, float, float]:
            page_no = child.page_no if child.page_no > 0 else 10**9
            top = child.norm_top if child.norm_top != float("inf") else 0.0
            left = child.norm_left if child.norm_left != float("inf") else 0.0

            is_table_context = child.label in ["TABLE", "TABLE_ROW", "TABLE_CELL"] or (
                child.label in ["TABLE", "TABLE_ROW"]
            )
            if is_table_context:
                return (page_no, top, child.column_no, left)
            else:
                return (page_no, child.column_no, top, left)

        node.children.sort(key=sort_key)
        for child in node.children:
            self._sort_tree_spatially(child)


def compute_bbox_overlap_ratio(box1: list[float], box2: Any) -> float:
    """Compatibility helper retained for tests/import stability."""
    try:
        import fitz  # noqa: PLC0415

        rect1 = fitz.Rect(box1[0], box1[1], box1[2], box1[3])
        area = rect1.get_area()
        if area == 0:
            return 0.0
        intersection = rect1.intersect(box2)
        if intersection.is_empty:
            return 0.0
        return float(intersection.get_area() / area)
    except Exception:
        return 0.0
