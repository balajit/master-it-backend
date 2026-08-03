from __future__ import annotations

from pathlib import Path

from learning_platform.capabilities.reviewer_render.service import ReviewerRenderService
from learning_platform.models.book import BookPage, HeadingItem, ListItem, TableItem, TextItem


def test_render_book_page_returns_pdf_and_png() -> None:
    service = ReviewerRenderService()
    page = BookPage(
        page_number=1,
        items=[
            HeadingItem(content="Chapter 1", order=1),
            TextItem(content="Intro content", order=2),
        ],
    )

    rendered = service.render_book_page(page)

    assert rendered.item_count == 2
    assert rendered.pdf_bytes.startswith(b"%PDF")
    assert rendered.png_bytes.startswith(b"\x89PNG")
    assert "Chapter 1" in rendered.text_summary


def test_build_summary_handles_list_and_table_items() -> None:
    service = ReviewerRenderService(max_text_chars=5000)
    page = BookPage(
        page_number=2,
        items=[
            ListItem(items=["A", "B"], order=1),
            TableItem(headers=["H1", "H2"], rows=[["r1c1", "r1c2"]], order=2),
        ],
    )

    rendered = service.render_book_page(page)

    assert "- A" in rendered.text_summary
    assert "H1 | H2" in rendered.text_summary
    assert "r1c1 | r1c2" in rendered.text_summary


def test_to_base64_returns_ascii() -> None:
    service = ReviewerRenderService()
    payload = service.to_base64(b"abc")
    assert payload == "YWJj"


def test_persist_generated_pdf_writes_expected_path(tmp_path: Path) -> None:
    service = ReviewerRenderService(reviewer_generated_root=tmp_path)

    saved = service.persist_generated_pdf(
        pdf_bytes=b"%PDF-1.7 test",
        document_name="My Document.pdf",
        page_id="5_42",
    )

    saved_path = Path(saved)
    assert saved_path == tmp_path / "My Document.pdf" / "5_42.pdf"
    assert saved_path.read_bytes() == b"%PDF-1.7 test"
