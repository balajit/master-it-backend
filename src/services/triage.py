from __future__ import annotations

from typing import Any

from learning_platform.agentic_ops import AgenticOpsSettings
from learning_platform.agentic_ops.contracts.mcp import ReportScope
from learning_platform.agentic_ops.triage.models import TriageResult
from learning_platform.agentic_ops.triage.service import TriageService

from database.repositories.triage import (
    complete_diagnosis_run,
    create_diagnosis_run,
    get_diagnosis_findings,
    get_diagnosis_run,
    insert_diagnosis_findings,
)


def _validate_document_scope(*, document_id: str) -> ReportScope:
    if not document_id.strip():
        raise ValueError("document_id is required")
    return ReportScope(kind="document", document_id=document_id)


def _summary_from_result(result: TriageResult) -> dict[str, object]:
    return {
        "rule_set_name": result.rule_set_name,
        "rule_set_version": result.rule_set_version,
        "stats": result.stats.model_dump(mode="json"),
        "missing_entry_tables": [
            row.model_dump(mode="json") for row in result.missing_entry_tables
        ],
    }


async def run_diagnosis(
    *,
    document_id: str,
) -> dict[str, Any]:
    scope = _validate_document_scope(document_id=document_id)

    diagnosis_id = await create_diagnosis_run(document_id=document_id, status="running")

    service = TriageService(settings=AgenticOpsSettings())

    try:
        result = await service.run(scope)
        await insert_diagnosis_findings(
            diagnosis_id=diagnosis_id,
            findings=[finding.model_dump(mode="json") for finding in result.findings],
        )
        await complete_diagnosis_run(
            diagnosis_id=diagnosis_id,
            status="completed",
            verdict=result.verdict,
            report_id=result.report_id,
            summary_json=_summary_from_result(result),
            error_message=None,
        )
    except Exception as exc:
        await complete_diagnosis_run(
            diagnosis_id=diagnosis_id,
            status="failed",
            verdict=None,
            report_id=None,
            summary_json=None,
            error_message=str(exc),
        )
        raise

    run_row = await get_diagnosis_run(diagnosis_id)
    findings = await get_diagnosis_findings(diagnosis_id)
    if run_row is None:
        raise RuntimeError("Failed to load diagnosis after completion")
    return _serialize_run_with_findings(run_row, findings)


def _serialize_run_with_findings(
    run_row: dict[str, Any], findings: list[dict[str, Any]]
) -> dict[str, Any]:
    summary_json = run_row.get("summary_json") or {}
    missing_tables = summary_json.get("missing_entry_tables")
    if not isinstance(missing_tables, list):
        missing_tables = []

    return {
        "diagnosis_id": run_row["id"],
        "document_id": run_row.get("document_id"),
        "status": run_row["status"],
        "verdict": run_row.get("verdict"),
        "report_id": run_row.get("report_id"),
        "created_at": run_row["created_at"],
        "completed_at": run_row.get("completed_at"),
        "summary": summary_json,
        "missing_entry_tables": missing_tables,
        "findings": [
            {
                "id": row["id"],
                "diagnosis_id": row["run_id"],
                "rule_id": row["rule_id"],
                "severity": row["severity"],
                "table_name": row["table_name"],
                "message": row["message"],
                "affected_count": row["affected_count"],
                "sample": row.get("sample_json") or {},
            }
            for row in findings
        ],
    }


async def get_diagnosis_view(diagnosis_id: int) -> dict[str, Any] | None:
    run_row = await get_diagnosis_run(diagnosis_id)
    if run_row is None:
        return None
    findings = await get_diagnosis_findings(diagnosis_id)
    return _serialize_run_with_findings(run_row, findings)


async def get_diagnosis_findings_view(diagnosis_id: int) -> list[dict[str, Any]]:
    rows = await get_diagnosis_findings(diagnosis_id)
    return [
        {
            "id": row["id"],
            "diagnosis_id": row["run_id"],
            "rule_id": row["rule_id"],
            "severity": row["severity"],
            "table_name": row["table_name"],
            "message": row["message"],
            "affected_count": row["affected_count"],
            "sample": row.get("sample_json") or {},
        }
        for row in rows
    ]
