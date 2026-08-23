import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.diagnosis import Diagnosis


async def list_diagnoses(
    db: AsyncSession, *, tenant_id: str, equipment_id: str | None = None
) -> list[Diagnosis]:
    query = (
        select(Diagnosis)
        .where(Diagnosis.tenant_id == tenant_id)
        .order_by(Diagnosis.created_at.desc())
    )
    if equipment_id:
        query = query.where(Diagnosis.equipment_id == equipment_id)
    result = await db.execute(query)
    return list(result.scalars().all())


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
