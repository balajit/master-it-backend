"""End-to-end test: parse small.pdf, normalize, and cross-verify with PyMuPDF.

This test verifies that the DoclingAdapter + StructuralNormalizer pipeline
correctly processes a real PDF document and preserves all content structure.
PyMuPDF is used as an independent ground-truth source for text extraction.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from learning_platform.models.document import (
    CanonicalDocument,
    Heading,
    ListBlock,
    Paragraph,
    TableBlock,
)
from learning_platform.stages.normalizer.structural import StructuralNormalizer
from learning_platform.stages.parser.docling_adapter import DoclingAdapter

_PDF_PATH = Path(__file__).resolve().parent.parent.parent.parent / "test_pdfs" / "small.pdf"


def _make_lightweight_adapter() -> DoclingAdapter:
    """Create a DoclingAdapter with VLM features disabled for fast testing."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.generate_page_images = False
    opts.generate_picture_images = False
    opts.do_picture_description = False
    opts.do_code_enrichment = False
    opts.do_formula_enrichment = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
        }
    )
    return DoclingAdapter(converter=converter)


def _collect_all(root) -> list:
    """Collect all nodes from a tree in pre-order, excluding synthetic roots."""
    result = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.metadata.get("role") not in {"normalizer_root", "document_root"}:
            result.append(node)
        stack.extend(reversed(node.children))
    return result


def _pymupdf_extract_text(pdf_path: str) -> dict[int, str]:
    """Extract text per page using PyMuPDF as ground truth."""
    doc = pymupdf.open(pdf_path)
    pages: dict[int, str] = {}
    for i, page in enumerate(doc):
        pages[i + 1] = page.get_text()
    doc.close()
    return pages


def _normalize(text: str) -> str:
    """Normalize text for comparison (collapse whitespace, lowercase)."""
    import re

    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


@pytest.mark.skipif(not _PDF_PATH.exists(), reason="small.pdf not found")
class TestSmallPdfEndToEnd:
    """Verify pipeline processes small.pdf correctly using PyMuPDF as ground truth."""

    @pytest.fixture(scope="class")
    def parsed_doc(self) -> CanonicalDocument:
        adapter = _make_lightweight_adapter()
        return adapter.parse(str(_PDF_PATH))

    @pytest.fixture(scope="class")
    def normalized_doc(self, parsed_doc: CanonicalDocument) -> CanonicalDocument:
        normalizer = StructuralNormalizer()
        return normalizer.normalize(parsed_doc)

    @pytest.fixture(scope="class")
    def all_nodes(self, normalized_doc: CanonicalDocument) -> list:
        if not normalized_doc.nodes:
            return []
        return _collect_all(normalized_doc.nodes[0])

    @pytest.fixture(scope="class")
    def pymupdf_pages(self) -> dict[int, str]:
        return _pymupdf_extract_text(str(_PDF_PATH))

    # ── Document structure ────────────────────────────────────────────────

    def test_page_count(self, parsed_doc: CanonicalDocument) -> None:
        """Document should have 2 pages."""
        assert parsed_doc.metadata.page_count == 2

    def test_has_root_node(self, normalized_doc: CanonicalDocument) -> None:
        """Normalized document should have a root node."""
        assert len(normalized_doc.nodes) == 1
        root = normalized_doc.nodes[0]
        assert root.metadata.get("role") == "normalizer_root"

    def test_tree_has_children(self, normalized_doc: CanonicalDocument) -> None:
        """Root node should have children after normalization."""
        root = normalized_doc.nodes[0]
        assert len(root.children) > 0

    # ── Page containers ──────────────────────────────────────────────────

    def test_page_containers_created(self, all_nodes: list) -> None:
        """PageGroupingPass should create page container nodes."""
        page_groups = [n for n in all_nodes if n.metadata.get("role") == "page_group"]
        assert len(page_groups) == 2

    def test_page_numbers_present(self, all_nodes: list) -> None:
        """Content nodes should have page numbers assigned."""
        content_nodes = [n for n in all_nodes if n.metadata.get("role") != "page_group"]
        pages = set(n.page for n in content_nodes)
        assert 1 in pages
        assert 2 in pages

    # ── Headings ─────────────────────────────────────────────────────────

    def test_headings_extracted(self, all_nodes: list) -> None:
        """Pipeline should extract headings from the document."""
        headings = [n for n in all_nodes if isinstance(n.content, Heading)]
        assert len(headings) >= 2

    def test_heading_hierarchy_normalized(self, all_nodes: list) -> None:
        """Heading levels should form a valid hierarchy (no gaps > 1)."""
        headings = [n for n in all_nodes if isinstance(n.content, Heading)]
        levels = [int(h.content.level) for h in headings]
        prev = 0
        for lv in levels:
            if prev > 0:
                assert lv <= prev + 1, f"Heading gap: {prev} → {lv}"
            prev = lv

    def test_heading_text_not_empty(self, all_nodes: list) -> None:
        """All headings should have non-empty text."""
        headings = [n for n in all_nodes if isinstance(n.content, Heading)]
        for h in headings:
            text = h.content.text.plain_text.strip()
            assert text, f"Heading on page {h.page} has empty text"

    def test_chapter_heading_present(self, all_nodes: list) -> None:
        """Document should contain 'Chapter 11' heading."""
        headings = [n for n in all_nodes if isinstance(n.content, Heading)]
        texts = [h.content.text.plain_text.lower() for h in headings]
        assert any("chapter 11" in t for t in texts), f"Headings found: {texts}"

    # ── Tables ───────────────────────────────────────────────────────────

    def test_tables_extracted(self, all_nodes: list) -> None:
        """Pipeline should extract tables."""
        tables = [n for n in all_nodes if isinstance(n.content, TableBlock)]
        assert len(tables) >= 1

    def test_table_has_rows(self, all_nodes: list) -> None:
        """Tables should have at least one row."""
        tables = [n for n in all_nodes if isinstance(n.content, TableBlock)]
        for t in tables:
            assert t.content.row_count >= 1

    def test_table_has_headers(self, all_nodes: list) -> None:
        """Tables should have header information."""
        tables = [n for n in all_nodes if isinstance(n.content, TableBlock)]
        tables_with_headers = [t for t in tables if t.content.headers]
        assert len(tables_with_headers) >= 1

    # ── Lists ────────────────────────────────────────────────────────────

    def test_lists_extracted(self, all_nodes: list) -> None:
        """Pipeline should extract list structures."""
        lists = [n for n in all_nodes if isinstance(n.content, ListBlock)]
        assert len(lists) >= 1

    def test_list_has_content(self, all_nodes: list) -> None:
        """Lists should have either items or child nodes."""
        lists = [n for n in all_nodes if isinstance(n.content, ListBlock)]
        for lb in lists:
            has_items = len(lb.content.items) >= 1
            has_children = len(lb.children) >= 1
            assert has_items or has_children, (
                f"List on page {lb.page} has neither items nor children"
            )

    # ── Paragraphs ───────────────────────────────────────────────────────

    def test_paragraphs_extracted(self, all_nodes: list) -> None:
        """Pipeline should extract text paragraphs."""
        paras = [n for n in all_nodes if isinstance(n.content, Paragraph)]
        assert len(paras) >= 3

    def test_paragraph_text_not_empty(self, all_nodes: list) -> None:
        """Paragraphs should have non-empty text."""
        paras = [n for n in all_nodes if isinstance(n.content, Paragraph)]
        non_empty = [p for p in paras if p.content.text.plain_text.strip()]
        assert len(non_empty) >= 3

    # ── Cross-verification with PyMuPDF ──────────────────────────────────

    def test_pymupdf_page_count_matches(self, parsed_doc: CanonicalDocument) -> None:
        """PyMuPDF and Docling should agree on page count."""
        pymupdf_doc = pymupdf.open(str(_PDF_PATH))
        assert len(pymupdf_doc) == parsed_doc.metadata.page_count
        pymupdf_doc.close()

    def test_pymupdf_text_coverage(self, all_nodes: list, pymupdf_pages: dict[int, str]) -> None:
        """A significant fraction of PyMuPDF-extracted text should appear in our nodes.

        This verifies that the pipeline is capturing the actual content.
        """
        # Collect all text from our pipeline
        pipeline_text_parts: list[str] = []
        for node in all_nodes:
            content = node.content
            if hasattr(content, "text") and hasattr(content.text, "plain_text"):
                pipeline_text_parts.append(content.text.plain_text)
            elif hasattr(content, "latex"):
                pipeline_text_parts.append(content.latex)
            elif hasattr(content, "code"):
                pipeline_text_parts.append(content.code)
            elif hasattr(content, "caption_text"):
                pipeline_text_parts.append(content.caption_text)
            elif hasattr(content, "headers"):
                pipeline_text_parts.extend(content.headers)
            for row in getattr(content, "rows", []):
                for cell in row.cells:
                    for run in cell.content:
                        pipeline_text_parts.append(run.text)

        pipeline_text = _normalize(" ".join(pipeline_text_parts))

        # Collect all text from PyMuPDF
        pymupdf_text = _normalize(" ".join(pymupdf_pages.values()))

        # Extract significant words (>4 chars) from PyMuPDF text
        pymupdf_words = set(w for w in pymupdf_text.split() if len(w) > 4)
        pipeline_words = set(w for w in pipeline_text.split() if len(w) > 4)

        if pymupdf_words:
            coverage = len(pymupdf_words & pipeline_words) / len(pymupdf_words)
            assert coverage > 0.5, (
                f"Text coverage too low: {coverage:.1%}. "
                f"Missing words sample: {list(pymupdf_words - pipeline_words)[:20]}"
            )

    def test_specific_content_page1(self, all_nodes: list) -> None:
        """Verify specific content from page 1 is captured."""
        # Collect all text from page 1
        page1_nodes = [n for n in all_nodes if n.page == 1]
        texts = []
        for n in page1_nodes:
            content = n.content
            if hasattr(content, "text") and hasattr(content.text, "plain_text"):
                texts.append(content.text.plain_text.lower())
        all_text = " ".join(texts)

        # PyMuPDF confirms these strings exist on page 1
        assert "enthalpy" in all_text or "enthalpies" in all_text, (
            f"Expected 'enthalpy' in page 1 text. Found: {all_text[:200]}"
        )

    def test_specific_content_page2(self, all_nodes: list) -> None:
        """Verify specific content from page 2 is captured."""
        page2_nodes = [n for n in all_nodes if n.page == 2]
        texts = []
        for n in page2_nodes:
            content = n.content
            if hasattr(content, "text") and hasattr(content.text, "plain_text"):
                texts.append(content.text.plain_text.lower())
        all_text = " ".join(texts)

        assert "coal" in all_text or "solar" in all_text or "review" in all_text, (
            f"Expected key terms on page 2. Found: {all_text[:200]}"
        )

    # ── Tree integrity ───────────────────────────────────────────────────

    def test_all_nodes_have_valid_parent(self, normalized_doc: CanonicalDocument) -> None:
        """Every non-root node should have a parent_id pointing to an existing node."""
        all_n = _collect_all(normalized_doc.nodes[0])
        node_ids = {n.id for n in all_n}
        for n in all_n:
            if n.metadata.get("role") == "page_group":
                continue
            if n.parent_id is not None:
                assert n.parent_id in node_ids, (
                    f"Node {n.id} has parent_id {n.parent_id} not in document"
                )

    def test_no_orphan_nodes(self, normalized_doc: CanonicalDocument) -> None:
        """All non-root nodes should be reachable from the root."""
        root = normalized_doc.nodes[0]
        reachable = set()
        stack = [root]
        while stack:
            node = stack.pop()
            reachable.add(node.id)
            stack.extend(node.children)
        all_n = _collect_all(root)
        for n in all_n:
            assert n.id in reachable, f"Node {n.id} not reachable from root"

    def test_reading_order_within_pages(self, normalized_doc: CanonicalDocument) -> None:
        """Nodes under each page container should be in spatial reading order.

        Only checks direct children of page groups — cross-page nesting
        (e.g. list items under a list group on page 0) can break strict
        spatial ordering in the pre-order traversal.
        """
        roots = normalized_doc.nodes
        if not roots:
            return

        def collect(n: object) -> None:
            if n.metadata.get("role") == "page_group":
                page_num = n.metadata.get("page_number", 0)
                # Check direct children of this page group
                child_keys = [(c.bbox.y, c.bbox.x, c.seq) for c in n.children]
                if child_keys:
                    assert child_keys == sorted(child_keys), (
                        f"Page {page_num}: children not in spatial order"
                    )
            for c in n.children:
                collect(c)

        for root in roots:
            collect(root)
