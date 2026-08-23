import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import PortableJSON, TimestampMixin, UUIDPkMixin


class AuditLog(UUIDPkMixin, TimestampMixin, Base):
    """Append-only event log for compliance-sensitive actions. Covers the
    diagnosis lifecycle (created, approved, rejected) and document
    lifecycle (uploaded, deleted) this phase — extending to every mutating
    endpoint follows the same `log_event` call, not built out for all of
    them yet (see docs/architecture-decisions.md)."""

    __tablename__ = "audit_logs"

    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    detail: Mapped[dict | None] = mapped_column(PortableJSON)
