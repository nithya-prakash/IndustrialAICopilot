import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import PortableJSON, TimestampMixin, UUIDPkMixin


class ImageAnalysisStatus(str, enum.Enum):
    analyzing = "analyzing"
    ready = "ready"
    failed = "failed"


class ImageAnalysis(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "image_analyses"

    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    equipment_type: Mapped[str | None] = mapped_column(String(128), index=True)
    equipment_id: Mapped[str | None] = mapped_column(String(128), index=True)

    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    vision_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    vision_model: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[ImageAnalysisStatus] = mapped_column(
        Enum(ImageAnalysisStatus, name="image_analysis_status"),
        default=ImageAnalysisStatus.analyzing,
        nullable=False,
    )
    # [{"description": str, "confidence": float}, ...]
    observations: Mapped[list | None] = mapped_column(PortableJSON)
    # ["Internal damage cannot be determined from the image.", ...]
    limitations: Mapped[list | None] = mapped_column(PortableJSON)
    raw_response: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
