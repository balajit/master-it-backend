from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.base import engine
from database.models_triage import TriageFindingModel, TriageRunModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def create_diagnosis_run(
    *,
    document_id: str,
    status: str = "running",
) -> int:
    async with AsyncSession(engine) as session:
        run = TriageRunModel(
            scope_kind="document",
            course_id=None,
            document_id=document_id,
            status=status,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return int(run.id)


async def complete_diagnosis_run(
    *,
    diagnosis_id: int,
    status: str,
    verdict: str | None,
    report_id: str | None,
    summary_json: dict[str, object] | None,
    error_message: str | None,
) -> bool:
    async with AsyncSession(engine) as session:
        run = (
            (
                await session.execute(
                    select(TriageRunModel).where(TriageRunModel.id == diagnosis_id)
                )
            )
            .scalars()
            .first()
        )
        if run is None:
            return False
        run.status = status
        run.verdict = verdict
        run.report_id = report_id
        run.summary_json = summary_json
        run.error_message = error_message
        run.completed_at = _utc_now()
        await session.commit()
        return True


async def insert_diagnosis_findings(
    *,
    diagnosis_id: int,
    findings: list[dict[str, Any]],
) -> int:
    if not findings:
        return 0

    rows: list[TriageFindingModel] = []
    for finding in findings:
        rows.append(
            TriageFindingModel(
                run_id=diagnosis_id,
                rule_id=str(finding.get("rule_id", "unknown")),
                severity=str(finding.get("severity", "warning")),
                table_name=str(finding.get("table_name", "")),
                message=str(finding.get("message", "")),
                affected_count=int(finding.get("affected_count", 0)),
                sample_json=finding.get("sample") or {},
            )
        )

    async with AsyncSession(engine) as session:
        session.add_all(rows)
        await session.commit()
        return len(rows)


async def get_diagnosis_run(diagnosis_id: int) -> dict[str, Any] | None:
    async with AsyncSession(engine) as session:
        run = (
            (
                await session.execute(
                    select(TriageRunModel).where(TriageRunModel.id == diagnosis_id)
                )
            )
            .scalars()
            .first()
        )
        if run is None:
            return None
        return {
            "id": int(run.id),
            "scope_kind": run.scope_kind,
            "course_id": run.course_id,
            "document_id": run.document_id,
            "status": run.status,
            "verdict": run.verdict,
            "report_id": run.report_id,
            "summary_json": run.summary_json or {},
            "error_message": run.error_message,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
        }


async def get_diagnosis_findings(diagnosis_id: int) -> list[dict[str, Any]]:
    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(TriageFindingModel)
                    .where(TriageFindingModel.run_id == diagnosis_id)
                    .order_by(TriageFindingModel.id.asc())
                )
            )
            .scalars()
            .all()
        )

    return [
        {
            "id": int(row.id),
            "run_id": int(row.run_id),
            "rule_id": row.rule_id,
            "severity": row.severity,
            "table_name": row.table_name,
            "message": row.message,
            "affected_count": int(row.affected_count),
            "sample_json": row.sample_json or {},
            "created_at": row.created_at,
        }
        for row in rows
    ]
