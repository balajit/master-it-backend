from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from schemas import (
    CancelDeleteActionRequest,
    CancelDeleteActionResponse,
    DiagnosisRunRead,
    DeleteDocumentProcessRunsRequest,
    DeleteDocumentProcessRunsResponse,
    DiagnosisFindingRead,
    DiagnosisRequest,
    RollbackDeleteActionRequest,
    RollbackDeleteActionResponse,
)
from services.triage import (
    get_diagnosis_findings_view,
    get_diagnosis_view,
    run_diagnosis,
)
from services.triage_actions import (
    cancel_delete_action,
    delete_document_process_runs,
    rollback_delete_action,
)

router: APIRouter = APIRouter(prefix="/api/v1/triage", tags=["triage"])


@router.post("/diagnoses", response_model=DiagnosisRunRead)
async def create_diagnosis_endpoint(
    body: DiagnosisRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> DiagnosisRunRead:
    _ = user
    diagnosis_view = await run_diagnosis(document_id=body.document_id)
    return DiagnosisRunRead.model_validate(diagnosis_view)


@router.get("/diagnoses/{diagnosis_id}", response_model=DiagnosisRunRead)
async def get_diagnosis_endpoint(
    diagnosis_id: int,
    user: dict[str, Any] = Depends(get_current_user),
) -> DiagnosisRunRead:
    _ = user
    diagnosis_view = await get_diagnosis_view(diagnosis_id)
    if diagnosis_view is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found")
    return DiagnosisRunRead.model_validate(diagnosis_view)


@router.get(
    "/diagnoses/{diagnosis_id}/findings", response_model=list[DiagnosisFindingRead]
)
async def get_diagnosis_findings_endpoint(
    diagnosis_id: int,
    user: dict[str, Any] = Depends(get_current_user),
) -> list[DiagnosisFindingRead]:
    _ = user
    diagnosis_view = await get_diagnosis_view(diagnosis_id)
    if diagnosis_view is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found")
    findings = await get_diagnosis_findings_view(diagnosis_id)
    return [DiagnosisFindingRead.model_validate(row) for row in findings]


@router.post(
    "/diagnoses/{diagnosis_id}/actions/delete-document-process-runs",
    response_model=DeleteDocumentProcessRunsResponse,
)
async def delete_document_process_runs_endpoint(
    diagnosis_id: int,
    body: DeleteDocumentProcessRunsRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> DeleteDocumentProcessRunsResponse:
    diagnosis_view = await get_diagnosis_view(diagnosis_id)
    if diagnosis_view is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found")
    try:
        payload = await delete_document_process_runs(
            process_ids=body.process_ids,
            reason=body.reason,
            confirm=body.confirm,
            action_id=body.action_id,
            diagnosis_id=diagnosis_id,
            user=user,
        )
    except HTTPException:
        raise
    return DeleteDocumentProcessRunsResponse.model_validate(payload)


@router.post(
    "/diagnoses/{diagnosis_id}/actions/{action_id}/cancel",
    response_model=CancelDeleteActionResponse,
)
async def cancel_delete_action_endpoint(
    diagnosis_id: int,
    action_id: str,
    body: CancelDeleteActionRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> CancelDeleteActionResponse:
    diagnosis_view = await get_diagnosis_view(diagnosis_id)
    if diagnosis_view is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found")
    try:
        payload = await cancel_delete_action(
            diagnosis_id=diagnosis_id,
            action_id=action_id,
            reason=body.reason,
            user=user,
        )
    except HTTPException:
        raise
    return CancelDeleteActionResponse.model_validate(payload)


@router.post(
    "/diagnoses/{diagnosis_id}/actions/{action_id}/rollback",
    response_model=RollbackDeleteActionResponse,
)
async def rollback_delete_action_endpoint(
    diagnosis_id: int,
    action_id: str,
    body: RollbackDeleteActionRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> RollbackDeleteActionResponse:
    diagnosis_view = await get_diagnosis_view(diagnosis_id)
    if diagnosis_view is None:
        raise HTTPException(status_code=404, detail="Diagnosis not found")
    try:
        payload = await rollback_delete_action(
            diagnosis_id=diagnosis_id,
            action_id=action_id,
            reason=body.reason,
            user=user,
        )
    except HTTPException:
        raise
    return RollbackDeleteActionResponse.model_validate(payload)
