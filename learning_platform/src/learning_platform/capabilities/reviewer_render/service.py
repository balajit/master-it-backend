from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from learning_platform.models.book import BookPage, ContentItem


class ReviewerRenderError(RuntimeError):
    """Raised when reviewer rendering operations fail."""


@dataclass(frozen=True)
class RenderedPageArtifacts:
    pdf_bytes: bytes
    png_bytes: bytes
    text_summary: str
    item_count: int
    truncated: bool


class ReviewerRenderService:
    """Render canonical and actual pages into comparable artifacts."""

    def __init__(
        self,
        *,
        max_text_chars: int = 12000,
        reviewer_generated_root: str | Path = "agentic_ops_managed_docs/reviewer_generated",
    ) -> None:
        self._max_text_chars = max(1000, int(max_text_chars))
        self._reviewer_generated_root = Path(reviewer_generated_root).expanduser().resolve()

    def render_book_page(self, book_page: BookPage) -> RenderedPageArtifacts:
        try:
            import pymupdf
        except Exception as exc:
            raise ReviewerRenderError("PyMuPDF dependency is required for page rendering") from exc

        text_summary = self._build_book_page_text_summary(book_page)

        doc = pymupdf.open()
        try:
            page = doc.new_page(width=612, height=792)
            cursor_y = 56.0
            for item in sorted(book_page.items, key=lambda row: row.order):
                block = self._format_item_text(item)
                if not block:
                    continue
                inserted = page.insert_textbox(
                    pymupdf.Rect(56.0, cursor_y, 556.0, 760.0),
                    block,
                    fontsize=11,
                    lineheight=1.25,
                    fontname="helv",
                )
                if inserted < 0:
                    break
                cursor_y += max(16.0, inserted + 12.0)
                if cursor_y >= 740.0:
                    break

            pdf_bytes = doc.tobytes(garbage=4, deflate=True)
        except Exception as exc:
            raise ReviewerRenderError(f"Failed rendering canonical book page: {exc}") from exc
        finally:
            doc.close()

        png_bytes = self.pdf_bytes_to_png_bytes(pdf_bytes)
        truncated = len(text_summary) >= self._max_text_chars
        return RenderedPageArtifacts(
            pdf_bytes=pdf_bytes,
            png_bytes=png_bytes,
            text_summary=text_summary,
            item_count=len(book_page.items),
            truncated=truncated,
        )

    def load_pdf_bytes_from_path(self, path: str) -> bytes:
        try:
            return Path(path).read_bytes()
        except Exception as exc:
            raise ReviewerRenderError(f"Failed to read PDF bytes from path: {path}") from exc

    def pdf_bytes_to_png_bytes(self, pdf_bytes: bytes) -> bytes:
        try:
            import pymupdf
        except Exception as exc:
            raise ReviewerRenderError(
                "PyMuPDF dependency is required for PDF rasterization"
            ) from exc

        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise ReviewerRenderError(
                f"Failed to open PDF bytes for rasterization: {exc}"
            ) from exc

        try:
            if len(doc) == 0:
                raise ReviewerRenderError("PDF has no pages")
            pix = doc[0].get_pixmap(alpha=False, dpi=144)
            return pix.tobytes("png")
        except ReviewerRenderError:
            raise
        except Exception as exc:
            raise ReviewerRenderError(f"Failed to convert PDF page to PNG: {exc}") from exc
        finally:
            doc.close()

    def persist_generated_pdf(
        self,
        *,
        pdf_bytes: bytes,
        document_name: str,
        page_id: str,
    ) -> str:
        safe_document_name = self._sanitize_path_component(document_name)
        safe_page_id = self._sanitize_path_component(page_id)
        if not safe_page_id:
            safe_page_id = "page"

        target_dir = self._reviewer_generated_root / safe_document_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{safe_page_id}.pdf"
        target_path.write_bytes(pdf_bytes)
        return str(target_path)

    @staticmethod
    def to_base64(payload: bytes) -> str:
        return base64.b64encode(payload).decode("ascii")

    def _build_book_page_text_summary(self, book_page: BookPage) -> str:
        chunks: list[str] = []
        for item in sorted(book_page.items, key=lambda row: row.order):
            formatted = self._format_item_text(item)
            if not formatted:
                continue
            chunks.append(formatted)
            if sum(len(chunk) for chunk in chunks) >= self._max_text_chars:
                break

        combined = "\n\n".join(chunks).strip()
        if not combined:
            return "[No canonical book items available for this page]"
        return combined[: self._max_text_chars]

    @staticmethod
    def _format_item_text(item: ContentItem) -> str:
        if item.type in {"text", "heading", "code"}:
            return str(getattr(item, "content", "")).strip()
        if item.type == "list":
            items = getattr(item, "items", [])
            if not isinstance(items, list):
                return ""
            return "\n".join(f"- {str(entry)}" for entry in items)
        if item.type == "form_area":
            items = getattr(item, "items", [])
            if not isinstance(items, list):
                return ""
            return "\n".join(f"[ ] {str(entry)}" for entry in items)
        if item.type == "table":
            headers = getattr(item, "headers", [])
            rows = getattr(item, "rows", [])
            table_lines: list[str] = []
            if isinstance(headers, list) and headers:
                table_lines.append(" | ".join(str(cell) for cell in headers))
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, list):
                        table_lines.append(" | ".join(str(cell) for cell in row))
            return "\n".join(table_lines)
        if item.type == "equation":
            return str(getattr(item, "latex", "")).strip()
        if item.type == "question":
            question_text = str(getattr(item, "content", "")).strip()
            options = getattr(item, "options", [])
            option_lines: list[str] = []
            if isinstance(options, list):
                for option in options:
                    text = ""
                    if isinstance(option, dict):
                        text = str(option.get("text", ""))
                    else:
                        text = str(getattr(option, "text", ""))
                    if text:
                        option_lines.append(f"- {text}")
            return "\n".join([question_text, *option_lines]).strip()
        if item.type == "image":
            caption = str(getattr(item, "caption", "")).strip()
            return caption or "[Image content]"
        metadata = getattr(item, "metadata", None)
        if isinstance(metadata, dict):
            return str(metadata.get("text", "")).strip()
        return ""

    @staticmethod
    def _sanitize_path_component(value: str) -> str:
        raw = value.strip()
        if not raw:
            return "unknown"
        safe = raw.replace("/", "_").replace("\\", "_")
        safe = safe.replace("\x00", "")
        safe = safe.strip(".")
        return safe or "unknown"


__all__ = ["ReviewerRenderService", "ReviewerRenderError", "RenderedPageArtifacts"]
