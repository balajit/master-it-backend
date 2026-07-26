"""Tests for table-of-contents parsing and auto-generation.

Tests both unit-level (internal methods directly) and integration-level
(Docling parsing real PDFs) for TOC handling.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fpdf import FPDF

from learning_platform.models.document import (
    DocumentNode,
    Heading,
    HeadingLevel,
    Paragraph,
    StyledText,
    TableOfContents,
    TableOfContentsEntry,
    TableOfContentsType,
    TextRun,
)
from learning_platform.stages.parser.docling_adapter import DoclingAdapter

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_heading_node(text: str, page: int = 1, number: str = "") -> DocumentNode:
    """Create a Heading DocumentNode for testing."""
    return DocumentNode(
        id=uuid4(),
        content=Heading(
            level=HeadingLevel.SECTION,
            text=StyledText(runs=[TextRun(text=text)]),
            number=number,
        ),
        page=page,
    )


def _build_pdf_headings_only(path: Path) -> None:
    """PDF with simple headings (no numbered prefixes) that Docling detects correctly."""
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 10, "Document Title", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Introduction", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 10, "Intro content here.")

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Background", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 10, "Background content here.")

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Analysis", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 10, "Analysis content here.")

    pdf.output(str(path))


def _build_pdf_toc_and_headings(path: Path) -> None:
    """PDF with a TOC-like first page plus section headings."""
    pdf = FPDF()
    pdf.add_page()

    # Page 1: TOC-like content
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, "Table of Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    for entry in [
        "Introduction .............. 2",
        "Background ............... 3",
        "Analysis .................. 4",
    ]:
        pdf.cell(0, 8, entry, new_x="LMARGIN", new_y="NEXT")

    # Page 2+: Headings
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Introduction", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 10, "Intro content.")

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Background", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.multi_cell(0, 10, "Background content.")

    pdf.output(str(path))


# ── Unit Tests: _make_toc ─────────────────────────────────────────────────


class TestMakeToc:
    """Unit tests for _make_toc parsing a document_index item."""

    def _make_item(self, text: str) -> object:
        """Create a mock item with document_index label."""

        class _Item:
            def __init__(self, t: str) -> None:
                self.text = t
                self.label = "document_index"
                self.self_ref = "mock_ref"
                self.prov = []

        return _Item(text)

    def test_toc_entries_with_dot_leader(self) -> None:
        adapter = DoclingAdapter()
        item = self._make_item(
            "Introduction .............. 2\n"
            "Methods ................... 3\n"
            "Results ................... 4"
        )
        node = adapter._make_toc(item, "/test.pdf")

        assert isinstance(node.content, TableOfContents)
        assert node.content.toc_type == TableOfContentsType.MANUAL
        assert len(node.content.entries) == 3

        assert node.content.entries[0].label == "Introduction"
        assert node.content.entries[0].page_number == 2

        assert node.content.entries[1].label == "Methods"
        assert node.content.entries[1].page_number == 3

        assert node.content.entries[2].label == "Results"
        assert node.content.entries[2].page_number == 4

    def test_toc_entries_with_dash_leader(self) -> None:
        adapter = DoclingAdapter()
        item = self._make_item("Chapter 1 -- 10\nChapter 2 -- 20")
        node = adapter._make_toc(item, "/test.pdf")

        assert isinstance(node.content, TableOfContents)
        assert len(node.content.entries) == 2
        assert node.content.entries[0].label == "Chapter 1"
        assert node.content.entries[0].page_number == 10

    def test_toc_entries_without_page_number(self) -> None:
        adapter = DoclingAdapter()
        item = self._make_item("Introduction\nMethods\nResults")
        node = adapter._make_toc(item, "/test.pdf")

        assert isinstance(node.content, TableOfContents)
        assert len(node.content.entries) == 3
        assert node.content.entries[0].label == "Introduction"
        assert node.content.entries[0].page_number == 0

    def test_toc_empty_text(self) -> None:
        adapter = DoclingAdapter()
        item = self._make_item("")
        node = adapter._make_toc(item, "/test.pdf")

        assert isinstance(node.content, TableOfContents)
        assert len(node.content.entries) == 0


# ── Unit Tests: _auto_generate_toc ────────────────────────────────────────


class TestAutoGenerateToc:
    """Unit tests for _auto_generate_toc building TOC from headings."""

    def test_generates_toc_from_headings(self) -> None:
        adapter = DoclingAdapter()
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            metadata={"role": "document_root"},
            children=[
                _make_heading_node("Introduction", page=1, number="1."),
                _make_heading_node("Methods", page=2, number="2."),
                _make_heading_node("Results", page=3, number="3."),
            ],
        )

        adapter._auto_generate_toc(root)

        toc_children = [c for c in root.children if isinstance(c.content, TableOfContents)]
        assert len(toc_children) == 1
        toc = toc_children[0].content
        assert toc.toc_type == TableOfContentsType.AUTO
        assert len(toc.entries) == 3

    def test_toc_entries_reference_heading_nodes(self) -> None:
        adapter = DoclingAdapter()
        heading1 = _make_heading_node("Introduction", page=1)
        heading2 = _make_heading_node("Methods", page=2)
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            children=[heading1, heading2],
        )

        adapter._auto_generate_toc(root)

        toc = next(c.content for c in root.children if isinstance(c.content, TableOfContents))
        assert toc.entries[0].node_id == heading1.id
        assert toc.entries[1].node_id == heading2.id

    def test_toc_entry_labels_match_heading_text(self) -> None:
        adapter = DoclingAdapter()
        heading = _make_heading_node("Background", page=2, number="2.")
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            children=[heading],
        )

        adapter._auto_generate_toc(root)

        toc = next(c.content for c in root.children if isinstance(c.content, TableOfContents))
        assert toc.entries[0].label == "2. Background"
        assert toc.entries[0].page_number == 2

    def test_toc_entry_indent_level_from_heading(self) -> None:
        adapter = DoclingAdapter()
        h1 = DocumentNode(
            id=uuid4(),
            content=Heading(
                level=HeadingLevel.CHAPTER,
                text=StyledText(runs=[TextRun(text="Chapter 1")]),
            ),
            page=1,
        )
        h2 = DocumentNode(
            id=uuid4(),
            content=Heading(
                level=HeadingLevel.SUBSECTION,
                text=StyledText(runs=[TextRun(text="Subsection")]),
            ),
            page=2,
        )
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            children=[h1, h2],
        )

        adapter._auto_generate_toc(root)

        toc = next(c.content for c in root.children if isinstance(c.content, TableOfContents))
        assert toc.entries[0].indent_level == HeadingLevel.CHAPTER.value
        assert toc.entries[1].indent_level == HeadingLevel.SUBSECTION.value

    def test_no_headings_no_toc(self) -> None:
        adapter = DoclingAdapter()
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            children=[
                DocumentNode(
                    id=uuid4(),
                    content=Paragraph(text=StyledText(runs=[TextRun(text="Some text")])),
                ),
            ],
        )

        adapter._auto_generate_toc(root)

        toc_children = [c for c in root.children if isinstance(c.content, TableOfContents)]
        assert len(toc_children) == 0

    def test_existing_toc_not_overwritten(self) -> None:
        adapter = DoclingAdapter()
        existing_toc = DocumentNode(
            id=uuid4(),
            content=TableOfContents(
                toc_type=TableOfContentsType.MANUAL,
                entries=[TableOfContentsEntry(label="Existing", page_number=1)],
            ),
        )
        heading = _make_heading_node("New Heading", page=2)
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            children=[existing_toc, heading],
        )

        adapter._auto_generate_toc(root)

        toc_children = [c for c in root.children if isinstance(c.content, TableOfContents)]
        assert len(toc_children) == 1
        assert toc_children[0].content.toc_type == TableOfContentsType.MANUAL
        assert len(toc_children[0].content.entries) == 1
        assert toc_children[0].content.entries[0].label == "Existing"

    def test_toc_inserted_as_first_child(self) -> None:
        adapter = DoclingAdapter()
        heading = _make_heading_node("First Heading", page=1)
        para = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="Paragraph")])),
        )
        root = DocumentNode(
            id=uuid4(),
            content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
            children=[heading, para],
        )

        adapter._auto_generate_toc(root)

        assert isinstance(root.children[0].content, TableOfContents)
        assert isinstance(root.children[1].content, Heading)
        assert isinstance(root.children[2].content, Paragraph)


# ── Integration Tests: Docling end-to-end ─────────────────────────────────


class TestDoclingEndToEnd:
    """Integration tests using Docling to parse real (generated) PDFs."""

    @staticmethod
    def _get_root(doc: object) -> DocumentNode:
        """Return the root node from a parsed CanonicalDocument."""
        return doc.nodes[0]  # type: ignore[union-attr]

    @staticmethod
    def _get_toc_children(root: DocumentNode) -> list[DocumentNode]:
        """Return TableOfContents children of root."""
        return [c for c in root.children if isinstance(c.content, TableOfContents)]

    @staticmethod
    def _get_heading_children(root: DocumentNode) -> list[DocumentNode]:
        """Return Heading children of root (non-recursive)."""
        return [c for c in root.children if isinstance(c.content, Heading)]

    def test_pdf_with_headings_gets_auto_toc(self, tmp_path: Path) -> None:
        pdf = tmp_path / "headings.pdf"
        _build_pdf_headings_only(pdf)

        adapter = DoclingAdapter()
        doc = adapter.parse(str(pdf))
        root = self._get_root(doc)

        toc_children = self._get_toc_children(root)
        assert len(toc_children) >= 1, "Expected at least one auto-generated TOC"
        assert toc_children[0].content.toc_type == TableOfContentsType.AUTO

    def test_auto_toc_entries_have_node_references(self, tmp_path: Path) -> None:
        pdf = tmp_path / "headings.pdf"
        _build_pdf_headings_only(pdf)

        adapter = DoclingAdapter()
        doc = adapter.parse(str(pdf))
        doc.rebuild_index()
        root = self._get_root(doc)

        toc_children = self._get_toc_children(root)
        assert toc_children, "No TOC nodes found"
        entries = toc_children[0].content.entries
        assert len(entries) >= 2, f"Expected >=2 TOC entries, got {len(entries)}"

        for entry in entries:
            assert entry.node_id is not None, f"TOC entry '{entry.label}' missing node_id"
            referenced = doc.get_node(entry.node_id)
            assert referenced is not None, (
                f"TOC entry '{entry.label}' references non-existent node"
            )
            assert isinstance(referenced.content, Heading), (
                f"TOC entry '{entry.label}' does not reference a Heading"
            )

    def test_toc_is_first_child_of_root(self, tmp_path: Path) -> None:
        pdf = tmp_path / "headings.pdf"
        _build_pdf_headings_only(pdf)

        adapter = DoclingAdapter()
        doc = adapter.parse(str(pdf))
        root = self._get_root(doc)

        assert len(root.children) > 0, "Root has no children"
        assert isinstance(root.children[0].content, TableOfContents)

    def test_toc_entry_labels_match_headings(self, tmp_path: Path) -> None:
        pdf = tmp_path / "headings.pdf"
        _build_pdf_headings_only(pdf)

        adapter = DoclingAdapter()
        doc = adapter.parse(str(pdf))
        root = self._get_root(doc)

        toc_children = self._get_toc_children(root)
        assert toc_children, "No TOC nodes found"
        entries = toc_children[0].content.entries

        heading_texts = [c.content.text.plain_text for c in self._get_heading_children(root)]

        for entry in entries:
            found = any(entry.label in ht or ht in entry.label for ht in heading_texts)
            assert found, f"TOC entry '{entry.label}' does not match any heading"

    def test_plain_document_no_toc(self, tmp_path: Path) -> None:
        pdf = tmp_path / "plain.pdf"
        p = FPDF()
        p.add_page()
        p.set_font("Helvetica", "", 12)
        p.multi_cell(0, 10, "Just plain text without any headings.")
        p.output(str(pdf))

        adapter = DoclingAdapter()
        doc = adapter.parse(str(pdf))
        root = self._get_root(doc)

        toc_children = self._get_toc_children(root)
        assert len(toc_children) == 0, "Plain document should not get a TOC"
