import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import list_audit_logs, log_event


async def test_log_event_creates_entry(db_session: AsyncSession) -> None:
    actor_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    entry = await log_event(
        db_session,
        tenant_id="acme",
        actor_user_id=actor_id,
        action="diagnosis.created",
        resource_type="diagnosis",
        resource_id=resource_id,
        detail={"confidence": 0.8},
    )
    await db_session.commit()

    assert entry.tenant_id == "acme"
    assert entry.actor_user_id == actor_id
    assert entry.resource_id == str(resource_id)
    assert entry.detail == {"confidence": 0.8}


async def test_log_event_without_detail_defaults_to_empty_dict(db_session: AsyncSession) -> None:
    entry = await log_event(
        db_session,
        tenant_id="acme",
        actor_user_id=None,
        action="system.event",
        resource_type="system",
        resource_id="n/a",
    )
    await db_session.commit()
    assert entry.detail == {}
    assert entry.actor_user_id is None


async def test_list_audit_logs_filters_by_tenant(db_session: AsyncSession) -> None:
    await log_event(
        db_session,
        tenant_id="acme",
        actor_user_id=None,
        action="document.uploaded",
        resource_type="document",
        resource_id=uuid.uuid4(),
    )
    await log_event(
        db_session,
        tenant_id="globex",
        actor_user_id=None,
        action="document.uploaded",
        resource_type="document",
        resource_id=uuid.uuid4(),
    )
    await db_session.commit()

    acme_logs = await list_audit_logs(db_session, tenant_id="acme")
    globex_logs = await list_audit_logs(db_session, tenant_id="globex")
    assert len(acme_logs) == 1
    assert len(globex_logs) == 1


async def test_list_audit_logs_filters_by_resource_type_and_id(db_session: AsyncSession) -> None:
    target_id = uuid.uuid4()
    await log_event(
        db_session,
        tenant_id="acme",
        actor_user_id=None,
        action="diagnosis.created",
        resource_type="diagnosis",
        resource_id=target_id,
    )
    await log_event(
        db_session,
        tenant_id="acme",
        actor_user_id=None,
        action="document.uploaded",
        resource_type="document",
        resource_id=uuid.uuid4(),
    )
    await db_session.commit()

    diagnosis_logs = await list_audit_logs(db_session, tenant_id="acme", resource_type="diagnosis")
    assert len(diagnosis_logs) == 1

    specific = await list_audit_logs(
        db_session, tenant_id="acme", resource_type="diagnosis", resource_id=target_id
    )
    assert len(specific) == 1
    assert specific[0].resource_id == str(target_id)


async def test_list_audit_logs_ordered_most_recent_first(db_session: AsyncSession) -> None:
    for i in range(3):
        await log_event(
            db_session,
            tenant_id="acme",
            actor_user_id=None,
            action=f"event.{i}",
            resource_type="test",
            resource_id=str(i),
        )
    await db_session.commit()

    logs = await list_audit_logs(db_session, tenant_id="acme")
    assert len(logs) == 3
    # Robust to same-microsecond ties on a fast sqlite test DB: descending
    # (or equal) created_at, not a hard-coded sequence.
    assert all(logs[i].created_at >= logs[i + 1].created_at for i in range(len(logs) - 1))
