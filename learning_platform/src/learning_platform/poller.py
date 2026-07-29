from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import async_sessionmaker

if TYPE_CHECKING:
    from learning_platform.service import LearningPlatformService

from learning_platform.security import InvalidPathError, resolve_safe_path

_LOG = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS: int = 10
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
        """Read ``registry.txt`` and create ``lp_document_process`` rows for
        any paths not yet tracked in the database."""
        registry_exists = await run_in_threadpool(self._registry_path.exists)
        if not registry_exists:
            return

        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        async with self._session_factory() as session:
            repo = DocumentProcessRepository(session)
            lines = await run_in_threadpool(self._read_registry_lines)
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

    def _read_registry_lines(self) -> list[str]:
        """Read registry file lines using blocking I/O in threadpool context."""
        with open(self._registry_path, encoding="utf-8") as registry_file:
            return registry_file.readlines()

    # ── Process pending entries from DB ──────────────────────────────────────

    async def _process_pending(self) -> None:
        """Pick up pending entries from ``lp_document_process`` and process
        them, updating state along the way."""
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        async with self._session_factory() as session:
            repo = DocumentProcessRepository(session)
            pending = await repo.find_pending()

        for row in pending:
            await self._try_process(row)

    async def _try_process(self, row: object) -> None:
        """Run the pipeline on a single ``DocumentProcessRow``.

        State transitions:

        * ``pending`` → ``processing`` → ``completed`` (success)
        * ``pending`` → ``processing`` → ``pending`` + retry (failure, retries remain)
        * ``pending`` → ``processing`` → ``failed`` (failure, max retries exceeded)
        """
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        proc = row  # type: ignore[var-annotated]

        async with self._session_factory() as session:
            repo = DocumentProcessRepository(session)
            # Re-fetch within this session to ensure clean state
            proc = await repo.find_by_id(proc.id)
            if proc is None or proc.status != "pending":
                return

            await repo.mark_processing(proc)
            await session.commit()

        try:
            async with self._session_factory() as session:
                await self._service.process(
                    proc.abs_path,
                    session=session,
                    document_process_id=proc.id,
                )
        except Exception:
            _LOG.exception("Processing failed: %s", proc.abs_path)
            async with self._session_factory() as session:
                repo = DocumentProcessRepository(session)
                proc = await repo.find_by_id(proc.id)
                if proc is None:
                    return
                if proc.retry_count + 1 >= proc.max_retries:
                    await repo.mark_failed(proc, "Max retries exceeded")
                    _LOG.warning(
                        "Document failed after %d retries: %s",
                        proc.max_retries,
                        proc.abs_path,
                    )
                else:
                    await repo.mark_retry(proc, "Pipeline error, will retry")
                    _LOG.info(
                        "Retry %d/%d for %s",
                        proc.retry_count,
                        proc.max_retries,
                        proc.abs_path,
                    )
                await session.commit()
            return

        async with self._session_factory() as session:
            repo = DocumentProcessRepository(session)
            proc = await repo.find_by_id(proc.id)
            if proc is not None:
                await repo.mark_completed(proc)
                await session.commit()
                _LOG.info("Processing completed: %s", proc.abs_path)
