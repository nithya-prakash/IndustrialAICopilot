import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    equipment_type: str | None
    equipment_id: str | None
    version_number: int | None
    status: DocumentStatus | None
    error_message: str | None
    page_count: int | None
    used_ocr: bool | None
    chunk_count: int
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
