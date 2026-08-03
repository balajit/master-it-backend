"""Unit tests for BookAssembler handling parser2 text/form-area nodes."""

from __future__ import annotations

from uuid import UUID, uuid4

from learning_platform.models.book import FormAreaItem as BookFormAreaItem
from learning_platform.models.book import TextItem as BookTextItem
from learning_platform.models.document import DocumentNode, FormAreaBlock, StyledText, TextRun
from learning_platform.models.document import TextItem as CanonicalTextItem
from learning_platform.stages.book_assembler.assembler import BookAssembler


def _text_node(*, text: str, page: int, seq: int, parent_id: UUID | None = None) -> DocumentNode:
    return DocumentNode(
        id=uuid4(),
        parent_id=parent_id,
        page=page,
        seq=seq,
        content=CanonicalTextItem(text=StyledText(runs=[TextRun(text=text)])),
    )


def test_node_to_item_maps_canonical_text_item() -> None:
    assembler = BookAssembler()
    node = _text_node(text="hello world", page=1, seq=0)

    mapped = assembler._node_to_item(node, order=0)

    assert isinstance(mapped, BookTextItem)
    assert mapped.content == "hello world"


def test_nodes_to_items_maps_form_area_and_skips_child_text_nodes() -> None:
    assembler = BookAssembler()

    form_node = DocumentNode(
        id=uuid4(),
        page=1,
        seq=0,
        content=FormAreaBlock(display_hint="word_bank"),
        metadata={"label": "form_area"},
    )
    child_one = _text_node(text="alpha", page=1, seq=1, parent_id=form_node.id)
    child_two = _text_node(text="beta", page=1, seq=2, parent_id=form_node.id)
    form_node.children = [child_one, child_two]

    items = assembler._nodes_to_items([form_node, child_one, child_two])

    assert len(items) == 1
    assert isinstance(items[0], BookFormAreaItem)
    assert items[0].items == ["alpha", "beta"]
    assert items[0].metadata.get("display_hint") == "word_bank"
