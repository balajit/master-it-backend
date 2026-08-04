"""Unit tests for parser2 bridge-tree mapping and ordering."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from learning_platform.models.document import ListBlock, TableBlock, TextItem
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

        DoclingPyMuPDFMerger._sort_tree_spatially(merger, root, column_tolerance=0.28)

        assert [child.text for child in root.children] == ["left-low", "right-top", "page-two"]

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


class TestBridgeToCanonicalMapping:
    def test_table_rows_are_container_nodes_and_cells_are_text_nodes(self) -> None:
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
            norm_top=0.12,
            norm_right=0.9,
            norm_bottom=0.2,
            is_synthetic=True,
            metadata={"role": "AI-table_row", "table_row_index": 0},
        )
        cell = _bridge_node(
            self_ref="#/tables/0/rows/0/cells/0",
            parent_cref="#/tables/0/rows/0",
            label="AI-TABLE_CELL",
            name="TableCell",
            text="Cell 1",
            page_no=1,
            norm_left=0.12,
            norm_top=0.13,
            norm_right=0.3,
            norm_bottom=0.19,
            metadata={
                "role": "AI-table_cell",
                "table_row_index": 0,
                "table_col_index": 0,
                "row_span": 1,
                "col_span": 1,
                "is_header": True,
            },
        )

        row.children.append(cell)
        table.children.append(row)
        root.children.append(table)

        bridge = BridgeDocument(root=root, source="test.pdf", title="Test", page_count=1)
        canonical_root = build_document_tree(bridge, "test.pdf")

        assert len(canonical_root.children) == 1
        table_node = canonical_root.children[0]
        assert isinstance(table_node.content, TableBlock)
        assert table_node.content.rows == []

        assert len(table_node.children) == 1
        row_node = table_node.children[0]
        assert row_node.metadata.get("role") == "AI-table_row"

        assert len(row_node.children) == 1
        cell_node = row_node.children[0]
        assert isinstance(cell_node.content, TextItem)
        assert cell_node.content.text.plain_text == "Cell 1"
        assert cell_node.metadata.get("role") == "AI-table_cell"
        assert cell_node.metadata.get("table_col_index") == 0
        assert cell_node.metadata.get("is_header") is True

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
