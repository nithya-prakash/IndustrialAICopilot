from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.diagnosis_agent import run_diagnosis
from app.config import get_settings
from app.core.deps import get_current_user
from app.core.rate_limit import limiter
from app.database import get_db
from app.models.approval import Approval
from app.models.diagnosis import Diagnosis
from app.models.user import User
from app.schemas.copilot import ApprovalResponse, CopilotQueryRequest, DiagnosisResponse

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])
_settings = get_settings()


def to_diagnosis_response(
    diagnosis: Diagnosis, approval: Approval | None = None
) -> DiagnosisResponse:
    return DiagnosisResponse(
        id=diagnosis.id,
        conversation_id=diagnosis.conversation_id,
        status=diagnosis.status.value,
        error_message=diagnosis.error_message,
        equipment_id=diagnosis.equipment_id,
        equipment_type=diagnosis.equipment_type,
        question=diagnosis.question,
        summary=diagnosis.summary,
        visual_observations=diagnosis.visual_observations or [],
        sensor_findings=diagnosis.sensor_findings or [],
        possible_causes=diagnosis.possible_causes or [],
        recommended_checks=diagnosis.recommended_checks or [],
        recommended_action=diagnosis.recommended_action,
        confidence=diagnosis.confidence,
        severity=diagnosis.severity.value,
        requires_human_approval=diagnosis.requires_human_approval,
        evidence=diagnosis.evidence or [],
        limitations=diagnosis.limitations or [],
        llm_provider=diagnosis.llm_provider,
        llm_model=diagnosis.llm_model,
        created_at=diagnosis.created_at,
        approval=(
            ApprovalResponse(
                id=approval.id,
                decision=approval.decision.value,
                supervisor_id=approval.supervisor_id,
                comments=approval.comments,
                created_at=approval.created_at,
            )
            if approval
            else None
        ),
    )


@router.post("/query", response_model=DiagnosisResponse)
@limiter.limit(_settings.rate_limit_ai)
async def query(
    request: Request,
    payload: CopilotQueryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DiagnosisResponse:
    diagnosis = await run_diagnosis(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        conversation_id=payload.conversation_id,
        question=payload.question,
        equipment_id=payload.equipment_id,
        equipment_type=payload.equipment_type,
        image_analysis_id=payload.image_analysis_id,
        sensor_snapshot=payload.sensor_readings,
    )
    return to_diagnosis_response(diagnosis)
