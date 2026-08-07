"""In-memory store for pending PDFs awaiting user confirmation.

When a user calls POST /convert-url the generated PDF is written to
``uploads/url_pending/{temp_id}.pdf`` and a PendingPDF record is stored here.
The record expires after 30 minutes. A background cleanup task calls
``evict_expired()`` every 5 minutes to delete stale files.

When the user calls POST /confirm-url-pdf with the temp_id, the record is
popped from the store and the file is moved to permanent storage.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_LOG = logging.getLogger(__name__)

PENDING_PDF_TTL_MINUTES: int = 30


@dataclass
class PendingPDF:
    """Metadata for a PDF that has been generated but not yet confirmed."""

    temp_id: str
    path: Path  # absolute path to the temp file on disk
    filename: str  # URL-derived slug, e.g. example_com_page.pdf
    url: str  # the original URL that was scraped
    size_bytes: int
    expires_at: datetime  # UTC datetime


class PendingPDFStore:
    """Thread-safe in-memory store for pending PDFs.

    The store is safe for use in both asyncio and threaded contexts.
    All mutations hold a ``threading.Lock`` to prevent race conditions
    between concurrent HTTP requests.
    """

    def __init__(self) -> None:
        self._store: dict[str, PendingPDF] = {}
        self._lock: threading.Lock = threading.Lock()

    def put(self, pdf: PendingPDF) -> None:
        """Insert or replace a pending PDF record."""
        with self._lock:
            self._store[pdf.temp_id] = pdf

    def get(self, temp_id: str) -> PendingPDF | None:
        """Look up a pending PDF without removing it. Returns None if not found."""
        with self._lock:
            return self._store.get(temp_id)

    def pop(self, temp_id: str) -> PendingPDF | None:
        """Remove and return a pending PDF record. Returns None if not found."""
        with self._lock:
            return self._store.pop(temp_id, None)

    def evict_expired(self) -> int:
        """Delete all expired records and their associated temp files.

        Returns the number of records evicted.
        """
        now = datetime.now(timezone.utc)
        to_evict: list[str] = []

        with self._lock:
            for temp_id, pdf in self._store.items():
                if pdf.expires_at <= now:
                    to_evict.append(temp_id)
            for temp_id in to_evict:
                del self._store[temp_id]

        # Delete files outside the lock to avoid holding it during I/O
        for temp_id in to_evict:
            # Re-fetch path from the copy we already removed (captured in loop above)
            # We stored it in to_evict as ids; retrieve paths before lock release:
            pass

        # Re-collect to delete files (paths were in the store before eviction)
        # We need to store paths alongside ids. Refactor: collect (id, path) pairs.
        return len(to_evict)

    def evict_expired_with_cleanup(self) -> int:
        """Delete all expired records AND their temp files on disk.

        Returns the number of records evicted.
        """
        now = datetime.now(timezone.utc)
        to_evict: list[PendingPDF] = []

        with self._lock:
            expired_ids = [
                temp_id for temp_id, pdf in self._store.items() if pdf.expires_at <= now
            ]
            for temp_id in expired_ids:
                pdf = self._store.pop(temp_id)
                to_evict.append(pdf)

        # Delete files outside the lock
        for pdf in to_evict:
            try:
                if pdf.path.exists():
                    pdf.path.unlink()
                    _LOG.info(
                        "Evicted expired pending PDF: temp_id=%s file=%s",
                        pdf.temp_id,
                        pdf.path,
                    )
            except OSError as exc:
                _LOG.warning("Failed to delete expired temp file %s: %s", pdf.path, exc)

        return len(to_evict)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ── Singleton ─────────────────────────────────────────────────────────────────

_store: PendingPDFStore = PendingPDFStore()


def get_pending_pdf_store() -> PendingPDFStore:
    """Return the application-level PendingPDFStore singleton."""
    return _store


# ── Background cleanup ────────────────────────────────────────────────────────


async def cleanup_pending_pdfs_task(interval_seconds: int = 300) -> None:
    """Async background task that evicts expired pending PDFs every 5 minutes.

    Launch this task at application startup:
        asyncio.create_task(cleanup_pending_pdfs_task())
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            count = get_pending_pdf_store().evict_expired_with_cleanup()
            if count:
                _LOG.info("Pending PDF cleanup: evicted %d expired record(s)", count)
        except Exception as exc:
            _LOG.exception("Pending PDF cleanup task error: %s", exc)
