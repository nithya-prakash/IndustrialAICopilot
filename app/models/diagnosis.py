import enum
import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import PortableJSON, TimestampMixin, UUIDPkMixin


class DiagnosisSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class DiagnosisStatus(str, enum.Enum):
    completed = "completed"
    failed = "failed"


class Diagnosis(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "diagnoses"

    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    equipment_id: Mapped[str | None] = mapped_column(String(128), index=True)
    equipment_type: Mapped[str | None] = mapped_column(String(128))

    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DiagnosisStatus] = mapped_column(
        Enum(DiagnosisStatus, name="diagnosis_status"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    summary: Mapped[str | None] = mapped_column(Text)
    # [{"description": str, "confidence": float}, ...] — copied from an
    # ImageAnalysis the agent looked up, not re-derived.
    visual_observations: Mapped[list | None] = mapped_column(PortableJSON)
    # [{"metric": str, "finding": str, ...}, ...]
    sensor_findings: Mapped[list | None] = mapped_column(PortableJSON)
    # [{"cause": str, "rank": int, "supporting_citations": [str, ...]}, ...]
    possible_causes: Mapped[list | None] = mapped_column(PortableJSON)
    recommended_checks: Mapped[list | None] = mapped_column(PortableJSON)
    recommended_action: Mapped[str | None] = mapped_column(Text)

    # Deterministic, rule-based — never the model's own self-reported
    # confidence. See app/agents/confidence.py.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[DiagnosisSeverity] = mapped_column(
        Enum(DiagnosisSeverity, name="diagnosis_severity"), nullable=False
    )
    # Always recomputed server-side from confidence/severity — never trusts
    # whatever the model itself claimed. See app/agents/confidence.py.
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # [{"type": "document_chunk"|"sensor_reading"|"image_observation"|
    #   "maintenance_record", "citation": str, "detail": str}, ...]
    evidence: Mapped[list | None] = mapped_column(PortableJSON)
    limitations: Mapped[list | None] = mapped_column(PortableJSON)
    # [{"tool": str, "input": dict, "summary": str}, ...] — a lightweight
    # audit trail. The full AuditLog (all requests, not just tool calls) is
    # Phase 7.
    tool_calls: Mapped[list | None] = mapped_column(PortableJSON)

    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
