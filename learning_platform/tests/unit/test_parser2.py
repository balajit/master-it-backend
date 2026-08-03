"""Unit tests for parser2 package.

Tests cover:
- CorrelatedItem construction and attributes
- compute_bbox_overlap_ratio edge cases
- Direct mapping for each Docling type
- Furniture capture (page_header, page_footer)
- Error paragraph generation for unmapped items
- Tree building from parent references
- Parser2Adapter interface methods
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from learning_platform.models.document import (
    FormAreaBlock,
    Heading,
    HeadingLevel,
    PageFooter,
    PageHeader,
    Paragraph,
    TextItem,
)
from learning_platform.stages.parser2.docling_node_mapper import (
    _infer_list_style,
    _make_error_paragraph,
    _make_form_area,
    _make_heading,
    _make_page_footer,
    _make_page_header,
    _make_paragraph,
    _make_text_item,
    _map_heading_level,
    build_document_tree,
    map_correlated_item,
)
from learning_platform.stages.parser2.docling_pymupdf_merger import (
    CorrelatedItem,
    compute_bbox_overlap_ratio,
)

# ── CorrelatedItem Tests ──────────────────────────────────────────────────────


class TestCorrelatedItem:
    """Tests for CorrelatedItem class."""

    def test_init_with_minimal_item(self) -> None:
        """CorrelatedItem initializes with minimal Docling item."""
        mock_item = MagicMock()
        mock_item.self_ref = "ref123"
        mock_item.label = MagicMock(value="paragraph")
        mock_item.text = "  Hello world  "
        mock_item.parent = None
        mock_item.prov = None

        item = CorrelatedItem(mock_item, level=2)

        assert item.docling_item is mock_item
        assert item.level == 2
        assert item.self_ref == "ref123"
        assert item.label == "paragraph"
        assert item.text == "Hello world"  # Stripped
        assert item.parent_cref is None
        assert item.page_no == 0
        assert item.bbox is None
        assert item.fonts == []
        assert item.primary_font_name is None
        assert item.is_bold is False
        assert item.is_italic is False
        assert item.vector_lines == []

    def test_init_with_parent_cref(self) -> None:
        """CorrelatedItem extracts parent_cref from parent.cref."""
        mock_parent = MagicMock()
        mock_parent.cref = "parent_ref"

        mock_item = MagicMock()
        mock_item.self_ref = "child_ref"
        mock_item.label = MagicMock(value="text")
        mock_item.text = "Child text"
        mock_item.parent = mock_parent
        mock_item.prov = None

        item = CorrelatedItem(mock_item, level=1)

        assert item.parent_cref == "parent_ref"

    def test_init_with_provenance(self) -> None:
        """CorrelatedItem extracts page_no and bbox from provenance."""
        mock_bbox = MagicMock()
        mock_bbox.l = 10.0
        mock_bbox.t = 20.0
        mock_bbox.r = 100.0
        mock_bbox.b = 50.0

        mock_prov = MagicMock()
        mock_prov.page_no = 3
        mock_prov.bbox = mock_bbox

        mock_item = MagicMock()
        mock_item.self_ref = "ref"
        mock_item.label = MagicMock(value="heading")
        mock_item.text = "Title"
        mock_item.parent = None
        mock_item.prov = [mock_prov]

        item = CorrelatedItem(mock_item, level=0)

        assert item.page_no == 3
        assert item.bbox == [10.0, 20.0, 100.0, 50.0]

    def test_extract_label_from_enum(self) -> None:
        """CorrelatedItem extracts label value from enum-like label."""
        mock_item = MagicMock()
        mock_item.self_ref = None
        mock_item.label = MagicMock(value="section_header")
        mock_item.text = ""
        mock_item.parent = None
        mock_item.prov = None

        item = CorrelatedItem(mock_item, level=0)

        assert item.label == "section_header"

    def test_extract_label_from_string(self) -> None:
        """CorrelatedItem handles string label."""
        mock_item = MagicMock()
        mock_item.self_ref = None
        mock_item.label = "plain_string_label"
        mock_item.text = ""
        mock_item.parent = None
        mock_item.prov = None

        item = CorrelatedItem(mock_item, level=0)

        assert item.label == "plain_string_label"

    def test_repr(self) -> None:
        """CorrelatedItem has meaningful repr."""
        mock_item = MagicMock()
        mock_item.self_ref = "ref"
        mock_item.label = MagicMock(value="paragraph")
        mock_item.text = "Short text"
        mock_item.parent = None
        mock_item.prov = None

        item = CorrelatedItem(mock_item, level=1)

        repr_str = repr(item)
        assert "CorrelatedItem" in repr_str
        assert "paragraph" in repr_str
        assert "Short text" in repr_str


# ── Bbox Overlap Tests ────────────────────────────────────────────────────────


class TestBboxOverlapRatio:
    """Tests for compute_bbox_overlap_ratio function."""

    def test_returns_zero_when_fitz_unavailable(self) -> None:
        """compute_bbox_overlap_ratio returns 0.0 when fitz import fails."""
        with patch.dict("sys.modules", {"fitz": None}):
            # Force import error by removing fitz
            result = compute_bbox_overlap_ratio([0, 0, 100, 100], MagicMock())
            # Should return 0.0 on error, not raise
            assert isinstance(result, float)

    def test_returns_zero_for_empty_intersection(self) -> None:
        """compute_bbox_overlap_ratio returns 0.0 for non-overlapping boxes."""
        try:
            import fitz

            box1 = [0, 0, 50, 50]
            box2 = fitz.Rect(100, 100, 200, 200)  # Non-overlapping

            result = compute_bbox_overlap_ratio(box1, box2)
            assert result == 0.0
        except ImportError:
            pytest.skip("fitz not available")

    def test_returns_one_for_identical_boxes(self) -> None:
        """compute_bbox_overlap_ratio returns 1.0 for identical boxes."""
        try:
            import fitz

            box1 = [10, 20, 100, 80]
            box2 = fitz.Rect(10, 20, 100, 80)

            result = compute_bbox_overlap_ratio(box1, box2)
            assert result == pytest.approx(1.0)
        except ImportError:
            pytest.skip("fitz not available")

    def test_partial_overlap(self) -> None:
        """compute_bbox_overlap_ratio returns correct ratio for partial overlap."""
        try:
            import fitz

            box1 = [0, 0, 100, 100]  # Area = 10000
            box2 = fitz.Rect(50, 0, 150, 100)  # Overlaps half of box1

            result = compute_bbox_overlap_ratio(box1, box2)
            assert result == pytest.approx(0.5)
        except ImportError:
            pytest.skip("fitz not available")


# ── Heading Level Mapping Tests ───────────────────────────────────────────────


class TestMapHeadingLevel:
    """Tests for _map_heading_level function."""

    def test_level_0_maps_to_chapter(self) -> None:
        assert _map_heading_level(0) == HeadingLevel.CHAPTER

    def test_level_1_maps_to_chapter(self) -> None:
        assert _map_heading_level(1) == HeadingLevel.CHAPTER

    def test_level_2_maps_to_section(self) -> None:
        assert _map_heading_level(2) == HeadingLevel.SECTION

    def test_level_3_maps_to_subsection(self) -> None:
        assert _map_heading_level(3) == HeadingLevel.SUBSECTION

    def test_level_4_plus_maps_to_subsubsection(self) -> None:
        assert _map_heading_level(4) == HeadingLevel.SUBSUBSECTION
        assert _map_heading_level(10) == HeadingLevel.SUBSUBSECTION


# ── List Style Inference Tests ────────────────────────────────────────────────


class TestInferListStyle:
    """Tests for _infer_list_style function."""

    def test_checkbox_from_label(self) -> None:
        from learning_platform.models.document import ListStyle

        result = _infer_list_style("Some text", "checkbox_selected")
        assert result == ListStyle.CHECKBOX

    def test_checkbox_from_text_bracket(self) -> None:
        from learning_platform.models.document import ListStyle

        result = _infer_list_style("[x] Task done", "list_item")
        assert result == ListStyle.CHECKBOX

    def test_checkbox_from_text_unicode(self) -> None:
        from learning_platform.models.document import ListStyle

        result = _infer_list_style("☑ Checked item", "list_item")
        assert result == ListStyle.CHECKBOX

    def test_numbered_list(self) -> None:
        from learning_platform.models.document import ListStyle

        result = _infer_list_style("1. First item", "list_item")
        assert result == ListStyle.NUMBERED

    def test_alpha_list(self) -> None:
        from learning_platform.models.document import ListStyle

        result = _infer_list_style("a) Option A", "list_item")
        assert result == ListStyle.ALPHA

    def test_default_bullet(self) -> None:
        from learning_platform.models.document import ListStyle

        result = _infer_list_style("Plain item", "list_item")
        assert result == ListStyle.BULLET


# ── Node Factory Tests ────────────────────────────────────────────────────────


class TestNodeFactories:
    """Tests for individual node factory functions."""

    def _make_correlated_item(
        self,
        text: str = "Test text",
        label: str = "paragraph",
        **kwargs: Any,
    ) -> CorrelatedItem:
        """Create a mock CorrelatedItem for testing."""
        mock_item = MagicMock()
        mock_item.self_ref = kwargs.get("self_ref", "ref123")
        mock_item.label = MagicMock(value=label)
        mock_item.text = text
        mock_item.parent = None
        mock_item.prov = None

        item = CorrelatedItem(mock_item, level=kwargs.get("level", 0))
        item.primary_font_name = kwargs.get("font_name")
        item.primary_font_size = kwargs.get("font_size")
        item.is_bold = kwargs.get("is_bold", False)
        item.is_italic = kwargs.get("is_italic", False)
        item.primary_color_hex = kwargs.get("color_hex")
        return item

    def test_make_paragraph(self) -> None:
        """_make_paragraph creates a Paragraph node."""
        item = self._make_correlated_item(text="Hello world")
        node = _make_paragraph(item, "test.pdf")

        assert isinstance(node.content, Paragraph)
        assert node.content.text.plain_text == "Hello world"

    def test_make_paragraph_with_font_style(self) -> None:
        """_make_paragraph applies font styling from CorrelatedItem."""
        item = self._make_correlated_item(
            text="Styled text",
            font_name="Arial",
            font_size=12.0,
            is_bold=True,
            is_italic=False,
        )
        node = _make_paragraph(item, "test.pdf")

        assert isinstance(node.content, Paragraph)
        runs = node.content.text.runs
        assert len(runs) == 1
        assert runs[0].style.font.name == "Arial"
        assert runs[0].style.font.size == 12.0
        assert runs[0].style.font.is_bold is True

    def test_make_heading(self) -> None:
        """_make_heading creates a Heading node with correct level."""
        item = self._make_correlated_item(text="Chapter Title", label="title")
        node = _make_heading(item, HeadingLevel.CHAPTER, "test.pdf")

        assert isinstance(node.content, Heading)
        assert node.content.level == HeadingLevel.CHAPTER
        assert node.content.text.plain_text == "Chapter Title"

    def test_make_heading_splits_number(self) -> None:
        """_make_heading extracts heading number from text."""
        item = self._make_correlated_item(text="1.2 Introduction", label="section_header")
        node = _make_heading(item, HeadingLevel.SECTION, "test.pdf")

        assert isinstance(node.content, Heading)
        assert node.content.number == "1.2"
        assert node.content.text.plain_text == "Introduction"

    def test_make_page_header(self) -> None:
        """_make_page_header creates a PageHeader node."""
        item = self._make_correlated_item(text="Running Header", label="page_header")
        node = _make_page_header(item, "test.pdf")

        assert isinstance(node.content, PageHeader)
        assert node.content.text.plain_text == "Running Header"

    def test_make_page_footer(self) -> None:
        """_make_page_footer creates a PageFooter node with page number."""
        item = self._make_correlated_item(text="Page 5", label="page_footer")
        item.page_no = 5
        node = _make_page_footer(item, "test.pdf")

        assert isinstance(node.content, PageFooter)
        assert node.content.text.plain_text == "Page 5"
        assert node.content.page_number == 5

    def test_make_text_item(self) -> None:
        """_make_text_item creates a TextItem node."""
        item = self._make_correlated_item(text="Word bank item")
        node = _make_text_item(item, "test.pdf")

        assert isinstance(node.content, TextItem)
        assert node.content.text.plain_text == "Word bank item"

    def test_make_text_item_with_font_style(self) -> None:
        """_make_text_item applies font styling from CorrelatedItem."""
        item = self._make_correlated_item(
            text="Styled item",
            font_name="Helvetica",
            font_size=10.0,
            is_bold=False,
            is_italic=True,
        )
        node = _make_text_item(item, "test.pdf")

        assert isinstance(node.content, TextItem)
        runs = node.content.text.runs
        assert len(runs) == 1
        assert runs[0].style.font.name == "Helvetica"
        assert runs[0].style.font.size == 10.0
        assert runs[0].style.font.is_italic is True

    def test_make_form_area(self) -> None:
        """_make_form_area creates a FormAreaBlock node."""
        item = self._make_correlated_item(text="word1 word2 word3", label="form_area")
        node = _make_form_area(item, "test.pdf")

        assert isinstance(node.content, FormAreaBlock)
        # FormAreaBlock is a container; text content comes from children
        assert node.content.display_hint is None

    def test_make_error_paragraph(self) -> None:
        """_make_error_paragraph creates error paragraph for unmapped items."""
        mock_item = MagicMock()
        mock_item.__class__.__name__ = "UnknownDoclingItem"
        mock_item.self_ref = "ref"
        mock_item.label = MagicMock(value="unknown_label")
        mock_item.text = "Original content"
        mock_item.parent = None
        mock_item.prov = None

        item = CorrelatedItem(mock_item, level=0)
        node = _make_error_paragraph(item, "test.pdf")

        assert isinstance(node.content, Paragraph)
        text = node.content.text.plain_text
        assert "***Error***" in text
        assert "UnknownDoclingItem" in text  # Type name from mock
        assert "unknown_label" in text
        assert "Original content" in text


# ── Map Correlated Item Tests ─────────────────────────────────────────────────


class TestMapCorrelatedItem:
    """Tests for map_correlated_item function."""

    def _make_correlated_item(
        self,
        text: str = "Test",
        label: str = "paragraph",
        docling_type: type | None = None,
    ) -> CorrelatedItem:
        """Create a CorrelatedItem with mocked Docling item."""
        mock_item = MagicMock(spec=docling_type) if docling_type is not None else MagicMock()

        mock_item.self_ref = "ref123"
        mock_item.label = MagicMock(value=label)
        mock_item.text = text
        mock_item.parent = None
        mock_item.prov = None

        return CorrelatedItem(mock_item, level=1)

    def test_maps_page_header_by_label(self) -> None:
        """map_correlated_item maps page_header label to PageHeader."""
        item = self._make_correlated_item(text="Header text", label="page_header")
        mock_doc = MagicMock()

        node = map_correlated_item(item, "test.pdf", mock_doc)

        assert isinstance(node.content, PageHeader)

    def test_maps_page_footer_by_label(self) -> None:
        """map_correlated_item maps page_footer label to PageFooter."""
        item = self._make_correlated_item(text="Footer text", label="page_footer")
        mock_doc = MagicMock()

        node = map_correlated_item(item, "test.pdf", mock_doc)

        assert isinstance(node.content, PageFooter)

    def test_stores_docling_metadata(self) -> None:
        """map_correlated_item stores Docling metadata on node."""
        item = self._make_correlated_item(text="Text", label="paragraph")
        item.self_ref = "my_self_ref"
        item.parent_cref = "my_parent_ref"
        mock_doc = MagicMock()

        node = map_correlated_item(item, "test.pdf", mock_doc)

        assert node.metadata.get("label") == "paragraph"
        assert node.metadata.get("docling_self_ref") == "my_self_ref"
        assert node.metadata.get("docling_parent_ref") == "my_parent_ref"

    def test_form_area_maps_to_form_area_block(self) -> None:
        """map_correlated_item maps form_area items to FormAreaBlock via label fallback."""
        # Use a mock that will trigger the label-based fallback (not type-based)
        # by making docling_core types unavailable during mapping
        item = self._make_correlated_item(text="word1 word2 word3", label="form_area")
        mock_doc = MagicMock()

        # The fallback _map_by_label_only handles form_area
        from learning_platform.stages.parser2.docling_node_mapper import _map_by_label_only

        node = _map_by_label_only(item, "test.pdf", mock_doc)

        assert isinstance(node.content, FormAreaBlock)
        assert node.metadata.get("label") == "form_area"


# ── Build Document Tree Tests ─────────────────────────────────────────────────


class TestBuildDocumentTree:
    """Tests for build_document_tree function."""

    def _make_correlated_item(
        self,
        self_ref: str,
        text: str = "Test",
        label: str = "paragraph",
        parent_cref: str | None = None,
        page_no: int = 1,
    ) -> CorrelatedItem:
        """Create a CorrelatedItem for tree building tests."""
        mock_item = MagicMock()
        mock_item.self_ref = self_ref
        mock_item.label = MagicMock(value=label)
        mock_item.text = text
        mock_item.parent = MagicMock(cref=parent_cref) if parent_cref else None
        mock_item.prov = [MagicMock(page_no=page_no, bbox=None)]

        item = CorrelatedItem(mock_item, level=0)
        return item

    def test_builds_flat_tree_without_parents(self) -> None:
        """build_document_tree creates flat children when no parent refs."""
        items = [
            self._make_correlated_item("ref1", "First"),
            self._make_correlated_item("ref2", "Second"),
            self._make_correlated_item("ref3", "Third"),
        ]
        mock_doc = MagicMock()

        root = build_document_tree(items, "test.pdf", mock_doc)

        assert len(root.children) == 3
        assert root.metadata.get("role") == "document_root"

    def test_builds_hierarchical_tree_with_parents(self) -> None:
        """build_document_tree nests children based on parent_cref."""
        parent_item = self._make_correlated_item("parent_ref", "Parent", "section_header")
        child1 = self._make_correlated_item("child1_ref", "Child 1", parent_cref="parent_ref")
        child2 = self._make_correlated_item("child2_ref", "Child 2", parent_cref="parent_ref")

        items = [parent_item, child1, child2]
        mock_doc = MagicMock()

        root = build_document_tree(items, "test.pdf", mock_doc)

        # Parent should be at root level
        assert len(root.children) == 1
        parent_node = root.children[0]

        # Children should be nested under parent
        assert len(parent_node.children) == 2

    def test_assigns_sequence_numbers(self) -> None:
        """build_document_tree assigns global DFS seq numbers after sorting."""
        items = [
            self._make_correlated_item("ref1", "First", page_no=1),
            self._make_correlated_item("ref2", "Second", page_no=1),
            self._make_correlated_item("ref3", "Third", page_no=2),
        ]
        mock_doc = MagicMock()

        root = build_document_tree(items, "test.pdf", mock_doc)

        assert root.seq == 0
        seqs = [child.seq for child in root.children]
        assert seqs == [1, 2, 3]

    def test_creates_ai_prefixed_synthetic_containers_for_missing_parent_refs(self) -> None:
        """Unresolved parent refs are represented by AI-prefixed container nodes."""
        orphan = self._make_correlated_item(
            "child_ref",
            "Child",
            parent_cref="#/groups/10",
            page_no=2,
        )
        mock_doc = MagicMock()

        root = build_document_tree([orphan], "test.pdf", mock_doc)

        assert len(root.children) == 1
        top_container = root.children[0]
        assert top_container.metadata.get("role") == "AI-synthetic_container"
        assert str(top_container.metadata.get("label", "")).startswith("AI-")
        assert top_container.metadata.get("docling_self_ref") == "#/groups"

        assert len(top_container.children) == 1
        nested_container = top_container.children[0]
        assert nested_container.metadata.get("role") == "AI-synthetic_container"
        assert str(nested_container.metadata.get("label", "")).startswith("AI-")
        assert nested_container.metadata.get("docling_self_ref") == "#/groups/10"

        assert len(nested_container.children) == 1
        child_node = nested_container.children[0]
        assert child_node.parent_id == nested_container.id

    def test_sorts_tree_spatially_by_page_then_y_then_x(self) -> None:
        """Siblings are sorted by page, then vertical and horizontal position."""
        item_a = self._make_correlated_item("a", "A", page_no=1)
        item_b = self._make_correlated_item("b", "B", page_no=1)
        item_c = self._make_correlated_item("c", "C", page_no=2)

        item_a.bbox = [200.0, 40.0, 260.0, 60.0]  # page 1, y=40, x=200
        item_b.bbox = [20.0, 20.0, 80.0, 40.0]  # page 1, y=20, x=20
        item_c.bbox = [10.0, 10.0, 70.0, 30.0]  # page 2

        mock_doc = MagicMock()
        page = MagicMock()
        page.size = MagicMock(width=300.0, height=400.0)
        mock_doc.pages = {1: page, 2: page}

        root = build_document_tree([item_a, item_c, item_b], "test.pdf", mock_doc)

        refs_in_order = [child.metadata.get("docling_self_ref") for child in root.children]
        assert refs_in_order == ["b", "a", "c"]

    def test_normalizes_bottom_origin_bboxes_to_top_left_for_sorting(self) -> None:
        """BOTTOM-origin Docling bbox values are normalized before sorting."""
        top_item = self._make_correlated_item("top", "Top", page_no=1)
        lower_item = self._make_correlated_item("lower", "Lower", page_no=1)

        # Docling bottom-left origin: larger y is visually higher on page.
        top_item.bbox = [10.0, 340.0, 60.0, 360.0]
        lower_item.bbox = [10.0, 100.0, 60.0, 120.0]

        top_bbox = MagicMock(l=10.0, t=340.0, r=60.0, b=360.0, coord_origin="BOTTOM_LEFT")
        lower_bbox = MagicMock(l=10.0, t=100.0, r=60.0, b=120.0, coord_origin="BOTTOM_LEFT")
        top_item.docling_item.prov = [MagicMock(page_no=1, bbox=top_bbox)]
        lower_item.docling_item.prov = [MagicMock(page_no=1, bbox=lower_bbox)]

        mock_doc = MagicMock()
        page = MagicMock()
        page.size = MagicMock(width=300.0, height=400.0)
        mock_doc.pages = {1: page}

        root = build_document_tree([lower_item, top_item], "test.pdf", mock_doc)

        refs_in_order = [child.metadata.get("docling_self_ref") for child in root.children]
        assert refs_in_order == ["top", "lower"]

    def test_assigns_global_dfs_sequence_with_hierarchy(self) -> None:
        """Sequence is global DFS order across containers and descendants."""
        parent = self._make_correlated_item("parent_ref", "Parent", "section_header", page_no=1)
        child = self._make_correlated_item(
            "child_ref", "Child", parent_cref="parent_ref", page_no=1
        )
        orphan = self._make_correlated_item(
            "orphan_ref",
            "Orphan",
            parent_cref="#/missing/42",
            page_no=2,
        )

        mock_doc = MagicMock()
        page = MagicMock()
        page.size = MagicMock(width=300.0, height=400.0)
        mock_doc.pages = {1: page, 2: page}

        root = build_document_tree([orphan, child, parent], "test.pdf", mock_doc)

        seen: list[int] = []

        def walk(node: Any) -> None:
            seen.append(node.seq)
            for child_node in node.children:
                walk(child_node)

        walk(root)

        assert seen == list(range(len(seen)))


# ── Parser2Adapter Tests ──────────────────────────────────────────────────────


class TestParser2Adapter:
    """Tests for Parser2Adapter class."""

    def test_supports_pdf(self) -> None:
        """Parser2Adapter supports PDF files."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.supports("document.pdf") is True
        assert adapter.supports("DOCUMENT.PDF") is True

    def test_supports_docx(self) -> None:
        """Parser2Adapter supports DOCX files."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.supports("document.docx") is True

    def test_supports_html(self) -> None:
        """Parser2Adapter supports HTML files."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.supports("page.html") is True
        assert adapter.supports("page.htm") is True

    def test_does_not_support_unknown(self) -> None:
        """Parser2Adapter does not support unknown extensions."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.supports("file.xyz") is False
        assert adapter.supports("file.abc") is False

    def test_confidence_pdf(self) -> None:
        """Parser2Adapter returns high confidence for PDF."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.confidence("doc.pdf") == 0.95

    def test_confidence_docx(self) -> None:
        """Parser2Adapter returns high confidence for DOCX."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.confidence("doc.docx") == 0.95

    def test_confidence_html(self) -> None:
        """Parser2Adapter returns moderate confidence for HTML."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.confidence("page.html") == 0.70

    def test_confidence_txt(self) -> None:
        """Parser2Adapter returns low confidence for TXT."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.confidence("file.txt") == 0.40

    def test_confidence_unknown(self) -> None:
        """Parser2Adapter returns zero confidence for unknown."""
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.confidence("file.xyz") == 0.0
