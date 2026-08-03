"""Destructive action service for MCP prepare/execute/cancel/rollback workflows."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from learning_platform.agentic_ops.contracts.mcp import (
    CancelAgentActionRequest,
    CanceledAgentActionResult,
    ExecutedAgentActionResult,
    ExecuteDeleteDocumentProcessRunsRequest,
    PreparedAgentActionResult,
    PrepareDeleteDocumentProcessRunsRequest,
    RollBackAgentActionRequest,
    RolledBackAgentActionResult,
)
from learning_platform.api.deps import get_session_factory
from learning_platform.infrastructure.persistence.models.document_process import DocumentProcessRow
from learning_platform.infrastructure.persistence.models.pipeline_log import PipelineLogRow
from learning_platform.infrastructure.persistence.models.roll_back_agent_action import (
    RollBackAgentActionRow,
)
from learning_platform.infrastructure.persistence.repositories.document_process import (
    DocumentProcessRepository,
)
from learning_platform.infrastructure.persistence.repositories.roll_back_agent_action import (
    RollBackAgentActionRepository,
)

ACTION_DELETE_DOCUMENT_PROCESS_RUNS = "delete_document_process_runs"
TOOL_PREPARE_DELETE_DOCUMENT_PROCESS_RUNS = "ops.prepare_delete_document_process_runs"


class AgenticActionError(RuntimeError):
    """Raised when destructive action workflow state is invalid."""


class AgenticActionService:
    """Implements prepare/execute/cancel/rollback for destructive actions."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        action_ttl_minutes: int = 30,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._action_ttl_minutes = action_ttl_minutes

    async def prepare_delete_document_process_runs(
        self,
        *,
        request: PrepareDeleteDocumentProcessRunsRequest,
    ) -> PreparedAgentActionResult:
        target_key = self._build_target_key(request.process_ids)

        async with self._session_factory() as session:
            rollback_repo = RollBackAgentActionRepository(session)
            existing_prepared = await rollback_repo.find_prepared_by_target_key(target_key)
            if existing_prepared is not None:
                return self._prepared_result_from_existing_action(
                    existing_prepared,
                    requested_ids=request.process_ids,
                    status="already_prepared",
                )

            document_process_repo = DocumentProcessRepository(session)
            existing_rows = await document_process_repo.list_entries_by_ids(request.process_ids)
            existing_ids = [int(row.id) for row in existing_rows]
            existing_id_set = set(existing_ids)
            requested_ids = self._normalize_process_ids(request.process_ids)
            missing_ids = sorted(
                process_id for process_id in requested_ids if process_id not in existing_id_set
            )

            pipeline_logs = await document_process_repo.list_pipeline_logs_by_process_ids(
                existing_ids
            )
            precheck_passed = len(existing_ids) > 0
            undo_steps = self._build_undo_steps(existing_rows, pipeline_logs)
            integrity_hash = RollBackAgentActionRepository._build_integrity_hash(undo_steps)

            target_summary: dict[str, object] = {
                "target_key": target_key,
                "requested_ids": requested_ids,
                "target_process_ids": existing_ids,
                "missing_process_ids": missing_ids,
                "deleted_process_ids": [],
                "deleted_pipeline_log_count": 0,
                "restored_row_count": 0,
                "cancel_reason": None,
            }

            action_row = await rollback_repo.create_prepared_action(
                action_type=ACTION_DELETE_DOCUMENT_PROCESS_RUNS,
                tool_name=TOOL_PREPARE_DELETE_DOCUMENT_PROCESS_RUNS,
                reason=request.reason,
                requested_by=request.requested_by,
                target_key=target_key,
                target_summary=target_summary,
                undo_steps=undo_steps,
                precheck_passed=precheck_passed,
                affected_row_count=len(existing_rows) + len(pipeline_logs),
                affected_file_count=len(existing_rows),
                ttl_minutes=self._action_ttl_minutes,
            )
            await session.commit()

        return PreparedAgentActionResult(
            action_id=action_row.id,
            action_type=action_row.action_type,
            status="prepared",
            precheck_passed=action_row.precheck_passed,
            requested_ids=requested_ids,
            target_process_ids=existing_ids,
            missing_process_ids=missing_ids,
            affected_row_count=action_row.affected_row_count,
            affected_file_count=action_row.affected_file_count,
            integrity_hash=integrity_hash,
            expires_at=action_row.expires_at,
        )

    async def execute_delete_document_process_runs(
        self,
        *,
        request: ExecuteDeleteDocumentProcessRunsRequest,
    ) -> ExecutedAgentActionResult:
        async with self._session_factory() as session:
            rollback_repo = RollBackAgentActionRepository(session)
            row = await rollback_repo.find_by_id(request.action_id)
            if row is None:
                raise AgenticActionError(f"Unknown action_id '{request.action_id}'")
            self._assert_action_type(row=row)
            self._assert_not_expired(rollback_repo=rollback_repo, row=row)

            if row.status == "applied":
                return self._executed_result_for_already_applied(row)
            if row.status == "rolled_back":
                raise AgenticActionError(
                    f"Action '{request.action_id}' is already rolled back; prepare a new action"
                )
            if row.status == "canceled":
                raise AgenticActionError(
                    f"Action '{request.action_id}' is canceled; prepare a new action"
                )
            if row.status != "prepared":
                raise AgenticActionError(
                    f"Action '{request.action_id}' is in status '{row.status}', cannot execute"
                )
            if not row.precheck_passed:
                raise AgenticActionError(
                    f"Action '{request.action_id}' precheck failed; execution blocked"
                )
            if not rollback_repo.validate_integrity(row):
                raise AgenticActionError(
                    f"Action '{request.action_id}' integrity check failed; execution blocked"
                )

            target_process_ids = self._target_process_ids(row)
            document_process_repo = DocumentProcessRepository(session)
            try:
                (
                    deleted_ids,
                    not_found_ids,
                    deleted_pipeline_log_count,
                ) = await document_process_repo.delete_entries_by_ids(target_process_ids)

                target_summary = self._target_summary(row)
                target_summary["deleted_process_ids"] = deleted_ids
                target_summary["deleted_pipeline_log_count"] = deleted_pipeline_log_count

                await rollback_repo.mark_applied(
                    row,
                    affected_row_count=len(deleted_ids) + deleted_pipeline_log_count,
                    affected_file_count=len(deleted_ids),
                    target_summary=target_summary,
                )
                await session.commit()
            except Exception as exc:
                await rollback_repo.mark_execute_failed(row, str(exc))
                await session.commit()
                raise

            refreshed = await rollback_repo.find_by_id(row.id)
            if refreshed is None:
                raise AgenticActionError(
                    f"Failed to reload action '{request.action_id}' after execute"
                )

        return ExecutedAgentActionResult(
            action_id=refreshed.id,
            action_type=refreshed.action_type,
            status="applied",
            deleted_process_ids=deleted_ids,
            missing_process_ids=not_found_ids,
            deleted_pipeline_log_count=deleted_pipeline_log_count,
            affected_row_count=refreshed.affected_row_count,
            affected_file_count=refreshed.affected_file_count,
            applied_at=refreshed.applied_at,
        )

    async def cancel_agent_action(
        self,
        *,
        request: CancelAgentActionRequest,
    ) -> CanceledAgentActionResult:
        async with self._session_factory() as session:
            rollback_repo = RollBackAgentActionRepository(session)
            row = await rollback_repo.find_by_id(request.action_id)
            if row is None:
                raise AgenticActionError(f"Unknown action_id '{request.action_id}'")
            self._assert_action_type(row=row)

            if row.status == "canceled":
                return CanceledAgentActionResult(
                    action_id=row.id,
                    action_type=row.action_type,
                    status="already_canceled",
                    canceled_at=row.canceled_at,
                )
            if row.status != "prepared":
                raise AgenticActionError(
                    f"Action '{request.action_id}' is in status '{row.status}', cannot cancel"
                )

            target_summary = self._target_summary(row)
            target_summary["cancel_reason"] = request.reason
            await rollback_repo.mark_canceled(row, target_summary=target_summary)
            await session.commit()

            refreshed = await rollback_repo.find_by_id(row.id)
            if refreshed is None:
                raise AgenticActionError(
                    f"Failed to reload action '{request.action_id}' after cancel"
                )

        return CanceledAgentActionResult(
            action_id=refreshed.id,
            action_type=refreshed.action_type,
            status="canceled",
            canceled_at=refreshed.canceled_at,
        )

    async def rollback_agent_action(
        self,
        *,
        request: RollBackAgentActionRequest,
    ) -> RolledBackAgentActionResult:
        async with self._session_factory() as session:
            rollback_repo = RollBackAgentActionRepository(session)
            row = await rollback_repo.find_by_id(request.action_id)
            if row is None:
                raise AgenticActionError(f"Unknown action_id '{request.action_id}'")
            self._assert_action_type(row=row)

            if row.status == "rolled_back":
                return self._rolled_back_result_for_already_rolled_back(row)

            if row.status != "applied":
                raise AgenticActionError(
                    f"Action '{request.action_id}' is in status '{row.status}', cannot rollback"
                )

            if not rollback_repo.validate_integrity(row):
                raise AgenticActionError(
                    f"Action '{request.action_id}' integrity check failed; rollback blocked"
                )

            try:
                restored_row_count = await self._restore_from_undo_steps(session=session, row=row)
                target_summary = self._target_summary(row)
                target_summary["rollback_reason"] = request.reason
                target_summary["restored_row_count"] = restored_row_count
                await rollback_repo.mark_rolled_back(row, target_summary=target_summary)
                await session.commit()
            except Exception as exc:
                await rollback_repo.mark_rollback_failed(row, str(exc))
                await session.commit()
                raise

            refreshed = await rollback_repo.find_by_id(row.id)
            if refreshed is None:
                raise AgenticActionError(
                    f"Failed to reload action '{request.action_id}' after rollback"
                )

        return RolledBackAgentActionResult(
            action_id=refreshed.id,
            action_type=refreshed.action_type,
            status="rolled_back",
            restored_row_count=restored_row_count,
            rolled_back_at=refreshed.rolled_back_at,
        )

    def _prepared_result_from_existing_action(
        self,
        row: RollBackAgentActionRow,
        *,
        requested_ids: list[int],
        status: str,
    ) -> PreparedAgentActionResult:
        return PreparedAgentActionResult(
            action_id=row.id,
            action_type=row.action_type,
            status=status,
            precheck_passed=row.precheck_passed,
            requested_ids=self._normalize_process_ids(requested_ids),
            target_process_ids=self._target_process_ids(row),
            missing_process_ids=self._missing_process_ids(row),
            affected_row_count=row.affected_row_count,
            affected_file_count=row.affected_file_count,
            integrity_hash=row.integrity_hash,
            expires_at=row.expires_at,
        )

    def _executed_result_for_already_applied(
        self,
        row: RollBackAgentActionRow,
    ) -> ExecutedAgentActionResult:
        summary = self._target_summary(row)
        deleted_process_ids = self._coerce_int_list(summary.get("deleted_process_ids"))
        missing_process_ids = self._missing_process_ids(row)
        deleted_pipeline_log_count = int(summary.get("deleted_pipeline_log_count", 0))
        return ExecutedAgentActionResult(
            action_id=row.id,
            action_type=row.action_type,
            status="already_applied",
            deleted_process_ids=deleted_process_ids,
            missing_process_ids=missing_process_ids,
            deleted_pipeline_log_count=deleted_pipeline_log_count,
            affected_row_count=row.affected_row_count,
            affected_file_count=row.affected_file_count,
            applied_at=row.applied_at,
        )

    def _rolled_back_result_for_already_rolled_back(
        self,
        row: RollBackAgentActionRow,
    ) -> RolledBackAgentActionResult:
        summary = self._target_summary(row)
        restored_row_count = int(summary.get("restored_row_count", 0))
        return RolledBackAgentActionResult(
            action_id=row.id,
            action_type=row.action_type,
            status="already_rolled_back",
            restored_row_count=restored_row_count,
            rolled_back_at=row.rolled_back_at,
        )

    def _assert_action_type(self, *, row: RollBackAgentActionRow) -> None:
        if row.action_type != ACTION_DELETE_DOCUMENT_PROCESS_RUNS:
            raise AgenticActionError(f"Action '{row.id}' has unsupported type '{row.action_type}'")

    def _assert_not_expired(
        self,
        *,
        rollback_repo: RollBackAgentActionRepository,
        row: RollBackAgentActionRow,
    ) -> None:
        if rollback_repo.is_expired(row):
            raise AgenticActionError(f"Action '{row.id}' has expired; prepare again")

    def _target_summary(self, row: RollBackAgentActionRow) -> dict[str, Any]:
        summary: dict[str, Any] = dict(row.target_summary_json or {})
        return summary

    def _target_process_ids(self, row: RollBackAgentActionRow) -> list[int]:
        summary = self._target_summary(row)
        return self._coerce_int_list(summary.get("target_process_ids"))

    def _missing_process_ids(self, row: RollBackAgentActionRow) -> list[int]:
        summary = self._target_summary(row)
        return self._coerce_int_list(summary.get("missing_process_ids"))

    def _build_target_key(self, process_ids: list[int]) -> str:
        normalized_ids = self._normalize_process_ids(process_ids)
        id_list = ",".join(str(process_id) for process_id in normalized_ids)
        payload = f"delete_document_process_runs|v1|process_ids={id_list}"
        return sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_process_ids(process_ids: list[int]) -> list[int]:
        return sorted(set(process_ids))

    def _build_undo_steps(
        self,
        process_rows: list[DocumentProcessRow],
        pipeline_rows: list[PipelineLogRow],
    ) -> list[dict[str, object]]:
        steps: list[dict[str, object]] = []
        for row in process_rows:
            steps.append(
                {
                    "table": "lp_document_process",
                    "pk": {"id": int(row.id)},
                    "row": {
                        "id": int(row.id),
                        "source": row.source,
                        "abs_path": row.abs_path,
                        "status": row.status,
                        "run_mode": row.run_mode,
                        "retry_count": int(row.retry_count),
                        "max_retries": int(row.max_retries),
                        "last_completed_stage": row.last_completed_stage,
                        "failed_stage": row.failed_stage,
                        "resume_state": row.resume_state_json,
                        "error_message": row.error_message,
                        "created_at": self._serialize_datetime(row.created_at),
                        "updated_at": self._serialize_datetime(row.updated_at),
                    },
                }
            )
        for row in pipeline_rows:
            steps.append(
                {
                    "table": "lp_pipeline_logs",
                    "pk": {"id": int(row.id)},
                    "row": {
                        "id": int(row.id),
                        "source": row.source,
                        "stage": row.stage,
                        "output": row.output,
                        "result": row.result,
                        "created_at": self._serialize_datetime(row.created_at),
                        "document_process_id": row.document_process_id,
                    },
                }
            )
        return steps

    async def _restore_from_undo_steps(
        self,
        *,
        session: AsyncSession,
        row: RollBackAgentActionRow,
    ) -> int:
        restored_count = 0
        undo_steps = list(row.undo_steps_json or [])

        process_rows: list[dict[str, Any]] = []
        pipeline_rows: list[dict[str, Any]] = []
        for step in undo_steps:
            table_name = str(step.get("table", ""))
            row_data = step.get("row")
            if not isinstance(row_data, dict):
                continue
            if table_name == "lp_document_process":
                process_rows.append(row_data)
            elif table_name == "lp_pipeline_logs":
                pipeline_rows.append(row_data)

        for row_data in process_rows:
            row_id_raw = row_data.get("id")
            if row_id_raw is None:
                continue
            row_id = int(row_id_raw)
            existing = await session.get(DocumentProcessRow, row_id)
            if existing is None:
                process_row = DocumentProcessRow(
                    id=row_id,
                    source=str(row_data.get("source", "")),
                    abs_path=str(row_data.get("abs_path", "")),
                    status=str(row_data.get("status", "pending")),
                    run_mode=str(row_data.get("run_mode", "process")),
                    retry_count=int(row_data.get("retry_count", 0)),
                    max_retries=int(row_data.get("max_retries", 3)),
                    last_completed_stage=self._optional_string(
                        row_data.get("last_completed_stage")
                    ),
                    failed_stage=self._optional_string(row_data.get("failed_stage")),
                    resume_state_json=self._optional_dict(row_data.get("resume_state")),
                    error_message=self._optional_string(row_data.get("error_message")),
                    created_at=self._optional_datetime(row_data.get("created_at")),
                    updated_at=self._optional_datetime(row_data.get("updated_at")),
                )
                await session.merge(process_row)
                restored_count += 1
                continue

            existing.source = str(row_data.get("source", existing.source))
            existing.abs_path = str(row_data.get("abs_path", existing.abs_path))
            existing.status = str(row_data.get("status", existing.status))
            existing.run_mode = str(row_data.get("run_mode", existing.run_mode))
            existing.retry_count = int(row_data.get("retry_count", existing.retry_count))
            existing.max_retries = int(row_data.get("max_retries", existing.max_retries))
            existing.last_completed_stage = self._optional_string(
                row_data.get("last_completed_stage")
            )
            existing.failed_stage = self._optional_string(row_data.get("failed_stage"))
            existing.resume_state_json = self._optional_dict(row_data.get("resume_state"))
            existing.error_message = self._optional_string(row_data.get("error_message"))
            restored_created_at = self._optional_datetime(row_data.get("created_at"))
            if restored_created_at is not None:
                existing.created_at = restored_created_at
            restored_updated_at = self._optional_datetime(row_data.get("updated_at"))
            if restored_updated_at is not None:
                existing.updated_at = restored_updated_at
            restored_count += 1

        for row_data in pipeline_rows:
            row_id_raw = row_data.get("id")
            if row_id_raw is None:
                continue
            row_id = int(row_id_raw)
            existing = await session.get(PipelineLogRow, row_id)
            if existing is not None:
                continue
            pipeline_row = PipelineLogRow(
                id=row_id,
                source=str(row_data.get("source", "")),
                stage=str(row_data.get("stage", "")),
                output=str(row_data.get("output", "")),
                result=str(row_data.get("result", "success")),
                created_at=self._optional_datetime(row_data.get("created_at")),
                document_process_id=self._optional_int(row_data.get("document_process_id")),
            )
            await session.merge(pipeline_row)
            restored_count += 1

        await session.flush()
        return restored_count

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int | float | str):
            return int(value)
        return None

    @staticmethod
    def _optional_dict(value: object) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        output: dict[str, object] = {}
        for key, item in value.items():
            output[str(key)] = item
        return output

    @staticmethod
    def _optional_datetime(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()

    @staticmethod
    def _coerce_int_list(value: object) -> list[int]:
        if not isinstance(value, list):
            return []
        output: list[int] = []
        for item in value:
            coerced = AgenticActionService._optional_int(item)
            if coerced is None:
                continue
            output.append(coerced)
        return output
