"""Loads the synthetic sensor CSVs (data/sensors/*.csv) into Postgres for a
given tenant — generates them first via generate_sample_sensor_data if
missing. Idempotent: skips a file whose equipment_id already has readings
for that tenant.

    docker compose run --rm backend python scripts/seed_sensor_data.py [tenant_id]

Defaults to the "evaluation" tenant (same one the RAG evaluation harness
uses), so the same demo user/tenant has both manuals and sensor history.
"""
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import hash_password  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.sensor import SensorReading  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services.sensor_service import bulk_ingest_csv  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sensors"

EQUIPMENT = {
    "motor_001.csv": ("MOTOR-001", "electric_motor"),
    "pump_001.csv": ("PUMP-001", "industrial_pump"),
    "conveyor_001.csv": ("CONVEYOR-001", "conveyor_system"),
}


async def _ensure_user(tenant_id: str) -> User:
    username = f"sensor-seed-{tenant_id}"
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        user = User(
            username=username,
            email=f"{username}@example.com",
            hashed_password=hash_password(str(uuid.uuid4())),
            role=UserRole.admin,
            tenant_id=tenant_id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def main(tenant_id: str) -> None:
    if not _DATA_DIR.exists() or not any(_DATA_DIR.glob("*.csv")):
        from scripts.generate_sample_sensor_data import (
            generate_conveyor_001,
            generate_motor_001,
            generate_pump_001,
        )

        generate_motor_001()
        generate_pump_001()
        generate_conveyor_001()

    user = await _ensure_user(tenant_id)

    for filename, (equipment_id, equipment_type) in EQUIPMENT.items():
        path = _DATA_DIR / filename
        if not path.exists():
            print(f"skip {filename}: file not found")
            continue

        async with AsyncSessionLocal() as db:
            existing = await db.execute(
                select(SensorReading.id)
                .where(
                    SensorReading.tenant_id == tenant_id,
                    SensorReading.equipment_id == equipment_id,
                )
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                print(f"skip {filename}: {equipment_id} already has readings for {tenant_id!r}")
                continue

            count = await bulk_ingest_csv(
                db,
                owner_id=user.id,
                tenant_id=tenant_id,
                equipment_id=equipment_id,
                equipment_type=equipment_type,
                csv_bytes=path.read_bytes(),
            )
            print(f"loaded {count} readings for {equipment_id} ({tenant_id!r}) from {filename}")


if __name__ == "__main__":
    tenant = sys.argv[1] if len(sys.argv) > 1 else "evaluation"
    asyncio.run(main(tenant))
