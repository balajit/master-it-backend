from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select

from learning_platform.infrastructure.persistence.models.roll_back_agent_action import (
    RollBackAgentActionRow,
)
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository


class RollBackAgentActionRepository(BaseRepository[RollBackAgentActionRow]):
    model_class = RollBackAgentActionRow

    async def find_prepared_by_target_key(self, target_key: str) -> RollBackAgentActionRow | None:
        stmt = select(RollBackAgentActionRow).where(
            RollBackAgentActionRow.target_key == target_key,
            RollBackAgentActionRow.status == "prepared",
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def create_prepared_action(
        self,
        *,
        action_type: str,
        tool_name: str,
        reason: str,
        requested_by: str,
        target_key: str,
        target_summary: dict[str, object],
        undo_steps: list[dict[str, object]],
        precheck_passed: bool,
        affected_row_count: int,
        affected_file_count: int,
        ttl_minutes: int,
    ) -> RollBackAgentActionRow:
        prepared_at = datetime.now(UTC)
        expires_at = prepared_at + timedelta(minutes=ttl_minutes)
        integrity_hash = self._build_integrity_hash(undo_steps)

        row = RollBackAgentActionRow(
            action_type=action_type,
            tool_name=tool_name,
            status="prepared",
            reason=reason,
            requested_by=requested_by,
            target_key=target_key,
            precheck_passed=precheck_passed,
            target_summary_json=target_summary,
            undo_steps_json=undo_steps,
            integrity_hash=integrity_hash,
            affected_row_count=affected_row_count,
            affected_file_count=affected_file_count,
            prepared_at=prepared_at,
            expires_at=expires_at,
        )
        row = await self._session.merge(row)
        await self._session.flush()
        return row

    async def mark_applied(
        self,
        row: RollBackAgentActionRow,
        *,
        affected_row_count: int,
        affected_file_count: int,
        target_summary: dict[str, object] | None = None,
    ) -> None:
        attached = await self._session.merge(row)
        attached.status = "applied"
        attached.applied_at = datetime.now(UTC)
        attached.affected_row_count = affected_row_count
        attached.affected_file_count = affected_file_count
        if target_summary is not None:
            attached.target_summary_json = target_summary
        attached.error_message = None
        await self._session.flush()

    async def mark_execute_failed(self, row: RollBackAgentActionRow, error_message: str) -> None:
        attached = await self._session.merge(row)
        attached.status = "execute_failed"
        attached.error_message = error_message
        await self._session.flush()

    async def mark_rolled_back(
        self,
        row: RollBackAgentActionRow,
        *,
        target_summary: dict[str, object] | None = None,
    ) -> None:
        attached = await self._session.merge(row)
        attached.status = "rolled_back"
        attached.rolled_back_at = datetime.now(UTC)
        if target_summary is not None:
            attached.target_summary_json = target_summary
        attached.error_message = None
        await self._session.flush()

    async def mark_canceled(
        self,
        row: RollBackAgentActionRow,
        *,
        target_summary: dict[str, object] | None = None,
    ) -> None:
        attached = await self._session.merge(row)
        attached.status = "canceled"
        attached.canceled_at = datetime.now(UTC)
        if target_summary is not None:
            attached.target_summary_json = target_summary
        attached.error_message = None
        await self._session.flush()

    async def mark_rollback_failed(self, row: RollBackAgentActionRow, error_message: str) -> None:
        attached = await self._session.merge(row)
        attached.status = "rollback_failed"
        attached.error_message = error_message
        await self._session.flush()

    @staticmethod
    def is_expired(row: RollBackAgentActionRow) -> bool:
        if row.expires_at is None:
            return False
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return datetime.now(UTC) > expires_at

    @staticmethod
    def _build_integrity_hash(undo_steps: list[dict[str, object]]) -> str:
        payload = json.dumps(undo_steps, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def validate_integrity(row: RollBackAgentActionRow) -> bool:
        steps: list[dict[str, object]] = list(row.undo_steps_json or [])
        computed = RollBackAgentActionRepository._build_integrity_hash(steps)
        return computed == row.integrity_hash
