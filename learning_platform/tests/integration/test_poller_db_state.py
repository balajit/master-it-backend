"""Integration test: poller syncs registry.txt → lp_document_process.

Verifies:
  1. FilePoller creates ``lp_document_process`` entries from registry.txt
  2. State transitions (pending → processing → completed / failed)
  3. ``DocumentProcessRepository`` queries and updates work as expected
  4. Entries are visible in the testing database

Run against the **testing** PostgreSQL (port 5433).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from learning_platform.config import get_settings
from learning_platform.infrastructure.persistence.engine import create_engine
from learning_platform.infrastructure.persistence.models.document_process import DocumentProcessRow
from learning_platform.infrastructure.persistence.repositories.document_process import (
    DocumentProcessRepository,
)
from learning_platform.poller import FilePoller

pytestmark = pytest.mark.integration


@pytest.fixture
def temp_upload_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def registry_file(temp_upload_dir: Path) -> Path:
    reg = temp_upload_dir / "registry.txt"
    reg.write_text("7/sample.pdf\n8/test.docx\n")
    return reg


@pytest.fixture
async def session_factory():
    settings = get_settings()
    engine = create_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_db(session_factory):
    """Clear lp_document_process before each test for isolation."""
    from sqlalchemy import text

    try:
        async with session_factory() as session:
            await session.execute(text("DELETE FROM lp_document_process"))
            await session.commit()
    except Exception:
        pass  # Silently skip if table doesn't exist (e.g. SQLite test DB)


@pytest.mark.asyncio
async def test_sync_registry_to_db_creates_entries(
    temp_upload_dir: Path,
    registry_file: Path,
    session_factory,
) -> None:
    poller = FilePoller(upload_path=str(temp_upload_dir), session_factory=session_factory)

    await poller._sync_registry_to_db()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        entries = await repo.find_pending()
        sources = {e.source for e in entries}
        assert "7/sample.pdf" in sources
        assert "8/test.docx" in sources
        assert len(entries) == 2

        for entry in entries:
            assert entry.status == "pending"
            assert entry.retry_count == 0
            assert entry.max_retries == 3


@pytest.mark.asyncio
async def test_sync_is_idempotent(
    temp_upload_dir: Path,
    registry_file: Path,
    session_factory,
) -> None:
    poller = FilePoller(upload_path=str(temp_upload_dir), session_factory=session_factory)

    await poller._sync_registry_to_db()
    await poller._sync_registry_to_db()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        entries = await repo.find_pending()
        assert len(entries) == 2


@pytest.mark.asyncio
async def test_state_transitions(
    temp_upload_dir: Path,
    registry_file: Path,
    session_factory,
) -> None:
    poller = FilePoller(upload_path=str(temp_upload_dir), session_factory=session_factory)

    await poller._sync_registry_to_db()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        entries = await repo.find_pending()
        proc = entries[0]

        assert proc.status == "pending"

        await repo.mark_processing(proc)
        assert proc.status == "processing"

        await repo.mark_completed(proc)
        assert proc.status == "completed"
        await session.commit()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        completed = await repo.find_by_id(proc.id)
        assert completed is not None
        assert completed.status == "completed"


@pytest.mark.asyncio
async def test_retry_and_failure(
    temp_upload_dir: Path,
    session_factory,
) -> None:
    reg = temp_upload_dir / "registry.txt"
    reg.write_text("9/fail.pdf\n")

    poller = FilePoller(upload_path=str(temp_upload_dir), session_factory=session_factory)
    await poller._sync_registry_to_db()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        entries = await repo.find_pending()
        proc = entries[0]

        await repo.mark_processing(proc)

        await repo.mark_retry(proc, "temporary error")
        assert proc.status == "pending"
        assert proc.retry_count == 1
        await session.commit()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        proc = await repo.find_by_id(proc.id)
        assert proc is not None
        assert proc.retry_count == 1
        assert proc.status == "pending"

        await repo.mark_processing(proc)

        await repo.mark_failed(proc, "permanent failure")
        assert proc.status == "failed"
        assert proc.error_message == "permanent failure"
        await session.commit()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        proc = await repo.find_by_id(proc.id)
        assert proc is not None
        assert proc.status == "failed"
        assert proc.error_message == "permanent failure"


@pytest.mark.asyncio
async def test_registry_entries_visible_in_db(
    temp_upload_dir: Path,
    registry_file: Path,
    session_factory,
) -> None:
    """Verify that the test database actually holds the synced entries
    by querying directly via raw SQL."""
    poller = FilePoller(upload_path=str(temp_upload_dir), session_factory=session_factory)
    await poller._sync_registry_to_db()

    async with session_factory() as session:
        from sqlalchemy import text

        result = await session.execute(
            text("SELECT source, status FROM lp_document_process ORDER BY id")
        )
        rows = result.all()
        assert len(rows) == 2
        assert rows[0].source == "7/sample.pdf"
        assert rows[0].status == "pending"
        assert rows[1].source == "8/test.docx"
        assert rows[1].status == "pending"
