from __future__ import annotations

import base64
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4


class ManagedDocsError(RuntimeError):
    """Base exception for managed-doc capability failures."""


class ManagedDocsValidationError(ManagedDocsError):
    """Raised when request input is invalid."""


class ManagedDocsSecurityError(ManagedDocsError):
    """Raised when source path violates configured guardrails."""


@dataclass(frozen=True)
class ManagedDocRecord:
    doc_id: str
    filename: str
    path: str
    size_bytes: int
    sha256: str
    page_count: int
    created_at: datetime
    source_mode: Literal["path", "base64"]
    source_path: str | None


@dataclass(frozen=True)
class SliceResult:
    doc_id: str
    source_mode: Literal["path", "base64"]
    orig_filename: str
    orig_path: str
    sliced_filename: str
    sliced_path: str | None
    start_page: int
    end_page: int
    total_pages: int
    sliced_page_count: int
    sliced_size_bytes: int
    sliced_sha256: str
    sliced_pdf_base64: str | None


class ManagedDocsService:
    """Capability service for MCP-managed document ingest, list, and page slicing."""

    def __init__(
        self,
        *,
        managed_docs_root: str,
        max_input_size_bytes: int = 30 * 1024 * 1024,
        max_pages_per_slice: int = 50,
        max_base64_return_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self._root = Path(managed_docs_root).expanduser().resolve()
        self._orig_dir = self._root / "orig"
        self._sliced_dir = self._root / "sliced"
        self._max_input_size_bytes = max_input_size_bytes
        self._max_pages_per_slice = max_pages_per_slice
        self._max_base64_return_bytes = max_base64_return_bytes
        self._ensure_dirs()

    def list_managed_documents(self) -> list[ManagedDocRecord]:
        records: list[ManagedDocRecord] = []
        for path in sorted(self._orig_dir.glob("*.pdf")):
            try:
                metadata = self._parse_filename_metadata(path.name)
                meta_sidecar = self._read_meta_sidecar(path)
            except ManagedDocsValidationError:
                continue
            stat_result = path.stat()
            source_path = meta_sidecar.get("source_path")
            if source_path is not None and not isinstance(source_path, str):
                source_path = None
            records.append(
                ManagedDocRecord(
                    doc_id=metadata.doc_id,
                    filename=metadata.filename,
                    path=str(path),
                    size_bytes=int(stat_result.st_size),
                    sha256=metadata.sha256,
                    page_count=self._safe_pdf_page_count(path),
                    created_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
                    source_mode=metadata.source_mode,
                    source_path=source_path,
                )
            )
        return records

    def slice_document_pages(
        self,
        *,
        mode: Literal["path", "base64"],
        start_page: int,
        end_page: int,
        source_path: str | None,
        source_pdf_base64: str | None,
        filename: str | None,
    ) -> SliceResult:
        if start_page < 1:
            raise ManagedDocsValidationError("start_page must be >= 1")
        if end_page < start_page:
            raise ManagedDocsValidationError(
                "end_page must be greater than or equal to start_page"
            )
        if (end_page - start_page + 1) > self._max_pages_per_slice:
            raise ManagedDocsValidationError(
                f"requested page span exceeds max_pages_per_slice={self._max_pages_per_slice}"
            )

        source_name = filename.strip() if isinstance(filename, str) and filename.strip() else None

        if mode == "path":
            if source_path is None or not source_path.strip():
                raise ManagedDocsValidationError("source_path is required when mode='path'")
            raw_source = Path(source_path).expanduser()
            if not raw_source.is_absolute():
                raise ManagedDocsSecurityError("source_path must be an absolute path")
            absolute_source = raw_source.resolve()
            if not absolute_source.exists():
                raise ManagedDocsValidationError("source_path does not exist")
            if absolute_source.suffix.lower() != ".pdf":
                raise ManagedDocsValidationError("source_path must point to a PDF file")
            input_size = absolute_source.stat().st_size
            if input_size > self._max_input_size_bytes:
                raise ManagedDocsValidationError(
                    f"input PDF exceeds max_input_size_bytes={self._max_input_size_bytes}"
                )
            source_bytes = absolute_source.read_bytes()
            provided_source_path = str(absolute_source)
            if source_name is None:
                source_name = absolute_source.name
        elif mode == "base64":
            if source_pdf_base64 is None or not source_pdf_base64.strip():
                raise ManagedDocsValidationError(
                    "source_pdf_base64 is required when mode='base64'"
                )
            try:
                source_bytes = base64.b64decode(source_pdf_base64, validate=True)
            except Exception as exc:
                raise ManagedDocsValidationError("source_pdf_base64 is not valid base64") from exc
            if len(source_bytes) > self._max_input_size_bytes:
                raise ManagedDocsValidationError(
                    f"input PDF exceeds max_input_size_bytes={self._max_input_size_bytes}"
                )
            provided_source_path = None
            if source_name is None:
                source_name = "uploaded.pdf"
        else:
            raise ManagedDocsValidationError("mode must be 'path' or 'base64'")

        if source_name is None:
            source_name = "document.pdf"
        safe_source_name = self._sanitize_pdf_filename(source_name)

        source_sha = self._sha256_hex(source_bytes)
        managed_doc_id = str(uuid4())
        orig_filename = self._build_orig_filename(
            doc_id=managed_doc_id,
            original_name=safe_source_name,
            sha256_hex=source_sha,
            source_mode=mode,
        )
        orig_path = self._orig_dir / orig_filename
        orig_path.write_bytes(source_bytes)
        self._write_meta_sidecar(
            orig_path,
            source_path=provided_source_path,
            source_mode=mode,
        )

        total_pages = self._pdf_page_count_from_bytes(source_bytes)
        if end_page > total_pages:
            raise ManagedDocsValidationError(
                f"requested page range {start_page}-{end_page} "
                f"is out of range for a {total_pages}-page PDF"
            )

        sliced_bytes = self._slice_bytes(source_bytes, start_page=start_page, end_page=end_page)
        sliced_sha = self._sha256_hex(sliced_bytes)
        sliced_filename = self._build_sliced_filename(
            doc_id=managed_doc_id,
            original_name=safe_source_name,
            start_page=start_page,
            end_page=end_page,
            sha256_hex=sliced_sha,
        )
        sliced_path = self._sliced_dir / sliced_filename
        sliced_path.write_bytes(sliced_bytes)

        sliced_b64: str | None = None
        if mode == "base64":
            if len(sliced_bytes) > self._max_base64_return_bytes:
                raise ManagedDocsValidationError(
                    "sliced PDF is too large for base64 mode response; choose mode='path'"
                )
            sliced_b64 = base64.b64encode(sliced_bytes).decode("ascii")

        return SliceResult(
            doc_id=managed_doc_id,
            source_mode=mode,
            orig_filename=orig_filename,
            orig_path=str(orig_path),
            sliced_filename=sliced_filename,
            sliced_path=str(sliced_path) if mode == "path" else None,
            start_page=start_page,
            end_page=end_page,
            total_pages=total_pages,
            sliced_page_count=end_page - start_page + 1,
            sliced_size_bytes=len(sliced_bytes),
            sliced_sha256=sliced_sha,
            sliced_pdf_base64=sliced_b64,
        )

    def ingest_existing_path(
        self, *, source_path: str, filename: str | None = None
    ) -> ManagedDocRecord:
        """Copy an existing absolute PDF path into managed `orig/` storage."""
        if not source_path.strip():
            raise ManagedDocsValidationError("source_path is required")
        raw_source = Path(source_path).expanduser()
        if not raw_source.is_absolute():
            raise ManagedDocsSecurityError("source_path must be an absolute path")
        source = raw_source.resolve()
        if not source.exists():
            raise ManagedDocsValidationError("source_path does not exist")
        if source.suffix.lower() != ".pdf":
            raise ManagedDocsValidationError("source_path must point to a PDF file")

        size_bytes = int(source.stat().st_size)
        if size_bytes > self._max_input_size_bytes:
            raise ManagedDocsValidationError(
                f"input PDF exceeds max_input_size_bytes={self._max_input_size_bytes}"
            )

        source_bytes = source.read_bytes()
        sha = self._sha256_hex(source_bytes)
        safe_name = self._sanitize_pdf_filename(filename or source.name)
        doc_id = str(uuid4())
        orig_filename = self._build_orig_filename(
            doc_id=doc_id,
            original_name=safe_name,
            sha256_hex=sha,
            source_mode="path",
        )
        dest = self._orig_dir / orig_filename
        shutil.copyfile(source, dest)
        self._write_meta_sidecar(dest, source_path=str(source), source_mode="path")

        return ManagedDocRecord(
            doc_id=doc_id,
            filename=orig_filename,
            path=str(dest),
            size_bytes=size_bytes,
            sha256=sha,
            page_count=self._pdf_page_count_from_bytes(source_bytes),
            created_at=datetime.now(UTC),
            source_mode="path",
            source_path=str(source),
        )

    def _slice_bytes(self, data: bytes, *, start_page: int, end_page: int) -> bytes:
        try:
            import pymupdf
        except Exception as exc:
            raise ManagedDocsError("PyMuPDF dependency is required for PDF slicing") from exc

        source_pdf = pymupdf.open(stream=data, filetype="pdf")
        try:
            sampled_pdf = pymupdf.open()
            try:
                sampled_pdf.insert_pdf(source_pdf, from_page=start_page - 1, to_page=end_page - 1)
                return sampled_pdf.tobytes(garbage=4, deflate=True)
            finally:
                sampled_pdf.close()
        finally:
            source_pdf.close()

    def _pdf_page_count_from_bytes(self, data: bytes) -> int:
        try:
            import pymupdf
        except Exception as exc:
            raise ManagedDocsError("PyMuPDF dependency is required for PDF slicing") from exc
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            return int(len(doc))
        finally:
            doc.close()

    def _safe_pdf_page_count(self, path: Path) -> int:
        try:
            return self._pdf_page_count_from_bytes(path.read_bytes())
        except Exception:
            return 0

    def _ensure_dirs(self) -> None:
        self._orig_dir.mkdir(parents=True, exist_ok=True)
        self._sliced_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha256_hex(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _sanitize_pdf_filename(name: str) -> str:
        raw = name.strip()
        fallback = "document.pdf"
        if not raw:
            return fallback
        safe = raw.replace("/", "_").replace("\\", "_")
        safe = safe.replace("\x00", "")
        stem = Path(safe).stem.strip() or "document"
        return f"{stem}.pdf"

    def _build_orig_filename(
        self,
        *,
        doc_id: str,
        original_name: str,
        sha256_hex: str,
        source_mode: Literal["path", "base64"],
    ) -> str:
        stem = Path(original_name).stem
        return f"{doc_id}__name={stem}__sha={sha256_hex}__mode={source_mode}.pdf"

    def _build_sliced_filename(
        self,
        *,
        doc_id: str,
        original_name: str,
        start_page: int,
        end_page: int,
        sha256_hex: str,
    ) -> str:
        stem = Path(original_name).stem
        return f"{doc_id}__name={stem}__p={start_page}-{end_page}__sha={sha256_hex}.pdf"

    @dataclass(frozen=True)
    class _OrigMeta:
        doc_id: str
        filename: str
        sha256: str
        source_mode: Literal["path", "base64"]

    def _parse_filename_metadata(self, file_name: str) -> _OrigMeta:
        if not file_name.endswith(".pdf"):
            raise ManagedDocsValidationError("managed filename must be PDF")
        core = file_name[:-4]
        parts = core.split("__")
        if len(parts) < 4:
            raise ManagedDocsValidationError("managed filename format is invalid")
        doc_id = parts[0]
        mapping: dict[str, str] = {}
        for token in parts[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            mapping[key] = value

        stem = mapping.get("name", "document")
        source_mode_raw = mapping.get("mode", "base64")
        if source_mode_raw not in {"path", "base64"}:
            raise ManagedDocsValidationError("managed filename source mode is invalid")
        source_mode = cast("Literal['path', 'base64']", source_mode_raw)
        return self._OrigMeta(
            doc_id=doc_id,
            filename=f"{stem}.pdf",
            sha256=mapping.get("sha", ""),
            source_mode=source_mode,
        )

    def _write_meta_sidecar(
        self,
        path: Path,
        *,
        source_path: str | None,
        source_mode: Literal["path", "base64"],
    ) -> None:
        payload = {
            "source_path": source_path,
            "source_mode": source_mode,
        }
        sidecar = path.with_suffix(path.suffix + ".meta.json")
        sidecar.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def _read_meta_sidecar(self, path: Path) -> dict[str, object]:
        sidecar = path.with_suffix(path.suffix + ".meta.json")
        if not sidecar.exists():
            return {}
        try:
            raw = sidecar.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}
