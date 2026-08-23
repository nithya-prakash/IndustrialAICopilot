import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.approval import Approval
from app.models.conversation import Conversation
from app.models.diagnosis import Diagnosis, DiagnosisStatus


async def list_diagnoses(
    db: AsyncSession,
    *,
    tenant_id: str,
    equipment_id: str | None = None,
    pending_approval_only: bool = False,
) -> list[Diagnosis]:
    query = (
        select(Diagnosis)
        .where(Diagnosis.tenant_id == tenant_id)
        .order_by(Diagnosis.created_at.desc())
    )
    if equipment_id:
        query = query.where(Diagnosis.equipment_id == equipment_id)
    if pending_approval_only:
        decided_ids = select(Approval.diagnosis_id)
        query = query.where(
            Diagnosis.status == DiagnosisStatus.completed,
            Diagnosis.requires_human_approval.is_(True),
            Diagnosis.id.not_in(decided_ids),
        )
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_approvals_for_diagnoses(
    db: AsyncSession, *, diagnosis_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Approval]:
    if not diagnosis_ids:
        return {}
    result = await db.execute(select(Approval).where(Approval.diagnosis_id.in_(diagnosis_ids)))
    return {a.diagnosis_id: a for a in result.scalars().all()}


async def get_diagnosis(
    db: AsyncSession, *, diagnosis_id: uuid.UUID, tenant_id: str
) -> Diagnosis | None:
    result = await db.execute(
        select(Diagnosis).where(Diagnosis.id == diagnosis_id, Diagnosis.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_conversations(
    db: AsyncSession, *, tenant_id: str, user_id: uuid.UUID
) -> list[Conversation]:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id, Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())


async def get_conversation(
    db: AsyncSession, *, conversation_id: uuid.UUID, tenant_id: str
) -> Conversation | None:
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()
