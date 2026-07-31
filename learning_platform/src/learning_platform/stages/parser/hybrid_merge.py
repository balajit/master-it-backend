"""Hybrid merge of PyMuPDF layout and Docling semantics.

This module aligns high-fidelity text layout lines from PyMuPDF with semantic
nodes extracted from Docling. The merge output is a canonical document root
where text comes from layout and semantics are promoted from aligned Docling
candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from learning_platform.models.document import (
    BlockStyle,
    BoundingBox,
    DocumentNode,
    Heading,
    HeadingLevel,
    InlineStyle,
    ListBlock,
    ListItem,
    ListStyle,
    Paragraph,
    Question,
    QuestionStatement,
    QuestionType,
    SourceLocation,
    StyledText,
    TableBlock,
    TableCell,
    TableRow,
    TextRun,
)
from learning_platform.stages.parser.docling_semantics import (
    SemanticExtraction,
    SemanticNodeCandidate,
)
from learning_platform.stages.parser.pymupdf_layout import LayoutDocument, LayoutLine

_HEADING_PREFIX_RE = re.compile(
    r"^(?:chapter|unit|module|part|lesson|section|topic|lab)\b",
    re.IGNORECASE,
)
_NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)[.)]\s+")
_TRUE_FALSE_INLINE_RE = re.compile(
    r"\(\s*(?:t\s*/\s*f|true\s*/\s*false|t|f)\s*\)",
    re.IGNORECASE,
)
_PROTECTED_SEMANTIC_TYPES: frozenset[str] = frozenset(
    {"table", "equation", "code_block", "figure"}
)
_LAYOUT_SEMANTIC_OVERLAP_THRESHOLD: float = 0.15
_WORD_BANK_MAX_VERTICAL_GAP: float = 30.0
_WORD_BANK_MAX_HORIZONTAL_GAP: float = 45.0
_WORD_BANK_LAYOUT_VERTICAL_PAD: float = 8.0
_WORD_BANK_ROW_CLUSTER_GAP: float = 12.0
_MARGIN_HEADING_ECHO_MAX: float = 60.0
_NUMBERED_LAYOUT_OVERLAP_THRESHOLD: float = 0.25
_NUMBERED_LAYOUT_SIMILARITY_THRESHOLD: float = 0.65


@dataclass(frozen=True)
class HybridMergeSettings:
    """Tunable scoring and fallback settings for alignment."""

    overlap_weight: float = 0.50
    distance_weight: float = 0.20
    reading_order_weight: float = 0.15
    text_similarity_weight: float = 0.15
    strict_match_threshold: float = 0.55
    relaxed_match_threshold: float = 0.35
    spatial_fallback_vertical_gap: float = 90.0


@dataclass(frozen=True)
class _ScoredCandidate:
    candidate: SemanticNodeCandidate
    score: float


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _strip_number_prefix(value: str) -> str:
    stripped = value.strip()
    numbered = _NUMBERED_ITEM_RE.match(stripped)
    if numbered is None:
        return stripped
    body = stripped[numbered.end() :].strip()
    body = _TRUE_FALSE_INLINE_RE.sub("", body).strip()
    return body or stripped


def _is_numbered_statement(value: str) -> bool:
    return _NUMBERED_ITEM_RE.match(value.strip()) is not None


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalized_text(left)
    right_norm = _normalized_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    left_words = set(left_norm.split())
    right_words = set(right_norm.split())
    if not left_words or not right_words:
        return 0.0
    intersection = len(left_words.intersection(right_words))
    union = len(left_words.union(right_words))
    if union <= 0:
        return 0.0
    return intersection / union


def _overlap_ratio(
    left_box: tuple[float, float, float, float],
    right_box: tuple[float, float, float, float],
) -> float:
    left_l, left_t, left_r, left_b = left_box
    right_l, right_t, right_r, right_b = right_box

    intersect_l = max(left_l, right_l)
    intersect_t = max(left_t, right_t)
    intersect_r = min(left_r, right_r)
    intersect_b = min(left_b, right_b)

    if intersect_r <= intersect_l or intersect_b <= intersect_t:
        return 0.0

    overlap_area = (intersect_r - intersect_l) * (intersect_b - intersect_t)
    left_area = max(0.0, (left_r - left_l) * (left_b - left_t))
    right_area = max(0.0, (right_r - right_l) * (right_b - right_t))
    if left_area <= 0.0 or right_area <= 0.0:
        return 0.0
    return overlap_area / min(left_area, right_area)


def _distance_score(
    left_box: tuple[float, float, float, float],
    right_box: tuple[float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> float:
    left_l, left_t, left_r, left_b = left_box
    right_l, right_t, right_r, right_b = right_box

    left_cx = (left_l + left_r) / 2.0
    left_cy = (left_t + left_b) / 2.0
    right_cx = (right_l + right_r) / 2.0
    right_cy = (right_t + right_b) / 2.0

    dx = abs(left_cx - right_cx)
    dy = abs(left_cy - right_cy)
    norm_x = dx / max(1.0, page_width)
    norm_y = dy / max(1.0, page_height)
    distance = min(1.0, (norm_x + norm_y) / 2.0)
    return 1.0 - distance


def _reading_order_score(layout_order: int, semantic_order: int, max_order: int) -> float:
    delta = abs(layout_order - semantic_order)
    if max_order <= 0:
        return 1.0
    norm = min(1.0, delta / max_order)
    return 1.0 - norm


def _node_box(candidate: SemanticNodeCandidate) -> tuple[float, float, float, float]:
    return (candidate.left, candidate.top, candidate.right, candidate.bottom)


def _line_box(line: LayoutLine) -> tuple[float, float, float, float]:
    return (line.bbox.left, line.bbox.top, line.bbox.right, line.bbox.bottom)


def _line_source_location(source: str, page_number: int, line_id: str) -> SourceLocation:
    return SourceLocation(file=source, page=page_number, element_ref=f"layout:{line_id}")


def _line_block_style(line: LayoutLine) -> BlockStyle | None:
    if not line.spans:
        return None
    primary = line.spans[0]
    font = primary.font
    style = BlockStyle()
    style.font.name = font.name
    style.font.size = font.size
    style.font.color = font.color
    style.font.is_bold = font.is_bold
    style.font.is_italic = font.is_italic
    style.font.is_underline = font.is_underline
    style.metadata = {
        "layout_span_count": len(line.spans),
    }
    return style


def _line_styled_text(line: LayoutLine) -> StyledText:
    runs: list[TextRun] = []
    for span in line.spans:
        run = TextRun(text=span.text)
        run.style = InlineStyle()
        run.style.font.name = span.font.name
        run.style.font.size = span.font.size
        run.style.font.color = span.font.color
        run.style.font.is_bold = span.font.is_bold
        run.style.font.is_italic = span.font.is_italic
        run.style.font.is_underline = span.font.is_underline
        run.metadata["layout_span_id"] = span.span_id
        run.metadata["span_order"] = span.span_index
        if span.font.is_monospace:
            run.metadata["is_monospace"] = True
        runs.append(run)
    return StyledText(runs=runs)


def _label_from_candidate(candidate: SemanticNodeCandidate) -> str:
    label = candidate.metadata.get("label")
    return str(label) if isinstance(label, str) else ""


def _semantic_kind(candidate: SemanticNodeCandidate, line_text: str) -> str:
    node_type = candidate.node_type
    if node_type == "question":
        return "question"
    if node_type == "heading":
        return "heading"
    if node_type == "list":
        question_signal = str(candidate.metadata.get("question_signal", "")).strip().lower()
        if question_signal.startswith("true_false") or question_signal == "fill_in_blank":
            return "question"
        label = _label_from_candidate(candidate)
        if label.startswith("checkbox_") and _is_numbered_statement(line_text):
            return "question"
        if label == "list_item" and _looks_checkbox_statement(line_text):
            return "question"
        return "list"

    label = _label_from_candidate(candidate)
    if label.startswith("checkbox_") and _is_numbered_statement(line_text):
        return "question"
    if label in {"section_header", "title", "subtitle"}:
        return "heading"
    if label == "list_item":
        return "list"
    if _HEADING_PREFIX_RE.match(line_text.strip()):
        return "heading"
    return "paragraph"


def _metadata_for_line(
    line: LayoutLine,
    *,
    semantic_candidate: SemanticNodeCandidate | None,
    relation_heading: str | None,
    relation_method: str,
    relation_confidence: float,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "layout_line_id": line.line_id,
        "layout_block_index": line.block_index,
        "layout_line_index": line.line_index,
        "layout_span_count": len(line.spans),
        "layout_origin": "pymupdf",
        "semantic_origin": "docling",
        "relation_method": relation_method,
        "relation_confidence": round(max(0.0, min(1.0, relation_confidence)), 4),
        "question_group_id": f"page-{line.page_number}-group",
        "sequence_index": line.order,
    }
    if relation_heading:
        metadata["resolved_section_heading"] = relation_heading
    if semantic_candidate is not None:
        if semantic_candidate.metadata:
            metadata.update(semantic_candidate.metadata)
        metadata["resolved_parent_ref"] = semantic_candidate.metadata.get("docling_parent_ref", "")
        metadata["semantic_node_type"] = semantic_candidate.node_type
        metadata["semantic_match_score"] = round(relation_confidence, 4)
    return metadata


def _looks_checkbox_statement(line_text: str) -> bool:
    stripped = line_text.strip()
    if not stripped:
        return False
    numbered = _NUMBERED_ITEM_RE.match(stripped)
    if numbered is None:
        return False
    if _TRUE_FALSE_INLINE_RE.search(stripped):
        return True
    body = stripped[numbered.end() :].strip()
    if not body:
        return False
    token_count = len(re.findall(r"[A-Za-z0-9]+", body))
    return token_count >= 5


class HybridMergeEngine:
    """Align PyMuPDF layout lines with Docling semantic nodes."""

    def __init__(self, settings: HybridMergeSettings | None = None) -> None:
        self._settings = settings or HybridMergeSettings()

    def merge(
        self,
        *,
        source: str,
        layout_doc: LayoutDocument,
        semantics: SemanticExtraction,
    ) -> DocumentNode:
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={"role": "document_root"},
        )

        candidates_by_page: dict[int, list[SemanticNodeCandidate]] = {}
        for candidate in semantics.candidates:
            candidates_by_page.setdefault(candidate.page_number, []).append(candidate)

        for page in layout_doc.pages:
            page_candidates = sorted(
                candidates_by_page.get(page.page_number, []),
                key=lambda candidate: (
                    candidate.order,
                    candidate.top,
                    candidate.left,
                ),
            )
            page_headings = [
                candidate
                for candidate in page_candidates
                if candidate.node_type == "heading" and candidate.text.strip()
            ]
            replaced_by_numbered_layout = self._select_numbered_layout_replacements(
                page_candidates=page_candidates,
                page_lines=page.lines,
            )

            word_bank_candidates = self._group_word_bank_candidates(page_candidates)
            consumed_candidate_ids = {
                candidate.node.id for group in word_bank_candidates for candidate in group
            }

            table_nodes = [
                self._build_word_bank_table_node(
                    source=source,
                    page_number=page.page_number,
                    group=group,
                    page_lines=page.lines,
                    page_headings=page_headings,
                )
                for group in word_bank_candidates
                if group
            ]
            for table_node in table_nodes:
                table_node.parent_id = root.id
                root.children.append(table_node)

            table_box_candidates = [
                self._semantic_candidate_from_node(node) for node in table_nodes
            ]

            emittable_candidates = [
                candidate
                for candidate in page_candidates
                if candidate.node.id not in consumed_candidate_ids
                and candidate.node.id not in replaced_by_numbered_layout
                and self._candidate_should_emit(candidate)
                and not self._is_margin_heading_echo_candidate(candidate, page_headings)
            ]

            for candidate in emittable_candidates:
                semantic_node = self._build_semantic_node(
                    source=source,
                    candidate=candidate,
                    page_number=page.page_number,
                    page_headings=page_headings,
                )
                semantic_node.parent_id = root.id
                root.children.append(semantic_node)

            for line in page.lines:
                matched_candidate = self._best_overlap_candidate_for_line(
                    line=line,
                    candidates=page_candidates,
                )
                if self._line_overlaps_semantic_candidates(
                    line=line,
                    candidates=[*emittable_candidates, *table_box_candidates],
                ):
                    continue

                relation_heading, relation_method, relation_confidence = self._resolve_relation(
                    line=line,
                    matched=matched_candidate,
                    page_headings=page_headings,
                )
                semantic_kind = (
                    _semantic_kind(matched_candidate, line.text)
                    if matched_candidate is not None
                    else "paragraph"
                )
                fallback_node = self._build_node(
                    source=source,
                    line=line,
                    semantic_kind=semantic_kind,
                    semantic_candidate=matched_candidate,
                    relation_heading=relation_heading,
                    relation_method=relation_method,
                    relation_confidence=relation_confidence,
                )
                fallback_node.parent_id = root.id
                root.children.append(fallback_node)

        root.children.sort(key=lambda node: (node.page, node.seq, node.bbox.y, node.bbox.x))

        return root

    def _group_word_bank_candidates(
        self,
        page_candidates: list[SemanticNodeCandidate],
    ) -> list[list[SemanticNodeCandidate]]:
        ranked = sorted(
            [
                candidate
                for candidate in page_candidates
                if candidate.node_type == "paragraph"
                and str(candidate.metadata.get("label", "")) == "text"
                and self._is_word_bank_phrase(candidate.text)
            ],
            key=lambda candidate: (candidate.top, candidate.left),
        )

        groups: list[list[SemanticNodeCandidate]] = []
        for candidate in ranked:
            if not groups:
                groups.append([candidate])
                continue

            current = groups[-1]
            previous = current[-1]
            same_row = abs(candidate.top - previous.top) <= _WORD_BANK_MAX_VERTICAL_GAP
            nearby_column = (
                candidate.left >= previous.left
                and (candidate.left - previous.right) <= _WORD_BANK_MAX_HORIZONTAL_GAP
            )
            stacked_row = (
                candidate.top > previous.top
                and (candidate.top - previous.bottom) <= _WORD_BANK_MAX_VERTICAL_GAP
            )

            if same_row and nearby_column:
                current.append(candidate)
                continue
            if stacked_row and len(current) >= 2:
                current.append(candidate)
                continue

            groups.append([candidate])

        return [group for group in groups if len(group) >= 4]

    @staticmethod
    def _is_word_bank_phrase(text: str) -> bool:
        normalized = _normalized_text(text)
        if not normalized:
            return False
        if len(normalized) > 40:
            return False
        if any(char.isdigit() for char in normalized):
            return False
        if "." in normalized:
            return False
        words = normalized.split()
        return 1 <= len(words) <= 3

    def _build_word_bank_table_node(
        self,
        *,
        source: str,
        page_number: int,
        group: list[SemanticNodeCandidate],
        page_lines: tuple[LayoutLine, ...],
        page_headings: list[SemanticNodeCandidate],
    ) -> DocumentNode:
        rows = self._word_bank_rows(group, page_lines=page_lines)
        table_rows: list[TableRow] = []
        max_columns = max((len(row) for row in rows), default=0)
        for row in rows:
            cells: list[TableCell] = []
            for value in row:
                cells.append(TableCell(content=[TextRun(text=value)]))
            for _ in range(max_columns - len(cells)):
                cells.append(TableCell(content=[TextRun(text="")]))
            table_rows.append(TableRow(cells=cells, is_header=False))

        min_left = min(candidate.left for candidate in group)
        min_top = min(candidate.top for candidate in group)
        max_right = max(candidate.right for candidate in group)
        max_bottom = max(candidate.bottom for candidate in group)

        reference = group[0]
        node = DocumentNode(
            id=uuid4(),
            content=TableBlock(
                rows=table_rows,
                headers=[],
                row_count=len(table_rows),
                column_count=max_columns,
                metadata={
                    "semantic_origin": "docling",
                    "table_inference": "word_bank",
                    "boundary_preserved": True,
                },
            ),
            page=page_number,
            seq=max(0, int(reference.order)),
            source=SourceLocation(
                file=source,
                page=page_number,
                element_ref=f"semantic-word-bank:{reference.node.id}",
            ),
            bbox=BoundingBox(
                x=float(min_left),
                y=float(min_top),
                width=max(0.0, float(max_right - min_left)),
                height=max(0.0, float(max_bottom - min_top)),
            ),
            metadata={
                "label": "word_bank_table",
                "semantic_origin": "docling",
                "boundary_preserved": True,
                "semantic_only": True,
                "semantic_node_type": "table",
            },
        )

        relation_heading, relation_method, relation_confidence = (
            self._resolve_relation_for_candidate(
                candidate=reference,
                page_headings=page_headings,
            )
        )
        node.metadata["relation_method"] = relation_method
        node.metadata["relation_confidence"] = round(
            max(0.0, min(1.0, relation_confidence)),
            4,
        )
        if relation_heading:
            node.metadata["resolved_section_heading"] = relation_heading
        return node

    def _word_bank_rows(
        self,
        group: list[SemanticNodeCandidate],
        *,
        page_lines: tuple[LayoutLine, ...],
    ) -> list[list[str]]:
        layout_rows = self._word_bank_rows_from_layout(group, page_lines=page_lines)
        if layout_rows:
            return layout_rows

        by_row: list[list[SemanticNodeCandidate]] = []
        sorted_group = sorted(group, key=lambda candidate: (candidate.top, candidate.left))
        for candidate in sorted_group:
            if not by_row:
                by_row.append([candidate])
                continue

            row = by_row[-1]
            if abs(candidate.top - row[0].top) <= _WORD_BANK_MAX_VERTICAL_GAP:
                row.append(candidate)
                continue
            by_row.append([candidate])

        return [
            [candidate.text.strip() for candidate in sorted(row, key=lambda item: item.left)]
            for row in by_row
        ]

    def _word_bank_rows_from_layout(
        self,
        group: list[SemanticNodeCandidate],
        *,
        page_lines: tuple[LayoutLine, ...],
    ) -> list[list[str]]:
        min_left = min(candidate.left for candidate in group)
        min_top = min(candidate.top for candidate in group)
        max_right = max(candidate.right for candidate in group)
        max_bottom = max(candidate.bottom for candidate in group)

        ranked_lines = sorted(page_lines, key=lambda line: (line.bbox.top, line.bbox.left))
        candidates: list[LayoutLine] = []
        for line in ranked_lines:
            text = line.text.strip()
            if not self._is_word_bank_phrase(text):
                continue
            if line.bbox.right < (min_left - _WORD_BANK_MAX_HORIZONTAL_GAP):
                continue
            if line.bbox.left > (max_right + _WORD_BANK_MAX_HORIZONTAL_GAP):
                continue
            if line.bbox.bottom < (min_top - _WORD_BANK_LAYOUT_VERTICAL_PAD):
                continue
            if line.bbox.top > (max_bottom + _WORD_BANK_LAYOUT_VERTICAL_PAD):
                continue
            candidates.append(line)

        if len(candidates) < (len(group) + 1):
            return []

        rows: list[list[LayoutLine]] = []
        for line in candidates:
            if not rows:
                rows.append([line])
                continue
            current = rows[-1]
            if abs(line.bbox.top - current[0].bbox.top) <= _WORD_BANK_ROW_CLUSTER_GAP:
                current.append(line)
                continue
            rows.append([line])

        serialized: list[list[str]] = []
        for row in rows:
            sorted_row = sorted(row, key=lambda line: line.bbox.left)
            serialized.append([line.text.strip() for line in sorted_row if line.text.strip()])

        if len(serialized) < 2:
            return []
        if max((len(row) for row in serialized), default=0) < 3:
            return []
        return serialized

    @staticmethod
    def _semantic_candidate_from_node(node: DocumentNode) -> SemanticNodeCandidate:
        bbox = node.bbox
        return SemanticNodeCandidate(
            node=node,
            page_number=max(0, int(node.page)),
            order=max(0, int(node.seq)),
            node_type=str(getattr(node.content, "type", "")),
            text="",
            left=float(bbox.x),
            top=float(bbox.y),
            right=float(bbox.x + bbox.width),
            bottom=float(bbox.y + bbox.height),
            metadata=dict(node.metadata),
        )

    @staticmethod
    def _candidate_should_emit(candidate: SemanticNodeCandidate) -> bool:
        if candidate.node_type in _PROTECTED_SEMANTIC_TYPES:
            return True

        content = candidate.node.content
        if candidate.node_type == "heading":
            return bool(HybridMergeEngine._styled_plain_text(getattr(content, "text", None)))
        if candidate.node_type == "paragraph":
            return bool(HybridMergeEngine._styled_plain_text(getattr(content, "text", None)))
        if candidate.node_type == "question":
            text = HybridMergeEngine._styled_plain_text(getattr(content, "text", None))
            statements = getattr(content, "statements", [])
            options = getattr(content, "options", [])
            blanks = getattr(content, "blanks", [])
            return bool(text or statements or options or blanks)
        if candidate.node_type == "list":
            items = getattr(content, "items", [])
            return any(item.text.plain_text.strip() for item in items)
        if candidate.node_type == "table_of_contents":
            entries = getattr(content, "entries", [])
            return bool(entries)
        return bool(candidate.text.strip())

    @staticmethod
    def _is_margin_heading_echo_candidate(
        candidate: SemanticNodeCandidate,
        page_headings: list[SemanticNodeCandidate],
    ) -> bool:
        if candidate.node_type != "paragraph":
            return False

        candidate_text = _normalized_text(candidate.text)
        if not candidate_text:
            return False

        heading_texts = {
            _normalized_text(heading.text) for heading in page_headings if heading.text.strip()
        }
        if candidate_text not in heading_texts:
            return False

        page_height = float(candidate.node.bbox.page_height)
        in_top_margin = candidate.top <= _MARGIN_HEADING_ECHO_MAX
        in_bottom_margin = page_height > 0.0 and candidate.bottom >= (
            page_height - _MARGIN_HEADING_ECHO_MAX
        )
        return in_top_margin or in_bottom_margin

    def _select_numbered_layout_replacements(
        self,
        *,
        page_candidates: list[SemanticNodeCandidate],
        page_lines: tuple[LayoutLine, ...],
    ) -> set[UUID]:
        numbered_lines = [
            line for line in page_lines if _NUMBERED_ITEM_RE.match(line.text.strip()) is not None
        ]
        if not numbered_lines:
            return set()

        replaced: set[UUID] = set()
        for candidate in page_candidates:
            if candidate.node_type not in {"paragraph", "list"}:
                continue
            label = _label_from_candidate(candidate)
            if label != "list_item" and not label.startswith("checkbox_"):
                continue

            candidate_text = _strip_number_prefix(candidate.text)
            if not candidate_text:
                continue

            for line in numbered_lines:
                overlap = _overlap_ratio(_node_box(candidate), _line_box(line))
                if overlap < _NUMBERED_LAYOUT_OVERLAP_THRESHOLD:
                    continue
                line_text = _strip_number_prefix(line.text)
                similarity = _text_similarity(candidate_text, line_text)
                if similarity < _NUMBERED_LAYOUT_SIMILARITY_THRESHOLD:
                    continue
                replaced.add(candidate.node.id)
                break

        return replaced

    @staticmethod
    def _best_overlap_candidate_for_line(
        *,
        line: LayoutLine,
        candidates: list[SemanticNodeCandidate],
    ) -> SemanticNodeCandidate | None:
        line_bounds = _line_box(line)
        best: SemanticNodeCandidate | None = None
        best_score = 0.0
        line_text = _strip_number_prefix(line.text)

        for candidate in candidates:
            overlap = _overlap_ratio(line_bounds, _node_box(candidate))
            if overlap <= 0.0:
                continue
            candidate_text = _strip_number_prefix(candidate.text)
            similarity = _text_similarity(line_text, candidate_text)
            score = (overlap * 0.8) + (similarity * 0.2)
            if score <= best_score:
                continue
            best = candidate
            best_score = score

        return best

    @staticmethod
    def _styled_plain_text(value: object) -> str:
        if isinstance(value, StyledText):
            return value.plain_text.strip()
        plain = getattr(value, "plain_text", None)
        if isinstance(plain, str):
            return plain.strip()
        return ""

    def _build_semantic_node(
        self,
        *,
        source: str,
        candidate: SemanticNodeCandidate,
        page_number: int,
        page_headings: list[SemanticNodeCandidate],
    ) -> DocumentNode:
        clone = candidate.node.model_copy(deep=True)
        clone.id = uuid4()
        clone.parent_id = None
        clone.children = []
        clone.page = page_number
        clone.seq = max(0, int(candidate.order))
        clone.source = SourceLocation(
            file=source,
            page=page_number,
            element_ref=f"semantic:{candidate.node.id}",
        )

        clone.bbox = BoundingBox(
            x=float(candidate.left),
            y=float(candidate.top),
            width=max(0.0, float(candidate.right - candidate.left)),
            height=max(0.0, float(candidate.bottom - candidate.top)),
            page_width=float(clone.bbox.page_width),
            page_height=float(clone.bbox.page_height),
            metadata=dict(clone.bbox.metadata),
        )

        relation_heading, relation_method, relation_confidence = (
            self._resolve_relation_for_candidate(
                candidate=candidate,
                page_headings=page_headings,
            )
        )

        metadata = dict(clone.metadata)
        metadata.setdefault("semantic_origin", "docling")
        metadata["boundary_preserved"] = True
        metadata["relation_method"] = relation_method
        metadata["relation_confidence"] = round(max(0.0, min(1.0, relation_confidence)), 4)
        metadata["semantic_node_type"] = candidate.node_type
        if relation_heading:
            metadata["resolved_section_heading"] = relation_heading
        if candidate.node_type in _PROTECTED_SEMANTIC_TYPES:
            metadata["semantic_only"] = True

        content = clone.content
        if isinstance(content, Heading):
            collapsed = self._collapse_duplicate_phrase(content.text.plain_text)
            if collapsed and collapsed != content.text.plain_text.strip():
                content.text = StyledText(runs=[TextRun(text=collapsed)])

        if isinstance(content, Question):
            normalized = self._normalize_question_content(
                question=content,
                line_text=content.text.plain_text,
                metadata=metadata,
            )
            merged_meta = dict(normalized.metadata)
            merged_meta.update(metadata)
            normalized.metadata = merged_meta
            clone.content = normalized

        clone.metadata = metadata
        return clone

    @staticmethod
    def _collapse_duplicate_phrase(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return ""

        tokens = normalized.split(" ")
        token_count = len(tokens)
        if token_count < 4 or token_count % 2 != 0:
            return normalized

        half = token_count // 2
        left = " ".join(tokens[:half]).strip()
        right = " ".join(tokens[half:]).strip()
        if _normalized_text(left) == _normalized_text(right):
            return left
        return normalized

    def _resolve_relation_for_candidate(
        self,
        *,
        candidate: SemanticNodeCandidate,
        page_headings: list[SemanticNodeCandidate],
    ) -> tuple[str | None, str, float]:
        if candidate.node_type == "heading":
            heading_text = candidate.text.strip() or None
            if heading_text:
                return heading_text, "hierarchy", 1.0

        parent_heading = candidate.metadata.get("resolved_section_heading")
        if isinstance(parent_heading, str) and parent_heading.strip():
            return parent_heading.strip(), "hierarchy", 1.0

        heading_candidate = self._nearest_heading_above_candidate(
            candidate=candidate,
            headings=page_headings,
        )
        if heading_candidate is not None:
            heading_text = heading_candidate.text.strip() or None
            if heading_text:
                return heading_text, "spatial", 0.6

        return None, "none", 0.0

    def _nearest_heading_above_candidate(
        self,
        *,
        candidate: SemanticNodeCandidate,
        headings: list[SemanticNodeCandidate],
    ) -> SemanticNodeCandidate | None:
        best: SemanticNodeCandidate | None = None
        best_gap: float | None = None

        for heading in headings:
            if heading.node.id == candidate.node.id:
                continue
            if heading.bottom > candidate.top:
                continue

            horizontal_overlap = min(candidate.right, heading.right) - max(
                candidate.left,
                heading.left,
            )
            if horizontal_overlap <= 0:
                continue

            vertical_gap = candidate.top - heading.bottom
            if vertical_gap > self._settings.spatial_fallback_vertical_gap:
                continue

            if best_gap is None or vertical_gap < best_gap:
                best = heading
                best_gap = vertical_gap

        return best

    @staticmethod
    def _line_overlaps_semantic_candidates(
        *,
        line: LayoutLine,
        candidates: list[SemanticNodeCandidate],
    ) -> bool:
        line_bounds = _line_box(line)
        for candidate in candidates:
            overlap = _overlap_ratio(line_bounds, _node_box(candidate))
            if overlap >= _LAYOUT_SEMANTIC_OVERLAP_THRESHOLD:
                return True
        return False

    def _best_candidate_for_line(
        self,
        *,
        line: LayoutLine,
        page_width: float,
        page_height: float,
        page_candidates: list[SemanticNodeCandidate],
        max_order: int,
    ) -> _ScoredCandidate | None:
        best: _ScoredCandidate | None = None
        for candidate in page_candidates:
            overlap = _overlap_ratio(_line_box(line), _node_box(candidate))
            distance = _distance_score(
                _line_box(line),
                _node_box(candidate),
                page_width=page_width,
                page_height=page_height,
            )
            order_score = _reading_order_score(line.order, candidate.order, max_order)
            text_score = _text_similarity(line.text, candidate.text)

            score = (
                overlap * self._settings.overlap_weight
                + distance * self._settings.distance_weight
                + order_score * self._settings.reading_order_weight
                + text_score * self._settings.text_similarity_weight
            )

            # Strict match on overlap or overall score.
            is_strict = (
                overlap >= self._settings.strict_match_threshold
                or score >= self._settings.strict_match_threshold
            )
            if not is_strict and overlap <= 0.0 and score < self._settings.relaxed_match_threshold:
                continue

            scored = _ScoredCandidate(candidate=candidate, score=score)
            if best is None or scored.score > best.score:
                best = scored

        return best

    def _resolve_relation(
        self,
        *,
        line: LayoutLine,
        matched: SemanticNodeCandidate | None,
        page_headings: list[SemanticNodeCandidate],
    ) -> tuple[str | None, str, float]:
        if matched is not None:
            heading = self._heading_from_candidate(matched)
            if heading:
                return heading, "hierarchy", 1.0

        heading_candidate = self._nearest_heading_above(line, page_headings)
        if heading_candidate is not None:
            heading_text = heading_candidate.text.strip() or None
            return heading_text, "spatial", 0.6

        return None, "none", 0.0

    @staticmethod
    def _heading_from_candidate(candidate: SemanticNodeCandidate) -> str | None:
        text = candidate.text.strip()
        if candidate.node_type == "heading" and text:
            return text
        parent_heading = candidate.metadata.get("resolved_section_heading")
        if isinstance(parent_heading, str) and parent_heading.strip():
            return parent_heading.strip()
        return None

    def _nearest_heading_above(
        self,
        line: LayoutLine,
        headings: list[SemanticNodeCandidate],
    ) -> SemanticNodeCandidate | None:
        line_left, line_top, line_right, _line_bottom = _line_box(line)
        best: SemanticNodeCandidate | None = None
        best_gap: float | None = None

        for heading in headings:
            heading_bottom = heading.bottom
            if heading_bottom > line_top:
                continue

            horizontal_overlap = min(line_right, heading.right) - max(line_left, heading.left)
            if horizontal_overlap <= 0:
                continue

            vertical_gap = line_top - heading_bottom
            if vertical_gap > self._settings.spatial_fallback_vertical_gap:
                continue

            if best_gap is None or vertical_gap < best_gap:
                best = heading
                best_gap = vertical_gap

        return best

    def _build_node(
        self,
        *,
        source: str,
        line: LayoutLine,
        semantic_kind: str,
        semantic_candidate: SemanticNodeCandidate | None,
        relation_heading: str | None,
        relation_method: str,
        relation_confidence: float,
    ) -> DocumentNode:
        bbox = BoundingBox(
            x=float(line.bbox.left),
            y=float(line.bbox.top),
            width=float(line.bbox.width),
            height=float(line.bbox.height),
            page_width=float(line.bbox.page_width),
            page_height=float(line.bbox.page_height),
        )
        metadata = _metadata_for_line(
            line,
            semantic_candidate=semantic_candidate,
            relation_heading=relation_heading,
            relation_method=relation_method,
            relation_confidence=relation_confidence,
        )

        styled_text = _line_styled_text(line)
        style = _line_block_style(line)

        content: Paragraph | Heading | ListBlock | Question
        level = 0

        if semantic_kind == "heading":
            level = self._heading_level_for_line(line)
            content = Heading(
                level=HeadingLevel(level),
                number="",
                text=styled_text,
                metadata=dict(metadata),
            )
        elif semantic_kind == "list":
            list_item = ListItem(text=styled_text)
            content = ListBlock(style=ListStyle.BULLET, items=[list_item], metadata=dict(metadata))
        elif semantic_kind == "question":
            if semantic_candidate is not None and isinstance(
                semantic_candidate.node.content, Question
            ):
                matched_content = semantic_candidate.node.content
                content = matched_content.model_copy(deep=True)
                content.text = styled_text
                merged_meta = dict(matched_content.metadata)
                merged_meta.update(metadata)
                content = self._normalize_question_content(
                    question=content,
                    line_text=line.text,
                    metadata=merged_meta,
                )
                content.metadata = merged_meta
            else:
                content = self._fallback_question_from_line(
                    styled_text=styled_text,
                    line_text=line.text,
                    metadata=dict(metadata),
                )
        else:
            content = Paragraph(text=styled_text, metadata=dict(metadata))

        return DocumentNode(
            id=uuid4(),
            content=content,
            page=line.page_number,
            seq=line.order,
            source=_line_source_location(source, line.page_number, line.line_id),
            bbox=bbox,
            style=style,
            level=level,
            metadata=dict(metadata),
        )

    def _normalize_question_content(
        self,
        *,
        question: Question,
        line_text: str,
        metadata: dict[str, Any],
    ) -> Question:
        if question.question_type != QuestionType.UNKNOWN:
            return question
        normalized = self._fallback_question_from_line(
            styled_text=question.text,
            line_text=line_text,
            metadata=dict(metadata),
        )
        if normalized.question_type != QuestionType.TRUE_FALSE:
            return question

        question.question_type = QuestionType.TRUE_FALSE
        if not question.statements:
            question.statements = normalized.statements
        return question

    def _fallback_question_from_line(
        self,
        *,
        styled_text: StyledText,
        line_text: str,
        metadata: dict[str, Any],
    ) -> Question:
        stripped = line_text.strip()
        numbered = _NUMBERED_ITEM_RE.match(stripped)
        label = str(metadata.get("label", ""))
        is_checkbox = label.startswith("checkbox_")
        checkbox_statement = is_checkbox and _looks_checkbox_statement(stripped)
        inline_marker = bool(_TRUE_FALSE_INLINE_RE.search(stripped))
        if numbered is not None and (checkbox_statement or inline_marker):
            statement_number = int(numbered.group(1))
            statement_text = stripped[numbered.end() :].strip()
            statement_text = _TRUE_FALSE_INLINE_RE.sub("", statement_text).strip()
            if not statement_text:
                statement_text = stripped
            metadata.setdefault("question_signal", "true_false")
            metadata.setdefault("numbered_item", statement_number)
            metadata.setdefault("statement_count", 1)
            return Question(
                question_type=QuestionType.TRUE_FALSE,
                text=styled_text,
                statements=[
                    QuestionStatement(
                        number=statement_number,
                        text=StyledText(runs=[TextRun(text=statement_text)]),
                    )
                ],
                metadata=metadata,
            )
        return Question(text=styled_text, metadata=metadata)

    @staticmethod
    def _heading_level_for_line(line: LayoutLine) -> int:
        if not line.spans:
            return int(HeadingLevel.SECTION)
        max_font = max(span.font.size for span in line.spans)
        if max_font >= 20.0:
            return int(HeadingLevel.CHAPTER)
        if max_font >= 15.0:
            return int(HeadingLevel.SECTION)
        if max_font >= 12.0:
            return int(HeadingLevel.SUBSECTION)
        return int(HeadingLevel.SUBSUBSECTION)

    def _append_unmatched_semantics(
        self,
        *,
        root: DocumentNode,
        source: str,
        page_number: int,
        page_candidates: list[SemanticNodeCandidate],
        used_candidates: set[UUID],
    ) -> None:
        for candidate in page_candidates:
            if candidate.node.id in used_candidates:
                continue

            if candidate.node_type not in {
                "table",
                "equation",
                "code_block",
                "figure",
                "question",
            }:
                continue

            clone = candidate.node.model_copy(deep=True)
            clone.id = uuid4()
            clone.parent_id = root.id
            clone.page = page_number
            clone.seq = max(clone.seq, 0)
            clone.source = SourceLocation(
                file=source,
                page=page_number,
                element_ref=f"semantic:{candidate.node.id}",
            )
            merged_meta = dict(clone.metadata)
            merged_meta["semantic_only"] = True
            merged_meta["semantic_node_type"] = candidate.node_type
            clone.metadata = merged_meta
            root.children.append(clone)
            used_candidates.add(candidate.node.id)
