"""Tests for PendingPDFStore."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


from services.pending_pdfs import PendingPDF, PendingPDFStore


def _make_pdf(temp_dir: Path, temp_id: str, expired: bool = False) -> PendingPDF:
    """Create a PendingPDF with a real temp file."""
    path = temp_dir / f"{temp_id}.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(minutes=1) if expired else now + timedelta(minutes=30)
    return PendingPDF(
        temp_id=temp_id,
        path=path,
        filename=f"{temp_id}.pdf",
        url="https://example.com",
        size_bytes=path.stat().st_size,
        expires_at=expires_at,
    )


class TestPendingPDFStore:
    def test_put_and_get(self) -> None:
        store = PendingPDFStore()
        with tempfile.TemporaryDirectory() as tmp:
            pdf = _make_pdf(Path(tmp), "abc123")
            store.put(pdf)
            result = store.get("abc123")
            assert result is not None
            assert result.temp_id == "abc123"
            assert result.filename == "abc123.pdf"

    def test_get_missing_returns_none(self) -> None:
        store = PendingPDFStore()
        assert store.get("nonexistent") is None

    def test_pop_removes_entry(self) -> None:
        store = PendingPDFStore()
        with tempfile.TemporaryDirectory() as tmp:
            pdf = _make_pdf(Path(tmp), "pop_me")
            store.put(pdf)
            popped = store.pop("pop_me")
            assert popped is not None
            assert store.get("pop_me") is None

    def test_pop_missing_returns_none(self) -> None:
        store = PendingPDFStore()
        assert store.pop("does_not_exist") is None

    def test_len(self) -> None:
        store = PendingPDFStore()
        with tempfile.TemporaryDirectory() as tmp:
            store.put(_make_pdf(Path(tmp), "a"))
            store.put(_make_pdf(Path(tmp), "b"))
            assert len(store) == 2

    def test_evict_expired_removes_entry_and_file(self) -> None:
        store = PendingPDFStore()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            expired = _make_pdf(tmp_path, "expired", expired=True)
            fresh = _make_pdf(tmp_path, "fresh", expired=False)
            store.put(expired)
            store.put(fresh)

            count = store.evict_expired_with_cleanup()

            assert count == 1
            assert store.get("expired") is None
            assert not expired.path.exists()  # file deleted
            assert store.get("fresh") is not None  # untouched
            assert fresh.path.exists()  # file preserved

    def test_evict_non_expired_keeps_entry(self) -> None:
        store = PendingPDFStore()
        with tempfile.TemporaryDirectory() as tmp:
            fresh = _make_pdf(Path(tmp), "keep_me", expired=False)
            store.put(fresh)
            count = store.evict_expired_with_cleanup()
            assert count == 0
            assert store.get("keep_me") is not None

    def test_evict_handles_missing_file_gracefully(self) -> None:
        """evict_expired_with_cleanup should not raise if the file is already gone."""
        store = PendingPDFStore()
        with tempfile.TemporaryDirectory() as tmp:
            expired = _make_pdf(Path(tmp), "gone", expired=True)
            expired.path.unlink()  # delete before eviction
            store.put(expired)
            # Should complete without raising
            count = store.evict_expired_with_cleanup()
            assert count == 1
