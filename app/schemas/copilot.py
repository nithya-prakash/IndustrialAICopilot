import uuid
from datetime import datetime

from pydantic import BaseModel


class CopilotQueryRequest(BaseModel):
    question: str
    conversation_id: uuid.UUID | None = None
    equipment_id: str | None = None
    equipment_type: str | None = None
    image_analysis_id: uuid.UUID | None = None
    sensor_readings: dict[str, float] | None = None


class CauseResponse(BaseModel):
    cause: str
    rank: int
    supporting_citations: list[str]


class EvidenceResponse(BaseModel):
    type: str
    citation: str
    detail: str


class ApprovalResponse(BaseModel):
    id: uuid.UUID
    decision: str
    supervisor_id: uuid.UUID
    comments: str | None
    created_at: datetime


class DiagnosisResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    error_message: str | None
    equipment_id: str | None
    equipment_type: str | None
    question: str
    summary: str | None
    visual_observations: list[dict]
    sensor_findings: list[dict]
    possible_causes: list[CauseResponse]
    recommended_checks: list[str]
    recommended_action: str | None
    confidence: float
    severity: str
    requires_human_approval: bool
    evidence: list[EvidenceResponse]
    limitations: list[str]
    llm_provider: str
    llm_model: str
    created_at: datetime
    approval: ApprovalResponse | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    diagnosis_id: uuid.UUID | None
    created_at: datetime


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    equipment_id: str | None
    created_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]
