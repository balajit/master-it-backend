from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from learning_platform.agentic_ops.actions.service import (
    AgenticActionError,
    AgenticActionService,
)
from learning_platform.agentic_ops.contracts.mcp import (
    CancelAgentActionRequest,
    ExecuteDeleteDocumentProcessRunsRequest,
    PrepareDeleteDocumentProcessRunsRequest,
    RollBackAgentActionRequest,
)
from learning_platform.infrastructure.persistence.models.base import Base
from learning_platform.infrastructure.persistence.models.pipeline_log import PipelineLogRow
from learning_platform.infrastructure.persistence.repositories.document_process import (
    DocumentProcessRepository,
)


async def _build_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_process_rows(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with session_factory() as session:
        repo = DocumentProcessRepository(session)
        row_1 = await repo.create_entry("source-1.pdf", "/tmp/source-1.pdf")
        row_2 = await repo.create_entry("source-2.pdf", "/tmp/source-2.pdf")
        await session.execute(
            PipelineLogRow.__table__.insert(),
            [
                {
                    "source": row_1.source,
                    "stage": "parser",
                    "output": "ok",
                    "result": "success",
                    "document_process_id": row_1.id,
                },
                {
                    "source": row_2.source,
                    "stage": "parser",
                    "output": "ok",
                    "result": "success",
                    "document_process_id": row_2.id,
                },
            ],
        )
        await session.commit()
        return row_1.id, row_2.id


async def test_prepare_execute_and_rollback_delete_document_process_runs() -> None:
    session_factory = await _build_session_factory()
    try:
        row_1_id, row_2_id = await _seed_process_rows(session_factory)
        service = AgenticActionService(session_factory=session_factory, action_ttl_minutes=30)

        prepare = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id, row_2_id],
                reason="cleanup bad pipeline rows",
                requested_by="qa-user",
            )
        )

        assert prepare.status == "prepared"
        assert prepare.precheck_passed is True
        assert prepare.target_process_ids == [row_1_id, row_2_id]

        execute = await service.execute_delete_document_process_runs(
            request=ExecuteDeleteDocumentProcessRunsRequest(
                action_id=prepare.action_id,
                requested_by="qa-user",
            )
        )

        assert execute.status == "applied"
        assert execute.deleted_process_ids == [row_1_id, row_2_id]
        assert execute.deleted_pipeline_log_count == 2

        async with session_factory() as session:
            repo = DocumentProcessRepository(session)
            assert await repo.find_by_id(row_1_id) is None
            assert await repo.find_by_id(row_2_id) is None

        rollback = await service.rollback_agent_action(
            request=RollBackAgentActionRequest(
                action_id=prepare.action_id,
                requested_by="qa-user",
                reason="undo test delete",
            )
        )

        assert rollback.status == "rolled_back"
        assert rollback.restored_row_count == 4

        async with session_factory() as session:
            repo = DocumentProcessRepository(session)
            assert await repo.find_by_id(row_1_id) is not None
            assert await repo.find_by_id(row_2_id) is not None
    finally:
        await session_factory.kw["bind"].dispose()


async def test_execute_requires_prepared_state() -> None:
    session_factory = await _build_session_factory()
    try:
        row_1_id, _ = await _seed_process_rows(session_factory)
        service = AgenticActionService(session_factory=session_factory, action_ttl_minutes=30)

        prepare = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id],
                reason="cleanup",
                requested_by="qa-user",
            )
        )

        _ = await service.execute_delete_document_process_runs(
            request=ExecuteDeleteDocumentProcessRunsRequest(
                action_id=prepare.action_id,
                requested_by="qa-user",
            )
        )

        second = await service.execute_delete_document_process_runs(
            request=ExecuteDeleteDocumentProcessRunsRequest(
                action_id=prepare.action_id,
                requested_by="qa-user",
            )
        )
        assert second.status == "already_applied"
    finally:
        await session_factory.kw["bind"].dispose()


async def test_prepare_is_idempotent_for_same_target_items() -> None:
    session_factory = await _build_session_factory()
    try:
        row_1_id, _ = await _seed_process_rows(session_factory)
        service = AgenticActionService(session_factory=session_factory, action_ttl_minutes=30)

        first = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id],
                reason="cleanup",
                requested_by="qa-user",
            )
        )
        second = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id],
                reason="cleanup",
                requested_by="another-user",
            )
        )

        assert first.action_id == second.action_id
        assert second.status == "already_prepared"
    finally:
        await session_factory.kw["bind"].dispose()


async def test_execute_allows_any_authorized_user() -> None:
    session_factory = await _build_session_factory()
    try:
        row_1_id, _ = await _seed_process_rows(session_factory)
        service = AgenticActionService(session_factory=session_factory, action_ttl_minutes=30)

        prepare = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id],
                reason="cleanup",
                requested_by="qa-user",
            )
        )

        result = await service.execute_delete_document_process_runs(
            request=ExecuteDeleteDocumentProcessRunsRequest(
                action_id=prepare.action_id,
                requested_by="different-user",
            )
        )
        assert result.status == "applied"
    finally:
        await session_factory.kw["bind"].dispose()


async def test_cancel_then_prepare_again_creates_new_action() -> None:
    session_factory = await _build_session_factory()
    try:
        row_1_id, _ = await _seed_process_rows(session_factory)
        service = AgenticActionService(session_factory=session_factory, action_ttl_minutes=30)

        first_prepare = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id],
                reason="cleanup",
                requested_by="qa-user",
            )
        )
        cancel = await service.cancel_agent_action(
            request=CancelAgentActionRequest(
                action_id=first_prepare.action_id,
                requested_by="reviewer-user",
                reason="do not proceed",
            )
        )
        second_prepare = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id],
                reason="cleanup-again",
                requested_by="qa-user",
            )
        )

        assert cancel.status == "canceled"
        assert second_prepare.status == "prepared"
        assert second_prepare.action_id != first_prepare.action_id
    finally:
        await session_factory.kw["bind"].dispose()


async def test_execute_rejects_canceled_action() -> None:
    session_factory = await _build_session_factory()
    try:
        row_1_id, _ = await _seed_process_rows(session_factory)
        service = AgenticActionService(session_factory=session_factory, action_ttl_minutes=30)

        prepare = await service.prepare_delete_document_process_runs(
            request=PrepareDeleteDocumentProcessRunsRequest(
                process_ids=[row_1_id],
                reason="cleanup",
                requested_by="qa-user",
            )
        )
        _ = await service.cancel_agent_action(
            request=CancelAgentActionRequest(
                action_id=prepare.action_id,
                requested_by="reviewer-user",
                reason="do not proceed",
            )
        )

        try:
            _ = await service.execute_delete_document_process_runs(
                request=ExecuteDeleteDocumentProcessRunsRequest(
                    action_id=prepare.action_id,
                    requested_by="qa-user",
                )
            )
            raise AssertionError("Expected AgenticActionError")
        except AgenticActionError as exc:
            assert "canceled" in str(exc)
    finally:
        await session_factory.kw["bind"].dispose()
