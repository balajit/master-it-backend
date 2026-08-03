from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from learning_platform.agentic_ops import AgenticOpsSettings
from learning_platform.agentic_ops.mcp.client import McpActionClient, McpClientError


def _require_corrective_actions_enabled(settings: AgenticOpsSettings) -> None:
    if settings.allow_corrective_actions:
        return
    raise HTTPException(status_code=403, detail="Corrective actions are disabled")


def _build_requested_by(user: dict[str, Any]) -> str:
    user_id = user.get("id")
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid user context")
    return f"user:{int(user_id)}"


def _build_action_client(settings: AgenticOpsSettings) -> McpActionClient:
    return McpActionClient(
        endpoint=settings.action_mcp_endpoint,
        timeout_seconds=settings.mcp_timeout_seconds,
        api_key=settings.action_mcp_api_key,
    )


def _ensure_manage_permission(user: dict[str, Any]) -> None:
    permissions = user.get("permissions")
    if not isinstance(permissions, list):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if "*" in permissions or "course:manage" in permissions:
        return
    raise HTTPException(status_code=403, detail="Insufficient permissions")


async def delete_document_process_runs(
    *,
    process_ids: list[int] | None,
    reason: str,
    confirm: bool,
    action_id: str | None,
    diagnosis_id: int,
    user: dict[str, Any],
) -> dict[str, Any]:
    settings = AgenticOpsSettings()
    _require_corrective_actions_enabled(settings)
    _ensure_manage_permission(user)

    requested_by = _build_requested_by(user)
    client = _build_action_client(settings)

    if not confirm:
        if not process_ids:
            raise HTTPException(status_code=422, detail="process_ids is required")
        try:
            prepared = await client.prepare_delete_document_process_runs(
                process_ids=process_ids,
                reason=reason,
                requested_by=requested_by,
            )
        except McpClientError as exc:
            raise _map_mcp_action_error(exc)
        return {
            "diagnosis_id": diagnosis_id,
            "status": "confirmation_required",
            "action_id": prepared.action_id,
            "action_type": prepared.action_type,
            "precheck_passed": prepared.precheck_passed,
            "preview": {
                "requested_ids": prepared.requested_ids,
                "target_process_ids": prepared.target_process_ids,
                "missing_process_ids": prepared.missing_process_ids,
                "affected_row_count": prepared.affected_row_count,
                "affected_file_count": prepared.affected_file_count,
                "integrity_hash": prepared.integrity_hash,
            },
            "expires_at": prepared.expires_at,
            "message": "Preparation complete. Submit confirm=true to execute delete.",
        }

    if not action_id or not action_id.strip():
        raise HTTPException(
            status_code=422, detail="action_id is required when confirm=true"
        )

    try:
        executed = await client.execute_delete_document_process_runs(
            action_id=action_id,
            requested_by=requested_by,
        )
    except McpClientError as exc:
        raise _map_mcp_action_error(exc)
    return {
        "diagnosis_id": diagnosis_id,
        "status": executed.status,
        "action_id": executed.action_id,
        "action_type": executed.action_type,
        "deleted_process_ids": executed.deleted_process_ids,
        "missing_process_ids": executed.missing_process_ids,
        "deleted_pipeline_log_count": executed.deleted_pipeline_log_count,
        "affected_row_count": executed.affected_row_count,
        "affected_file_count": executed.affected_file_count,
        "applied_at": executed.applied_at,
    }


async def cancel_delete_action(
    *,
    diagnosis_id: int,
    action_id: str,
    reason: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    settings = AgenticOpsSettings()
    _require_corrective_actions_enabled(settings)
    _ensure_manage_permission(user)

    requested_by = _build_requested_by(user)
    client = _build_action_client(settings)
    try:
        canceled = await client.cancel_agent_action(
            action_id=action_id,
            requested_by=requested_by,
            reason=reason,
        )
    except McpClientError as exc:
        raise _map_mcp_action_error(exc)
    return {
        "diagnosis_id": diagnosis_id,
        "status": canceled.status,
        "action_id": canceled.action_id,
        "action_type": canceled.action_type,
        "canceled_at": canceled.canceled_at,
    }


async def rollback_delete_action(
    *,
    diagnosis_id: int,
    action_id: str,
    reason: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    settings = AgenticOpsSettings()
    _require_corrective_actions_enabled(settings)
    _ensure_manage_permission(user)

    requested_by = _build_requested_by(user)
    client = _build_action_client(settings)
    try:
        rolled_back = await client.rollback_agent_action(
            action_id=action_id,
            requested_by=requested_by,
            reason=reason,
        )
    except McpClientError as exc:
        raise _map_mcp_action_error(exc)
    return {
        "diagnosis_id": diagnosis_id,
        "status": rolled_back.status,
        "action_id": rolled_back.action_id,
        "action_type": rolled_back.action_type,
        "restored_row_count": rolled_back.restored_row_count,
        "rolled_back_at": rolled_back.rolled_back_at,
    }


def _map_mcp_action_error(exc: McpClientError) -> HTTPException:
    message = str(exc)
    if "Unknown action_id" in message:
        return HTTPException(status_code=404, detail=message)
    if "cannot" in message or "blocked" in message or "expired" in message:
        return HTTPException(status_code=409, detail=message)
    return HTTPException(status_code=502, detail=message)
