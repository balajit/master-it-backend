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

import copy
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict
from uuid import uuid4

from learning_platform.models.document import (
    BoundingBox,
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Equation,
    Figure,
    FillInBlank,
    Heading,
    HeadingLevel,
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
    TableOfContents,
    TableOfContentsEntry,
    TableOfContentsType,
    TableRow,
    TextRun,
)
from learning_platform.stages.parser.docling_semantics import DoclingSemanticExtractor
from learning_platform.stages.parser.hybrid_merge import HybridMergeEngine, HybridMergeSettings
from learning_platform.stages.parser.pymupdf_layout import PyMuPDFLayoutExtractor

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter

_LOG = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".doc",
        ".xls",
        ".ppt",
        ".odt",
        ".ods",
        ".odp",
        ".epub",
        ".md",
        ".asciidoc",
        ".adoc",
        ".html",
        ".htm",
        ".xhtml",
        ".csv",
        ".txt",
        ".xml",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".tif",
        ".bmp",
        ".webp",
    }
)

_FORMULA_HINT_RE = re.compile(
    r"(?:\\frac|\\sum|\\int|[A-Za-z]\s*=\s*[^=]|\b\d+\s*[-+*/=]\s*\d+)",
)
_CODE_HINT_RE = re.compile(
    r"(?:\bdef\b|\bclass\b|\breturn\b|#include\b|public\s+static|\{.*\}|\bselect\b.+\bfrom\b)",
    re.IGNORECASE,
)


class PdfOcrStrategy(StrEnum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class PdfDocumentClass(StrEnum):
    DIGITAL = "digital"
    SCANNED = "scanned"
    MIXED = "mixed"


@dataclass(frozen=True)
class _SecondPassPlan:
    page_number: int
    reasons: tuple[str, ...]
    do_ocr: bool
    do_picture_description: bool
    do_code_enrichment: bool
    do_formula_enrichment: bool


@dataclass(frozen=True)
class _PdfParseSummary:
    document_class: PdfDocumentClass
    ocr_enabled: bool
    second_pass_enabled: bool
    selected_pages: tuple[int, ...]
    selected_reasons: dict[int, tuple[str, ...]]


HEADING_RE = re.compile(r"^((?:\d+\.)*\d+|[A-Z]\.|Appendix\s+[A-Z])\s+(.*)$")

TOC_ENTRY_RE = re.compile(r"^(.+?)\s*[.\-–—]{2,}\s*(\d+)\s*$")

_FILL_IN_BLANK_RE = re.compile(r"\((\d+)\)\s*(?:_{2,}|\.{2,}|$)")
_NUMBERED_STATEMENT_RE = re.compile(r"^\s*(\d+)[.)]\s+")
_TRUE_FALSE_INSTRUCTION_RE = re.compile(
    r"\btrue\s*(?:/|\s+or\s+)\s*false\b|\bwrite\s+true\b.*\bfalse\b",
    re.IGNORECASE,
)
_FILL_BLANK_INSTRUCTION_RE = re.compile(
    r"\bfill\s+in\s+the\s+blank(?:s)?\b|\bcomplete\s+the\s+blank(?:s)?\b",
    re.IGNORECASE,
)
_TRUE_FALSE_INLINE_RE = re.compile(
    r"\(\s*(?:t\s*/\s*f|true\s*/\s*false|t|f)\s*\)",
    re.IGNORECASE,
)
_TRUE_FALSE_MIN_WORDS = 5


class DoclingAdapter:
    """Adapter wrapping IBM Docling for use as an ``AbstractParser``.

    Parameters
    ----------
    converter : DocumentConverter | None
        An optional pre-configured ``DocumentConverter`` instance. When
        ``None`` the adapter creates one with default settings. This
        allows callers to inject a custom converter (Dependency Inversion).
    """

    def __init__(
        self,
        converter: DocumentConverter | None = None,
        *,
        pdf_ocr_strategy: PdfOcrStrategy | str = PdfOcrStrategy.AUTO,
        pdf_classifier_sample_pages: int = 5,
        pdf_classifier_min_chars_per_page: int = 80,
        pdf_classifier_digital_ratio: float = 0.80,
        pdf_classifier_scanned_ratio: float = 0.20,
        pdf_second_pass_enabled: bool = True,
        pdf_second_pass_max_pages: int = 12,
        pdf_second_pass_low_text_chars: int = 120,
        hybrid_overlap_weight: float = 0.50,
        hybrid_distance_weight: float = 0.20,
        hybrid_reading_order_weight: float = 0.15,
        hybrid_text_similarity_weight: float = 0.15,
        hybrid_strict_match_threshold: float = 0.55,
        hybrid_relaxed_match_threshold: float = 0.35,
        hybrid_spatial_fallback_vertical_gap: float = 90.0,
    ) -> None:
        self._converter = converter
        self._pdf_converter_cache: dict[tuple[bool, bool, bool, bool], DocumentConverter] = {}
        self._pdf_ocr_strategy = self._coerce_ocr_strategy(pdf_ocr_strategy)
        self._pdf_classifier_sample_pages = max(1, pdf_classifier_sample_pages)
        self._pdf_classifier_min_chars_per_page = max(1, pdf_classifier_min_chars_per_page)
        self._pdf_classifier_digital_ratio = max(0.0, min(1.0, pdf_classifier_digital_ratio))
        self._pdf_classifier_scanned_ratio = max(0.0, min(1.0, pdf_classifier_scanned_ratio))
        self._pdf_second_pass_enabled = pdf_second_pass_enabled
        self._pdf_second_pass_max_pages = max(1, pdf_second_pass_max_pages)
        self._pdf_second_pass_low_text_chars = max(1, pdf_second_pass_low_text_chars)
        self._layout_extractor = PyMuPDFLayoutExtractor()
        self._semantic_extractor = DoclingSemanticExtractor()
        self._hybrid_merge = HybridMergeEngine(
            HybridMergeSettings(
                overlap_weight=max(0.0, min(1.0, hybrid_overlap_weight)),
                distance_weight=max(0.0, min(1.0, hybrid_distance_weight)),
                reading_order_weight=max(0.0, min(1.0, hybrid_reading_order_weight)),
                text_similarity_weight=max(0.0, min(1.0, hybrid_text_similarity_weight)),
                strict_match_threshold=max(0.0, min(1.0, hybrid_strict_match_threshold)),
                relaxed_match_threshold=max(0.0, min(1.0, hybrid_relaxed_match_threshold)),
                spatial_fallback_vertical_gap=max(0.0, hybrid_spatial_fallback_vertical_gap),
            )
        )


    # ── AbstractParser Protocol ───────────────────────────────────────────

    def parse(self, source: str) -> CanonicalDocument:
        """Convert *source* into a ``CanonicalDocument`` via Docling."""
        _LOG.info("DoclingAdapter.parse: %s", source)
        suffix = Path(source).suffix.lower()

        parse_summary: _PdfParseSummary | None = None
        if suffix == ".pdf":
            root_node, title, page_count, parse_summary = self._parse_pdf(source)
        else:
            converter = self._get_converter()
            result = converter.convert(source)
            docling_doc = result.document
            root_node = self._build_tree(docling_doc, source)
            title = docling_doc.name or Path(source).stem
            page_count = len(docling_doc.pages) if hasattr(docling_doc, "pages") else 0

        self._auto_generate_toc(root_node)
        self._promote_question_nodes(root_node)

        custom_metadata: dict[str, Any] = {}
        docling_parse_metadata: dict[str, Any] = {}
        if parse_summary is not None:
            docling_parse_metadata.update(
                {
                    "pdf_document_class": parse_summary.document_class.value,
                    "ocr_enabled": parse_summary.ocr_enabled,
                    "second_pass_enabled": parse_summary.second_pass_enabled,
                    "selected_pages": list(parse_summary.selected_pages),
                    "selected_reasons": {
                        str(page_number): list(reasons)
                        for page_number, reasons in parse_summary.selected_reasons.items()
                    },
                }
            )

        hybrid_parse_metadata = root_node.metadata.get("docling_parse")
        if isinstance(hybrid_parse_metadata, dict):
            docling_parse_metadata.update(hybrid_parse_metadata)

        if docling_parse_metadata:
            custom_metadata["docling_parse"] = docling_parse_metadata

        return CanonicalDocument(
            source=str(source),
            title=title,
            metadata=DocumentMetadata(
                title=title,
                file_type=Path(source).suffix.lstrip("."),
                page_count=page_count,
                custom=custom_metadata,
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

        from docling.document_converter import DocumentConverter

        self._converter = DocumentConverter()

        return self._converter

    def _parse_pdf(self, source: str) -> tuple[DocumentNode, str, int, _PdfParseSummary]:
        document_class = self._classify_pdf_document(source)
        ocr_enabled = self._should_enable_ocr(document_class)
        base_converter = self._get_pdf_converter(
            do_ocr=ocr_enabled,
            do_picture_description=False,
            do_code_enrichment=False,
            do_formula_enrichment=False,
        )
        base_result = base_converter.convert(source)
        base_doc = base_result.document
        root_node = self._build_tree(base_doc, source)

        selected_reasons: dict[int, tuple[str, ...]] = {}
        if self._pdf_second_pass_enabled:
            plans = self._build_second_pass_plans(root_node, ocr_enabled=ocr_enabled)
            for plan in plans:
                selected_reasons[plan.page_number] = plan.reasons
            if plans:
                self._run_second_pass(source, root_node, plans)

        root_node = self._build_hybrid_pdf_tree(
            source=source,
            semantic_root=root_node,
            ocr_enabled=ocr_enabled,
            document_class=document_class,
            selected_reasons=selected_reasons,
        )

        summary = _PdfParseSummary(
            document_class=document_class,
            ocr_enabled=ocr_enabled,
            second_pass_enabled=bool(selected_reasons),
            selected_pages=tuple(sorted(selected_reasons.keys())),
            selected_reasons=selected_reasons,
        )

        title = base_doc.name or Path(source).stem
        page_count = len(base_doc.pages) if hasattr(base_doc, "pages") else 0
        return root_node, title, page_count, summary

    def _build_hybrid_pdf_tree(
        self,
        *,
        source: str,
        semantic_root: DocumentNode,
        ocr_enabled: bool,
        document_class: PdfDocumentClass,
        selected_reasons: dict[int, tuple[str, ...]],
    ) -> DocumentNode:
        layout_doc = self._layout_extractor.extract(source)
        semantics = self._semantic_extractor.extract(semantic_root)
        hybrid_root = self._hybrid_merge.merge(
            source=source,
            layout_doc=layout_doc,
            semantics=semantics,
        )
        hybrid_root.metadata["docling_parse"] = {
            "ocr_enabled": ocr_enabled,
            "pdf_document_class": document_class.value,
            "second_pass_enabled": bool(selected_reasons),
            "selected_pages": sorted(selected_reasons.keys()),
            "selected_reasons": {
                str(page_number): list(reasons)
                for page_number, reasons in selected_reasons.items()
            },
            "layout_pages": len(layout_doc.pages),
            "semantic_candidates": len(semantics.candidates),
            "hybrid_enabled": True,
        }
        return self._repair_hybrid_hierarchy(hybrid_root)

    def _repair_hybrid_hierarchy(self, root: DocumentNode) -> DocumentNode:
        """Apply relation metadata to create heading-owned hierarchy.

        The hybrid merge emits a flat page-ordered list under the synthetic
        document root. This pass reparents content beneath the latest heading
        when relation metadata indicates heading ownership.
        """

        heading_stack: list[DocumentNode] = []
        new_children: list[DocumentNode] = []

        for node in root.children:
            node.children = []
            content = node.content
            if isinstance(content, Heading):
                heading_stack.clear()
                heading_stack.append(node)
                node.parent_id = root.id
                new_children.append(node)
                continue

            resolved_heading = str(node.metadata.get("resolved_section_heading") or "").strip()
            if resolved_heading and heading_stack:
                current_heading = heading_stack[-1]
                current_text = self._normalize_text(current_heading.content.text.plain_text)
                target_text = self._normalize_text(resolved_heading)
                if target_text and current_text == target_text:
                    node.parent_id = current_heading.id
                    current_heading.children.append(node)
                    continue

            node.parent_id = root.id
            new_children.append(node)

        root.children = new_children
        return root

    @staticmethod
    def _coerce_ocr_strategy(value: PdfOcrStrategy | str) -> PdfOcrStrategy:
        if isinstance(value, PdfOcrStrategy):
            return value
        try:
            return PdfOcrStrategy(str(value).strip().lower())
        except ValueError:
            _LOG.warning("Invalid OCR strategy '%s'; defaulting to auto", value)
            return PdfOcrStrategy.AUTO

    def _should_enable_ocr(self, document_class: PdfDocumentClass) -> bool:
        if self._pdf_ocr_strategy == PdfOcrStrategy.ALWAYS:
            return True
        if self._pdf_ocr_strategy == PdfOcrStrategy.NEVER:
            return False
        return document_class != PdfDocumentClass.DIGITAL

    def _classify_pdf_document(self, source: str) -> PdfDocumentClass:
        try:
            import pymupdf

            pdf = pymupdf.open(source)
            try:
                total_pages = len(pdf)
                if total_pages <= 0:
                    return PdfDocumentClass.MIXED

                sampled_indexes = self._sample_pdf_page_indexes(
                    total_pages,
                    self._pdf_classifier_sample_pages,
                )
                text_pages = 0
                for page_idx in sampled_indexes:
                    page_text = pdf[page_idx].get_text("text")
                    stripped_len = len(re.sub(r"\s+", "", page_text))
                    if stripped_len >= self._pdf_classifier_min_chars_per_page:
                        text_pages += 1

                ratio = text_pages / max(1, len(sampled_indexes))
                return self._classify_pdf_text_ratio(ratio)
            finally:
                pdf.close()
        except Exception as exc:
            _LOG.warning("PDF preflight classification failed for %s: %s", source, exc)
            return PdfDocumentClass.MIXED

    def _classify_pdf_text_ratio(self, ratio: float) -> PdfDocumentClass:
        if ratio >= self._pdf_classifier_digital_ratio:
            return PdfDocumentClass.DIGITAL
        if ratio <= self._pdf_classifier_scanned_ratio:
            return PdfDocumentClass.SCANNED
        return PdfDocumentClass.MIXED

    @staticmethod
    def _sample_pdf_page_indexes(total_pages: int, sample_size: int) -> list[int]:
        if total_pages <= 0:
            return []
        if sample_size <= 1 or total_pages == 1:
            return [0]
        if total_pages <= sample_size:
            return list(range(total_pages))

        indexes: set[int] = set()
        span = total_pages - 1
        denominator = sample_size - 1
        for i in range(sample_size):
            idx = round((i * span) / denominator)
            indexes.add(min(total_pages - 1, max(0, idx)))
        return sorted(indexes)

    def _get_pdf_converter(
        self,
        *,
        do_ocr: bool,
        do_picture_description: bool,
        do_code_enrichment: bool,
        do_formula_enrichment: bool,
    ) -> DocumentConverter:
        cache_key = (
            do_ocr,
            do_picture_description,
            do_code_enrichment,
            do_formula_enrichment,
        )
        cached = self._pdf_converter_cache.get(cache_key)
        if cached is not None:
            return cached

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        opts = PdfPipelineOptions()
        opts.do_table_structure = True
        opts.do_ocr = do_ocr
        opts.do_picture_description = do_picture_description
        opts.do_code_enrichment = do_code_enrichment
        opts.do_formula_enrichment = do_formula_enrichment
        opts.generate_page_images = False
        opts.generate_picture_images = False
        opts.images_scale = 1.0

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
        self._pdf_converter_cache[cache_key] = converter
        return converter

    def _build_second_pass_plans(
        self,
        root_node: DocumentNode,
        *,
        ocr_enabled: bool,
    ) -> list[_SecondPassPlan]:
        nodes_by_page: dict[int, list[DocumentNode]] = defaultdict(list)
        all_nodes: list[DocumentNode] = []
        self._collect_nodes(root_node, all_nodes)

        for node in all_nodes:
            if node.page <= 0 or node.metadata.get("role") == "document_root":
                continue
            nodes_by_page[node.page].append(node)

        plans: list[_SecondPassPlan] = []
        for page_number in sorted(nodes_by_page.keys()):
            nodes = nodes_by_page[page_number]
            page_text = self._page_text(nodes)
            normalized_length = len(re.sub(r"\s+", "", page_text))

            reasons: list[str] = []
            if normalized_length < self._pdf_second_pass_low_text_chars:
                reasons.append("ocr_rescue")
            if self._page_needs_figure_description(nodes):
                reasons.append("figure_description")
            if self._page_needs_formula_enrichment(nodes, page_text):
                reasons.append("formula_enrichment")
            if self._page_needs_code_enrichment(nodes, page_text):
                reasons.append("code_enrichment")

            if not reasons:
                continue

            reasons_tuple = tuple(sorted(set(reasons)))
            plans.append(
                _SecondPassPlan(
                    page_number=page_number,
                    reasons=reasons_tuple,
                    do_ocr=(ocr_enabled or "ocr_rescue" in reasons_tuple),
                    do_picture_description="figure_description" in reasons_tuple,
                    do_code_enrichment="code_enrichment" in reasons_tuple,
                    do_formula_enrichment="formula_enrichment" in reasons_tuple,
                )
            )

        plans.sort(key=lambda plan: (-len(plan.reasons), plan.page_number))
        return plans[: self._pdf_second_pass_max_pages]

    def _run_second_pass(
        self,
        source: str,
        root_node: DocumentNode,
        plans: list[_SecondPassPlan],
    ) -> None:
        for plan in plans:
            converter = self._get_pdf_converter(
                do_ocr=plan.do_ocr,
                do_picture_description=plan.do_picture_description,
                do_code_enrichment=plan.do_code_enrichment,
                do_formula_enrichment=plan.do_formula_enrichment,
            )
            try:
                result = converter.convert(
                    source,
                    page_range=(plan.page_number, plan.page_number),
                )
            except Exception as exc:
                _LOG.warning(
                    "Second pass failed for page %d (%s): %s",
                    plan.page_number,
                    ",".join(plan.reasons),
                    exc,
                )
                continue

            second_root = self._build_tree(result.document, source)
            self._merge_second_pass_page(root_node, second_root, plan)

    def _merge_second_pass_page(
        self,
        base_root: DocumentNode,
        second_root: DocumentNode,
        plan: _SecondPassPlan,
    ) -> None:
        base_nodes = self._nodes_for_page(base_root, plan.page_number)
        second_nodes = self._nodes_for_page(second_root, plan.page_number)
        if not second_nodes:
            return

        if plan.do_picture_description:
            self._merge_figures(base_root, base_nodes, second_nodes)

        if plan.do_formula_enrichment:
            self._merge_nodes_by_type(
                base_root,
                base_nodes,
                second_nodes,
                allowed_types={"equation"},
            )

        if plan.do_code_enrichment:
            self._merge_nodes_by_type(
                base_root,
                base_nodes,
                second_nodes,
                allowed_types={"code_block"},
            )

        if "ocr_rescue" in plan.reasons:
            self._merge_nodes_by_type(
                base_root,
                base_nodes,
                second_nodes,
                allowed_types={"paragraph", "heading", "list"},
            )

    def _merge_figures(
        self,
        base_root: DocumentNode,
        base_nodes: list[DocumentNode],
        second_nodes: list[DocumentNode],
    ) -> None:
        base_figures = [
            node for node in base_nodes if getattr(node.content, "type", "") == "figure"
        ]
        second_figures = [
            node for node in second_nodes if getattr(node.content, "type", "") == "figure"
        ]

        for second in second_figures:
            second_content = second.content
            matched = None
            for base in base_figures:
                base_content = base.content
                same_uri = bool(base_content.image_uri) and (
                    base_content.image_uri == second_content.image_uri
                )
                same_caption = (
                    bool(base_content.caption_text)
                    and base_content.caption_text.strip() == second_content.caption_text.strip()
                )
                if same_uri or same_caption:
                    matched = base
                    break

            if matched is None:
                cloned = self._append_root_child(base_root, second)
                base_nodes.append(cloned)
                base_figures.append(cloned)
                continue

            matched_content = matched.content
            if not matched_content.caption_text.strip() and second_content.caption_text.strip():
                matched_content.caption_text = second_content.caption_text
            if not matched_content.alt_text.strip() and second_content.alt_text.strip():
                matched_content.alt_text = second_content.alt_text
            if second_content.metadata:
                merged_meta = {**matched_content.metadata, **second_content.metadata}
                matched_content.metadata = merged_meta

    def _merge_nodes_by_type(
        self,
        base_root: DocumentNode,
        base_nodes: list[DocumentNode],
        second_nodes: list[DocumentNode],
        *,
        allowed_types: set[str],
    ) -> None:
        for second in second_nodes:
            content_type = getattr(second.content, "type", "")
            if content_type not in allowed_types:
                continue
            if self._is_duplicate_node(second, base_nodes):
                continue
            cloned = self._append_root_child(base_root, second)
            base_nodes.append(cloned)

    @staticmethod
    def _append_root_child(root_node: DocumentNode, node: DocumentNode) -> DocumentNode:
        cloned = copy.deepcopy(node)
        cloned.parent_id = root_node.id
        root_node.children.append(cloned)
        return cloned

    def _is_duplicate_node(
        self, candidate: DocumentNode, existing_nodes: list[DocumentNode]
    ) -> bool:
        candidate_type = getattr(candidate.content, "type", "")
        candidate_text = self._normalize_text(self._node_text(candidate))
        if not candidate_text:
            return False
        for existing in existing_nodes:
            existing_type = getattr(existing.content, "type", "")
            if existing_type != candidate_type:
                continue
            existing_text = self._normalize_text(self._node_text(existing))
            if existing_text and existing_text == candidate_text:
                return True
        return False

    def _nodes_for_page(self, root_node: DocumentNode, page_number: int) -> list[DocumentNode]:
        all_nodes: list[DocumentNode] = []
        self._collect_nodes(root_node, all_nodes)
        return [
            node
            for node in all_nodes
            if node.page == page_number and node.metadata.get("role") != "document_root"
        ]

    def _page_text(self, nodes: list[DocumentNode]) -> str:
        parts = [self._node_text(node) for node in nodes]
        return " ".join(part for part in parts if part).strip()

    def _node_text(self, node: DocumentNode) -> str:
        content = node.content
        content_type = getattr(content, "type", "")
        if hasattr(content, "text") and hasattr(content.text, "plain_text"):
            return content.text.plain_text.strip()
        if content_type == "equation":
            return getattr(content, "latex", "").strip()
        if content_type == "code_block":
            return getattr(content, "code", "").strip()
        if content_type == "list":
            list_items = getattr(content, "items", [])
            return " ".join(item.text.plain_text for item in list_items).strip()
        if content_type == "table":
            headers = getattr(content, "headers", [])
            return " ".join(str(header) for header in headers).strip()
        if content_type == "figure":
            caption = getattr(content, "caption_text", "")
            alt_text = getattr(content, "alt_text", "")
            return f"{caption} {alt_text}".strip()
        return ""

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip().lower()
        return normalized

    @staticmethod
    def _page_needs_figure_description(nodes: list[DocumentNode]) -> bool:
        for node in nodes:
            if not isinstance(node.content, Figure):
                continue
            if not node.content.caption_text.strip() and not node.content.alt_text.strip():
                return True
        return False

    def _page_needs_formula_enrichment(self, nodes: list[DocumentNode], page_text: str) -> bool:
        if not page_text:
            return False
        has_equation = any(isinstance(node.content, Equation) for node in nodes)
        return (not has_equation) and bool(_FORMULA_HINT_RE.search(page_text))

    @staticmethod
    def _page_needs_code_enrichment(nodes: list[DocumentNode], page_text: str) -> bool:
        if not page_text:
            return False
        has_code = any(getattr(node.content, "type", "") == "code_block" for node in nodes)
        return (not has_code) and bool(_CODE_HINT_RE.search(page_text))

    def _build_tree(self, docling_doc: object, source: str) -> DocumentNode:
        """Walk the Docling DOM and produce a canonical ``DocumentNode`` tree.

        The returned node is a synthetic root whose children represent the
        document's top-level reading order. This method preserves Docling's
        parent-child relationships instead of flattening everything.
        """
        # Step 1: Map all Docling items to DocumentNodes
        ref_to_node: dict[str, DocumentNode] = {}
        page_seq: dict[int, int] = {}
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
        page_width, page_height = self._docling_page_size(docling_doc, page)

        bbox = BoundingBox()
        if prov is not None:
            raw_bbox = getattr(prov, "bbox", None)
            if raw_bbox is not None:
                left_raw = float(getattr(raw_bbox, "l", 0.0) or 0.0)
                right_raw = float(getattr(raw_bbox, "r", 0.0) or 0.0)
                top_raw = float(getattr(raw_bbox, "t", 0.0) or 0.0)
                bottom_raw = float(getattr(raw_bbox, "b", 0.0) or 0.0)

                left = min(left_raw, right_raw)
                right = max(left_raw, right_raw)
                coord_origin = str(getattr(raw_bbox, "coord_origin", "")).upper()
                if "BOTTOMLEFT" in coord_origin and page_height > 0.0:
                    top = page_height - max(top_raw, bottom_raw)
                    bottom = page_height - min(top_raw, bottom_raw)
                else:
                    top = min(top_raw, bottom_raw)
                    bottom = max(top_raw, bottom_raw)

                bbox = BoundingBox(
                    x=left,
                    y=top,
                    width=max(0.0, right - left),
                    height=max(0.0, bottom - top),
                    page_width=page_width,
                    page_height=page_height,
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
            node = self._make_paragraph_or_question(item, source, label_value)
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

    @staticmethod
    def _docling_page_size(docling_doc: object, page_number: int) -> tuple[float, float]:
        pages = getattr(docling_doc, "pages", None)
        if not isinstance(pages, dict):
            return (0.0, 0.0)

        page_obj = pages.get(page_number)
        if page_obj is None:
            return (0.0, 0.0)

        size = getattr(page_obj, "size", None)
        if size is None:
            return (0.0, 0.0)

        width = float(getattr(size, "width", 0.0) or 0.0)
        height = float(getattr(size, "height", 0.0) or 0.0)
        return (width, height)

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

    def _make_paragraph_or_question(
        self,
        item: object,
        source: str,
        label_value: str,
    ) -> DocumentNode:
        text = getattr(item, "text", "") or ""
        question = self._question_from_text(text, label_value)
        if question is not None:
            return DocumentNode(
                id=uuid4(),
                content=question,
                source=SourceLocation(file=source),
            )
        return self._make_paragraph(item, source)

    def _question_from_text(self, text: str, label_value: str) -> Question | None:
        stripped = text.strip()
        if not stripped:
            return None

        fill_blank_ids = [int(match.group(1)) for match in _FILL_IN_BLANK_RE.finditer(stripped)]
        if fill_blank_ids:
            metadata: dict[str, Any] = {
                "question_signal": "fill_in_blank",
                "fill_in_blank_ids": fill_blank_ids,
            }
            if label_value:
                metadata["label"] = label_value
            blanks = [
                FillInBlank(blank_id=blank_id, placeholder=f"({blank_id})")
                for blank_id in fill_blank_ids
            ]
            return Question(
                question_type=QuestionType.FILL_IN_BLANK,
                text=StyledText(runs=[TextRun(text=stripped)]),
                blanks=blanks,
                metadata=metadata,
            )

        numbered = _NUMBERED_STATEMENT_RE.match(stripped)
        checkbox_label = label_value.startswith("checkbox_")
        has_true_false_marker = bool(_TRUE_FALSE_INLINE_RE.search(stripped))
        is_true_false_checkbox = checkbox_label and self._looks_like_true_false_statement(stripped)
        if numbered is not None and (has_true_false_marker or is_true_false_checkbox):
            statements = self._extract_numbered_statements(stripped)
            if not statements:
                number = int(numbered.group(1))
                statement_text = stripped[numbered.end() :].strip()
                statement_text = _TRUE_FALSE_INLINE_RE.sub("", statement_text).strip()
                statement_plain = statement_text or stripped
                statements = [
                    QuestionStatement(
                        number=number,
                        text=StyledText(runs=[TextRun(text=statement_plain)]),
                    )
                ]
            number = int(statements[0].number or int(numbered.group(1)))

            metadata = {
                "question_signal": "true_false",
                "numbered_item": number,
                "statement_count": len(statements),
            }
            if checkbox_label:
                metadata["checkbox_state"] = label_value.removeprefix("checkbox_")
            if label_value:
                metadata["label"] = label_value

            return Question(
                question_type=QuestionType.TRUE_FALSE,
                text=StyledText(runs=[TextRun(text=stripped)]),
                statements=statements,
                metadata=metadata,
            )

        if label_value == "form_area":
            metadata = {
                "question_signal": "form_area",
                "label": label_value,
            }
            return Question(
                question_type=QuestionType.SHORT_ANSWER,
                text=StyledText(runs=[TextRun(text=stripped)]),
                metadata=metadata,
            )

        return None

    @staticmethod
    def _looks_like_true_false_statement(text: str) -> bool:
        numbered = _NUMBERED_STATEMENT_RE.match(text)
        if numbered is None:
            return False
        if _TRUE_FALSE_INLINE_RE.search(text):
            return True
        body = text[numbered.end() :].strip()
        if not body:
            return False
        token_count = len(re.findall(r"[A-Za-z0-9]+", body))
        return token_count >= _TRUE_FALSE_MIN_WORDS

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

    def _promote_question_nodes(self, root: DocumentNode) -> None:
        """Promote numbered worksheet lines to canonical Question nodes.

        This pass uses nearby instruction text (for example, "true or false"
        directions) so each numbered statement is represented as its own
        Question block in the CanonicalDocument tree.
        """

        question_mode: QuestionType | None = None

        for node in self._iter_nodes_preorder(root):
            content = node.content
            if isinstance(content, Heading):
                question_mode = None
                continue

            if isinstance(content, Question):
                if content.question_type in {
                    QuestionType.TRUE_FALSE,
                    QuestionType.FILL_IN_BLANK,
                }:
                    question_mode = content.question_type
                continue

            text = self._promotable_text(content)
            if text is None:
                continue
            if not text:
                continue

            if _TRUE_FALSE_INSTRUCTION_RE.search(text):
                question_mode = QuestionType.TRUE_FALSE
                continue

            if _FILL_BLANK_INSTRUCTION_RE.search(text):
                question_mode = QuestionType.FILL_IN_BLANK
                continue

            if question_mode == QuestionType.TRUE_FALSE:
                promoted = self._build_true_false_statement_question(text, node.metadata)
                if promoted is not None:
                    node.content = promoted
                    continue

            if question_mode == QuestionType.FILL_IN_BLANK:
                promoted = self._question_from_text(text, str(node.metadata.get("label", "")))
                if promoted is not None and promoted.question_type == QuestionType.FILL_IN_BLANK:
                    node.content = promoted

    def _promotable_text(self, content: object) -> str | None:
        if isinstance(content, Paragraph):
            return content.text.plain_text.strip()
        if isinstance(content, ListBlock):
            item_texts = [item.text.plain_text.strip() for item in content.items]
            merged = " ".join(text for text in item_texts if text).strip()
            return merged or None
        return None

    def _extract_numbered_statements(self, text: str) -> list[QuestionStatement]:
        matches = list(_NUMBERED_STATEMENT_RE.finditer(text))
        if not matches:
            return []

        statements: list[QuestionStatement] = []
        for index, match in enumerate(matches):
            segment_start = match.end()
            segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            statement_number = int(match.group(1))
            statement_text = text[segment_start:segment_end].strip(" ;|\t\n")
            statement_text = _TRUE_FALSE_INLINE_RE.sub("", statement_text).strip()
            if not statement_text:
                continue
            statements.append(
                QuestionStatement(
                    number=statement_number,
                    text=StyledText(runs=[TextRun(text=statement_text)]),
                )
            )
        return statements

    def _build_true_false_statement_question(
        self,
        text: str,
        node_metadata: dict[str, Any],
    ) -> Question | None:
        statements = self._extract_numbered_statements(text)
        if not statements:
            return None

        number = statements[0].number

        metadata: dict[str, Any] = {
            "question_signal": "true_false_context",
            "numbered_item": number,
            "statement_count": len(statements),
        }
        label = node_metadata.get("label")
        if isinstance(label, str) and label:
            metadata["label"] = label
            if label.startswith("checkbox_"):
                metadata["checkbox_state"] = label.removeprefix("checkbox_")

        return Question(
            question_type=QuestionType.TRUE_FALSE,
            text=StyledText(runs=[TextRun(text=text)]),
            statements=statements,
            metadata=metadata,
        )

    def _iter_nodes_preorder(self, node: DocumentNode) -> list[DocumentNode]:
        result: list[DocumentNode] = []
        for child in node.children:
            result.append(child)
            result.extend(self._iter_nodes_preorder(child))
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

    def _collect_nodes(self, node: DocumentNode, node_map: list[DocumentNode]) -> None:
        node_map.append(node)
        for child in node.children:
            self._collect_nodes(child, node_map)
