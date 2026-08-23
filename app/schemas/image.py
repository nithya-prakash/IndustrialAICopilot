import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.image_analysis import ImageAnalysisStatus


class ObservationResponse(BaseModel):
    description: str
    confidence: float


class ImageAnalysisResponse(BaseModel):
    id: uuid.UUID
    status: ImageAnalysisStatus
    equipment_type: str | None
    equipment_id: str | None
    vision_provider: str
    vision_model: str
    observations: list[ObservationResponse]
    limitations: list[str]
    error_message: str | None
    created_at: datetime
