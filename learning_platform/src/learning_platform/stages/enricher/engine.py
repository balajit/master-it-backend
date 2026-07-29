"""Enrichment Engine — runs detectors and merges their annotations.

The engine is the single entry point for semantic enrichment.  It holds
a list of ``Detector`` instances, executes each one, and merges the
resulting annotations into a unified list.

Design Principles
-----------------
- **No document mutation**: The engine returns annotations; it does not
  modify the ``CanonicalDocument``.  A separate adapter can apply
  annotations to the document if needed.
- **Detector independence**: Each detector runs in isolation.  The engine
  does not pass results between detectors.
- **Deduplication**: Annotations that reference the same node and carry
  the same ``type`` are merged by keeping the highest-confidence variant.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from learning_platform.models.annotation import Annotation
from learning_platform.models.document import CanonicalDocument

if TYPE_CHECKING:
    from learning_platform.config import Settings

_LOG = logging.getLogger(__name__)


@runtime_checkable
class _DetectorProtocol(Protocol):
    """Typed detector contract used by ``EnrichmentEngine``."""

    def detect(self, document: CanonicalDocument) -> list[Annotation]: ...


def _annotation_key(annotation: Annotation) -> tuple[str, str]:
    """Return a deduplication key: ``(type, node_id)``."""
    return (annotation.type, str(annotation.node_id))


class EnrichmentEngine:
    """Orchestrates detectors and merges their annotations.

    Parameters
    ----------
    detectors : Sequence[_DetectorProtocol] | None
        Detectors to execute.  When ``None`` the engine starts empty
        and detectors must be added via ``add_detector()``.
    fail_fast : bool
        When ``True``, detector exceptions raise immediately. When
        ``False``, failures are logged and processing continues.
    """

    def __init__(
        self,
        detectors: Sequence[_DetectorProtocol] | None = None,
        *,
        fail_fast: bool = False,
    ) -> None:
        self._detectors: list[_DetectorProtocol] = list(detectors) if detectors is not None else []
        self._fail_fast = fail_fast

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        detectors: Sequence[_DetectorProtocol] | None = None,
    ) -> EnrichmentEngine:
        """Build an engine with environment-aware failure policy.

        Policy A:
        - debug=False => fail-fast
        - debug=True  => best-effort
        """
        return cls(detectors=detectors, fail_fast=not settings.debug)

    @property
    def detectors(self) -> list[_DetectorProtocol]:
        """Return a copy of the current detector list."""
        return list(self._detectors)

    def add_detector(self, detector: _DetectorProtocol) -> None:
        """Register a detector for future ``enrich()`` calls."""
        self._detectors.append(detector)

    @property
    def fail_fast(self) -> bool:
        """Return whether detector errors fail the stage."""
        return self._fail_fast

    def enrich(self, document: CanonicalDocument) -> list[Annotation]:
        """Run all detectors and return merged, deduplicated annotations.

        Detectors are executed in registration order.  When two detectors
        produce annotations for the same ``(type, node_id)`` pair, the
        one with higher ``confidence`` wins.  Ties are broken by
        first-seen order.
        """
        _LOG.info(
            "Enriching document '%s' with %d detectors",
            document.title,
            len(self._detectors),
        )

        all_annotations: list[Annotation] = []
        for detector in self._detectors:
            detector_name = type(detector).__name__
            _LOG.debug("Running detector: %s", detector_name)
            try:
                found = detector.detect(document)
                _LOG.debug("  → %d annotations from %s", len(found), detector_name)
                all_annotations.extend(found)
            except Exception as exc:
                if self._fail_fast:
                    raise RuntimeError(f"Detector {detector_name} failed") from exc
                _LOG.exception("Detector %s failed", detector_name)

        merged = self._deduplicate(all_annotations)
        _LOG.info(
            "Enrichment complete: %d raw → %d merged annotations",
            len(all_annotations),
            len(merged),
        )
        return merged

    @staticmethod
    def _deduplicate(annotations: list[Annotation]) -> list[Annotation]:
        """Keep the highest-confidence annotation for each ``(type, node_id)``."""
        best: dict[tuple[str, str], Annotation] = {}
        for ann in annotations:
            key = _annotation_key(ann)
            existing = best.get(key)
            if existing is None or ann.confidence > existing.confidence:
                best[key] = ann
        return list(best.values())
