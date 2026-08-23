from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment, MaintenanceTask


@dataclass
class MaintenanceTaskStatus:
    task_name: str
    interval_days: int
    last_performed_at: datetime | None
    next_due_at: datetime | None
    days_until_due: int | None
    is_overdue: bool


async def get_equipment(db: AsyncSession, *, tenant_id: str, equipment_id: str) -> Equipment | None:
    result = await db.execute(
        select(Equipment).where(
            Equipment.tenant_id == tenant_id, Equipment.equipment_id == equipment_id
        )
    )
    return result.scalar_one_or_none()


async def create_equipment(
    db: AsyncSession,
    *,
    tenant_id: str,
    equipment_id: str,
    equipment_type: str,
    name: str | None = None,
    notes: str | None = None,
) -> Equipment:
    record = Equipment(
        tenant_id=tenant_id,
        equipment_id=equipment_id,
        equipment_type=equipment_type,
        name=name,
        notes=notes,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def add_maintenance_task(
    db: AsyncSession,
    *,
    tenant_id: str,
    equipment_id: str,
    task_name: str,
    interval_days: int,
    last_performed_at: datetime | None = None,
    notes: str | None = None,
) -> MaintenanceTask:
    task = MaintenanceTask(
        tenant_id=tenant_id,
        equipment_id=equipment_id,
        task_name=task_name,
        interval_days=interval_days,
        last_performed_at=last_performed_at,
        notes=notes,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def get_maintenance_schedule(
    db: AsyncSession, *, tenant_id: str, equipment_id: str
) -> list[MaintenanceTaskStatus]:
    """This is the literal `get_maintenance_schedule` agent tool — built as
    a plain function here so the tool wrapper is a thin pass-through."""
    result = await db.execute(
        select(MaintenanceTask).where(
            MaintenanceTask.tenant_id == tenant_id, MaintenanceTask.equipment_id == equipment_id
        )
    )
    tasks = result.scalars().all()

    now = datetime.now(UTC)
    statuses = []
    for task in tasks:
        next_due_at = None
        days_until_due = None
        is_overdue = False
        if task.last_performed_at is not None:
            # SQLite (used by the unit test DB) doesn't preserve tz-awareness
            # on DateTime(timezone=True) round-trips the way Postgres does —
            # normalize defensively rather than assume the DB backend kept it.
            last_performed = task.last_performed_at
            if last_performed.tzinfo is None:
                last_performed = last_performed.replace(tzinfo=UTC)
            next_due_at = last_performed + timedelta(days=task.interval_days)
            days_until_due = (next_due_at - now).days
            is_overdue = days_until_due < 0

        statuses.append(
            MaintenanceTaskStatus(
                task_name=task.task_name,
                interval_days=task.interval_days,
                last_performed_at=task.last_performed_at,
                next_due_at=next_due_at,
                days_until_due=days_until_due,
                is_overdue=is_overdue,
            )
        )
    return statuses


async def list_equipment_ids(db: AsyncSession, *, tenant_id: str) -> list[str]:
    result = await db.execute(
        select(Equipment.equipment_id).where(Equipment.tenant_id == tenant_id)
    )
    return list(result.scalars().all())
