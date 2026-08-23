from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.equipment_service import (
    add_maintenance_task,
    create_equipment,
    get_equipment,
    get_maintenance_schedule,
)


async def test_create_and_get_equipment(db_session: AsyncSession) -> None:
    await create_equipment(
        db_session,
        tenant_id="acme",
        equipment_id="MOTOR-001",
        equipment_type="electric_motor",
        name="Line 3 motor",
    )
    record = await get_equipment(db_session, tenant_id="acme", equipment_id="MOTOR-001")
    assert record is not None
    assert record.equipment_type == "electric_motor"


async def test_get_equipment_isolated_by_tenant(db_session: AsyncSession) -> None:
    await create_equipment(
        db_session, tenant_id="acme", equipment_id="MOTOR-001", equipment_type="electric_motor"
    )
    record = await get_equipment(db_session, tenant_id="globex", equipment_id="MOTOR-001")
    assert record is None


async def test_maintenance_schedule_with_no_tasks_is_empty(db_session: AsyncSession) -> None:
    statuses = await get_maintenance_schedule(
        db_session, tenant_id="acme", equipment_id="NOPE-001"
    )
    assert statuses == []


async def test_maintenance_task_overdue_detection(db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    await add_maintenance_task(
        db_session,
        tenant_id="acme",
        equipment_id="MOTOR-001",
        task_name="Lubrication",
        interval_days=30,
        last_performed_at=now - timedelta(days=45),  # overdue by 15 days
    )
    await add_maintenance_task(
        db_session,
        tenant_id="acme",
        equipment_id="MOTOR-001",
        task_name="Bearing inspection",
        interval_days=90,
        last_performed_at=now - timedelta(days=10),  # not due yet
    )

    statuses = await get_maintenance_schedule(
        db_session, tenant_id="acme", equipment_id="MOTOR-001"
    )
    by_name = {s.task_name: s for s in statuses}

    assert by_name["Lubrication"].is_overdue is True
    assert by_name["Bearing inspection"].is_overdue is False


async def test_maintenance_task_never_performed_has_no_due_date(db_session: AsyncSession) -> None:
    await add_maintenance_task(
        db_session,
        tenant_id="acme",
        equipment_id="MOTOR-001",
        task_name="Initial calibration",
        interval_days=365,
        last_performed_at=None,
    )
    statuses = await get_maintenance_schedule(
        db_session, tenant_id="acme", equipment_id="MOTOR-001"
    )
    assert statuses[0].next_due_at is None
    assert statuses[0].is_overdue is False


async def test_maintenance_schedule_isolated_by_tenant(db_session: AsyncSession) -> None:
    await add_maintenance_task(
        db_session,
        tenant_id="acme",
        equipment_id="MOTOR-001",
        task_name="Lubrication",
        interval_days=30,
    )
    statuses = await get_maintenance_schedule(
        db_session, tenant_id="globex", equipment_id="MOTOR-001"
    )
    assert statuses == []
