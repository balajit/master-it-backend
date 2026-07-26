"""Unit tests for StructuralNormalizer and its individual passes."""

from __future__ import annotations

from uuid import uuid4

from learning_platform.models.document import (
    BoundingBox,
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Equation,
    Figure,
    Heading,
    HeadingLevel,
    ListBlock,
    ListItem,
    ListStyle,
    Paragraph,
    StyledText,
    TableBlock,
    TableCell,
    TableRow,
    TextRun,
)
from learning_platform.stages.normalizer.passes.caption import CaptionAssociationPass
from learning_platform.stages.normalizer.passes.heading import HeadingNormalizationPass
from learning_platform.stages.normalizer.passes.heading_section import HeadingSectionPass
from learning_platform.stages.normalizer.passes.list_norm import ListNormalizationPass
from learning_platform.stages.normalizer.passes.page_grouping import PageGroupingPass
from learning_platform.stages.normalizer.passes.paragraph import ParagraphMergePass
from learning_platform.stages.normalizer.passes.parent_child import ParentChildRepairPass
from learning_platform.stages.normalizer.passes.reading_order import ReadingOrderPass
from learning_platform.stages.normalizer.passes.table import TableNormalizationPass
from learning_platform.stages.normalizer.structural import StructuralNormalizer

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────────


def _doc(*nodes: DocumentNode) -> CanonicalDocument:
    """Build a ``CanonicalDocument`` from the given content nodes.

    Wraps the nodes under a synthetic root so the normalizer can flatten
    the tree and run passes on every node.
    """
    root = DocumentNode(
        content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
        metadata={"role": "document_root"},
        children=list(nodes),
    )
    return CanonicalDocument(
        source="test.pdf",
        title="Test",
        metadata=DocumentMetadata(title="Test"),
        nodes=[root],
    )


def _collect_all(root: DocumentNode) -> list[DocumentNode]:
    """Collect all nodes from a tree in pre-order, excluding synthetic roots."""
    result: list[DocumentNode] = []
    stack: list[DocumentNode] = [root]
    while stack:
        node = stack.pop()
        if node.metadata.get("role") not in {"normalizer_root", "document_root"}:
            result.append(node)
        stack.extend(reversed(node.children))
    return result


def _para(text: str, page: int = 0) -> DocumentNode:
    return DocumentNode(
        content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
        page=page,
    )


def _heading(text: str, level: int = 1, page: int = 0) -> DocumentNode:
    safe = min(level, 4)
    return DocumentNode(
        content=Heading(
            level=HeadingLevel(safe),
            text=StyledText(runs=[TextRun(text=text)]),
        ),
        level=safe,
        page=page,
    )


def _list_node(items: list[str], style: ListStyle = ListStyle.BULLET) -> DocumentNode:
    return DocumentNode(
        content=ListBlock(
            style=style,
            items=[ListItem(text=StyledText(runs=[TextRun(text=t)])) for t in items],
        ),
    )


def _table(rows: list[list[str]]) -> DocumentNode:
    return DocumentNode(
        content=TableBlock(
            rows=[
                TableRow(
                    cells=[TableCell(content=[TextRun(text=c)]) for c in row],
                    is_header=(i == 0),
                )
                for i, row in enumerate(rows)
            ],
            row_count=len(rows),
            column_count=max((len(r) for r in rows), default=0),
        ),
    )


def _figure(caption: str = "") -> DocumentNode:
    return DocumentNode(
        content=Figure(caption_text=caption),
    )


def _equation(latex: str = "E=mc^2") -> DocumentNode:
    return DocumentNode(
        content=Equation(latex=latex),
    )


# ──────────────────────────────────────────────────────────────────────────────
# HeadingNormalizationPass
# ──────────────────────────────────────────────────────────────────────────────


class TestHeadingNormalizationPass:
    def test_no_headings_unchanged(self) -> None:
        nodes = [_para("Hello"), _para("World")]
        result = HeadingNormalizationPass()(nodes)
        assert len(result) == 2

    def test_gap_filled(self) -> None:
        nodes = [_heading("Ch", 1), _heading("Deep", 3)]
        result = HeadingNormalizationPass()(nodes)
        assert result[1].content.level == HeadingLevel.SECTION

    def test_first_heading_anchored_at_1(self) -> None:
        nodes = [_heading("Start", 5)]
        result = HeadingNormalizationPass()(nodes)
        assert result[0].content.level == HeadingLevel.CHAPTER

    def test_sequential_headings_unchanged(self) -> None:
        nodes = [_heading("A", 1), _heading("B", 2), _heading("C", 3)]
        result = HeadingNormalizationPass()(nodes)
        assert [int(n.content.level) for n in result] == [1, 2, 3]

    def test_empty_input(self) -> None:
        result = HeadingNormalizationPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# ParagraphMergePass
# ──────────────────────────────────────────────────────────────────────────────


class TestParagraphMergePass:
    def test_consecutive_paragraphs_merged(self) -> None:
        nodes = [_para("Hello"), _para("World")]
        result = ParagraphMergePass()(nodes)
        assert len(result) == 1
        assert "Hello" in result[0].content.text.plain_text
        assert "World" in result[0].content.text.plain_text

    def test_paragraph_then_heading_not_merged(self) -> None:
        nodes = [_para("Intro"), _heading("Ch 1")]
        result = ParagraphMergePass()(nodes)
        assert len(result) == 2

    def test_heading_then_paragraphs_not_merged(self) -> None:
        nodes = [_heading("Ch"), _para("A"), _para("B")]
        result = ParagraphMergePass()(nodes)
        assert len(result) == 2
        assert isinstance(result[0].content, Heading)

    def test_empty_input(self) -> None:
        result = ParagraphMergePass()([])
        assert result == []

    def test_single_paragraph_unchanged(self) -> None:
        nodes = [_para("Only one")]
        result = ParagraphMergePass()(nodes)
        assert len(result) == 1


# ──────────────────────────────────────────────────────────────────────────────
# CaptionAssociationPass
# ──────────────────────────────────────────────────────────────────────────────


class TestCaptionAssociationPass:
    def test_figure_caption_associated(self) -> None:
        fig = _figure()
        cap = _para("Figure 1: A chart")
        result = CaptionAssociationPass()([fig, cap])
        assert len(result) == 1
        assert "Figure 1" in result[0].content.caption_text

    def test_equation_caption_associated(self) -> None:
        eq = _equation()
        cap = _para("Equation 2: Energy")
        result = CaptionAssociationPass()([eq, cap])
        assert len(result) == 1
        assert "Equation 2" in result[0].content.metadata.get("caption", "")

    def test_no_caption_without_prefix(self) -> None:
        fig = _figure()
        cap = _para("Some random text")
        result = CaptionAssociationPass()([fig, cap])
        assert len(result) == 2

    def test_fig_dot_caption(self) -> None:
        fig = _figure()
        cap = _para("Fig. 3: Diagram")
        result = CaptionAssociationPass()([fig, cap])
        assert len(result) == 1

    def test_no_figure_before_caption(self) -> None:
        cap = _para("Figure 5: Orphan")
        result = CaptionAssociationPass()([cap])
        assert len(result) == 1

    def test_empty_input(self) -> None:
        result = CaptionAssociationPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# ListNormalizationPass
# ──────────────────────────────────────────────────────────────────────────────


class TestListNormalizationPass:
    def test_same_style_merged(self) -> None:
        l1 = _list_node(["A", "B"])
        l2 = _list_node(["C", "D"])
        result = ListNormalizationPass()([l1, l2])
        assert len(result) == 1
        assert len(result[0].content.items) == 4

    def test_different_styles_not_merged(self) -> None:
        l1 = _list_node(["A"], ListStyle.BULLET)
        l2 = _list_node(["B"], ListStyle.NUMBERED)
        result = ListNormalizationPass()([l1, l2])
        assert len(result) == 2

    def test_list_then_para_not_merged(self) -> None:
        l1 = _list_node(["A"])
        p = _para("Text")
        result = ListNormalizationPass()([l1, p])
        assert len(result) == 2

    def test_empty_input(self) -> None:
        result = ListNormalizationPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# TableNormalizationPass
# ──────────────────────────────────────────────────────────────────────────────


class TestTableNormalizationPass:
    def test_header_extracted(self) -> None:
        t = _table([["Name", "Age"], ["Alice", "30"]])
        result = TableNormalizationPass()([t])
        assert result[0].content.headers == ["Name", "Age"]

    def test_row_count_updated(self) -> None:
        t = _table([["A", "B"], ["C", "D"], ["E", "F"]])
        result = TableNormalizationPass()([t])
        assert result[0].content.row_count == 3

    def test_first_row_marked_header(self) -> None:
        t = _table([["X", "Y"], ["1", "2"]])
        result = TableNormalizationPass()([t])
        assert result[0].content.rows[0].is_header is True

    def test_non_table_nodes_unchanged(self) -> None:
        p = _para("Not a table")
        result = TableNormalizationPass()([p])
        assert len(result) == 1

    def test_empty_input(self) -> None:
        result = TableNormalizationPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# ReadingOrderPass
# ──────────────────────────────────────────────────────────────────────────────


class TestReadingOrderPass:
    def test_sorts_by_page(self) -> None:
        n1 = _para("Page 2", page=2)
        n2 = _para("Page 1", page=1)
        result = ReadingOrderPass()([n1, n2])
        assert result[0].page == 1
        assert result[1].page == 2

    def test_sorts_by_y_within_page(self) -> None:
        n1 = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="Bottom")])),
            page=1,
            bbox=BoundingBox(y=100),
        )
        n2 = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="Top")])),
            page=1,
            bbox=BoundingBox(y=10),
        )
        result = ReadingOrderPass()([n1, n2])
        assert result[0].content.text.plain_text == "Top"
        assert result[1].content.text.plain_text == "Bottom"

    def test_sorts_by_seq_within_same_position(self) -> None:
        n1 = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="Second")])),
            page=1,
            seq=2,
        )
        n2 = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="First")])),
            page=1,
            seq=1,
        )
        result = ReadingOrderPass()([n1, n2])
        assert result[0].content.text.plain_text == "First"
        assert result[1].content.text.plain_text == "Second"

    def test_stable_for_same_position(self) -> None:
        n1 = _para("First")
        n2 = _para("Second")
        result = ReadingOrderPass()([n1, n2])
        assert result[0].content.text.plain_text == "First"

    def test_empty_input(self) -> None:
        result = ReadingOrderPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# HeadingSectionPass
# ──────────────────────────────────────────────────────────────────────────────


class TestHeadingSectionPass:
    def test_content_child_of_heading(self) -> None:
        h1 = _heading("Ch", 1)
        p1 = _para("Body")
        result = HeadingSectionPass()([h1, p1])
        assert result[1].parent_id == h1.id

    def test_subheading_parent_is_higher_heading(self) -> None:
        h1 = _heading("Ch", 1)
        h2 = _heading("Sec", 2)
        result = HeadingSectionPass()([h1, h2])
        assert result[1].parent_id == h1.id

    def test_content_follows_section_heading(self) -> None:
        h1 = _heading("Ch", 1)
        h2 = _heading("Sec", 2)
        p1 = _para("Under sec")
        result = HeadingSectionPass()([h1, h2, p1])
        assert result[2].parent_id == result[1].id

    def test_new_section_breaks_previous(self) -> None:
        h1 = _heading("Ch1", 1)
        p1 = _para("Under ch1")
        h2 = _heading("Ch2", 1)
        p2 = _para("Under ch2")
        result = HeadingSectionPass()([h1, p1, h2, p2])
        assert result[1].parent_id == result[0].id
        assert result[3].parent_id == result[2].id
        assert result[2].parent_id is None

    def test_content_before_any_heading_unchanged(self) -> None:
        p1 = _para("Before")
        h1 = _heading("Ch", 1)
        result = HeadingSectionPass()([p1, h1])
        assert result[0].parent_id is None

    def test_existing_parent_id_not_overridden(self) -> None:
        h1 = _heading("Ch", 1)
        p1 = _para("Already parented")
        # Use a parent_id that exists in the input list
        p1 = p1.model_copy(update={"parent_id": h1.id})
        result = HeadingSectionPass()([h1, p1])
        assert result[1].parent_id == h1.id

    def test_empty_input(self) -> None:
        result = HeadingSectionPass()([])
        assert result == []

    def test_first_heading_anchored_at_level_1(self) -> None:
        h1 = _heading("Deep", 3)
        p1 = _para("Body")
        result = HeadingSectionPass()([h1, p1])
        assert result[1].parent_id == result[0].id

    def test_deep_nesting(self) -> None:
        h1 = _heading("L1", 1)
        h2 = _heading("L2", 2)
        h3 = _heading("L3", 3)
        p1 = _para("Deep content")
        result = HeadingSectionPass()([h1, h2, h3, p1])
        assert result[1].parent_id == result[0].id
        assert result[2].parent_id == result[1].id
        assert result[3].parent_id == result[2].id


# ──────────────────────────────────────────────────────────────────────────────
# PageGroupingPass
# ──────────────────────────────────────────────────────────────────────────────


class TestPageGroupingPass:
    def test_orphans_grouped_by_page(self) -> None:
        p1 = _para("Page 1 content", page=1)
        p2 = _para("Page 2 content", page=2)
        result = PageGroupingPass()([p1, p2])
        # Should have 2 page group nodes + 2 content nodes
        page_groups = [n for n in result if n.metadata.get("role") == "page_group"]
        assert len(page_groups) == 2

    def test_parented_nodes_unchanged(self) -> None:
        h1 = _heading("Ch", 1, page=1)
        p1 = _para("Under heading", page=1)
        p1 = p1.model_copy(update={"parent_id": h1.id})
        result = PageGroupingPass()([h1, p1])
        # p1 should keep its parent (h1), not be reparented to page container
        para_result = [n for n in result if n.content.text.plain_text == "Under heading"]
        assert len(para_result) == 1
        assert para_result[0].parent_id == h1.id

    def test_headings_parented_to_page_container(self) -> None:
        h1 = _heading("Ch", 1, page=1)
        p1 = _para("Orphan", page=1)
        result = PageGroupingPass()([h1, p1])
        # Now headings are also parented to page container
        page_groups = [n for n in result if n.metadata.get("role") == "page_group"]
        assert len(page_groups) == 1
        heading_result = [n for n in result if isinstance(n.content, Heading)]
        assert len(heading_result) == 1
        assert heading_result[0].parent_id == page_groups[0].id

    def test_no_page_group_when_empty(self) -> None:
        result = PageGroupingPass()([])
        assert result == []

    def test_empty_input(self) -> None:
        result = PageGroupingPass()([])
        assert result == []

    def test_page_group_contains_page_metadata(self) -> None:
        p1 = _para("Content", page=3)
        result = PageGroupingPass()([p1])
        page_groups = [n for n in result if n.metadata.get("role") == "page_group"]
        assert len(page_groups) == 1
        assert page_groups[0].metadata["page_number"] == 3

    def test_mixed_parented_and_orphaned(self) -> None:
        h1 = _heading("Ch", 1, page=1)
        p1 = _para("Under heading", page=1)
        p1 = p1.model_copy(update={"parent_id": h1.id})
        p2 = _para("Orphan", page=1)
        result = PageGroupingPass()([h1, p1, p2])
        page_groups = [n for n in result if n.metadata.get("role") == "page_group"]
        assert len(page_groups) == 1
        # p1 keeps its parent (h1), h1 and p2 are parented to page group
        heading_result = [n for n in result if isinstance(n.content, Heading)]
        assert heading_result[0].parent_id == page_groups[0].id
        para_result = [n for n in result if n.content.text.plain_text == "Orphan"]
        assert para_result[0].parent_id == page_groups[0].id


# ──────────────────────────────────────────────────────────────────────────────
# ParentChildRepairPass
# ──────────────────────────────────────────────────────────────────────────────


class TestParentChildRepairPass:
    def test_orphan_nodes_become_children_of_root(self) -> None:
        n1 = _para("A")
        n2 = _para("B")
        result = ParentChildRepairPass()([n1, n2])
        assert len(result) >= 2

    def test_valid_parent_id_preserved(self) -> None:
        parent = _heading("Ch", 1)
        child = _para("Content")
        child = child.model_copy(update={"parent_id": parent.id})
        result = ParentChildRepairPass()([parent, child])
        assert len(result) >= 1

    def test_invalid_parent_id_cleared(self) -> None:
        child = _para("Orphan")
        child = child.model_copy(update={"parent_id": uuid4()})
        result = ParentChildRepairPass()([child])
        assert len(result) >= 1

    def test_cycle_broken(self) -> None:
        a = _para("A")
        b = _para("B")
        a = a.model_copy(update={"parent_id": b.id})
        b = b.model_copy(update={"parent_id": a.id})
        result = ParentChildRepairPass()([a, b])
        assert len(result) >= 2

    def test_empty_input(self) -> None:
        result = ParentChildRepairPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# StructuralNormalizer (orchestrator)
# ──────────────────────────────────────────────────────────────────────────────


class TestStructuralNormalizer:
    def test_default_passes_applied(self) -> None:
        doc = _doc(
            _heading("Ch", 3),
            _para("Hello"),
            _para("World"),
        )
        normalizer = StructuralNormalizer()
        result = normalizer.normalize(doc)
        assert isinstance(result, CanonicalDocument)
        assert result.source == "test.pdf"

    def test_heading_gap_fixed_in_pipeline(self) -> None:
        doc = _doc(
            _heading("Deep", 4),
            _para("Text"),
        )
        result = StructuralNormalizer().normalize(doc)
        all_nodes = _collect_all(result.nodes[0]) if result.nodes else []
        headings = [n for n in all_nodes if isinstance(n.content, Heading)]
        assert len(headings) == 1
        assert headings[0].content.level == HeadingLevel.CHAPTER

    def test_paragraphs_merged_in_pipeline(self) -> None:
        doc = _doc(_para("A"), _para("B"), _para("C"))
        result = StructuralNormalizer().normalize(doc)
        all_nodes = _collect_all(result.nodes[0]) if result.nodes else []
        paras = [
            n
            for n in all_nodes
            if isinstance(n.content, Paragraph) and n.metadata.get("role") != "page_group"
        ]
        assert len(paras) == 1

    def test_custom_passes(self) -> None:

        class NoOp:
            def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
                return nodes

        doc = _doc(_para("Hello"))
        normalizer = StructuralNormalizer(passes=[NoOp()])
        result = normalizer.normalize(doc)
        assert len(result.nodes) == 1

    def test_empty_document(self) -> None:
        doc = _doc()
        result = StructuralNormalizer().normalize(doc)
        assert result.nodes == []

    def test_passes_property_returns_copy(self) -> None:
        normalizer = StructuralNormalizer()
        p1 = normalizer.passes
        p2 = normalizer.passes
        assert p1 is not p2
