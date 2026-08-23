import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.copilot import to_diagnosis_response
from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.copilot import DiagnosisResponse
from app.services.approval_service import (
    AlreadyDecidedError,
    DiagnosisNotCompletedError,
    DiagnosisNotFoundError,
    approve_diagnosis,
    get_approval,
    reject_diagnosis,
)
from app.services.diagnosis_service import (
    get_approvals_for_diagnoses,
    get_diagnosis,
    list_diagnoses,
)
from app.services.report_service import format_diagnostic_report

router = APIRouter(prefix="/api/v1/diagnoses", tags=["diagnoses"])

_require_supervisor = require_roles(UserRole.supervisor, UserRole.admin)


@router.get("", response_model=list[DiagnosisResponse])
async def list_all(
    equipment_id: str | None = None,
    pending_approval: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DiagnosisResponse]:
    diagnoses = await list_diagnoses(
        db,
        tenant_id=user.tenant_id,
        equipment_id=equipment_id,
        pending_approval_only=pending_approval,
    )
    approvals = await get_approvals_for_diagnoses(db, diagnosis_ids=[d.id for d in diagnoses])
    return [to_diagnosis_response(d, approvals.get(d.id)) for d in diagnoses]


@router.get("/{diagnosis_id}", response_model=DiagnosisResponse)
async def get_one(
    diagnosis_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiagnosisResponse:
    diagnosis = await get_diagnosis(db, diagnosis_id=diagnosis_id, tenant_id=user.tenant_id)
    if diagnosis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis not found")
    approval = await get_approval(db, diagnosis_id=diagnosis_id)
    return to_diagnosis_response(diagnosis, approval)


@router.get("/{diagnosis_id}/report", response_class=PlainTextResponse)
async def report(
    diagnosis_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    diagnosis = await get_diagnosis(db, diagnosis_id=diagnosis_id, tenant_id=user.tenant_id)
    if diagnosis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis not found")
    return format_diagnostic_report(diagnosis)


def _handle_decision_errors(exc: Exception):
    if isinstance(exc, DiagnosisNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis not found")
    if isinstance(exc, DiagnosisNotCompletedError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, AlreadyDecidedError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return exc


@router.post("/{diagnosis_id}/approve", response_model=DiagnosisResponse)
async def approve(
    diagnosis_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    user: User = Depends(_require_supervisor),
    db: AsyncSession = Depends(get_db),
) -> DiagnosisResponse:
    try:
        approval = await approve_diagnosis(
            db,
            tenant_id=user.tenant_id,
            diagnosis_id=diagnosis_id,
            supervisor_id=user.id,
            comments=payload.comments,
        )
    except (DiagnosisNotFoundError, DiagnosisNotCompletedError, AlreadyDecidedError) as exc:
        raise _handle_decision_errors(exc) from exc

    diagnosis = await get_diagnosis(db, diagnosis_id=diagnosis_id, tenant_id=user.tenant_id)
    return to_diagnosis_response(diagnosis, approval)


@router.post("/{diagnosis_id}/reject", response_model=DiagnosisResponse)
async def reject(
    diagnosis_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    user: User = Depends(_require_supervisor),
    db: AsyncSession = Depends(get_db),
) -> DiagnosisResponse:
    try:
        approval = await reject_diagnosis(
            db,
            tenant_id=user.tenant_id,
            diagnosis_id=diagnosis_id,
            supervisor_id=user.id,
            comments=payload.comments,
        )
    except (DiagnosisNotFoundError, DiagnosisNotCompletedError, AlreadyDecidedError) as exc:
        raise _handle_decision_errors(exc) from exc

    diagnosis = await get_diagnosis(db, diagnosis_id=diagnosis_id, tenant_id=user.tenant_id)
    return to_diagnosis_response(diagnosis, approval)
