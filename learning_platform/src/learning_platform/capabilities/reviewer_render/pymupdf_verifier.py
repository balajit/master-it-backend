from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class PyMuPdfVerificationResult:
    text_char_count_actual: int
    text_char_count_generated: int
    token_count_actual: int
    token_count_generated: int
    text_similarity_ratio: float
    missing_token_count: int
    missing_token_examples: list[str]
    image_count_actual: int
    image_count_generated: int
    font_count_actual: int
    font_count_generated: int
    has_text_loss: bool
    has_asset_mismatch: bool

    @property
    def should_skip_llm(self) -> bool:
        return self.has_text_loss or self.has_asset_mismatch

    def to_dict(self) -> dict[str, object]:
        return {
            "text_char_count_actual": self.text_char_count_actual,
            "text_char_count_generated": self.text_char_count_generated,
            "token_count_actual": self.token_count_actual,
            "token_count_generated": self.token_count_generated,
            "text_similarity_ratio": self.text_similarity_ratio,
            "missing_token_count": self.missing_token_count,
            "missing_token_examples": self.missing_token_examples,
            "image_count_actual": self.image_count_actual,
            "image_count_generated": self.image_count_generated,
            "font_count_actual": self.font_count_actual,
            "font_count_generated": self.font_count_generated,
            "has_text_loss": self.has_text_loss,
            "has_asset_mismatch": self.has_asset_mismatch,
            "should_skip_llm": self.should_skip_llm,
        }


class PyMuPdfVerifier:
    """Deterministic page-level verifier before multimodal review."""

    def __init__(
        self,
        *,
        min_text_similarity_ratio: float = 0.92,
        max_missing_tokens: int = 0,
    ) -> None:
        self._min_text_similarity_ratio = min_text_similarity_ratio
        self._max_missing_tokens = max_missing_tokens

    def compare_page_pdfs(
        self,
        *,
        actual_pdf_bytes: bytes,
        generated_pdf_bytes: bytes,
    ) -> PyMuPdfVerificationResult:
        try:
            import pymupdf
        except Exception as exc:
            raise RuntimeError(
                "PyMuPDF dependency is required for deterministic verification"
            ) from exc

        actual_doc = pymupdf.open(stream=actual_pdf_bytes, filetype="pdf")
        generated_doc = pymupdf.open(stream=generated_pdf_bytes, filetype="pdf")
        try:
            if len(actual_doc) == 0 or len(generated_doc) == 0:
                raise ValueError("Both PDFs must contain at least one page")

            actual_page = actual_doc[0]
            generated_page = generated_doc[0]

            actual_text = actual_page.get_text("text") or ""
            generated_text = generated_page.get_text("text") or ""
            actual_tokens = self._tokenize(actual_text)
            generated_tokens = self._tokenize(generated_text)

            similarity_ratio = SequenceMatcher(a=actual_text, b=generated_text).ratio()
            missing_tokens = self._missing_tokens(actual_tokens, generated_tokens)

            image_count_actual = len(actual_page.get_images(full=True))
            image_count_generated = len(generated_page.get_images(full=True))
            font_count_actual = len(actual_page.get_fonts(full=True))
            font_count_generated = len(generated_page.get_fonts(full=True))

            has_text_loss = bool(
                similarity_ratio < self._min_text_similarity_ratio
                or len(missing_tokens) > self._max_missing_tokens
            )
            has_asset_mismatch = bool(
                image_count_actual != image_count_generated
                or font_count_actual != font_count_generated
            )

            return PyMuPdfVerificationResult(
                text_char_count_actual=len(actual_text),
                text_char_count_generated=len(generated_text),
                token_count_actual=len(actual_tokens),
                token_count_generated=len(generated_tokens),
                text_similarity_ratio=round(float(similarity_ratio), 6),
                missing_token_count=len(missing_tokens),
                missing_token_examples=missing_tokens[:20],
                image_count_actual=image_count_actual,
                image_count_generated=image_count_generated,
                font_count_actual=font_count_actual,
                font_count_generated=font_count_generated,
                has_text_loss=has_text_loss,
                has_asset_mismatch=has_asset_mismatch,
            )
        finally:
            actual_doc.close()
            generated_doc.close()

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token for token in text.lower().split() if token]

    @staticmethod
    def _missing_tokens(actual_tokens: list[str], generated_tokens: list[str]) -> list[str]:
        generated_set = set(generated_tokens)
        ordered: list[str] = []
        seen: set[str] = set()
        for token in actual_tokens:
            if token in generated_set or token in seen:
                continue
            seen.add(token)
            ordered.append(token)
        return ordered


__all__ = ["PyMuPdfVerifier", "PyMuPdfVerificationResult"]
