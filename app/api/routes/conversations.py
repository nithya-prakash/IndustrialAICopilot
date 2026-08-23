import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.database import get_db
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.copilot import ConversationDetailResponse, ConversationResponse, MessageResponse
from app.services.diagnosis_service import get_conversation, list_conversations

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def _to_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        equipment_id=conversation.equipment_id,
        created_at=conversation.created_at,
    )


@router.get("", response_model=list[ConversationResponse])
async def list_all(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ConversationResponse]:
    conversations = await list_conversations(db, tenant_id=user.tenant_id, user_id=user.id)
    return [_to_response(c) for c in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_one(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailResponse:
    conversation = await get_conversation(
        db, conversation_id=conversation_id, tenant_id=user.tenant_id
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        equipment_id=conversation.equipment_id,
        created_at=conversation.created_at,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role.value,
                content=m.content,
                diagnosis_id=m.diagnosis_id,
                created_at=m.created_at,
            )
            for m in conversation.messages
        ],
    )
