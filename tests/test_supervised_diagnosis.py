import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("langgraph")

from app.agents import supervised  # noqa: E402
from app.models.diagnosis import DiagnosisStatus  # noqa: E402
from app.tools.executor import ToolExecutionResult  # noqa: E402
from tests.test_supervisor_graph import CITE, FakeModel  # noqa: E402


async def test_supervised_diagnosis_persists_and_resumes(db_session: AsyncSession, monkeypatch):
    async def fake_execute(name, tool_input, ctx):
        return ToolExecutionResult(
            output={}, citations=[CITE], evidence=[{"type": "document_chunk", "citation": CITE}]
        )

    monkeypatch.setattr(supervised, "execute_tool", fake_execute)
    monkeypatch.setattr(supervised.get_settings(), "confidence_approval_threshold", 0.99)

    diagnosis = await supervised.run_supervised_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="Why hot?",
        model_call=FakeModel(["documents", "synthesize"]),
    )
    assert diagnosis.status == DiagnosisStatus.completed
    assert diagnosis.requires_human_approval is True
    assert diagnosis.possible_causes[0]["supporting_citations"] == [CITE]
    assert diagnosis.id in supervised._paused_threads

    monkeypatch.setattr(supervised, "call_model", FakeModel([]))
    resumed = await supervised.resume_if_paused(
        db_session, tenant_id="acme", diagnosis_id=diagnosis.id, decision="approved", reviewer="u"
    )
    assert resumed is True
    assert diagnosis.id not in supervised._paused_threads
