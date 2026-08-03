from __future__ import annotations

import base64
from pathlib import Path

import pytest

from learning_platform.capabilities.managed_docs.service import (
    ManagedDocsService,
    ManagedDocsValidationError,
)


def _make_pdf_bytes(page_count: int) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    try:
        for index in range(page_count):
            page = doc.new_page()
            page.insert_text((72, 72), f"page-{index + 1}")
        return doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()


def _page_count(path: Path) -> int:
    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        return int(len(doc))
    finally:
        doc.close()


def test_slice_document_pages_path_mode_saves_orig_and_sliced(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(_make_pdf_bytes(page_count=5))

    service = ManagedDocsService(managed_docs_root=str(tmp_path / "managed"))
    result = service.slice_document_pages(
        mode="path",
        start_page=2,
        end_page=4,
        source_path=str(source),
        source_pdf_base64=None,
        filename=None,
    )

    assert result.source_mode == "path"
    assert Path(result.orig_path).exists()
    assert Path(result.sliced_path).exists()
    assert _page_count(Path(result.sliced_path)) == 3
    assert result.sliced_pdf_base64 is None


def test_slice_document_pages_base64_mode_returns_base64(tmp_path: Path) -> None:
    source_bytes = _make_pdf_bytes(page_count=3)
    source_b64 = base64.b64encode(source_bytes).decode("ascii")

    service = ManagedDocsService(managed_docs_root=str(tmp_path / "managed"))
    result = service.slice_document_pages(
        mode="base64",
        start_page=1,
        end_page=1,
        source_path=None,
        source_pdf_base64=source_b64,
        filename="uploaded.pdf",
    )

    assert result.source_mode == "base64"
    assert result.sliced_pdf_base64 is not None
    decoded = base64.b64decode(result.sliced_pdf_base64)
    sliced = tmp_path / "decoded.pdf"
    sliced.write_bytes(decoded)
    assert _page_count(sliced) == 1


def test_list_managed_documents_returns_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(_make_pdf_bytes(page_count=2))
    service = ManagedDocsService(managed_docs_root=str(tmp_path / "managed"))

    _ = service.slice_document_pages(
        mode="path",
        start_page=1,
        end_page=1,
        source_path=str(source),
        source_pdf_base64=None,
        filename="sample.pdf",
    )

    rows = service.list_managed_documents()
    assert len(rows) == 1
    assert rows[0].source_mode == "path"
    assert rows[0].source_path == str(source.resolve())
    assert rows[0].path.endswith(".pdf")


def test_slice_document_pages_rejects_invalid_range(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(_make_pdf_bytes(page_count=2))
    service = ManagedDocsService(managed_docs_root=str(tmp_path / "managed"))

    with pytest.raises(ManagedDocsValidationError, match="greater than or equal"):
        _ = service.slice_document_pages(
            mode="path",
            start_page=2,
            end_page=1,
            source_path=str(source),
            source_pdf_base64=None,
            filename=None,
        )
