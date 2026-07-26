"""Marker adapter — wraps VikParuchuri/marker and converts output to CanonicalDocument.

This adapter does NOT implement parsing internals. It delegates to Marker's
``convert_pdf`` (or ``convert_single``) and maps the result into the canonical
tree of ``DocumentNode`` instances.

Marker specializes in fast PDF-to-markdown conversion with good layout
preservation.
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

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})


class MarkerAdapter:
    """Adapter wrapping VikParuchuri/marker for use as an ``AbstractParser``.

    Parameters
    ----------
    marker_config : dict | None
        Configuration forwarded to the Marker conversion function.
    """

    def __init__(self, marker_config: dict | None = None) -> None:
        self._config = marker_config or {}

    # ── AbstractParser Protocol ───────────────────────────────────────────

    def parse(self, source: str) -> CanonicalDocument:
        """Convert *source* into a ``CanonicalDocument`` via Marker.

        .. warning::
            Marker internals are NOT implemented. This stub returns a
            placeholder document. Replace the body with actual Marker
            integration when the dependency is available.
        """
        _LOG.warning("MarkerAdapter.parse is a stub — returning placeholder for %s", source)
        root = DocumentNode(
            content=Paragraph(text=StyledText(runs=[TextRun(text=f"[Marker stub] {source}")])),
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
        """Return ``True`` if *source* is a PDF file."""
        return Path(source).suffix.lower() in _SUPPORTED_EXTENSIONS

    def confidence(self, source: str) -> float:
        """Return a confidence score for Marker parsing.

        Marker is purpose-built for PDF conversion and has high confidence
        for that format. It does not support other formats.
        """
        ext = Path(source).suffix.lower()
        if ext == ".pdf":
            return 0.90
        return 0.0

    # ── Internal helpers ──────────────────────────────────────────────────

    def _run_marker(self, source: str) -> str:
        """Run Marker's conversion and return raw markdown output.

        When Marker is installed this method imports and calls
        ``marker.convert_single`` (or ``marker.convert_pdf``). The lazy
        import avoids hard-dependency at module load time.

        Returns
        -------
        str
            Markdown text produced by Marker.

        Raises
        ------
        NotImplementedError
            If the ``marker`` package is not installed.
        """
        _LOG.info("Running Marker conversion for %s with config: %s", source, self._config)
        # TODO: import and call the real Marker conversion here.
        # Example (when marker is installed):
        #   from marker.convert import convert_pdf
        #   rendered = convert_pdf(source, **self._config)
        #   return rendered.markdown
        raise NotImplementedError(
            "Marker conversion is not yet implemented. "
            "Install marker-py and implement _run_marker()."
        )
