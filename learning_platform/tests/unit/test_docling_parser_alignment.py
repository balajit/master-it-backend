from __future__ import annotations

from typing import Any

from learning_platform.models.document import (
    BlockStyle,
    BoundingBox,
    DocumentNode,
    FormAreaBlock,
    Heading,
    HeadingLevel,
    ListBlock,
    ListItem,
    ListStyle,
    Paragraph,
    Question,
    QuestionType,
    StyledText,
    TextItem,
    TextRun,
)
from learning_platform.stages.parser.docling_adapter import (
    CorrelatedItem,
    DoclingAdapter,
    _compute_bbox_overlap_ratio,
)
from learning_platform.stages.parser.pymupdf_layout import _to_bbox


def _raw_bbox(
    *,
    left: float,
    top: float,
    right: float,
    bottom: float,
    coord_origin: str,
) -> object:
    return type(
        "RawBBox",
        (),
        {
            "l": left,
            "t": top,
            "r": right,
            "b": bottom,
            "coord_origin": coord_origin,
        },
    )()


def test_docling_bottom_left_bbox_is_converted_to_top_left() -> None:
    converted = DoclingAdapter._docling_bbox_to_top_left(
        _raw_bbox(
            left=108.0,
            top=691.8457,
            right=200.8710,
            bottom=682.0969,
            coord_origin="BOTTOMLEFT",
        ),
        page_width=612.0,
        page_height=792.0,
    )

    assert round(converted.x, 2) == 108.00
    assert round(converted.y, 2) == 100.15
    assert round(converted.width, 2) == 92.87
    assert round(converted.height, 2) == 9.75


def test_docling_top_left_bbox_stays_top_left() -> None:
    converted = DoclingAdapter._docling_bbox_to_top_left(
        _raw_bbox(
            left=108.0,
            top=98.12,
            right=200.87,
            bottom=110.38,
            coord_origin="TOPLEFT",
        ),
        page_width=612.0,
        page_height=792.0,
    )

    assert round(converted.x, 2) == 108.00
    assert round(converted.y, 2) == 98.12
    assert round(converted.width, 2) == 92.87
    assert round(converted.height, 2) == 12.26


def test_layout_bbox_normalizes_reversed_coordinates() -> None:
    bbox = _to_bbox((420.0, 220.0, 100.0, 140.0), page_width=612.0, page_height=792.0)
    assert bbox.left == 100.0
    assert bbox.top == 140.0
    assert bbox.right == 420.0
    assert bbox.bottom == 220.0


def test_list_style_inference_from_text_and_label() -> None:
    assert (
        DoclingAdapter._infer_list_style(text="1. First item", label_value="list_item")
        == ListStyle.NUMBERED
    )
    assert (
        DoclingAdapter._infer_list_style(text="(ignored)", label_value="checkbox_selected")
        == ListStyle.CHECKBOX
    )
    assert (
        DoclingAdapter._infer_list_style(text="IV) Roman item", label_value="list_item")
        == ListStyle.ROMAN
    )
    assert (
        DoclingAdapter._infer_list_style(text="a) Alpha item", label_value="list_item")
        == ListStyle.ALPHA
    )
    assert (
        DoclingAdapter._infer_list_style(text="• Bullet item", label_value="list_item")
        == ListStyle.BULLET
    )


def test_repair_hierarchy_prefers_docling_parent_refs_and_hydrates_list_items() -> None:
    adapter = DoclingAdapter(converter=None)
    root = DocumentNode(
        content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
        metadata={"role": "document_root"},
    )

    heading = DocumentNode(
        content=Heading(
            level=HeadingLevel.SECTION,
            text=StyledText(runs=[TextRun(text="Section 1")]),
        ),
        page=1,
        seq=1,
        bbox=BoundingBox(
            x=80.0, y=100.0, width=160.0, height=20.0, page_width=612.0, page_height=792.0
        ),
        metadata={"docling_self_ref": "#/texts/1"},
    )
    list_group = DocumentNode(
        content=ListBlock(style=ListStyle.BULLET, items=[]),
        page=1,
        seq=2,
        bbox=BoundingBox(
            x=80.0, y=130.0, width=300.0, height=16.0, page_width=612.0, page_height=792.0
        ),
        metadata={"docling_self_ref": "#/groups/3", "resolved_parent_ref": "#/texts/1"},
    )
    list_item = DocumentNode(
        content=ListBlock(
            style=ListStyle.NUMBERED,
            items=[
                ListItem(text=StyledText(runs=[TextRun(text="1. Item one")])),
            ],
        ),
        page=1,
        seq=3,
        bbox=BoundingBox(
            x=95.0, y=132.0, width=220.0, height=12.0, page_width=612.0, page_height=792.0
        ),
        metadata={"docling_self_ref": "#/texts/2", "resolved_parent_ref": "#/groups/3"},
    )

    root.children = [heading, list_group, list_item]
    repaired = adapter._repair_hybrid_hierarchy(root)

    assert len(repaired.children) == 1
    assert repaired.children[0].id == heading.id
    assert len(heading.children) == 1
    assert heading.children[0].id == list_group.id
    assert len(list_group.children) == 1
    assert list_group.children[0].id == list_item.id
    assert list_group.content.style == ListStyle.NUMBERED
    assert [item.text.plain_text for item in list_group.content.items] == ["1. Item one"]


# ── CorrelatedItem helpers ────────────────────────────────────────────────────


def _make_docling_item(
    *,
    self_ref: str = "#/texts/1",
    text: str = "hello",
    parent_cref: str | None = None,
) -> Any:
    class _Parent:
        def __init__(self, cref: str) -> None:
            self.cref = cref

    class _Item:
        def __init__(self) -> None:
            self.self_ref = self_ref
            self.text = text
            self.label = "text"
            self.prov: list[Any] = []
            self.parent = _Parent(parent_cref) if parent_cref else None

    return _Item()


def _make_correlated_item(
    *,
    self_ref: str = "#/texts/1",
    text: str = "hello",
    font_name: str = "Arial",
    font_size: float = 12.0,
    color: str = "#000000",
    is_bold: bool = False,
    is_italic: bool = False,
    vector_line_count: int = 0,
) -> CorrelatedItem:
    item = _make_docling_item(self_ref=self_ref, text=text)
    ci = CorrelatedItem(item, level=0)
    ci.primary_font_name = font_name
    ci.primary_font_size = font_size
    ci.primary_color_hex = color
    ci.is_bold = is_bold
    ci.is_italic = is_italic
    ci.fonts = [
        {
            "font": font_name,
            "size": font_size,
            "color": color,
            "is_bold": is_bold,
            "is_italic": is_italic,
        }
    ]
    ci.vector_lines = [{"length": 120.0, "top": 200.0} for _ in range(vector_line_count)]
    return ci


class TestCorrelatedItem:
    def test_repr_shows_label_and_text_preview(self) -> None:
        item = _make_docling_item(text="A quick brown fox jumps over the lazy dog")
        ci = CorrelatedItem(item, level=1)
        r = repr(ci)
        assert "text" in r  # label
        assert "A quick brown fox jumps over" in r

    def test_parent_cref_captured(self) -> None:
        item = _make_docling_item(parent_cref="#/groups/2")
        ci = CorrelatedItem(item, level=0)
        assert ci.parent_cref == "#/groups/2"

    def test_no_parent_gives_none(self) -> None:
        item = _make_docling_item(parent_cref=None)
        ci = CorrelatedItem(item, level=0)
        assert ci.parent_cref is None

    def test_defaults_are_empty(self) -> None:
        item = _make_docling_item()
        ci = CorrelatedItem(item, level=0)
        assert ci.fonts == []
        assert ci.vector_lines == []
        assert ci.is_bold is False
        assert ci.is_italic is False
        assert ci.primary_font_name is None


class TestComputeBboxOverlapRatio:
    def test_returns_zero_on_import_error(self) -> None:
        # Without a real fitz.Rect we can only verify it doesn't raise
        result = _compute_bbox_overlap_ratio([0.0, 0.0, 10.0, 10.0], object())
        assert result == 0.0


class TestApplyCorrelatedItemToNode:
    def test_sets_block_style_from_font_data(self) -> None:
        adapter = DoclingAdapter()
        node = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="x")])),
        )
        ci = _make_correlated_item(font_name="Helvetica", font_size=14.0, is_bold=True)
        adapter._apply_correlated_item_to_node(node, ci)

        assert node.style is not None
        assert isinstance(node.style, BlockStyle)
        assert node.style.font.name == "Helvetica"
        assert node.style.font.size == 14.0
        assert node.style.font.is_bold is True
        assert node.style.font.is_italic is False

    def test_stores_pymupdf_font_in_metadata(self) -> None:
        adapter = DoclingAdapter()
        node = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="x")])),
        )
        ci = _make_correlated_item(font_name="Times", font_size=11.0, color="#ff0000")
        adapter._apply_correlated_item_to_node(node, ci)

        assert "pymupdf_font" in node.metadata
        assert node.metadata["pymupdf_font"]["name"] == "Times"
        assert node.metadata["pymupdf_font"]["color"] == "#ff0000"

    def test_stores_vector_lines_in_metadata(self) -> None:
        adapter = DoclingAdapter()
        node = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="x")])),
        )
        ci = _make_correlated_item(vector_line_count=2)
        adapter._apply_correlated_item_to_node(node, ci)

        assert "vector_lines" in node.metadata
        assert len(node.metadata["vector_lines"]) == 2
        assert node.metadata["vector_lines"][0]["length"] == 120.0

    def test_no_style_when_no_font_data(self) -> None:
        adapter = DoclingAdapter()
        node = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="x")])),
        )
        item = _make_docling_item()
        ci = CorrelatedItem(item, level=0)  # no font data set
        adapter._apply_correlated_item_to_node(node, ci)

        assert node.style is None
        assert "pymupdf_font" not in node.metadata
        assert "vector_lines" not in node.metadata


class TestMakeHeadingWithCorrelatedItem:
    def test_inline_style_set_from_correlated_bold(self) -> None:
        adapter = DoclingAdapter()
        item = _make_docling_item(text="Chapter One")
        ci = _make_correlated_item(font_name="Arial Bold", font_size=18.0, is_bold=True)

        node = adapter._make_heading(
            item, HeadingLevel.CHAPTER, "/tmp/test.pdf", correlated_item=ci
        )

        assert isinstance(node.content, Heading)
        run = node.content.text.runs[0]
        assert run.style.font.is_bold is True
        assert run.style.font.name == "Arial Bold"
        assert run.style.font.size == 18.0

    def test_no_correlated_item_gives_default_inline_style(self) -> None:
        adapter = DoclingAdapter()
        item = _make_docling_item(text="Plain Heading")

        node = adapter._make_heading(item, HeadingLevel.SECTION, "/tmp/test.pdf")

        assert isinstance(node.content, Heading)
        run = node.content.text.runs[0]
        # Default InlineStyle — font not bold
        assert run.style.font.is_bold is False


class TestMakeParagraphOrQuestionWithVectorLines:
    def test_vector_line_promotes_to_short_answer(self) -> None:
        adapter = DoclingAdapter()
        item = _make_docling_item(text="Your answer here")
        ci = _make_correlated_item(vector_line_count=1)

        node = adapter._make_paragraph_or_question(
            item, "/tmp/test.pdf", "text", correlated_item=ci
        )

        assert isinstance(node.content, Question)
        assert node.content.question_type == QuestionType.SHORT_ANSWER
        assert node.content.metadata["question_signal"] == "vector_answer_line"
        assert node.content.metadata["vector_line_count"] == 1

    def test_text_classification_takes_priority_over_vector_line(self) -> None:
        """Fill-in-blank text classification should not be overridden by vector lines."""
        adapter = DoclingAdapter()
        item = _make_docling_item(text="The body has the six signs (1) ____")
        ci = _make_correlated_item(vector_line_count=1)

        node = adapter._make_paragraph_or_question(
            item, "/tmp/test.pdf", "text", correlated_item=ci
        )

        assert isinstance(node.content, Question)
        assert node.content.question_type == QuestionType.FILL_IN_BLANK

    def test_no_vector_lines_stays_paragraph(self) -> None:
        adapter = DoclingAdapter()
        item = _make_docling_item(text="Plain paragraph text")
        ci = _make_correlated_item(vector_line_count=0)

        node = adapter._make_paragraph_or_question(
            item, "/tmp/test.pdf", "text", correlated_item=ci
        )

        assert isinstance(node.content, Paragraph)

    def test_no_correlated_item_stays_paragraph(self) -> None:
        adapter = DoclingAdapter()
        item = _make_docling_item(text="Plain paragraph text")

        node = adapter._make_paragraph_or_question(item, "/tmp/test.pdf", "text")

        assert isinstance(node.content, Paragraph)


class TestDirectLegacyMappings:
    def test_make_text_item_returns_canonical_text_item(self) -> None:
        adapter = DoclingAdapter()
        item = _make_docling_item(text="Word bank option")
        ci = _make_correlated_item(font_name="Arial", font_size=11.0)

        node = adapter._make_text_item(item, "/tmp/test.pdf", correlated_item=ci)

        assert isinstance(node.content, TextItem)
        assert node.content.text.plain_text == "Word bank option"
        assert node.content.text.runs[0].style.font.name == "Arial"

    def test_make_form_area_returns_canonical_form_area(self) -> None:
        adapter = DoclingAdapter()
        item = _make_docling_item(text="")

        node = adapter._make_form_area(item, "/tmp/test.pdf")

        assert isinstance(node.content, FormAreaBlock)


class TestEnrichNodesFromCorrelatedIndex:
    def test_enriches_node_with_matching_self_ref(self) -> None:
        adapter = DoclingAdapter()
        node = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="x")])),
            metadata={"docling_self_ref": "#/texts/42"},
        )
        root = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={"role": "document_root"},
            children=[node],
        )
        node.parent_id = root.id

        ci = _make_correlated_item(self_ref="#/texts/42", font_name="Georgia", font_size=10.0)
        index: dict[str, CorrelatedItem] = {"#/texts/42": ci}

        adapter._enrich_nodes_from_correlated_index(root, index)

        assert node.style is not None
        assert node.style.font.name == "Georgia"

    def test_skips_nodes_without_self_ref(self) -> None:
        adapter = DoclingAdapter()
        node = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="x")])),
        )
        root = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={"role": "document_root"},
            children=[node],
        )
        ci = _make_correlated_item(font_name="Georgia", font_size=10.0)
        index: dict[str, CorrelatedItem] = {"#/texts/1": ci}

        adapter._enrich_nodes_from_correlated_index(root, index)

        assert node.style is None  # no self_ref → not enriched
