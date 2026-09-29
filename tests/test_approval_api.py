import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.diagnosis import Diagnosis, DiagnosisSeverity, DiagnosisStatus
from tests.helpers import create_user


async def _register(
    client: AsyncClient, username: str, tenant_id: str, role: str = "technician"
) -> dict:
    return await create_user(client, username, tenant_id, role)


async def _make_diagnosis(
    db_session: AsyncSession,
    *,
    tenant_id: str = "acme",
    requires_approval: bool = True,
    user_id: uuid.UUID | None = None,
) -> Diagnosis:
    conversation = Conversation(tenant_id=tenant_id, user_id=uuid.uuid4(), title="test")
    db_session.add(conversation)
    await db_session.flush()

    diagnosis = Diagnosis(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        user_id=user_id or uuid.uuid4(),
        question="Why is it hot?",
        status=DiagnosisStatus.completed,
        summary="Test summary",
        confidence=0.6,
        severity=DiagnosisSeverity.high,
        requires_human_approval=requires_approval,
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5-20251001",
    )
    db_session.add(diagnosis)
    await db_session.commit()
    await db_session.refresh(diagnosis)
    return diagnosis


async def test_technician_cannot_approve(client: AsyncClient, db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    tech = await _register(client, "tech_a", "acme", role="technician")

    response = await client.post(
        f"/api/v1/diagnoses/{diagnosis.id}/approve",
        headers={"Authorization": f"Bearer {tech['access_token']}"},
        json={},
    )
    assert response.status_code == 403


async def test_supervisor_can_approve(client: AsyncClient, db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    supervisor = await _register(client, "super_a", "acme", role="supervisor")

    response = await client.post(
        f"/api/v1/diagnoses/{diagnosis.id}/approve",
        headers={"Authorization": f"Bearer {supervisor['access_token']}"},
        json={"comments": "Looks good."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approval"]["decision"] == "approved"
    assert body["approval"]["comments"] == "Looks good."


async def test_admin_can_reject(client: AsyncClient, db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    admin = await _register(client, "admin_a", "acme", role="admin")

    response = await client.post(
        f"/api/v1/diagnoses/{diagnosis.id}/reject",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
        json={"comments": "Not convincing."},
    )
    assert response.status_code == 200
    assert response.json()["approval"]["decision"] == "rejected"


async def test_cannot_approve_twice_via_api(client: AsyncClient, db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    supervisor = await _register(client, "super_a", "acme", role="supervisor")
    headers = {"Authorization": f"Bearer {supervisor['access_token']}"}

    first = await client.post(f"/api/v1/diagnoses/{diagnosis.id}/approve", headers=headers, json={})
    assert first.status_code == 200

    second = await client.post(f"/api/v1/diagnoses/{diagnosis.id}/reject", headers=headers, json={})
    assert second.status_code == 409


async def test_approve_nonexistent_diagnosis_404(client: AsyncClient) -> None:
    supervisor = await _register(client, "super_a", "acme", role="supervisor")
    response = await client.post(
        f"/api/v1/diagnoses/{uuid.uuid4()}/approve",
        headers={"Authorization": f"Bearer {supervisor['access_token']}"},
        json={},
    )
    assert response.status_code == 404


async def test_approve_cross_tenant_diagnosis_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    diagnosis = await _make_diagnosis(db_session, tenant_id="acme")
    supervisor = await _register(client, "super_b", "globex", role="supervisor")

    response = await client.post(
        f"/api/v1/diagnoses/{diagnosis.id}/approve",
        headers={"Authorization": f"Bearer {supervisor['access_token']}"},
        json={},
    )
    assert response.status_code == 404


async def test_pending_approval_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    pending = await _make_diagnosis(db_session, requires_approval=True)
    not_required = await _make_diagnosis(db_session, requires_approval=False)
    supervisor = await _register(client, "super_a", "acme", role="supervisor")
    headers = {"Authorization": f"Bearer {supervisor['access_token']}"}

    # decide the "not required" one too, to prove pending filter also
    # excludes already-decided diagnoses regardless of the approval flag
    await client.post(f"/api/v1/diagnoses/{not_required.id}/approve", headers=headers, json={})

    all_diagnoses = await client.get("/api/v1/diagnoses", headers=headers)
    pending_only = await client.get(
        "/api/v1/diagnoses", headers=headers, params={"pending_approval": "true"}
    )

    assert len(all_diagnoses.json()) == 2
    pending_ids = {d["id"] for d in pending_only.json()}
    assert pending_ids == {str(pending.id)}


async def test_audit_logs_endpoint_requires_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    diagnosis = await _make_diagnosis(db_session)
    supervisor = await _register(client, "super_a", "acme", role="supervisor")
    admin = await _register(client, "admin_a", "acme", role="admin")

    await client.post(
        f"/api/v1/diagnoses/{diagnosis.id}/approve",
        headers={"Authorization": f"Bearer {supervisor['access_token']}"},
        json={},
    )

    supervisor_attempt = await client.get(
        "/api/v1/audit-logs", headers={"Authorization": f"Bearer {supervisor['access_token']}"}
    )
    assert supervisor_attempt.status_code == 403

    admin_attempt = await client.get(
        "/api/v1/audit-logs", headers={"Authorization": f"Bearer {admin['access_token']}"}
    )
    assert admin_attempt.status_code == 200
    actions = [log["action"] for log in admin_attempt.json()]
    assert "diagnosis.approved" in actions


async def test_supervisor_cannot_decide_on_own_diagnosis(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    supervisor = await _register(client, "super_a", "acme", role="supervisor")
    own = await _make_diagnosis(db_session, user_id=uuid.UUID(supervisor["user"]["id"]))
    headers = {"Authorization": f"Bearer {supervisor['access_token']}"}

    for decision in ("approve", "reject"):
        response = await client.post(
            f"/api/v1/diagnoses/{own.id}/{decision}", headers=headers, json={}
        )
        assert response.status_code == 403
        assert "own diagnosis" in response.json()["detail"]

    # Nothing was recorded, so a different supervisor can still decide.
    other = await _register(client, "super_b", "acme", role="supervisor")
    response = await client.post(
        f"/api/v1/diagnoses/{own.id}/approve",
        headers={"Authorization": f"Bearer {other['access_token']}"},
        json={},
    )
    assert response.status_code == 200


async def test_concurrent_decision_losing_the_race_returns_409_not_500(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    """Simulates two decisions arriving at the same moment: the second one's
    "already decided?" check runs before the first one's row exists, so only
    the unique constraint on approvals.diagnosis_id can stop it."""
    from app.services import approval_service

    diagnosis = await _make_diagnosis(db_session)
    first = await _register(client, "super_a", "acme", role="supervisor")
    second = await _register(client, "super_b", "acme", role="supervisor")

    response = await client.post(
        f"/api/v1/diagnoses/{diagnosis.id}/approve",
        headers={"Authorization": f"Bearer {first['access_token']}"},
        json={},
    )
    assert response.status_code == 200

    real_get_approval = approval_service.get_approval
    calls = {"n": 0}

    async def stale_first_check(db, *, diagnosis_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # the racing request didn't see the first decision yet
        return await real_get_approval(db, diagnosis_id=diagnosis_id)

    monkeypatch.setattr(approval_service, "get_approval", stale_first_check)

    racing = await client.post(
        f"/api/v1/diagnoses/{diagnosis.id}/reject",
        headers={"Authorization": f"Bearer {second['access_token']}"},
        json={},
    )
    assert racing.status_code == 409
    assert "already approved" in racing.json()["detail"]


async def test_diagnosis_response_names_who_requested_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    supervisor = await _register(client, "super_a", "acme", role="supervisor")
    own = await _make_diagnosis(db_session, user_id=uuid.UUID(supervisor["user"]["id"]))
    response = await client.get(
        f"/api/v1/diagnoses/{own.id}",
        headers={"Authorization": f"Bearer {supervisor['access_token']}"},
    )
    assert response.json()["requested_by_user_id"] == supervisor["user"]["id"]
