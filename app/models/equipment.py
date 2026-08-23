from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPkMixin


class Equipment(UUIDPkMixin, TimestampMixin, Base):
    """Added in Phase 6, not earlier — Document/ImageAnalysis/SensorReading
    all got by with a plain equipment_id string because nothing needed real
    per-equipment data. get_maintenance_schedule does, so this is the actual
    trigger point (see docs/architecture-decisions.md)."""

    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("tenant_id", "equipment_id", name="uq_equipment_tenant_id"),)

    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_type: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class MaintenanceTask(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "maintenance_tasks"

    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    last_performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
