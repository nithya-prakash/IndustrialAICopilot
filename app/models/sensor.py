import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPkMixin


class SensorReading(UUIDPkMixin, TimestampMixin, Base):
    """One row per (equipment, metric, timestamp) — a narrow/long schema
    rather than one wide row per snapshot. This maps directly onto
    query_sensor_history(equipment_id, metric, start_time, end_time) and
    lets new metrics show up without a schema change."""

    __tablename__ = "sensor_readings"

    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    equipment_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    equipment_type: Mapped[str | None] = mapped_column(String(128), index=True)

    metric: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))

    # When the sensor actually recorded this value — distinct from
    # created_at (TimestampMixin), which is when the row was ingested.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
