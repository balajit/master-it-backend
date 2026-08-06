"""Unit tests for parser2 bridge-tree mapping and ordering."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from learning_platform.models.document import ListBlock, ListStyle, TableBlock
from learning_platform.stages.parser2.docling_node_mapper import build_document_tree
from learning_platform.stages.parser2.docling_pymupdf_merger import (
    BridgeDocument,
    BridgeNode,
    DoclingPyMuPDFMerger,
    compute_bbox_overlap_ratio,
)


def _bridge_node(
    *,
    self_ref: str,
    parent_cref: str | None,
    label: str,
    name: str,
    text: str,
    page_no: int,
    norm_left: float,
    norm_top: float,
    norm_right: float,
    norm_bottom: float,
    level: int = 0,
    is_synthetic: bool = False,
    metadata: dict[str, Any] | None = None,
) -> BridgeNode:
    return BridgeNode(
        self_ref=self_ref,
        parent_cref=parent_cref,
        label=label,
        name=name,
        text=text,
        page_no=page_no,
        norm_left=norm_left,
        norm_top=norm_top,
        norm_right=norm_right,
        norm_bottom=norm_bottom,
        level=level,
        is_synthetic=is_synthetic,
        metadata=metadata or {},
    )


class TestOverlapRatio:
    def test_returns_zero_for_no_overlap(self) -> None:
        try:
            import fitz

            result = compute_bbox_overlap_ratio([0, 0, 10, 10], fitz.Rect(20, 20, 30, 30))
            assert result == 0.0
        except ImportError:
            pytest.skip("fitz not available")

    def test_returns_one_for_identical_boxes(self) -> None:
        try:
            import fitz

            result = compute_bbox_overlap_ratio([1, 2, 9, 12], fitz.Rect(1, 2, 9, 12))
            assert result == pytest.approx(1.0)
        except ImportError:
            pytest.skip("fitz not available")


class TestBridgeTreeBuilding:
    def test_builds_synthetic_parent_chain_for_missing_ref(self) -> None:
        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)
        merger.body_ref = "#/body"
        merger.ref_to_node = {}
        merger.nodes_by_id = {}

        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        merger.ref_to_node["#/body"] = root
        merger.nodes_by_id[root.id] = root

        leaf = _bridge_node(
            self_ref="#/texts/1",
            parent_cref="#/groups/10",
            label="paragraph",
            name="TextItem",
            text="leaf",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.2,
            norm_bottom=0.12,
        )

        DoclingPyMuPDFMerger._attach_parent_child(merger, [leaf], root)

        assert len(root.children) == 1
        container = root.children[0]
        assert container.is_synthetic is True
        assert container.metadata.get("role") == "AI-synthetic_container"
        assert len(container.children) == 1

    def test_covered_by_picture_detects_overlapping_picture(self) -> None:
        picture = _bridge_node(
            self_ref="#/pictures/0",
            parent_cref="#/body",
            label="picture",
            name="PictureItem",
            text="",
            page_no=2,
            norm_left=0.2,
            norm_top=0.2,
            norm_right=0.5,
            norm_bottom=0.5,
        )
        covered = DoclingPyMuPDFMerger._covered_by_picture(
            (0.25, 0.25, 0.45, 0.45),
            [picture],
        )
        assert covered is True

    def test_covered_by_picture_ignores_disjoint_picture(self) -> None:
        picture = _bridge_node(
            self_ref="#/pictures/0",
            parent_cref="#/body",
            label="picture",
            name="PictureItem",
            text="",
            page_no=2,
            norm_left=0.2,
            norm_top=0.2,
            norm_right=0.5,
            norm_bottom=0.5,
        )
        covered = DoclingPyMuPDFMerger._covered_by_picture(
            (0.6, 0.6, 0.9, 0.9),
            [picture],
        )
        assert covered is False

    def test_extract_fitz_fallback_images_adds_missing_picture(self) -> None:
        from unittest.mock import MagicMock  # noqa: PLC0415

        import fitz  # noqa: PLC0415

        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)
        merger.fitz_doc = [MagicMock()]

        pdf_page = merger.fitz_doc[0]
        pdf_page.rect.width = 612.0
        pdf_page.rect.height = 792.0
        pdf_page.get_images.return_value = [(42,)]
        pdf_page.get_image_rects.return_value = [fitz.Rect(100, 100, 172, 172)]

        pixmap = MagicMock()
        pixmap.width = 72
        pixmap.height = 72
        pixmap.samples = b"\xff\x00\x00" * (72 * 72)
        pdf_page.get_pixmap.return_value = pixmap

        all_nodes: list[BridgeNode] = []
        merger.nodes_by_id = {}
        DoclingPyMuPDFMerger._extract_fitz_fallback_images(merger, all_nodes)

        assert len(all_nodes) == 1
        node = all_nodes[0]
        assert node.name == "PictureItem"
        assert node.label == "picture"
        assert node.is_synthetic is True
        assert node.page_no == 1
        assert node.is_image is True
        assert node.image_pil is not None
        assert node.metadata["image_source"] == "fitz_fallback"

    def test_extract_fitz_fallback_images_skips_covered_picture(self) -> None:
        from unittest.mock import MagicMock  # noqa: PLC0415

        import fitz  # noqa: PLC0415

        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)
        merger.fitz_doc = [MagicMock()]

        pdf_page = merger.fitz_doc[0]
        pdf_page.rect.width = 612.0
        pdf_page.rect.height = 792.0
        pdf_page.get_images.return_value = [(42,)]
        pdf_page.get_image_rects.return_value = [fitz.Rect(100, 100, 172, 172)]

        existing = _bridge_node(
            self_ref="#/pictures/0",
            parent_cref="#/body",
            label="picture",
            name="PictureItem",
            text="",
            page_no=1,
            norm_left=100 / 612,
            norm_top=100 / 792,
            norm_right=172 / 612,
            norm_bottom=172 / 792,
        )
        all_nodes: list[BridgeNode] = [existing]
        merger.nodes_by_id = {}
        DoclingPyMuPDFMerger._extract_fitz_fallback_images(merger, all_nodes)

        assert len(all_nodes) == 1

    def test_column_aware_sort_orders_by_page_column_then_y(self) -> None:
        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)
        root = BridgeNode(label="AI-BODY", name="Body")

        right_top = _bridge_node(
            self_ref="#/texts/right-top",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="right-top",
            page_no=1,
            norm_left=0.75,
            norm_top=0.10,
            norm_right=0.90,
            norm_bottom=0.14,
        )
        left_low = _bridge_node(
            self_ref="#/texts/left-low",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="left-low",
            page_no=1,
            norm_left=0.05,
            norm_top=0.25,
            norm_right=0.20,
            norm_bottom=0.30,
        )
        page_two = _bridge_node(
            self_ref="#/texts/page-two",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="page-two",
            page_no=2,
            norm_left=0.05,
            norm_top=0.05,
            norm_right=0.20,
            norm_bottom=0.08,
        )

        root.children = [right_top, page_two, left_low]

        # Assign column_no manually — left-side nodes get col 0, right-side col 1.
        # In real usage _assign_page_columns does this from bounding box centers.
        left_low.column_no = 0  # norm_left=0.05 → left column
        right_top.column_no = 1  # norm_left=0.75 → right column
        page_two.column_no = 0

        DoclingPyMuPDFMerger._sort_tree_spatially(merger, root)

        # Expected order: left_low (p1, col0, y=0.25), right_top (p1, col1, y=0.10), page_two (p2)
        assert [child.text for child in root.children] == ["left-low", "right-top", "page-two"]

    def test_assign_page_columns_splits_into_columns(self) -> None:
        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)

        left = _bridge_node(
            self_ref="#/texts/left",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="left",
            page_no=1,
            norm_left=0.05,
            norm_top=0.10,
            norm_right=0.45,
            norm_bottom=0.20,
        )
        right = _bridge_node(
            self_ref="#/texts/right",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="right",
            page_no=1,
            norm_left=0.55,
            norm_top=0.10,
            norm_right=0.95,
            norm_bottom=0.20,
        )

        DoclingPyMuPDFMerger._assign_page_columns(merger, [left, right], num_columns=2)

        # left center_x ≈ 0.25, right center_x ≈ 0.75 → different columns
        assert left.column_no != right.column_no
        assert left.column_no < right.column_no  # left col < right col

    def test_assign_page_columns_no_op_when_no_valid_nodes(self) -> None:
        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)
        # node with no valid bbox
        no_bbox = BridgeNode(label="paragraph", name="TextItem", text="orphan")
        DoclingPyMuPDFMerger._assign_page_columns(merger, [no_bbox], num_columns=2)
        assert no_bbox.column_no == 0  # unchanged default

    def test_assign_page_columns_single_column_page_stays_in_column_zero(self) -> None:
        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)

        wide = _bridge_node(
            self_ref="#/texts/wide",
            parent_cref="#/body",
            label="section_header",
            name="SectionHeaderItem",
            text="wide heading",
            page_no=1,
            norm_left=0.127,
            norm_top=0.104,
            norm_right=0.611,
            norm_bottom=0.12,
        )
        short = _bridge_node(
            self_ref="#/texts/short",
            parent_cref="#/body",
            label="text",
            name="TextItem",
            text="short line",
            page_no=1,
            norm_left=0.127,
            norm_top=0.174,
            norm_right=0.436,
            norm_bottom=0.19,
        )
        list_group = _bridge_node(
            self_ref="#/groups/1",
            parent_cref="#/body",
            label="list",
            name="ListGroup",
            text="",
            page_no=1,
            norm_left=0.127,
            norm_top=0.200,
            norm_right=0.443,
            norm_bottom=0.26,
        )

        # Left-aligned lines with overlapping x-intervals form a single column
        # even though the wide line extends further right.
        DoclingPyMuPDFMerger._assign_page_columns(merger, [wide, short, list_group], num_columns=2)
        assert wide.column_no == 0
        assert short.column_no == 0
        assert list_group.column_no == 0

    def test_propagates_bounds_from_nested_children(self) -> None:
        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)
        root = BridgeNode(label="AI-BODY", name="Body")
        container = BridgeNode(label="AI-CONTAINER", name="SyntheticContainer", is_synthetic=True)
        child = _bridge_node(
            self_ref="#/texts/child",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="child",
            page_no=3,
            norm_left=0.2,
            norm_top=0.15,
            norm_right=0.45,
            norm_bottom=0.3,
        )
        container.children.append(child)
        root.children.append(container)

        DoclingPyMuPDFMerger._propagate_bounds(merger, root)

        assert container.page_no == 3
        assert container.norm_left == pytest.approx(0.2)
        assert container.norm_top == pytest.approx(0.15)
        assert container.norm_right == pytest.approx(0.45)
        assert container.norm_bottom == pytest.approx(0.3)


class TestTableCellExtraction:
    def test_extract_table_cell_nodes_uses_bbox_fallback_when_no_prov(self) -> None:
        merger = DoclingPyMuPDFMerger.__new__(DoclingPyMuPDFMerger)
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        table_node = BridgeNode(
            self_ref="#/tables/0",
            parent_cref="#/body",
            label="table",
            name="TableItem",
            level=1,
        )
        merger.body_ref = "#/body"
        merger.ref_to_node = {"#/body": root, "#/tables/0": table_node}
        merger.nodes_by_id = {root.id: root, table_node.id: table_node}
        root.children.append(table_node)

        class FakeBBox:
            l: float = 124.8
            t: float = 255.74
            r: float = 269.85
            b: float = 264.99
            coord_origin: str = "TOPLEFT"

        class FakeCell:
            def __init__(self, row: int, col: int, text: str, header: bool) -> None:
                self.text = text
                self.bbox = FakeBBox()
                self.start_row_offset_idx = row
                self.start_col_offset_idx = col
                self.row_span = 1
                self.col_span = 1
                self.column_header = header

        class FakeData:
            table_cells = [
                FakeCell(0, 0, "Header A", True),
                FakeCell(0, 1, "Header B", True),
            ]

        class FakeTable:
            self_ref = "#/tables/0"
            data = FakeData()

        class FakeBBox2:
            height: float = 792.0
            width: float = 612.0

        class FakePdfPage:
            rect = FakeBBox2()

        class FakeFitzDoc:
            def __getitem__(self, index: int) -> FakePdfPage:
                return FakePdfPage()

        class FakeStyleCache:
            def query_style(self, **_: Any) -> dict[str, Any]:
                return {
                    "font_name": "Helvetica-Bold",
                    "font_size": 10.0,
                    "color_hex": "#000000",
                    "is_bold": True,
                    "is_italic": False,
                    "fitz_text": "Header A",
                }

        merger.docling_doc = type("FakeDoc", (), {"tables": [FakeTable()]})()
        merger.fitz_doc = FakeFitzDoc()
        merger.page_style_caches = {1: FakeStyleCache()}

        DoclingPyMuPDFMerger._extract_table_cell_nodes(merger, root)

        assert len(root.children) == 1
        table_node = root.children[0]
        assert table_node.label == "table"
        assert len(table_node.children) == 1

        row_node = table_node.children[0]
        assert row_node.label == "AI-TABLE_ROW"
        assert len(row_node.children) == 2

        header_cell = row_node.children[0]
        assert header_cell.label == "AI-TABLE_CELL"
        assert header_cell.metadata["is_header"] is True
        assert header_cell.page_no == 1
        assert header_cell.norm_left > 0.0
        assert header_cell.norm_top > 0.0
        assert header_cell.norm_right < 1.0
        assert header_cell.norm_bottom < 1.0
        assert header_cell.is_bold is True
        assert header_cell.font_name == "Helvetica-Bold"


class TestBridgeToCanonicalMapping:
    def _build_table_bridge(self) -> BridgeDocument:
        """Build a bridge tree with a 2x2 table (header row + body row)."""
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")

        table = _bridge_node(
            self_ref="#/tables/0",
            parent_cref="#/body",
            label="table",
            name="TableItem",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.8,
        )
        root.children.append(table)

        for row_idx, (cells, row_metadata) in enumerate(
            [
                (
                    [("Header A", True), ("Header B", True)],
                    {"role": "AI-table_row", "table_row_index": 0},
                ),
                (
                    [("Body A1", False), ("Body B1", False)],
                    {"role": "AI-table_row", "table_row_index": 1},
                ),
            ]
        ):
            row = _bridge_node(
                self_ref=f"#/tables/0/rows/{row_idx}",
                parent_cref="#/tables/0",
                label="AI-TABLE_ROW",
                name="TableRowContainer",
                text="",
                page_no=1,
                norm_left=0.1,
                norm_top=0.1 + row_idx * 0.3,
                norm_right=0.9,
                norm_bottom=0.2 + row_idx * 0.3,
                is_synthetic=True,
                metadata=row_metadata,
            )
            table.children.append(row)
            for col_idx, (text, is_header) in enumerate(cells):
                cell = _bridge_node(
                    self_ref=f"#/tables/0/rows/{row_idx}/cells/{col_idx}",
                    parent_cref=f"#/tables/0/rows/{row_idx}",
                    label="AI-TABLE_CELL",
                    name="TableCell",
                    text=text,
                    page_no=1,
                    norm_left=0.1 + col_idx * 0.4,
                    norm_top=0.1 + row_idx * 0.3,
                    norm_right=0.3 + col_idx * 0.4,
                    norm_bottom=0.2 + row_idx * 0.3,
                    metadata={
                        "role": "AI-table_cell",
                        "table_row_index": row_idx,
                        "table_col_index": col_idx,
                        "row_span": 1,
                        "col_span": 1,
                        "is_header": is_header,
                    },
                )
                if row_idx == 0 and col_idx == 0:
                    cell.font_name = "Helvetica-Bold"
                    cell.font_size = 10.0
                    cell.is_bold = True
                row.children.append(cell)

        return BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1)

    def test_table_item_maps_to_populated_table_block(self) -> None:
        bridge = self._build_table_bridge()
        canonical_root = build_document_tree(bridge, "test.pdf")

        assert len(canonical_root.children) == 1
        table_node = canonical_root.children[0]
        assert isinstance(table_node.content, TableBlock)

        content = table_node.content
        assert content.row_count == 2
        assert content.column_count == 2
        assert content.headers == ["Header A", "Header B"]

        header_row, body_row = content.rows
        assert header_row.is_header is True
        assert body_row.is_header is False

        assert [c.content[0].text for c in header_row.cells] == ["Header A", "Header B"]
        assert [c.header for c in header_row.cells] == [True, True]
        assert [c.content[0].text for c in body_row.cells] == ["Body A1", "Body B1"]
        assert [c.header for c in body_row.cells] == [False, False]

        # Font styling from the bridge cell is preserved on the TextRun.
        styled = header_row.cells[0].content[0].style
        assert styled.font.name == "Helvetica-Bold"
        assert styled.font.is_bold is True

        # Rows/cells are folded into the block, not duplicated as children.
        assert table_node.children == []

    def test_synthetic_picture_maps_to_figure_with_image_data(self) -> None:
        try:
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            pytest.skip("Pillow not installed")

        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        picture = _bridge_node(
            self_ref=None,
            parent_cref=None,
            label="picture",
            name="PictureItem",
            text="",
            page_no=2,
            norm_left=0.2,
            norm_top=0.2,
            norm_right=0.5,
            norm_bottom=0.5,
            level=1,
            is_synthetic=True,
            metadata={"role": "AI-synthetic_picture", "image_source": "fitz_fallback"},
        )
        picture.image_pil = Image.new("RGB", (4, 4), color=(255, 0, 0))
        picture.image_format = "PNG"
        picture.image_width = 4
        picture.image_height = 4
        picture.is_image = True
        root.children.append(picture)

        bridge = BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1)
        canonical_root = build_document_tree(bridge, "test.pdf")

        assert len(canonical_root.children) == 1
        figure_node = canonical_root.children[0]
        from learning_platform.models.document import Figure  # noqa: PLC0415

        assert isinstance(figure_node.content, Figure)
        assert figure_node.content.image_base64 is not None

    def test_table_column_count_accounts_for_merged_cell_gaps(self) -> None:
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        table = _bridge_node(
            self_ref="#/tables/0",
            parent_cref="#/body",
            label="table",
            name="TableItem",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.8,
        )
        row = _bridge_node(
            self_ref="#/tables/0/rows/0",
            parent_cref="#/tables/0",
            label="AI-TABLE_ROW",
            name="TableRowContainer",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.2,
            is_synthetic=True,
            metadata={"role": "AI-table_row", "table_row_index": 0},
        )
        table.children.append(row)
        root.children.append(table)

        for col_idx, text in [(0, "A"), (2, "C")]:
            row.children.append(
                _bridge_node(
                    self_ref=f"#/tables/0/rows/0/cells/{col_idx}",
                    parent_cref="#/tables/0/rows/0",
                    label="AI-TABLE_CELL",
                    name="TableCell",
                    text=text,
                    page_no=1,
                    norm_left=0.1 + col_idx * 0.4,
                    norm_top=0.1,
                    norm_right=0.3 + col_idx * 0.4,
                    norm_bottom=0.2,
                    metadata={
                        "role": "AI-table_cell",
                        "table_row_index": 0,
                        "table_col_index": col_idx,
                        "row_span": 1,
                        "col_span": 2,
                        "is_header": False,
                    },
                )
            )

        canonical_root = build_document_tree(
            BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1),
            "test.pdf",
        )
        table_node = canonical_root.children[0]
        assert isinstance(table_node.content, TableBlock)
        assert table_node.content.column_count == 3
        assert table_node.content.rows[0].cells[0].col_span == 2

    def test_list_hydration_moves_single_item_children_into_parent_list(self) -> None:
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        list_group = _bridge_node(
            self_ref="#/groups/1",
            parent_cref="#/body",
            label="list",
            name="GroupItem",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.3,
        )
        list_item = _bridge_node(
            self_ref="#/texts/1",
            parent_cref="#/groups/1",
            label="list_item",
            name="ListItem",
            text="1. First",
            page_no=1,
            norm_left=0.12,
            norm_top=0.12,
            norm_right=0.4,
            norm_bottom=0.14,
        )
        list_group.children.append(list_item)
        root.children.append(list_group)

        bridge = BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1)
        canonical_root = build_document_tree(bridge, "test.pdf")

        group_node = canonical_root.children[0]
        assert isinstance(group_node.content, ListBlock)
        assert len(group_node.content.items) == 1
        assert group_node.content.items[0].text.plain_text == "1. First"
        assert group_node.children == []

    def test_list_group_style_is_adopted_from_first_item(self) -> None:
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        list_group = _bridge_node(
            self_ref="#/groups/1",
            parent_cref="#/body",
            label="list",
            name="GroupItem",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.3,
        )
        list_group.children.extend(
            [
                _bridge_node(
                    self_ref="#/texts/1",
                    parent_cref="#/groups/1",
                    label="list_item",
                    name="ListItem",
                    text="1. First",
                    page_no=1,
                    norm_left=0.12,
                    norm_top=0.12,
                    norm_right=0.4,
                    norm_bottom=0.14,
                ),
                _bridge_node(
                    self_ref="#/texts/2",
                    parent_cref="#/groups/1",
                    label="list_item",
                    name="ListItem",
                    text="2. Second",
                    page_no=1,
                    norm_left=0.12,
                    norm_top=0.16,
                    norm_right=0.4,
                    norm_bottom=0.18,
                ),
            ]
        )
        root.children.append(list_group)

        canonical_root = build_document_tree(
            BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1),
            "test.pdf",
        )
        group_node = canonical_root.children[0]
        assert isinstance(group_node.content, ListBlock)
        assert group_node.content.style == ListStyle.NUMBERED
        assert [item.text.plain_text for item in group_node.content.items] == [
            "1. First",
            "2. Second",
        ]

    def test_list_hydration_preserves_sibling_nested_sub_list(self) -> None:
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        list_group = _bridge_node(
            self_ref="#/groups/1",
            parent_cref="#/body",
            label="list",
            name="GroupItem",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.5,
        )
        list_group.children.append(
            _bridge_node(
                self_ref="#/texts/1",
                parent_cref="#/groups/1",
                label="list_item",
                name="ListItem",
                text="1. First",
                page_no=1,
                norm_left=0.12,
                norm_top=0.12,
                norm_right=0.4,
                norm_bottom=0.14,
            )
        )
        nested_group = _bridge_node(
            self_ref="#/groups/2",
            parent_cref="#/groups/1",
            label="list",
            name="GroupItem",
            text="",
            page_no=1,
            norm_left=0.2,
            norm_top=0.18,
            norm_right=0.9,
            norm_bottom=0.4,
        )
        nested_group.children.append(
            _bridge_node(
                self_ref="#/texts/2",
                parent_cref="#/groups/2",
                label="list_item",
                name="ListItem",
                text="1. Sub",
                page_no=1,
                norm_left=0.22,
                norm_top=0.2,
                norm_right=0.4,
                norm_bottom=0.22,
            )
        )
        list_group.children.append(nested_group)
        root.children.append(list_group)

        canonical_root = build_document_tree(
            BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1),
            "test.pdf",
        )
        group_node = canonical_root.children[0]
        assert isinstance(group_node.content, ListBlock)
        assert [item.text.plain_text for item in group_node.content.items] == ["1. First"]
        assert len(group_node.children) == 1
        nested = group_node.children[0]
        assert isinstance(nested.content, ListBlock)
        assert [item.text.plain_text for item in nested.content.items] == ["1. Sub"]

    def test_list_hydration_preserves_nested_sub_list_under_item(self) -> None:
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        list_group = _bridge_node(
            self_ref="#/groups/1",
            parent_cref="#/body",
            label="list",
            name="GroupItem",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.5,
        )
        list_item = _bridge_node(
            self_ref="#/texts/1",
            parent_cref="#/groups/1",
            label="list_item",
            name="ListItem",
            text="1. First",
            page_no=1,
            norm_left=0.12,
            norm_top=0.12,
            norm_right=0.4,
            norm_bottom=0.14,
        )
        nested_group = _bridge_node(
            self_ref="#/groups/2",
            parent_cref="#/texts/1",
            label="list",
            name="GroupItem",
            text="",
            page_no=1,
            norm_left=0.2,
            norm_top=0.16,
            norm_right=0.9,
            norm_bottom=0.3,
        )
        nested_group.children.append(
            _bridge_node(
                self_ref="#/texts/2",
                parent_cref="#/groups/2",
                label="list_item",
                name="ListItem",
                text="a. Sub",
                page_no=1,
                norm_left=0.22,
                norm_top=0.18,
                norm_right=0.4,
                norm_bottom=0.2,
            )
        )
        list_item.children.append(nested_group)
        list_group.children.append(list_item)
        root.children.append(list_group)

        canonical_root = build_document_tree(
            BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1),
            "test.pdf",
        )
        group_node = canonical_root.children[0]
        assert isinstance(group_node.content, ListBlock)
        assert [item.text.plain_text for item in group_node.content.items] == ["1. First"]
        assert len(group_node.children) == 1
        nested = group_node.children[0]
        assert isinstance(nested.content, ListBlock)
        assert [item.text.plain_text for item in nested.content.items] == ["a. Sub"]

    def test_checkbox_item_maps_to_checkbox_list_item(self) -> None:
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        list_group = _bridge_node(
            self_ref="#/groups/1",
            parent_cref="#/body",
            label="list",
            name="GroupItem",
            text="",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.9,
            norm_bottom=0.3,
        )
        list_group.children.append(
            _bridge_node(
                self_ref="#/texts/1",
                parent_cref="#/groups/1",
                label="checkbox_item",
                name="ListItem",
                text="[x] Done",
                page_no=1,
                norm_left=0.12,
                norm_top=0.12,
                norm_right=0.4,
                norm_bottom=0.14,
            )
        )
        root.children.append(list_group)

        canonical_root = build_document_tree(
            BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1),
            "test.pdf",
        )
        group_node = canonical_root.children[0]
        assert isinstance(group_node.content, ListBlock)
        assert group_node.content.style == ListStyle.CHECKBOX
        assert len(group_node.content.items) == 1
        assert group_node.content.items[0].checked is True

    def test_assigns_global_dfs_seq_on_final_tree(self) -> None:
        root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        a = _bridge_node(
            self_ref="#/texts/a",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="A",
            page_no=1,
            norm_left=0.1,
            norm_top=0.1,
            norm_right=0.2,
            norm_bottom=0.11,
        )
        b = _bridge_node(
            self_ref="#/texts/b",
            parent_cref="#/body",
            label="paragraph",
            name="TextItem",
            text="B",
            page_no=1,
            norm_left=0.2,
            norm_top=0.2,
            norm_right=0.3,
            norm_bottom=0.21,
        )
        c = _bridge_node(
            self_ref="#/texts/c",
            parent_cref="#/texts/a",
            label="paragraph",
            name="TextItem",
            text="C",
            page_no=1,
            norm_left=0.12,
            norm_top=0.12,
            norm_right=0.22,
            norm_bottom=0.13,
        )
        a.children.append(c)
        root.children.extend([a, b])

        bridge = BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1)
        canonical_root = build_document_tree(bridge, "test.pdf")

        seen: list[int] = []

        def walk(node: Any) -> None:
            seen.append(node.seq)
            for child in node.children:
                walk(child)

        walk(canonical_root)
        assert seen == list(range(len(seen)))


class TestAdapterInterface:
    def test_parser2_adapter_supports_extensions(self) -> None:
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.supports("x.pdf") is True
        assert adapter.supports("x.docx") is True
        assert adapter.supports("x.xyz") is False

    def test_parser2_adapter_confidence(self) -> None:
        from learning_platform.stages.parser2 import Parser2Adapter

        adapter = Parser2Adapter()
        assert adapter.confidence("x.pdf") == 0.95
        assert adapter.confidence("x.html") == 0.70
        assert adapter.confidence("x.txt") == 0.40
        assert adapter.confidence("x.unknown") == 0.0

    def test_parse_uses_bridge_and_mapper(self) -> None:
        from learning_platform.stages.parser2 import Parser2Adapter

        fake_root = BridgeNode(self_ref="#/body", label="AI-BODY", name="Body")
        bridge = BridgeDocument(root=fake_root, source="doc.pdf", title="Doc", page_count=3)

        with patch(
            "learning_platform.stages.parser2.docling_pymupdf_adapter.DoclingPyMuPDFMerger"
        ) as merger_cls:
            merger = merger_cls.return_value.__enter__.return_value
            merger.build_bridge_tree.return_value = bridge
            merger.title = "Doc"
            merger.page_count = 3

            adapter = Parser2Adapter()
            doc = adapter.parse("doc.pdf")

        assert doc.title == "Doc"
        assert doc.metadata.page_count == 3
        assert len(doc.nodes) == 1
