"""Seeds Equipment + MaintenanceTask rows for the demo equipment used
throughout this project's sample data (MOTOR-001, PUMP-001, CONVEYOR-001) —
so the get_maintenance_schedule tool has something real to query.

    docker compose run --rm backend python scripts/seed_equipment_data.py [tenant_id]

Idempotent: skips a piece of equipment that already exists for the tenant.
Defaults to the "evaluation" tenant, matching the other seed scripts.
"""
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.equipment_service import (  # noqa: E402
    add_maintenance_task,
    create_equipment,
    get_equipment,
)

NOW = datetime.now(UTC)

EQUIPMENT = [
    {
        "equipment_id": "MOTOR-001",
        "equipment_type": "electric_motor",
        "name": "Line 3 drive motor",
        "tasks": [
            {"task_name": "Bearing inspection", "interval_days": 90, "days_since": 45},
            {"task_name": "Lubrication", "interval_days": 30, "days_since": 40},  # overdue
            {"task_name": "Vibration analysis", "interval_days": 60, "days_since": 20},
        ],
    },
    {
        "equipment_id": "PUMP-001",
        "equipment_type": "industrial_pump",
        "name": "Cooling loop pump",
        "tasks": [
            {"task_name": "Seal inspection", "interval_days": 120, "days_since": 30},
            {"task_name": "Impeller check", "interval_days": 180, "days_since": 60},
        ],
    },
    {
        "equipment_id": "CONVEYOR-001",
        "equipment_type": "conveyor_system",
        "name": "Packaging line conveyor",
        "tasks": [
            {"task_name": "Belt tension check", "interval_days": 30, "days_since": 10},
            {"task_name": "Motor current check", "interval_days": 45, "days_since": 50},  # overdue
        ],
    },
]


async def main(tenant_id: str) -> None:
    async with AsyncSessionLocal() as db:
        for item in EQUIPMENT:
            existing = await get_equipment(
                db, tenant_id=tenant_id, equipment_id=item["equipment_id"]
            )
            if existing is not None:
                print(f"skip {item['equipment_id']}: already exists for {tenant_id!r}")
                continue

            await create_equipment(
                db,
                tenant_id=tenant_id,
                equipment_id=item["equipment_id"],
                equipment_type=item["equipment_type"],
                name=item["name"],
            )
            for task in item["tasks"]:
                await add_maintenance_task(
                    db,
                    tenant_id=tenant_id,
                    equipment_id=item["equipment_id"],
                    task_name=task["task_name"],
                    interval_days=task["interval_days"],
                    last_performed_at=NOW - timedelta(days=task["days_since"]),
                )
            print(f"seeded {item['equipment_id']} with {len(item['tasks'])} maintenance tasks")


if __name__ == "__main__":
    tenant = sys.argv[1] if len(sys.argv) > 1 else "evaluation"
    asyncio.run(main(tenant))
