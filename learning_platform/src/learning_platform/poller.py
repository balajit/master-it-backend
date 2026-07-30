from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import async_sessionmaker

if TYPE_CHECKING:
    from learning_platform.service import LearningPlatformService

from learning_platform.security import InvalidPathError, resolve_safe_path

_LOG = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS: int = 10
BOOK_POLL_INTERVAL_SECONDS: int = 30
MAX_RETRIES: int = 3


class FilePoller:
    """Monitors ``registry.txt`` and creates ``lp_document_process`` entries.

    State machine (DB-driven)::

        registry.txt  ──→  lp_document_process (status=pending)
                                  │
                          ┌──────┴──────┐
                          ▼             ▼
                    processing       processing
                          │             │
                    ┌─────┴─────┐  failure (< max)
                    ▼           ▼       └──→ pending (retry+1)
               completed    failed (>= max)
    """

    def __init__(
        self,
        upload_path: str,
        session_factory: async_sessionmaker,
        service: object | None = None,
        poll_interval: int = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._upload_path = upload_path
        self._registry_path = Path(upload_path) / "registry.txt"
        self._session_factory = session_factory
        self._poll_interval = poll_interval
        if service is not None:
            self._service: LearningPlatformService = service  # type: ignore[assignment]
        else:
            from learning_platform.service import get_service

            self._service = get_service()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._process_lock = asyncio.Lock()
        self._processing_recovery_done = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        _LOG.info(
            "FilePoller started (interval=%ds, registry=%s)",
            self._poll_interval,
            self._registry_path,
        )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        _LOG.info("FilePoller stopping...")
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        """Main polling loop."""
        while not self._stop_event.is_set():
            try:
                await self._sync_registry_to_db()
                await self._process_pending()
            except Exception:
                _LOG.exception("Poller iteration failed")
            await asyncio.sleep(self._poll_interval)

    # ── registry.txt → lp_document_process ───────────────────────────────────

    async def _sync_registry_to_db(self) -> None:
        """Atomically swap the registry file and create ``lp_document_process`` rows
        for any paths not yet tracked in the database."""
        swap_path = self._registry_path.with_suffix(".txt.processing")

        # Atomically rename the file so concurrent writes by register_document()
        # either complete before the rename or create a fresh registry.txt.
        try:
            os.rename(self._registry_path, swap_path)
        except FileNotFoundError:
            return

        try:
            lines = await run_in_threadpool(self._read_file_lines, swap_path)

            from learning_platform.infrastructure.persistence.repositories import (
                DocumentProcessRepository,
            )

            async with self._session_factory() as session:
                repo = DocumentProcessRepository(session)
                for line in lines:
                    rel_path: str = line.strip()
                    if not rel_path:
                        continue
                    try:
                        safe_abs = resolve_safe_path(Path(self._upload_path), rel_path)
                    except InvalidPathError:
                        _LOG.warning("Skipping unsafe registry path: %s", rel_path)
                        continue
                    existing = await repo.find_by_source(rel_path)
                    if existing is not None:
                        continue
                    abs_path: str = str(safe_abs)
                    await repo.create_entry(rel_path, abs_path)
                await session.commit()
        finally:
            # Remove the swapped file regardless of outcome
            if swap_path.exists():
                os.remove(swap_path)

    @staticmethod
    def _read_file_lines(path: Path) -> list[str]:
        """Read all lines from a file using blocking I/O in threadpool context."""
        with open(path, encoding="utf-8") as f:
            return f.readlines()

    # ── Process pending entries from DB ──────────────────────────────────────

    async def _process_pending(self) -> None:
        """Pick up pending entries from ``lp_document_process`` and process
        them, updating state along the way."""
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        async with self._process_lock:
            if not self._processing_recovery_done:
                await self._recover_processing_rows_after_restart()

            async with self._session_factory() as session:
                repo = DocumentProcessRepository(session)
                pending = await repo.find_pending()

            for row in pending:
                await self._try_process(row)

    async def _recover_processing_rows_after_restart(self) -> None:
        """Requeue in-flight processing rows once at poller startup.

        This recovery is intentionally one-time. Running it repeatedly causes
        active in-progress jobs to be reset to pending and reprocessed.
        """
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        recovered_count = 0
        async with self._session_factory() as session:
            repo = DocumentProcessRepository(session)
            processing = await repo.find_processing()
            for row in processing:
                if getattr(row, "last_completed_stage", None) == "pipeline":
                    # Primary pipeline already completed; row is waiting on BookPipeline.
                    continue
                await repo.requeue_processing_after_restart(
                    row,
                    "Recovered processing row after restart",
                )
                recovered_count += 1

            if recovered_count > 0:
                await session.commit()

        self._processing_recovery_done = True
        if recovered_count > 0:
            _LOG.info("Recovered %d in-flight processing rows", recovered_count)

    async def _try_process(self, row: object) -> None:
        """Run the pipeline on a single ``DocumentProcessRow``.

        State transitions:

        * ``pending`` → ``processing`` (primary pipeline success; waits on BookPipeline)
        * ``pending`` → ``processing`` → ``pending`` + retry (failure, retries remain)
        * ``pending`` → ``processing`` → ``failed`` (failure, max retries exceeded)
        """
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        proc = row  # type: ignore[var-annotated]
        proc_id = getattr(proc, "id", None)
        if not isinstance(proc_id, int):
            return

        async with self._session_factory() as session:
            repo = DocumentProcessRepository(session)
            # Re-fetch within this session to ensure clean state
            proc = await repo.find_by_id(proc_id)
            if proc is None or proc.status != "pending":
                return

            await repo.mark_processing(proc)
            await session.commit()

        try:
            async with self._session_factory() as session:
                await self._service.process(
                    proc.abs_path,
                    session=session,
                    document_process_id=proc_id,
                    dedupe_by_source=False,
                )
        except Exception:
            _LOG.exception("Processing failed: %s", proc.abs_path)
            async with self._session_factory() as session:
                repo = DocumentProcessRepository(session)
                proc = await repo.find_by_id(proc_id)
                if proc is None:
                    return
                if proc.retry_count + 1 >= proc.max_retries:
                    await repo.mark_failed(
                        proc,
                        proc.error_message or "Max retries exceeded",
                    )
                    _LOG.warning(
                        "Document failed after %d retries: %s",
                        proc.max_retries,
                        proc.abs_path,
                    )
                else:
                    await repo.mark_retry(
                        proc,
                        proc.error_message or "Pipeline error, will retry",
                    )
                    _LOG.info(
                        "Retry %d/%d for %s",
                        proc.retry_count,
                        proc.max_retries,
                        proc.abs_path,
                    )
                await session.commit()
            return

        _LOG.info(
            "Primary pipeline completed for process_id=%s path=%s; awaiting book pipeline",
            proc_id,
            proc.abs_path,
        )


class BookProcessPoller:
    """Picks up pending ``lp_book_process`` entries and runs ``BookPipeline``.

    State machine::

        lp_book_process (status=pending)
                │
                ▼
            processing
                │
           ┌────┴────┐
           ▼         ▼
      completed  failed (< max)
                     │
                     └──→ pending (retry+1)
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        poll_interval: int = BOOK_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        _LOG.info(
            "BookProcessPoller started (interval=%ds)",
            self._poll_interval,
        )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        _LOG.info("BookProcessPoller stopping...")
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        """Main polling loop."""
        while not self._stop_event.is_set():
            try:
                await self._process_pending()
            except Exception:
                _LOG.exception("BookProcessPoller iteration failed")
            await asyncio.sleep(self._poll_interval)

    # ── Process pending entries ─────────────────────────────────────────────

    async def _process_pending(self) -> None:
        """Pick up pending book_process entries and assemble books."""
        from learning_platform.infrastructure.persistence.repositories.book_process import (
            BookProcessRepository,
        )

        async with self._session_factory() as session:
            repo = BookProcessRepository(session)
            pending = await repo.find_pending()

        for row in pending:
            await self._try_process(row)

    async def _try_process(self, row: object) -> None:
        """Run BookPipeline on a single ``BookProcessRow``."""
        from learning_platform.infrastructure.persistence.repositories.book_process import (
            BookProcessRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )
        from learning_platform.pipeline.book_pipeline import BookPipeline

        proc = row  # type: ignore[var-annotated]

        async with self._session_factory() as session:
            repo = BookProcessRepository(session)
            proc = await repo.find_by_id(proc.id)  # type: ignore[attr-defined]
            if proc is None or proc.status != "pending":
                return

            await repo.mark_processing(proc)
            await session.commit()

        try:
            async with self._session_factory() as session:
                book_pipeline = BookPipeline(session)
                await book_pipeline.run(UUID(proc.document_id))
        except Exception:
            _LOG.exception("Book assembly failed for document %s", proc.document_id)
            async with self._session_factory() as session:
                repo = BookProcessRepository(session)
                doc_proc_repo = DocumentProcessRepository(session)
                proc = await repo.find_by_id(proc.id)  # type: ignore[attr-defined]
                if proc is None:
                    return

                doc_uuid = None
                try:
                    doc_uuid = UUID(proc.document_id)
                except Exception:
                    doc_uuid = None

                doc_proc_row = None
                if doc_uuid is not None:
                    doc_proc_row = await doc_proc_repo.find_latest_by_document_id(doc_uuid)

                if proc.retry_count + 1 >= proc.max_retries:
                    await repo.mark_failed(proc, "Max retries exceeded")
                    if doc_proc_row is not None:
                        await doc_proc_repo.mark_failed(
                            doc_proc_row,
                            "BookPipeline failed: max retries exceeded",
                        )
                    _LOG.warning(
                        "Book assembly failed after %d retries for document %s",
                        proc.max_retries,
                        proc.document_id,
                    )
                else:
                    await repo.mark_retry(proc, "BookPipeline error, will retry")
                    if doc_proc_row is not None:
                        await doc_proc_repo.mark_book_pending(
                            doc_proc_row,
                            "BookPipeline error, will retry",
                        )
                    _LOG.info(
                        "Retry %d/%d for document %s",
                        proc.retry_count,
                        proc.max_retries,
                        proc.document_id,
                    )
                await session.commit()
            return

        async with self._session_factory() as session:
            repo = BookProcessRepository(session)
            doc_proc_repo = DocumentProcessRepository(session)
            proc = await repo.find_by_id(proc.id)  # type: ignore[attr-defined]
            if proc is not None:
                await repo.mark_completed(proc)

                doc_uuid = None
                try:
                    doc_uuid = UUID(proc.document_id)
                except Exception:
                    doc_uuid = None

                if doc_uuid is not None:
                    doc_proc_row = await doc_proc_repo.find_latest_by_document_id(doc_uuid)
                    if doc_proc_row is not None:
                        await doc_proc_repo.mark_completed(doc_proc_row)

                await session.commit()
                _LOG.info(
                    "Book assembly completed for document %s",
                    proc.document_id,
                )
