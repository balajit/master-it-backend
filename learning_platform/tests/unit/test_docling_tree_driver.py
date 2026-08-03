from __future__ import annotations

import json
from pathlib import Path

from learning_platform.debug.docling_tree_driver import build_tree_json, render_tree, run
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Heading,
    HeadingLevel,
    Paragraph,
    StyledText,
    TextRun,
)


def _styled(text: str) -> StyledText:
    return StyledText(runs=[TextRun(text=text)])


def _sample_document(source: str) -> CanonicalDocument:
    root = DocumentNode(content=Paragraph(text=_styled("")), metadata={"role": "document_root"})
    heading = DocumentNode(
        content=Heading(level=HeadingLevel.CHAPTER, text=_styled("Chapter One")),
        page=1,
        parent_id=root.id,
    )
    paragraph = DocumentNode(
        content=Paragraph(text=_styled("This is a paragraph for tree output tests.")),
        page=1,
        parent_id=heading.id,
    )
    heading.children = [paragraph]
    root.children = [heading]

    return CanonicalDocument(
        source=source,
        title="Demo",
        metadata=DocumentMetadata(title="Demo", page_count=1, file_type="pdf"),
        nodes=[root],
    )


def test_render_tree_contains_hierarchy_and_counts() -> None:
    doc = _sample_document("/tmp/demo.pdf")

    output = render_tree(
        doc,
        max_preview_chars=20,
        include_bbox=False,
        include_source=False,
        include_type_counts=True,
    )

    assert "title=Demo" in output
    assert "tree_node_count=3" in output
    assert "type_counts=heading:1, paragraph:2" in output
    assert "- type=paragraph" in output
    assert 'text="This is a paragraph..."' in output


def test_build_tree_json_has_expected_shape() -> None:
    doc = _sample_document("/tmp/demo.pdf")

    payload = build_tree_json(doc, max_preview_chars=100)

    assert payload["title"] == "Demo"
    assert payload["tree_node_count"] == 3
    assert payload["type_counts"] == {"heading": 1, "paragraph": 2}
    assert payload["tree"]["children_count"] == 1
    assert payload["tree"]["children"][0]["type"] == "heading"


def test_run_json_prints_tree(monkeypatch, tmp_path: Path, capsys) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4 mock")

    class _Adapter:
        def supports(self, _source: str) -> bool:
            return True

        def parse(self, parsed_source: str) -> CanonicalDocument:
            return _sample_document(parsed_source)

    monkeypatch.setattr(
        "learning_platform.debug.docling_tree_driver.DoclingAdapter", lambda: _Adapter()
    )

    exit_code = run([str(source), "--json", "--max-preview-chars", "12"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["tree_node_count"] == 3
    assert payload["tree"]["children"][0]["preview"] == "Chapter One"


def test_run_rejects_missing_source(capsys) -> None:
    exit_code = run(["/definitely/missing/file.pdf"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "source file does not exist" in captured.err
