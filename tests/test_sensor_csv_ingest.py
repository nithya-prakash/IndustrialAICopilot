import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sensor import SensorReading
from app.services.sensor_service import InvalidSensorDataError, bulk_ingest_csv

SAMPLE_CSV = (
    "timestamp,temperature,vibration_rms,rpm\n"
    "2026-08-10T00:00:00+00:00,58.1,2.0,1480\n"
    "2026-08-10T01:00:00+00:00,58.4,2.1,1479\n"
    "2026-08-10T02:00:00+00:00,,2.3,1481\n"  # missing temperature value on this row
)


async def test_bulk_ingest_csv_creates_one_row_per_metric_per_timestamp(
    db_session: AsyncSession,
) -> None:
    owner_id = uuid.uuid4()
    count = await bulk_ingest_csv(
        db_session,
        owner_id=owner_id,
        tenant_id="acme",
        equipment_id="MOTOR-001",
        equipment_type="electric_motor",
        csv_bytes=SAMPLE_CSV.encode(),
    )
    # 3 rows * 3 metrics = 9, minus the one missing temperature value = 8
    assert count == 8

    result = await db_session.execute(
        select(SensorReading).where(SensorReading.metric == "temperature")
    )
    temps = result.scalars().all()
    assert len(temps) == 2  # only 2 of 3 rows had a temperature value


async def test_bulk_ingest_csv_missing_timestamp_column_raises(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidSensorDataError):
        await bulk_ingest_csv(
            db_session,
            owner_id=uuid.uuid4(),
            tenant_id="acme",
            equipment_id="MOTOR-001",
            equipment_type=None,
            csv_bytes=b"temperature,vibration_rms\n58.1,2.0\n",
        )


async def test_bulk_ingest_csv_sets_unit_from_known_metric_names(
    db_session: AsyncSession,
) -> None:
    await bulk_ingest_csv(
        db_session,
        owner_id=uuid.uuid4(),
        tenant_id="acme",
        equipment_id="MOTOR-001",
        equipment_type=None,
        csv_bytes=SAMPLE_CSV.encode(),
    )
    result = await db_session.execute(
        select(SensorReading).where(SensorReading.metric == "vibration_rms").limit(1)
    )
    reading = result.scalar_one()
    assert reading.unit == "mm/s"
