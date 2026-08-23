import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalDecision
from app.models.conversation import Conversation
from app.models.diagnosis import Diagnosis, DiagnosisSeverity, DiagnosisStatus
from app.services.approval_service import (
    AlreadyDecidedError,
    DiagnosisNotCompletedError,
    DiagnosisNotFoundError,
    approve_diagnosis,
    get_approval,
    reject_diagnosis,
)


async def _make_diagnosis(
    db_session: AsyncSession, *, tenant_id: str = "acme", status=DiagnosisStatus.completed
) -> Diagnosis:
    conversation = Conversation(tenant_id=tenant_id, user_id=uuid.uuid4(), title="test")
    db_session.add(conversation)
    await db_session.flush()

    diagnosis = Diagnosis(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        user_id=uuid.uuid4(),
        question="Why is it hot?",
        status=status,
        summary="Test summary" if status == DiagnosisStatus.completed else None,
        confidence=0.6,
        severity=DiagnosisSeverity.high,
        requires_human_approval=True,
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5-20251001",
    )
    db_session.add(diagnosis)
    await db_session.commit()
    await db_session.refresh(diagnosis)
    return diagnosis


async def test_approve_diagnosis_creates_approval_record(db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    supervisor_id = uuid.uuid4()

    approval = await approve_diagnosis(
        db_session,
        tenant_id="acme",
        diagnosis_id=diagnosis.id,
        supervisor_id=supervisor_id,
        comments="Looks correct.",
    )

    assert approval.decision == ApprovalDecision.approved
    assert approval.supervisor_id == supervisor_id
    assert approval.comments == "Looks correct."


async def test_reject_diagnosis_creates_approval_record(db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    approval = await reject_diagnosis(
        db_session,
        tenant_id="acme",
        diagnosis_id=diagnosis.id,
        supervisor_id=uuid.uuid4(),
        comments="Not enough evidence.",
    )
    assert approval.decision == ApprovalDecision.rejected


async def test_cannot_decide_twice(db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    await approve_diagnosis(
        db_session, tenant_id="acme", diagnosis_id=diagnosis.id, supervisor_id=uuid.uuid4()
    )

    with pytest.raises(AlreadyDecidedError):
        await reject_diagnosis(
            db_session, tenant_id="acme", diagnosis_id=diagnosis.id, supervisor_id=uuid.uuid4()
        )


async def test_cannot_decide_on_nonexistent_diagnosis(db_session: AsyncSession) -> None:
    with pytest.raises(DiagnosisNotFoundError):
        await approve_diagnosis(
            db_session, tenant_id="acme", diagnosis_id=uuid.uuid4(), supervisor_id=uuid.uuid4()
        )


async def test_cannot_decide_on_diagnosis_from_another_tenant(db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session, tenant_id="acme")
    with pytest.raises(DiagnosisNotFoundError):
        await approve_diagnosis(
            db_session, tenant_id="globex", diagnosis_id=diagnosis.id, supervisor_id=uuid.uuid4()
        )


async def test_cannot_decide_on_failed_diagnosis(db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session, status=DiagnosisStatus.failed)
    with pytest.raises(DiagnosisNotCompletedError):
        await approve_diagnosis(
            db_session, tenant_id="acme", diagnosis_id=diagnosis.id, supervisor_id=uuid.uuid4()
        )


async def test_get_approval_returns_none_when_undecided(db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    assert await get_approval(db_session, diagnosis_id=diagnosis.id) is None


async def test_get_approval_returns_decision_after_approval(db_session: AsyncSession) -> None:
    diagnosis = await _make_diagnosis(db_session)
    await approve_diagnosis(
        db_session, tenant_id="acme", diagnosis_id=diagnosis.id, supervisor_id=uuid.uuid4()
    )
    approval = await get_approval(db_session, diagnosis_id=diagnosis.id)
    assert approval is not None
    assert approval.decision == ApprovalDecision.approved
