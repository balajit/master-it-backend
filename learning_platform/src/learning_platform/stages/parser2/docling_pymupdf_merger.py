"""Docling + PyMuPDF merger — correlates Docling structure with PyMuPDF typography.

This module provides the correlation engine that enriches Docling's semantic
structure with PyMuPDF's low-level font metrics and vector graphics data.

The ``DoclingPyMuPDFMerger`` class runs both parsers and spatially correlates
their outputs using bounding box overlap. The result is a list of
``CorrelatedItem`` objects that carry both semantic structure (from Docling)
and visual styling (from PyMuPDF).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

_LOG = logging.getLogger(__name__)


class CorrelatedItem:
    """Wraps a Docling item with PyMuPDF-derived typography and vector-line data.

    Attributes
    ----------
    docling_item : Any
        The raw Docling item object.
    level : int
        Hierarchy depth from Docling's iterate_items.
    self_ref : str | None
        Docling's self-reference identifier.
    label : str
        Docling's semantic label (e.g., "paragraph", "section_header").
    text : str
        Extracted text content.
    parent_cref : str | None
        Parent's correlation reference for tree building.
    page_no : int
        1-indexed page number from provenance.
    bbox : list[float] | None
        Bounding box [l, t, r, b] from Docling provenance.
    fonts : list[dict]
        All PyMuPDF spans that overlap this item.
    primary_font_name : str | None
        Dominant font name from first matching span.
    primary_font_size : float | None
        Dominant font size in points.
    primary_color_hex : str | None
        Dominant color as hex string (e.g., "#000000").
    is_bold : bool
        True if any matching span is bold.
    is_italic : bool
        True if any matching span is italic.
    vector_lines : list[dict]
        Horizontal vector lines sitting directly below this item.
    """

    def __init__(self, docling_item: Any, level: int) -> None:
        self.docling_item: Any = docling_item
        self.level: int = level
        self.self_ref: str | None = getattr(docling_item, "self_ref", None) or None
        self.label: str = self._extract_label(docling_item)
        self.text: str = (getattr(docling_item, "text", "") or "").strip()

        # Parent reference for tree building
        _parent = getattr(docling_item, "parent", None)
        self.parent_cref: str | None = (
            getattr(_parent, "cref", None) if _parent is not None else None
        )

        # Page and bbox from provenance
        self.page_no: int = 0
        self.bbox: list[float] | None = None
        prov_list = getattr(docling_item, "prov", None)
        if prov_list:
            prov = prov_list[0]
            self.page_no = int(getattr(prov, "page_no", 0) or 0)
            raw_bbox = getattr(prov, "bbox", None)
            if raw_bbox is not None:
                self.bbox = [
                    float(getattr(raw_bbox, "l", 0.0)),
                    float(getattr(raw_bbox, "t", 0.0)),
                    float(getattr(raw_bbox, "r", 0.0)),
                    float(getattr(raw_bbox, "b", 0.0)),
                ]

        # PyMuPDF correlated typography (populated by merger)
        self.fonts: list[dict[str, Any]] = []
        self.primary_font_name: str | None = None
        self.primary_font_size: float | None = None
        self.primary_color_hex: str | None = None
        self.is_bold: bool = False
        self.is_italic: bool = False

        # Vector answer-blank lines sitting directly below this item
        self.vector_lines: list[dict[str, Any]] = []

    @staticmethod
    def _extract_label(docling_item: Any) -> str:
        """Extract label value as string from Docling item."""
        label = getattr(docling_item, "label", None)
        if label is None:
            return type(docling_item).__name__
        return getattr(label, "value", str(label))

    def __repr__(self) -> str:
        font_part = (
            f" | Font: {self.primary_font_name}, {self.primary_font_size}pt"
            if self.primary_font_name
            else ""
        )
        lines_part = f" | Lines: {len(self.vector_lines)}" if self.vector_lines else ""
        preview = self.text[:35]
        return f"<CorrelatedItem [{self.label}] '{preview}...'{font_part}{lines_part}>"


def compute_bbox_overlap_ratio(box1: Sequence[float], box2: Any) -> float:
    """Return the fraction of *box1* area covered by *box2*.

    Parameters
    ----------
    box1 : Sequence[float]
        Bounding box [l, t, r, b] in Docling coordinate space.
    box2 : fitz.Rect
        PyMuPDF Rect in the same coordinate space.

    Returns
    -------
    float
        Overlap ratio in [0.0, 1.0]. Returns 0.0 on any error.
    """
    try:
        import fitz  # noqa: PLC0415

        rect1 = fitz.Rect(box1[0], box1[1], box1[2], box1[3])
        rect1_area = rect1.get_area()
        if rect1_area == 0:
            return 0.0
        # intersect() modifies rect1 in place, so get area first
        intersection = rect1.intersect(box2)
        if intersection.is_empty:
            return 0.0
        return float(intersection.get_area() / rect1_area)
    except Exception:
        return 0.0


class DoclingPyMuPDFMerger:
    """Merges Docling semantic structure with PyMuPDF typography and vector graphics.

    This class runs Docling conversion, opens the PDF with PyMuPDF, and
    spatially correlates items from both sources. The result is a list of
    ``CorrelatedItem`` objects enriched with font metrics and vector-line data.

    Parameters
    ----------
    source : str
        Path to the PDF file.

    Attributes
    ----------
    docling_doc : object
        The Docling document after conversion.
    fitz_doc : fitz.Document | None
        The PyMuPDF document (None for non-PDF files).
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self._is_pdf = source.lower().endswith(".pdf")

        # Step A: Run Docling conversion
        _LOG.info("DoclingPyMuPDFMerger: Running Docling conversion for %s", source)
        from docling.document_converter import DocumentConverter  # noqa: PLC0415

        converter = DocumentConverter()
        result = converter.convert(source)
        self.docling_doc = result.document

        # Step B: Open PyMuPDF document (PDF only)
        self.fitz_doc: Any = None
        if self._is_pdf:
            try:
                import fitz  # noqa: PLC0415

                self.fitz_doc = fitz.open(source)
            except Exception as exc:
                _LOG.warning("Failed to open PDF with PyMuPDF: %s", exc)

    def close(self) -> None:
        """Close the PyMuPDF document if open."""
        if self.fitz_doc is not None:
            import contextlib

            with contextlib.suppress(Exception):
                self.fitz_doc.close()
            self.fitz_doc = None

    def __enter__(self) -> DoclingPyMuPDFMerger:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def correlate(self) -> list[CorrelatedItem]:
        """Iterate Docling items and enrich each with PyMuPDF data.

        Returns
        -------
        list[CorrelatedItem]
            List of correlated items with font and vector-line enrichment.
        """
        correlated_items: list[CorrelatedItem] = []

        # Cache PyMuPDF data per page to avoid redundant extraction
        page_cache: dict[int, dict[str, Any]] = {}

        try:
            items_with_levels = list(self.docling_doc.iterate_items(with_groups=True))
        except (AttributeError, TypeError) as exc:
            _LOG.warning("DoclingDocument does not support iterate_items: %s", exc)
            return []

        for doc_item, level in items_with_levels:
            item_wrapper = CorrelatedItem(doc_item, level)

            # Only correlate if we have a PDF and valid bbox
            if self.fitz_doc is not None and item_wrapper.bbox and item_wrapper.page_no > 0:
                page_no = item_wrapper.page_no
                docling_bbox = item_wrapper.bbox

                # Fetch or extract PyMuPDF page data
                if page_no not in page_cache:
                    try:
                        page_cache[page_no] = self._extract_pymupdf_page_data(page_no)
                    except Exception as exc:
                        _LOG.debug("PyMuPDF extraction failed for page %d: %s", page_no, exc)
                        page_cache[page_no] = {"spans": [], "vector_lines": []}

                pymupdf_data = page_cache[page_no]

                # Correlate spans (fonts/formatting)
                matching_spans = [
                    s
                    for s in pymupdf_data["spans"]
                    if compute_bbox_overlap_ratio(docling_bbox, s["rect"]) > 0.3
                ]
                if matching_spans:
                    item_wrapper.fonts = matching_spans
                    item_wrapper.primary_font_name = str(matching_spans[0]["font"])
                    item_wrapper.primary_font_size = float(matching_spans[0]["size"])
                    item_wrapper.primary_color_hex = str(matching_spans[0]["color"])
                    item_wrapper.is_bold = any(s["is_bold"] for s in matching_spans)
                    item_wrapper.is_italic = any(s["is_italic"] for s in matching_spans)

                # Correlate horizontal vector rules sitting directly below
                item_bottom_y = docling_bbox[3]
                for v_line in pymupdf_data["vector_lines"]:
                    gap = v_line["top"] - item_bottom_y
                    if 0.0 <= gap <= 15.0:
                        vr = v_line["rect"]
                        # Require horizontal overlap with item bbox
                        if not (vr.x1 < docling_bbox[0] or vr.x0 > docling_bbox[2]):
                            item_wrapper.vector_lines.append(v_line)

            correlated_items.append(item_wrapper)

        return correlated_items

    def _extract_pymupdf_page_data(self, page_num: int) -> dict[str, Any]:
        """Extract text spans and horizontal vector lines from a PyMuPDF page.

        Parameters
        ----------
        page_num : int
            1-indexed page number.

        Returns
        -------
        dict
            Dictionary with keys "spans" and "vector_lines".
        """
        import fitz  # noqa: PLC0415

        page = self.fitz_doc[page_num - 1]  # fitz is 0-indexed

        # Extract text spans with font metadata
        spans: list[dict[str, Any]] = []
        raw_dict = page.get_text("rawdict")
        for block in raw_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    spans.append(
                        {
                            "rect": fitz.Rect(span["bbox"]),
                            "text": span.get("text", ""),
                            "font": span.get("font", ""),
                            "size": round(float(span.get("size", 0.0)), 2),
                            "color": f"#{int(span.get('color', 0)):06x}",
                            "is_bold": bool(span.get("flags", 0) & (1 << 4)),
                            "is_italic": bool(span.get("flags", 0) & (1 << 1)),
                        }
                    )

        # Extract horizontal vector lines (answer blanks, rules)
        vector_lines: list[dict[str, Any]] = []
        for path in page.get_drawings():
            for item in path.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                # Keep only horizontal rules (dy < 2 pt, dx >= 20 pt)
                if abs(p1.y - p2.y) < 2.0 and abs(p1.x - p2.x) >= 20.0:
                    line_rect = fitz.Rect(
                        min(p1.x, p2.x),
                        min(p1.y, p2.y) - 2,
                        max(p1.x, p2.x),
                        max(p1.y, p2.y) + 2,
                    )
                    vector_lines.append(
                        {
                            "rect": line_rect,
                            "length": round(abs(p1.x - p2.x), 2),
                            "top": float(line_rect.y0),
                        }
                    )

        return {"spans": spans, "vector_lines": vector_lines}

    @property
    def title(self) -> str:
        """Return document title from Docling."""
        return getattr(self.docling_doc, "name", "") or ""

    @property
    def page_count(self) -> int:
        """Return page count from Docling."""
        pages = getattr(self.docling_doc, "pages", None)
        if pages is not None:
            return len(pages)
        return 0
