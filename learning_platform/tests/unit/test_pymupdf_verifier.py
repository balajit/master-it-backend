from __future__ import annotations

import pymupdf

from learning_platform.capabilities.reviewer_render.pymupdf_verifier import PyMuPdfVerifier


def _build_single_page_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=612, height=792)
        page.insert_text((56, 72), text, fontsize=12, fontname="helv")
        return doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()


def test_verifier_detects_high_similarity() -> None:
    verifier = PyMuPdfVerifier(min_text_similarity_ratio=0.90, max_missing_tokens=1)
    actual = _build_single_page_pdf("alpha beta gamma")
    generated = _build_single_page_pdf("alpha beta gamma")

    result = verifier.compare_page_pdfs(actual_pdf_bytes=actual, generated_pdf_bytes=generated)

    assert result.text_similarity_ratio >= 0.99
    assert result.missing_token_count == 0
    assert result.should_skip_llm is False


def test_verifier_detects_text_loss() -> None:
    verifier = PyMuPdfVerifier(min_text_similarity_ratio=0.95, max_missing_tokens=0)
    actual = _build_single_page_pdf("alpha beta gamma delta")
    generated = _build_single_page_pdf("alpha gamma")

    result = verifier.compare_page_pdfs(actual_pdf_bytes=actual, generated_pdf_bytes=generated)

    assert result.missing_token_count >= 1
    assert result.has_text_loss is True
    assert result.should_skip_llm is True
