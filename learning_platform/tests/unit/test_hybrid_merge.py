from __future__ import annotations

from uuid import uuid4

from learning_platform.models.document import (
    BoundingBox,
    DocumentNode,
    Heading,
    HeadingLevel,
    Paragraph,
    Question,
    QuestionType,
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
from learning_platform.stages.parser.hybrid_merge import HybridMergeEngine
from learning_platform.stages.parser.pymupdf_layout import (
    LayoutBBox,
    LayoutDocument,
    LayoutFontSpec,
    LayoutLine,
    LayoutPage,
    LayoutSpan,
)


def _font() -> LayoutFontSpec:
    return LayoutFontSpec(
        name="Times-Roman",
        size=11.0,
        color="#000000",
        is_bold=False,
        is_italic=False,
        is_underline=False,
        is_monospace=False,
    )


def _line(
    *,
    line_id: str,
    order: int,
    text: str,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> LayoutLine:
    bbox = LayoutBBox(
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        page_width=612.0,
        page_height=792.0,
    )
    span = LayoutSpan(
        span_id=f"span-{line_id}",
        page_number=1,
        order=order,
        block_index=0,
        line_index=order,
        span_index=0,
        text=text,
        bbox=bbox,
        font=_font(),
    )
    return LayoutLine(
        line_id=line_id,
        page_number=1,
        order=order,
        block_index=0,
        line_index=order,
        text=text,
        bbox=bbox,
        spans=(span,),
    )


def _semantic_candidate(
    *,
    node: DocumentNode,
    node_type: str,
    text: str,
    order: int,
    left: float,
    top: float,
    right: float,
    bottom: float,
    metadata: dict[str, object] | None = None,
) -> SemanticNodeCandidate:
    return SemanticNodeCandidate(
        node=node,
        page_number=1,
        order=order,
        node_type=node_type,
        text=text,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        metadata=dict(metadata or {}),
    )


def test_semantic_table_is_preserved_and_overlapping_layout_lines_suppressed() -> None:
    table_node = DocumentNode(
        id=uuid4(),
        page=1,
        seq=1,
        bbox=BoundingBox(
            x=100.0,
            y=100.0,
            width=320.0,
            height=90.0,
            page_width=612.0,
            page_height=792.0,
        ),
        content=TableBlock(
            headers=["atmosphere", "ozone"],
            rows=[
                TableRow(
                    cells=[
                        TableCell(content=[TextRun(text="atmosphere")]),
                        TableCell(content=[TextRun(text="ozone")]),
                    ],
                    is_header=True,
                )
            ],
            row_count=1,
            column_count=2,
        ),
        metadata={"label": "table"},
    )
    table_candidate = _semantic_candidate(
        node=table_node,
        node_type="table",
        text="atmosphere | ozone",
        order=1,
        left=100.0,
        top=100.0,
        right=420.0,
        bottom=190.0,
        metadata={"label": "table"},
    )

    inside_table_line = _line(
        line_id="line-inside-table",
        order=0,
        text="atmosphere oxygen gas ozone",
        left=120.0,
        top=120.0,
        right=390.0,
        bottom=132.0,
    )
    outside_line = _line(
        line_id="line-outside-table",
        order=2,
        text="Earth's (1) atmosphere is made up of layers.",
        left=120.0,
        top=260.0,
        right=500.0,
        bottom=272.0,
    )

    layout_doc = LayoutDocument(
        source="/tmp/sample.pdf",
        pages=(
            LayoutPage(
                page_number=1,
                width=612.0,
                height=792.0,
                lines=(inside_table_line, outside_line),
            ),
        ),
    )
    semantics = SemanticExtraction(candidates=(table_candidate,))

    merged = HybridMergeEngine().merge(
        source="/tmp/sample.pdf",
        layout_doc=layout_doc,
        semantics=semantics,
    )

    table_items = [node for node in merged.children if node.content.type == "table"]
    text_items = [node for node in merged.children if node.content.type == "paragraph"]

    assert len(table_items) == 1
    assert len(text_items) == 1
    assert text_items[0].content.text.plain_text == "Earth's (1) atmosphere is made up of layers."


def test_semantic_paragraph_boundaries_are_preserved_without_cross_concat() -> None:
    para_one = DocumentNode(
        id=uuid4(),
        page=1,
        seq=1,
        bbox=BoundingBox(
            x=80.0, y=200.0, width=430.0, height=18.0, page_width=612.0, page_height=792.0
        ),
        content=Paragraph(text=StyledText(runs=[TextRun(text="First paragraph sentence.")])),
        metadata={"label": "text"},
    )
    para_two = DocumentNode(
        id=uuid4(),
        page=1,
        seq=2,
        bbox=BoundingBox(
            x=80.0, y=240.0, width=430.0, height=18.0, page_width=612.0, page_height=792.0
        ),
        content=Paragraph(text=StyledText(runs=[TextRun(text="Second paragraph sentence.")])),
        metadata={"label": "text"},
    )

    candidates = (
        _semantic_candidate(
            node=para_one,
            node_type="paragraph",
            text="First paragraph sentence.",
            order=1,
            left=80.0,
            top=200.0,
            right=510.0,
            bottom=218.0,
            metadata={"label": "text"},
        ),
        _semantic_candidate(
            node=para_two,
            node_type="paragraph",
            text="Second paragraph sentence.",
            order=2,
            left=80.0,
            top=240.0,
            right=510.0,
            bottom=258.0,
            metadata={"label": "text"},
        ),
    )

    layout_doc = LayoutDocument(
        source="/tmp/sample.pdf",
        pages=(
            LayoutPage(
                page_number=1,
                width=612.0,
                height=792.0,
                lines=(
                    _line(
                        line_id="line-1",
                        order=1,
                        text="First paragraph sentence.",
                        left=85.0,
                        top=202.0,
                        right=500.0,
                        bottom=214.0,
                    ),
                    _line(
                        line_id="line-2",
                        order=2,
                        text="Second paragraph sentence.",
                        left=85.0,
                        top=242.0,
                        right=500.0,
                        bottom=254.0,
                    ),
                ),
            ),
        ),
    )

    merged = HybridMergeEngine().merge(
        source="/tmp/sample.pdf",
        layout_doc=layout_doc,
        semantics=SemanticExtraction(candidates=candidates),
    )

    paragraphs = [node for node in merged.children if node.content.type == "paragraph"]
    assert len(paragraphs) == 2
    assert paragraphs[0].content.text.plain_text == "First paragraph sentence."
    assert paragraphs[1].content.text.plain_text == "Second paragraph sentence."


def test_short_checkbox_label_does_not_force_true_false_question_type() -> None:
    question_node = DocumentNode(
        id=uuid4(),
        page=1,
        seq=1,
        bbox=BoundingBox(
            x=80.0, y=400.0, width=240.0, height=16.0, page_width=612.0, page_height=792.0
        ),
        content=Question(
            question_type=QuestionType.UNKNOWN,
            text=StyledText(runs=[TextRun(text="26. Organic chemistry")]),
        ),
        metadata={"label": "checkbox_unselected"},
    )

    merged = HybridMergeEngine().merge(
        source="/tmp/sample.pdf",
        layout_doc=LayoutDocument(
            source="/tmp/sample.pdf",
            pages=(LayoutPage(page_number=1, width=612.0, height=792.0, lines=()),),
        ),
        semantics=SemanticExtraction(
            candidates=(
                _semantic_candidate(
                    node=question_node,
                    node_type="question",
                    text="26. Organic chemistry",
                    order=1,
                    left=80.0,
                    top=400.0,
                    right=320.0,
                    bottom=416.0,
                    metadata={"label": "checkbox_unselected"},
                ),
            )
        ),
    )

    questions = [node for node in merged.children if node.content.type == "question"]
    assert len(questions) == 1
    assert questions[0].content.question_type == QuestionType.UNKNOWN


def test_numbered_layout_lines_replace_semantic_list_items_and_emit_question_node() -> None:
    semantic_node = DocumentNode(
        id=uuid4(),
        page=1,
        seq=10,
        bbox=BoundingBox(
            x=110.0,
            y=200.0,
            width=260.0,
            height=12.0,
            page_width=612.0,
            page_height=792.0,
        ),
        content=Paragraph(text=StyledText(runs=[TextRun(text="26. Organic chemistry")])),
        metadata={"label": "checkbox_unselected"},
    )
    candidate = _semantic_candidate(
        node=semantic_node,
        node_type="paragraph",
        text="26. Organic chemistry",
        order=10,
        left=110.0,
        top=200.0,
        right=370.0,
        bottom=212.0,
        metadata={"label": "checkbox_unselected"},
    )

    layout_doc = LayoutDocument(
        source="/tmp/sample.pdf",
        pages=(
            LayoutPage(
                page_number=1,
                width=612.0,
                height=792.0,
                lines=(
                    _line(
                        line_id="line-26",
                        order=10,
                        text="26. Organic chemistry",
                        left=112.0,
                        top=201.0,
                        right=372.0,
                        bottom=213.0,
                    ),
                ),
            ),
        ),
    )

    merged = HybridMergeEngine().merge(
        source="/tmp/sample.pdf",
        layout_doc=layout_doc,
        semantics=SemanticExtraction(candidates=(candidate,)),
    )

    assert len(merged.children) == 1
    only = merged.children[0]
    assert only.content.type == "question"
    assert only.content.question_type == QuestionType.UNKNOWN


def test_word_bank_rows_use_layout_line_grid_when_available() -> None:
    phrases = (
        ("atmosphere stratosphere", 91.5, 224.4, 149.8, 249.4),
        ("oxygen gas troposphere", 186.1, 224.4, 243.3, 249.4),
        ("ozone ultraviolet radiation", 282.1, 224.4, 376.3, 249.4),
        ("ozone hole", 412.9, 224.4, 465.4, 233.4),
    )
    candidates: list[SemanticNodeCandidate] = []
    for idx, (text, left, top, right, bottom) in enumerate(phrases, start=1):
        node = DocumentNode(
            id=uuid4(),
            page=1,
            seq=idx,
            bbox=BoundingBox(
                x=left,
                y=top,
                width=right - left,
                height=bottom - top,
                page_width=612.0,
                page_height=792.0,
            ),
            content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
            metadata={"label": "text"},
        )
        candidates.append(
            _semantic_candidate(
                node=node,
                node_type="paragraph",
                text=text,
                order=idx,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                metadata={"label": "text"},
            )
        )

    layout_doc = LayoutDocument(
        source="/tmp/sample.pdf",
        pages=(
            LayoutPage(
                page_number=1,
                width=612.0,
                height=792.0,
                lines=(
                    _line(
                        line_id="wb-1-1",
                        order=30,
                        text="atmosphere",
                        left=91.5,
                        top=223.6,
                        right=147.1,
                        bottom=233.6,
                    ),
                    _line(
                        line_id="wb-1-2",
                        order=31,
                        text="oxygen gas",
                        left=186.1,
                        top=223.6,
                        right=238.6,
                        bottom=233.6,
                    ),
                    _line(
                        line_id="wb-1-3",
                        order=32,
                        text="ozone",
                        left=282.1,
                        top=223.6,
                        right=311.0,
                        bottom=233.6,
                    ),
                    _line(
                        line_id="wb-1-4",
                        order=33,
                        text="ozone hole",
                        left=412.9,
                        top=223.6,
                        right=465.4,
                        bottom=233.6,
                    ),
                    _line(
                        line_id="wb-2-1",
                        order=34,
                        text="stratosphere",
                        left=91.5,
                        top=239.6,
                        right=149.8,
                        bottom=249.6,
                    ),
                    _line(
                        line_id="wb-2-2",
                        order=35,
                        text="troposphere",
                        left=186.1,
                        top=239.6,
                        right=243.3,
                        bottom=249.6,
                    ),
                    _line(
                        line_id="wb-2-3",
                        order=36,
                        text="ultraviolet radiation",
                        left=282.1,
                        top=239.6,
                        right=376.3,
                        bottom=249.6,
                    ),
                ),
            ),
        ),
    )

    merged = HybridMergeEngine().merge(
        source="/tmp/sample.pdf",
        layout_doc=layout_doc,
        semantics=SemanticExtraction(candidates=tuple(candidates)),
    )

    tables = [node for node in merged.children if node.content.type == "table"]
    assert len(tables) == 1
    rows = tables[0].content.rows
    assert len(rows) == 2
    assert [run.text for run in rows[0].cells[0].content] == ["atmosphere"]
    assert [run.text for run in rows[1].cells[1].content] == ["troposphere"]
    assert [run.text for run in rows[1].cells[2].content] == ["ultraviolet radiation"]


def test_margin_heading_echo_paragraph_is_not_emitted() -> None:
    heading_node = DocumentNode(
        id=uuid4(),
        page=1,
        seq=1,
        bbox=BoundingBox(
            x=80.0,
            y=80.0,
            width=280.0,
            height=20.0,
            page_width=612.0,
            page_height=792.0,
        ),
        content=Heading(
            level=HeadingLevel.SECTION,
            text=StyledText(runs=[TextRun(text="Section 1.2 continued")]),
        ),
        metadata={"label": "section_header"},
    )
    echo_node = DocumentNode(
        id=uuid4(),
        page=1,
        seq=2,
        bbox=BoundingBox(
            x=82.0,
            y=749.0,
            width=278.0,
            height=11.0,
            page_width=612.0,
            page_height=792.0,
        ),
        content=Paragraph(text=StyledText(runs=[TextRun(text="Section 1.2 continued")])),
        metadata={"label": "text"},
    )

    merged = HybridMergeEngine().merge(
        source="/tmp/sample.pdf",
        layout_doc=LayoutDocument(
            source="/tmp/sample.pdf",
            pages=(LayoutPage(page_number=1, width=612.0, height=792.0, lines=()),),
        ),
        semantics=SemanticExtraction(
            candidates=(
                _semantic_candidate(
                    node=heading_node,
                    node_type="heading",
                    text="Section 1.2 continued",
                    order=1,
                    left=80.0,
                    top=80.0,
                    right=360.0,
                    bottom=100.0,
                    metadata={"label": "section_header"},
                ),
                _semantic_candidate(
                    node=echo_node,
                    node_type="paragraph",
                    text="Section 1.2 continued",
                    order=2,
                    left=82.0,
                    top=749.0,
                    right=360.0,
                    bottom=760.0,
                    metadata={"label": "text"},
                ),
            )
        ),
    )

    headings = [node for node in merged.children if node.content.type == "heading"]
    paragraphs = [node for node in merged.children if node.content.type == "paragraph"]
    assert len(headings) == 1
    assert len(paragraphs) == 0


def test_duplicate_heading_phrase_collapses_to_single_phrase() -> None:
    heading_node = DocumentNode(
        id=uuid4(),
        page=1,
        seq=1,
        bbox=BoundingBox(
            x=80.0,
            y=100.0,
            width=320.0,
            height=24.0,
            page_width=612.0,
            page_height=792.0,
        ),
        content=Heading(
            level=HeadingLevel.CHAPTER,
            text=StyledText(
                runs=[TextRun(text="Introduction to Chemistry Introduction to Chemistry")]
            ),
        ),
        metadata={"label": "section_header"},
    )

    merged = HybridMergeEngine().merge(
        source="/tmp/sample.pdf",
        layout_doc=LayoutDocument(
            source="/tmp/sample.pdf",
            pages=(LayoutPage(page_number=1, width=612.0, height=792.0, lines=()),),
        ),
        semantics=SemanticExtraction(
            candidates=(
                _semantic_candidate(
                    node=heading_node,
                    node_type="heading",
                    text="Introduction to Chemistry Introduction to Chemistry",
                    order=1,
                    left=80.0,
                    top=100.0,
                    right=400.0,
                    bottom=124.0,
                    metadata={"label": "section_header"},
                ),
            )
        ),
    )

    headings = [node for node in merged.children if node.content.type == "heading"]
    assert len(headings) == 1
    assert headings[0].content.text.plain_text == "Introduction to Chemistry"
