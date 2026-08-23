import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval, ApprovalDecision
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.services.audit_service import log_event


class DiagnosisNotFoundError(Exception):
    pass


class DiagnosisNotCompletedError(Exception):
    pass


class AlreadyDecidedError(Exception):
    def __init__(self, existing: Approval):
        self.existing = existing
        super().__init__(f"Diagnosis already {existing.decision.value}")


async def get_approval(db: AsyncSession, *, diagnosis_id: uuid.UUID) -> Approval | None:
    result = await db.execute(select(Approval).where(Approval.diagnosis_id == diagnosis_id))
    return result.scalar_one_or_none()


async def _decide(
    db: AsyncSession,
    *,
    tenant_id: str,
    diagnosis_id: uuid.UUID,
    supervisor_id: uuid.UUID,
    decision: ApprovalDecision,
    comments: str | None,
) -> Approval:
    result = await db.execute(
        select(Diagnosis).where(Diagnosis.id == diagnosis_id, Diagnosis.tenant_id == tenant_id)
    )
    diagnosis = result.scalar_one_or_none()
    if diagnosis is None:
        raise DiagnosisNotFoundError(str(diagnosis_id))
    if diagnosis.status != DiagnosisStatus.completed:
        raise DiagnosisNotCompletedError(
            f"Cannot decide on a diagnosis with status {diagnosis.status.value!r}"
        )

    existing = await get_approval(db, diagnosis_id=diagnosis_id)
    if existing is not None:
        raise AlreadyDecidedError(existing)

    approval = Approval(
        tenant_id=tenant_id,
        diagnosis_id=diagnosis_id,
        supervisor_id=supervisor_id,
        decision=decision,
        comments=comments,
    )
    db.add(approval)
    await db.flush()

    await log_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=supervisor_id,
        action=f"diagnosis.{decision.value}",
        resource_type="diagnosis",
        resource_id=diagnosis_id,
        detail={"comments": comments, "severity": diagnosis.severity.value},
    )

    await db.commit()
    await db.refresh(approval)
    return approval


async def approve_diagnosis(
    db: AsyncSession,
    *,
    tenant_id: str,
    diagnosis_id: uuid.UUID,
    supervisor_id: uuid.UUID,
    comments: str | None = None,
) -> Approval:
    return await _decide(
        db,
        tenant_id=tenant_id,
        diagnosis_id=diagnosis_id,
        supervisor_id=supervisor_id,
        decision=ApprovalDecision.approved,
        comments=comments,
    )


async def reject_diagnosis(
    db: AsyncSession,
    *,
    tenant_id: str,
    diagnosis_id: uuid.UUID,
    supervisor_id: uuid.UUID,
    comments: str | None = None,
) -> Approval:
    return await _decide(
        db,
        tenant_id=tenant_id,
        diagnosis_id=diagnosis_id,
        supervisor_id=supervisor_id,
        decision=ApprovalDecision.rejected,
        comments=comments,
    )
