import hashlib
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval, ApprovalDecision
from app.models.conversation import Conversation
from app.models.diagnosis import Diagnosis, DiagnosisSeverity, DiagnosisStatus
from app.services.incident_memory import search_past_incidents
from app.tools.executor import ToolContext, execute_tool


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic bag-of-words hashing embedding, L2-normalised (hermetic, no model download)."""
    out = []
    for text in texts:
        vec = [0.0] * 64
        for word in text.lower().replace(".", " ").replace(";", " ").split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        out.append([v / norm for v in vec])
    return out


async def _diagnosis(db, *, tenant, equipment, question, summary, cause, decision):
    conversation = Conversation(tenant_id=tenant, user_id=uuid.uuid4(), title=question[:50])
    db.add(conversation)
    await db.flush()
    d = Diagnosis(
        tenant_id=tenant,
        conversation_id=conversation.id,
        user_id=uuid.uuid4(),
        equipment_id=equipment,
        question=question,
        status=DiagnosisStatus.completed,
        summary=summary,
        possible_causes=[{"cause": cause, "rank": 1, "supporting_citations": []}],
        recommended_action="Replace the bearing",
        confidence=0.7,
        severity=DiagnosisSeverity.high,
        requires_human_approval=True,
        llm_provider="test",
        llm_model="test",
    )
    db.add(d)
    await db.flush()
    if decision is not None:
        db.add(
            Approval(
                tenant_id=tenant, diagnosis_id=d.id, supervisor_id=uuid.uuid4(), decision=decision
            )
        )
    await db.commit()
    return d


async def test_only_approved_same_tenant_incidents_are_remembered(db_session: AsyncSession):
    ok = await _diagnosis(
        db_session,
        tenant="acme",
        equipment="MOTOR-047",
        question="Grinding noise and vibration on the motor",
        summary="Bearing failure causing grinding noise",
        cause="Worn bearing",
        decision=ApprovalDecision.approved,
    )
    await _diagnosis(
        db_session,
        tenant="acme",
        equipment="MOTOR-047",
        question="Grinding noise from the motor",
        summary="Bearing noise",
        cause="Worn bearing",
        decision=ApprovalDecision.rejected,
    )
    await _diagnosis(
        db_session,
        tenant="acme",
        equipment="MOTOR-047",
        question="Grinding noise from the motor",
        summary="Bearing noise",
        cause="Worn bearing",
        decision=None,
    )
    await _diagnosis(
        db_session,
        tenant="other",
        equipment="MOTOR-047",
        question="Grinding noise from the motor",
        summary="Bearing noise",
        cause="Worn bearing",
        decision=ApprovalDecision.approved,
    )

    found = await search_past_incidents(
        db_session, tenant_id="acme", query="grinding noise bearing", embed=fake_embed
    )
    assert [i.diagnosis_id for i in found] == [ok.id]


async def test_ranking_is_semantic_and_same_equipment_gets_a_bonus(db_session: AsyncSession):
    bearing = await _diagnosis(
        db_session,
        tenant="acme",
        equipment="MOTOR-001",
        question="Grinding noise",
        summary="Bearing wear grinding noise",
        cause="Worn bearing",
        decision=ApprovalDecision.approved,
    )
    await _diagnosis(
        db_session,
        tenant="acme",
        equipment="MOTOR-001",
        question="Pump leaking oil",
        summary="Seal failure leaking oil",
        cause="Failed seal",
        decision=ApprovalDecision.approved,
    )
    found = await search_past_incidents(
        db_session,
        tenant_id="acme",
        query="grinding noise worn bearing",
        equipment_id="MOTOR-001",
        embed=fake_embed,
    )
    assert found[0].diagnosis_id == bearing.id
    assert found[0].similarity > 0.4


async def test_no_history_or_empty_query_returns_nothing(db_session: AsyncSession):
    assert (
        await search_past_incidents(db_session, tenant_id="acme", query="x", embed=fake_embed) == []
    )
    await _diagnosis(
        db_session,
        tenant="acme",
        equipment="M",
        question="q",
        summary="s",
        cause="c",
        decision=ApprovalDecision.approved,
    )
    assert (
        await search_past_incidents(db_session, tenant_id="acme", query="  ", embed=fake_embed)
        == []
    )


async def test_tool_returns_citable_past_incident_evidence(db_session: AsyncSession, monkeypatch):
    from app.services import incident_memory

    monkeypatch.setattr(incident_memory, "embed_texts", fake_embed)
    monkeypatch.setattr(
        "app.tools.executor.search_past_incidents",
        lambda db, **kw: search_past_incidents(db, embed=fake_embed, **kw),
    )
    await _diagnosis(
        db_session,
        tenant="acme",
        equipment="MOTOR-047",
        question="Bearing failure grinding noise",
        summary="Bearing failure",
        cause="Worn bearing",
        decision=ApprovalDecision.approved,
    )
    result = await execute_tool(
        "search_past_incidents",
        {"query": "grinding noise bearing", "equipment_id": "MOTOR-047"},
        ToolContext(db=db_session, tenant_id="acme"),
    )
    assert result.error is None and result.evidence[0]["type"] == "past_incident"
    assert result.citations[0].startswith("[Past incident ") and "MOTOR-047" in result.citations[0]
    assert "not proof" in result.output["note"]
