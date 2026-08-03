"""PyMuPDF layout extraction for hybrid PDF parsing.

This module provides a deterministic, typed representation of PDF text layout
that preserves span geometry and typography. The hybrid parser uses this as
the primary source of text fidelity and reading order.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import pymupdf


@dataclass(frozen=True)
class LayoutBBox:
    """Rectangle coordinates in PDF points (top-left origin)."""

    left: float
    top: float
    right: float
    bottom: float
    page_width: float
    page_height: float

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.bottom - self.top)


@dataclass(frozen=True)
class LayoutFontSpec:
    """Span-level font and style characteristics."""

    name: str
    size: float
    color: str
    is_bold: bool
    is_italic: bool
    is_underline: bool
    is_monospace: bool


@dataclass(frozen=True)
class LayoutSpan:
    """A single styled span of text extracted by PyMuPDF."""

    span_id: str
    page_number: int
    order: int
    block_index: int
    line_index: int
    span_index: int
    text: str
    bbox: LayoutBBox
    font: LayoutFontSpec


@dataclass(frozen=True)
class LayoutLine:
    """A logical line composed of one or more spans."""

    line_id: str
    page_number: int
    order: int
    block_index: int
    line_index: int
    text: str
    bbox: LayoutBBox
    spans: tuple[LayoutSpan, ...]


@dataclass(frozen=True)
class LayoutPage:
    """All extracted layout content for a single page."""

    page_number: int
    width: float
    height: float
    lines: tuple[LayoutLine, ...]


@dataclass(frozen=True)
class LayoutDocument:
    """Full multi-page PyMuPDF layout extraction result."""

    source: str
    pages: tuple[LayoutPage, ...]


def _rgb_to_hex(color_int: int | None) -> str:
    if color_int is None:
        return "#000000"
    red = (color_int >> 16) & 0xFF
    green = (color_int >> 8) & 0xFF
    blue = color_int & 0xFF
    return f"#{red:02x}{green:02x}{blue:02x}"


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_dict(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _span_text(span: dict[str, object]) -> str:
    text_raw = span.get("text")
    if isinstance(text_raw, str) and text_raw:
        return text_raw

    chars_raw = span.get("chars")
    if not isinstance(chars_raw, list):
        return ""

    chars: list[str] = []
    for item in chars_raw:
        if not isinstance(item, dict):
            continue
        char = item.get("c")
        if isinstance(char, str):
            chars.append(char)
    return "".join(chars)


def _to_bbox(
    bbox: object,
    *,
    page_width: float,
    page_height: float,
) -> LayoutBBox:
    values = bbox if isinstance(bbox, (list, tuple)) else []
    if len(values) != 4:
        return LayoutBBox(
            left=0.0,
            top=0.0,
            right=0.0,
            bottom=0.0,
            page_width=page_width,
            page_height=page_height,
        )
    left_raw, top_raw, right_raw, bottom_raw = (
        float(values[0]),
        float(values[1]),
        float(values[2]),
        float(values[3]),
    )

    left = min(left_raw, right_raw)
    right = max(left_raw, right_raw)
    top = min(top_raw, bottom_raw)
    bottom = max(top_raw, bottom_raw)

    return LayoutBBox(
        left=round(left, 4),
        top=round(top, 4),
        right=round(right, 4),
        bottom=round(bottom, 4),
        page_width=page_width,
        page_height=page_height,
    )


class PyMuPDFLayoutExtractor:
    """Extract page-aware span/line layout using PyMuPDF."""

    def extract(self, source: str) -> LayoutDocument:
        pages: list[LayoutPage] = []
        with pymupdf.open(source) as pdf:
            for page_index in range(len(pdf)):
                page_number = page_index + 1
                page = pdf[page_index]
                page_rect = page.rect
                page_width = float(page_rect.width)
                page_height = float(page_rect.height)

                lines: list[LayoutLine] = []
                line_order = 0
                raw_data = page.get_text("rawdict", sort=True)
                blocks_raw = raw_data.get("blocks") if isinstance(raw_data, dict) else []
                blocks = blocks_raw if isinstance(blocks_raw, list) else []

                for block_index, block in enumerate(blocks):
                    if not isinstance(block, dict):
                        continue
                    if int(block.get("type", -1)) != 0:
                        continue

                    block_lines_raw = block.get("lines")
                    block_lines = block_lines_raw if isinstance(block_lines_raw, list) else []

                    for local_line_index, line in enumerate(block_lines):
                        if not isinstance(line, dict):
                            continue

                        spans_raw = line.get("spans")
                        spans_source = spans_raw if isinstance(spans_raw, list) else []
                        line_spans: list[LayoutSpan] = []

                        for span_index, span in enumerate(spans_source):
                            span_dict = _as_dict(span)
                            if span_dict is None:
                                continue

                            text = _span_text(span_dict)
                            if not text:
                                continue

                            span_bbox = _to_bbox(
                                span_dict.get("bbox"),
                                page_width=page_width,
                                page_height=page_height,
                            )

                            flags = _safe_int(span_dict.get("flags", 0), 0)
                            char_flags = _safe_int(span_dict.get("char_flags", 0), 0)
                            font_name = str(span_dict.get("font") or "")
                            font_size = round(float(span_dict.get("size", 0.0) or 0.0), 4)
                            color_raw = span_dict.get("color")
                            color_value = (
                                _safe_int(color_raw, 0) if color_raw is not None else None
                            )
                            font_color = _rgb_to_hex(color_value)

                            span_id = _stable_id(
                                source,
                                page_number,
                                block_index,
                                local_line_index,
                                span_index,
                                span_bbox.left,
                                span_bbox.top,
                                span_bbox.right,
                                span_bbox.bottom,
                                text,
                            )

                            line_spans.append(
                                LayoutSpan(
                                    span_id=span_id,
                                    page_number=page_number,
                                    order=line_order,
                                    block_index=block_index,
                                    line_index=local_line_index,
                                    span_index=span_index,
                                    text=text,
                                    bbox=span_bbox,
                                    font=LayoutFontSpec(
                                        name=font_name,
                                        size=font_size,
                                        color=font_color,
                                        is_bold=bool(flags & (2**4)),
                                        is_italic=bool(flags & (2**1)),
                                        is_underline=bool(char_flags & (2**1)),
                                        is_monospace=bool(flags & (2**3)),
                                    ),
                                )
                            )

                        if not line_spans:
                            continue

                        line_text = "".join(span.text for span in line_spans)
                        line_text = " ".join(line_text.split())
                        if not line_text:
                            continue

                        line_bbox = _to_bbox(
                            line.get("bbox"),
                            page_width=page_width,
                            page_height=page_height,
                        )
                        line_id = _stable_id(
                            source,
                            page_number,
                            block_index,
                            local_line_index,
                            line_bbox.left,
                            line_bbox.top,
                            line_bbox.right,
                            line_bbox.bottom,
                            line_text,
                        )
                        lines.append(
                            LayoutLine(
                                line_id=line_id,
                                page_number=page_number,
                                order=line_order,
                                block_index=block_index,
                                line_index=local_line_index,
                                text=line_text,
                                bbox=line_bbox,
                                spans=tuple(line_spans),
                            )
                        )
                        line_order += 1

                pages.append(
                    LayoutPage(
                        page_number=page_number,
                        width=page_width,
                        height=page_height,
                        lines=tuple(lines),
                    )
                )

        return LayoutDocument(source=source, pages=tuple(pages))
