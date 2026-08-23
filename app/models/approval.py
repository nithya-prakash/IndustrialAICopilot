import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPkMixin


class ApprovalDecision(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"


class Approval(UUIDPkMixin, TimestampMixin, Base):
    """One decision per diagnosis — a diagnosis is approved or rejected
    once, not re-decided. A technician who disagrees with a rejection asks
    a new question (a new Diagnosis), which keeps the approval history a
    simple, honest record rather than a mutable one. created_at (from
    TimestampMixin) is the decision timestamp."""

    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("diagnosis_id", name="uq_approval_diagnosis_id"),)

    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diagnoses.id"), nullable=False, index=True
    )
    supervisor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, name="approval_decision"), nullable=False
    )
    comments: Mapped[str | None] = mapped_column(Text)
