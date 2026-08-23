import csv
import io
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sensor import SensorReading

# Illustrative units, not a spec sheet. Deliberately not exhaustive: a unit
# is only listed here for a metric the sample data actually uses.
DEFAULT_UNITS = {
    "temperature": "C",
    "vibration_rms": "mm/s",
    "rpm": "rpm",
    "pressure": "bar",
}

# Only vibration_rms has a fixed threshold here, because it's the one metric
# the synthetic sample manual (data/manuals/electric_motor_manual.pdf,
# "Troubleshooting > Excessive vibration") states an explicit number for:
# "Vibration RMS values above 4.5 mm/s ... generally warrant further
# investigation." No fixed threshold is invented for the other metrics —
# anomaly detection for those relies on statistical baseline comparison
# instead of a fabricated "safe range".
ILLUSTRATIVE_THRESHOLDS: dict[str, dict] = {
    "vibration_rms": {
        "max": 4.5,
        "min": None,
        "source": "electric_motor_manual.pdf, Troubleshooting > Excessive vibration",
    },
}


class InvalidSensorDataError(Exception):
    pass


async def ingest_snapshot(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    tenant_id: str,
    equipment_id: str,
    equipment_type: str | None,
    readings: dict[str, float],
    recorded_at: datetime,
) -> list[SensorReading]:
    if not readings:
        raise InvalidSensorDataError("At least one metric reading is required")

    rows = []
    for metric, value in readings.items():
        row = SensorReading(
            tenant_id=tenant_id,
            owner_id=owner_id,
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            metric=metric,
            value=float(value),
            unit=DEFAULT_UNITS.get(metric),
            recorded_at=recorded_at,
        )
        db.add(row)
        rows.append(row)

    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


async def bulk_ingest_csv(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    tenant_id: str,
    equipment_id: str,
    equipment_type: str | None,
    csv_bytes: bytes,
) -> int:
    """Expects a wide-format CSV: a `timestamp` column plus one column per
    metric (e.g. temperature,vibration_rms,rpm,pressure). Used by the
    sample-data seed script for historical/demo data — not exposed as a
    public upload endpoint (see docs/architecture-decisions.md for why)."""
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    if reader.fieldnames is None or "timestamp" not in reader.fieldnames:
        raise InvalidSensorDataError("CSV must have a 'timestamp' column")

    metric_columns = [c for c in reader.fieldnames if c != "timestamp"]
    rows = []
    for line in reader:
        recorded_at = datetime.fromisoformat(line["timestamp"])
        for metric in metric_columns:
            raw_value = line.get(metric)
            if raw_value in (None, ""):
                continue
            rows.append(
                SensorReading(
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    equipment_id=equipment_id,
                    equipment_type=equipment_type,
                    metric=metric,
                    value=float(raw_value),
                    unit=DEFAULT_UNITS.get(metric),
                    recorded_at=recorded_at,
                )
            )

    db.add_all(rows)
    await db.commit()
    return len(rows)


async def query_sensor_history(
    db: AsyncSession,
    *,
    tenant_id: str,
    equipment_id: str,
    metric: str,
    start_time: datetime,
    end_time: datetime,
) -> list[SensorReading]:
    """This is the literal `query_sensor_history` tool the diagnosis agent
    (Phase 6) will call. Built and tested here as a plain function so the
    agent tool wrapper is a thin pass-through, not new logic."""
    result = await db.execute(
        select(SensorReading)
        .where(
            SensorReading.tenant_id == tenant_id,
            SensorReading.equipment_id == equipment_id,
            SensorReading.metric == metric,
            SensorReading.recorded_at >= start_time,
            SensorReading.recorded_at <= end_time,
        )
        .order_by(SensorReading.recorded_at)
    )
    return list(result.scalars().all())


async def list_known_metrics(db: AsyncSession, *, tenant_id: str, equipment_id: str) -> list[str]:
    result = await db.execute(
        select(SensorReading.metric)
        .where(SensorReading.tenant_id == tenant_id, SensorReading.equipment_id == equipment_id)
        .distinct()
    )
    return sorted(result.scalars().all())
