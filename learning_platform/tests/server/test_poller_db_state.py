"""Server integration test: poller syncs registry.txt → lp_document_process.

Verifies:
  1. FilePoller creates ``lp_document_process`` entries from registry.txt
  2. State transitions (pending → processing → completed / failed)
  3. ``DocumentProcessRepository`` queries and updates work as expected
  4. Entries are visible in the testing database

Requires a live PostgreSQL instance on port 5433 (testing DB).
Run with: uv run pytest learning_platform/tests/server/ -m server
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from learning_platform.config import get_settings
from learning_platform.infrastructure.persistence.engine import create_engine
from learning_platform.infrastructure.persistence.models import Base
from learning_platform.infrastructure.persistence.models.document import CanonicalDocumentRow
from learning_platform.infrastructure.persistence.repositories.book_process import (
    BookProcessRepository,
)
from learning_platform.infrastructure.persistence.repositories.document_process import (
    DocumentProcessRepository,
)
from learning_platform.poller import BookProcessPoller, FilePoller

pytestmark = pytest.mark.server


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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

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


@pytest.mark.asyncio
async def test_mark_processing_handles_detached_row(session_factory) -> None:
    """Regression: mark_processing should work with detached ORM rows.

    Poller state transitions can cross session boundaries.  This test ensures
    repository methods re-attach rows before mutation.
    """
    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        row = await repo.create_entry("11/detached.pdf", "/tmp/11/detached.pdf")
        await session.commit()

    # `row` is now detached (previous session closed).
    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        await repo.mark_processing(row)
        await session.commit()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        loaded = await repo.find_by_source("11/detached.pdf")
        assert loaded is not None
        assert loaded.status == "processing"


@pytest.mark.asyncio
async def test_sync_registry_skips_unsafe_paths(
    temp_upload_dir: Path,
    session_factory,
) -> None:
    reg = temp_upload_dir / "registry.txt"
    reg.write_text("../escape.pdf\n/sneaky.pdf\n10/ok.pdf\n")

    poller = FilePoller(upload_path=str(temp_upload_dir), session_factory=session_factory)
    await poller._sync_registry_to_db()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        entries = await repo.find_pending()
        sources = {e.source for e in entries}
        assert "10/ok.pdf" in sources
        assert "../escape.pdf" not in sources
        assert "/sneaky.pdf" not in sources


@pytest.mark.asyncio
async def test_process_pending_uses_service_process(
    temp_upload_dir: Path,
    session_factory,
) -> None:
    rel_path = "12/service-path.pdf"
    abs_path = temp_upload_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"fake")

    mock_process = AsyncMock(return_value=SimpleNamespace())
    mock_service = SimpleNamespace(process=mock_process)
    poller = FilePoller(
        upload_path=str(temp_upload_dir),
        session_factory=session_factory,
        service=mock_service,
    )

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        row = await repo.create_entry(rel_path, str(abs_path))
        row_id = row.id
        await session.commit()

    await poller._process_pending()

    mock_process.assert_awaited_once()
    await_args = mock_process.await_args
    assert await_args is not None
    assert await_args.args[0] == str(abs_path)
    assert "session" in await_args.kwargs
    assert await_args.kwargs["document_process_id"] == row_id
    assert await_args.kwargs["dedupe_by_source"] is False

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        completed = await repo.find_by_id(row_id)
        assert completed is not None
        assert completed.status == "processing"


@pytest.mark.asyncio
async def test_process_pending_requeues_stuck_processing_rows(
    temp_upload_dir: Path,
    session_factory,
) -> None:
    rel_path = "13/stuck.pdf"
    abs_path = temp_upload_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"fake")

    mock_service = SimpleNamespace(process=AsyncMock(return_value=SimpleNamespace()))
    poller = FilePoller(
        upload_path=str(temp_upload_dir),
        session_factory=session_factory,
        service=mock_service,
    )

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        row = await repo.create_entry(rel_path, str(abs_path))
        await repo.mark_processing(row)
        row_id = row.id
        await session.commit()

    await poller._process_pending()

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        completed = await repo.find_by_id(row_id)
        assert completed is not None
        assert completed.status == "processing"
        assert completed.run_mode == "retry"


@pytest.mark.asyncio
async def test_process_pending_does_not_reprocess_after_initial_run(
    temp_upload_dir: Path,
    session_factory,
) -> None:
    rel_path = "15/no-rerun.pdf"
    abs_path = temp_upload_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"fake")

    mock_service = SimpleNamespace(process=AsyncMock(return_value=SimpleNamespace()))
    poller = FilePoller(
        upload_path=str(temp_upload_dir),
        session_factory=session_factory,
        service=mock_service,
    )

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        row = await repo.create_entry(rel_path, str(abs_path))
        row_id = row.id
        await session.commit()

    await poller._process_pending()
    await poller._process_pending()

    assert mock_service.process.await_count == 1

    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        row = await repo.find_by_id(row_id)
        assert row is not None
        assert row.status == "processing"


@pytest.mark.asyncio
async def test_book_process_completion_marks_document_process_completed(
    temp_upload_dir: Path,
    session_factory,
) -> None:
    rel_path = "14/book-finalize.pdf"
    abs_path = str(temp_upload_dir / rel_path)
    doc_id = uuid4()

    async with session_factory() as session:
        session.add(
            CanonicalDocumentRow(
                id=doc_id,
                source=abs_path,
                title="Book Finalize",
                metadata_json={},
                nodes_json={},
            )
        )

        doc_repo = DocumentProcessRepository(session)
        doc_proc = await doc_repo.create_entry(rel_path, abs_path)
        await doc_repo.mark_processing(doc_proc)

        book_repo = BookProcessRepository(session)
        await book_repo.create_entry(str(doc_id))
        await session.commit()

        doc_process_id = doc_proc.id

    poller = BookProcessPoller(session_factory=session_factory)
    with patch(
        "learning_platform.pipeline.book_pipeline.BookPipeline.run",
        new=AsyncMock(return_value=SimpleNamespace()),
    ):
        await poller._process_pending()

    async with session_factory() as session:
        doc_repo = DocumentProcessRepository(session)
        doc_proc = await doc_repo.find_by_id(doc_process_id)
        assert doc_proc is not None
        assert doc_proc.status == "completed"

        book_repo = BookProcessRepository(session)
        book_proc = await book_repo.find_by_document_id(str(doc_id))
        assert book_proc is not None
        assert book_proc.status == "completed"
