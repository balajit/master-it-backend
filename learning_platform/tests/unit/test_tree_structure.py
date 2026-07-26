"""Tests for document tree structure, page grouping, and image handling."""

from __future__ import annotations

import uuid

from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Figure,
    Heading,
    HeadingLevel,
    ListBlock,
    ListItem,
    ListStyle,
    Paragraph,
    StyledText,
    TextRun,
)
from learning_platform.stages.normalizer.passes.heading_section import HeadingSectionPass
from learning_platform.stages.normalizer.passes.page_grouping import PageGroupingPass

# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────


def _para(text: str, page: int = 1) -> DocumentNode:
    return DocumentNode(
        content=Paragraph(text=StyledText(runs=[TextRun(text=text)])),
        page=page,
    )


def _heading(text: str, level: int = 1, page: int = 1) -> DocumentNode:
    return DocumentNode(
        content=Heading(
            level=HeadingLevel(min(level, 4)),
            text=StyledText(runs=[TextRun(text=text)]),
        ),
        page=page,
    )


def _list_group(items: list[str], page: int = 1) -> DocumentNode:
    """Create a ListBlock container with child list items."""
    children = []
    for item_text in items:
        child = DocumentNode(
            content=ListBlock(
                style=ListStyle.BULLET,
                items=[ListItem(text=StyledText(runs=[TextRun(text=item_text)]))],
            ),
            page=page,
        )
        children.append(child)

    parent = DocumentNode(
        content=ListBlock(style=ListStyle.BULLET, items=[]),
        page=page,
        children=children,
    )
    # Set parent_id on children
    for child in children:
        child.parent_id = parent.id

    return parent


def _figure(
    caption: str = "",
    image_uri: str = "",
    mimetype: str = "",
    page: int = 1,
) -> DocumentNode:
    return DocumentNode(
        content=Figure(
            caption_text=caption,
            image_uri=image_uri,
            mimetype=mimetype,
        ),
        page=page,
    )


def _doc(*nodes: DocumentNode) -> CanonicalDocument:
    root = DocumentNode(
        id=uuid.uuid4(),
        content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
        metadata={"role": "document_root"},
        children=list(nodes),
    )
    return CanonicalDocument(
        title="test",
        source="test.pdf",
        nodes=[root],
        metadata=DocumentMetadata(title="test", source="test.pdf"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Docling Tree Structure
# ──────────────────────────────────────────────────────────────────────────────


class TestDoclingTreeStructure:
    """Test that Docling adapter preserves parent-child relationships."""

    def test_list_items_have_parent(self) -> None:
        """List items should have parent_id pointing to the list group."""
        list_node = _list_group(["Item 1", "Item 2", "Item 3"])

        assert list_node.children[0].parent_id == list_node.id
        assert list_node.children[1].parent_id == list_node.id
        assert list_node.children[2].parent_id == list_node.id

    def test_list_children_are_list_blocks(self) -> None:
        """List items should be ListBlock nodes."""
        list_node = _list_group(["Item 1", "Item 2"])

        for child in list_node.children:
            assert isinstance(child.content, ListBlock)

    def test_section_with_children(self) -> None:
        """Section header should have text and list as children."""
        heading = _heading("Section 1", level=1)
        para = _para("Some text")
        list_node = _list_group(["Item 1", "Item 2"])

        # Simulate Docling tree structure
        heading.children = [para, list_node]
        para.parent_id = heading.id
        list_node.parent_id = heading.id

        assert len(heading.children) == 2
        assert heading.children[0].parent_id == heading.id
        assert heading.children[1].parent_id == heading.id

    def test_figure_metadata(self) -> None:
        """Figure should have correct metadata fields."""
        fig = _figure(
            caption="Figure 1",
            image_uri="data:image/png;base64,abc123",
            mimetype="image/png",
        )

        content = fig.content
        assert isinstance(content, Figure)
        assert content.caption_text == "Figure 1"
        assert content.image_uri == "data:image/png;base64,abc123"
        assert content.mimetype == "image/png"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Page Grouping Pass
# ──────────────────────────────────────────────────────────────────────────────


class TestPageGroupingPass:
    """Test page container node creation."""

    def test_creates_page_containers(self) -> None:
        """Each page should get a page container node."""
        p1 = _para("Page 1 content", page=1)
        p2 = _para("Page 2 content", page=2)

        result = PageGroupingPass()([p1, p2])

        page_groups = [n for n in result if n.metadata.get("role") == "page_group"]
        assert len(page_groups) == 2

    def test_page_container_has_page_number(self) -> None:
        """Page container should have page_number metadata."""
        p1 = _para("Content", page=3)

        result = PageGroupingPass()([p1])

        page_groups = [n for n in result if n.metadata.get("role") == "page_group"]
        assert len(page_groups) == 1
        assert page_groups[0].metadata["page_number"] == 3

    def test_nodes_parented_to_page_container(self) -> None:
        """Nodes should be children of their page's container."""
        p1 = _para("Page 1", page=1)
        p2 = _para("Page 2", page=2)

        result = PageGroupingPass()([p1, p2])

        # Find page containers
        page_groups = {}
        for n in result:
            if n.metadata.get("role") == "page_group":
                page_groups[n.metadata["page_number"]] = n

        # Check that nodes are parented correctly
        for node in result:
            if node.metadata.get("role") == "page_group":
                continue
            if node.page in page_groups:
                assert node.parent_id == page_groups[node.page].id

    def test_preserves_existing_parent_same_page(self) -> None:
        """Nodes with valid parent on same page should keep parent."""
        heading = _heading("Section", page=1)
        para = _para("Content", page=1)
        para.parent_id = heading.id

        result = PageGroupingPass()([heading, para])

        # Find the para node in result
        para_nodes = [n for n in result if n.content.text.plain_text == "Content"]
        assert len(para_nodes) == 1
        # para should keep its parent (heading)
        assert para_nodes[0].parent_id == heading.id

    def test_preserves_cross_page_parent_child(self) -> None:
        """Nodes with parent on different page should preserve parent-child relationship."""
        heading = _heading("Section", page=1)
        para = _para("Content", page=2)
        para.parent_id = heading.id  # Parent is on page 1, but node is on page 2

        result = PageGroupingPass()([heading, para])

        # para should preserve its parent_id pointing to the heading
        para_result = [n for n in result if n.content.text.plain_text == "Content"][0]
        assert para_result.parent_id == heading.id

    def test_empty_input(self) -> None:
        """Empty input should return empty list."""
        result = PageGroupingPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Heading Section Pass
# ──────────────────────────────────────────────────────────────────────────────


class TestHeadingSectionPass:
    """Test heading-based section hierarchy."""

    def test_content_under_heading(self) -> None:
        """Content should be child of preceding heading."""
        h1 = _heading("Chapter 1", level=1)
        p1 = _para("Content")

        result = HeadingSectionPass()([h1, p1])

        assert result[1].parent_id == result[0].id

    def test_subheading_under_heading(self) -> None:
        """Subheading should be child of higher-level heading."""
        h1 = _heading("Chapter", level=1)
        h2 = _heading("Section", level=2)

        result = HeadingSectionPass()([h1, h2])

        assert result[1].parent_id == result[0].id

    def test_preserves_existing_parent(self) -> None:
        """Nodes with existing parent_id should not be changed if parent exists."""
        h1 = _heading("Chapter", level=1)
        h2 = _heading("Section", level=2)
        p1 = _para("Content")
        p1.parent_id = h1.id  # Parent exists in the node list

        result = HeadingSectionPass()([h1, h2, p1])

        # p1 should keep its parent (h1) since it exists
        para_result = [n for n in result if n.content.text.plain_text == "Content"][0]
        assert para_result.parent_id == h1.id

    def test_invalid_parent_id_cleared(self) -> None:
        """Nodes with invalid parent_id should have it cleared."""
        h1 = _heading("Chapter", level=1)
        p1 = _para("Content")
        p1.parent_id = uuid.uuid4()  # Non-existent parent

        result = HeadingSectionPass()([h1, p1])

        # Should be reparented to h1 since original parent was invalid
        assert result[1].parent_id == result[0].id

    def test_skips_page_containers(self) -> None:
        """Page containers should not be affected by heading logic."""
        page_group = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={"role": "page_group", "page_number": 1},
            page=1,
        )
        h1 = _heading("Chapter", level=1)

        result = HeadingSectionPass()([page_group, h1])

        # Page container should be unchanged
        assert result[0].metadata.get("role") == "page_group"
        # Heading should be at root level (no parent)
        assert result[1].parent_id is None

    def test_empty_input(self) -> None:
        """Empty input should return empty list."""
        result = HeadingSectionPass()([])
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Integration with Docling tree
# ──────────────────────────────────────────────────────────────────────────────


class TestDoclingTreeIntegration:
    """Test full tree structure as produced by Docling adapter."""

    def test_section_with_list_children(self) -> None:
        """A section should contain text and list children."""
        # Simulate Docling output
        heading = _heading("What you'll learn", level=1, page=1)
        para = _para("This guide covers:", page=1)
        list_node = _list_group(["Item 1", "Item 2", "Item 3"], page=1)

        # Build tree structure
        heading.children = [para, list_node]
        para.parent_id = heading.id
        list_node.parent_id = heading.id

        # Verify structure
        assert len(heading.children) == 2
        assert heading.children[0].content.text.plain_text == "This guide covers:"
        assert heading.children[1].parent_id == heading.id

        # List items should be children of list
        list_children = heading.children[1].children
        assert len(list_children) == 3
        for child in list_children:
            assert child.parent_id == heading.children[1].id

    def test_multiple_sections_on_page(self) -> None:
        """Multiple sections on same page should be siblings."""
        h1 = _heading("Section 1", level=1, page=1)
        h2 = _heading("Section 2", level=1, page=1)
        p1 = _para("Content 1", page=1)
        p2 = _para("Content 2", page=1)

        # Build tree
        h1.children = [p1]
        p1.parent_id = h1.id
        h2.children = [p2]
        p2.parent_id = h2.id

        # Both should be root-level (no parent)
        assert h1.parent_id is None
        assert h2.parent_id is None

    def test_figure_in_section(self) -> None:
        """Figure should be child of section."""
        heading = _heading("Section", level=1, page=1)
        fig = _figure(caption="Figure 1", page=1)

        heading.children = [fig]
        fig.parent_id = heading.id

        assert heading.children[0].parent_id == heading.id
        assert isinstance(heading.children[0].content, Figure)
