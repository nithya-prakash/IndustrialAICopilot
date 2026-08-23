import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.copilot import to_diagnosis_response
from app.core.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.copilot import DiagnosisResponse
from app.services.diagnosis_service import get_diagnosis, list_diagnoses
from app.services.report_service import format_diagnostic_report

router = APIRouter(prefix="/api/v1/diagnoses", tags=["diagnoses"])


@router.get("", response_model=list[DiagnosisResponse])
async def list_all(
    equipment_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DiagnosisResponse]:
    diagnoses = await list_diagnoses(db, tenant_id=user.tenant_id, equipment_id=equipment_id)
    return [to_diagnosis_response(d) for d in diagnoses]


@router.get("/{diagnosis_id}", response_model=DiagnosisResponse)
async def get_one(
    diagnosis_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiagnosisResponse:
    diagnosis = await get_diagnosis(db, diagnosis_id=diagnosis_id, tenant_id=user.tenant_id)
    if diagnosis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diagnosis not found")
    return to_diagnosis_response(diagnosis)


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
