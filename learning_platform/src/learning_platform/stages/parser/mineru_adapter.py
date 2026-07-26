"""MinerU adapter — wraps OpenDataLab MinerU and converts output to CanonicalDocument.

This adapter does NOT implement parsing internals. It delegates to MinerU's
``MagicData`` pipeline and maps the result into the canonical tree of
``DocumentNode`` instances.

MinerU specializes in academic paper extraction with strong support for
mathematical formulae, tables, and multi-column layouts.
"""

from __future__ import annotations

import logging
from pathlib import Path

from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
    DocumentNode,
    Paragraph,
    SourceLocation,
    StyledText,
    TextRun,
)

_LOG = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".docx", ".html", ".htm", ".md", ".txt"}
)


class MinerUAdapter:
    """Adapter wrapping OpenDataLab MinerU for use as an ``AbstractParser``.

    Parameters
    ----------
    pipeline_kwargs : dict | None
        Keyword arguments forwarded to the MinerU pipeline constructor.
    """

    def __init__(self, pipeline_kwargs: dict | None = None) -> None:
        self._pipeline_kwargs = pipeline_kwargs or {}
        self._pipeline: object | None = None

    # ── AbstractParser Protocol ───────────────────────────────────────────

    def parse(self, source: str) -> CanonicalDocument:
        """Convert *source* into a ``CanonicalDocument`` via MinerU.

        .. warning::
            MinerU internals are NOT implemented. This stub returns a
            placeholder document. Replace the body with actual MinerU
            integration when the dependency is available.
        """
        _LOG.warning("MinerUAdapter.parse is a stub — returning placeholder for %s", source)
        root = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text=f"[MinerU stub] {source}")])),
            source=SourceLocation(file=source),
        )

        return CanonicalDocument(
            source=str(source),
            title=Path(source).stem,
            metadata=DocumentMetadata(
                file_type=Path(source).suffix.lstrip("."),
            ),
            nodes=[root],
        )

    def supports(self, source: str) -> bool:
        """Return ``True`` if *source* has a MinerU-supported extension."""
        return Path(source).suffix.lower() in _SUPPORTED_EXTENSIONS

    def confidence(self, source: str) -> float:
        """Return a confidence score for MinerU parsing.

        MinerU excels at academic PDFs with formulae and tables. It has
        moderate confidence for other PDF layouts and low confidence for
        non-PDF formats.
        """
        ext = Path(source).suffix.lower()
        if ext == ".pdf":
            return 0.80
        if ext in {".docx", ".html", ".htm"}:
            return 0.40
        if ext in {".md", ".txt"}:
            return 0.20
        return 0.0

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_pipeline(self) -> object:
        """Return the MinerU pipeline, creating one if needed.

        When MinerU is installed this method imports and initialises
        ``magic_pdf.data.data_reader_writer.PipeRunner`` (or equivalent).
        The lazy import avoids hard-dependency at module load time.
        """
        if self._pipeline is not None:
            return self._pipeline

        _LOG.info("Initialising MinerU pipeline with kwargs: %s", self._pipeline_kwargs)
        # TODO: import and instantiate the real MinerU pipeline here.
        # Example (when mineru is installed):
        #   from magic_pdf.data.data_reader_writer import PipeRunner
        #   self._pipeline = PipeRunner(**self._pipeline_kwargs)
        raise NotImplementedError(
            "MinerU pipeline integration is not yet implemented. "
            "Install magic-pdf and implement _get_pipeline()."
        )
