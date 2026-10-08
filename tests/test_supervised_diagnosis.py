import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("langgraph")

from app.agents import supervised  # noqa: E402
from app.models.diagnosis import DiagnosisStatus  # noqa: E402
from app.tools.executor import ToolExecutionResult  # noqa: E402
from tests.test_supervisor_graph import CITE, FakeModel  # noqa: E402


@pytest.fixture(autouse=True)
def memory_checkpointer(monkeypatch):
    """Tests run on SQLite, so use an in-memory checkpointer shared across calls in a test."""
    from langgraph.checkpoint.memory import MemorySaver

    saver = MemorySaver()

    async def get(db=None):
        return saver

    monkeypatch.setattr(supervised, "get_checkpointer", get)


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

    monkeypatch.setattr(supervised, "call_model", FakeModel([]))
    resumed = await supervised.resume_if_paused(
        db_session, tenant_id="acme", diagnosis_id=diagnosis.id, decision="approved", reviewer="u"
    )
    assert resumed is True
    # Already resumed, and a diagnosis that never paused, both report False.
    again = await supervised.resume_if_paused(
        db_session, tenant_id="acme", diagnosis_id=diagnosis.id, decision="approved", reviewer="u"
    )
    unknown = await supervised.resume_if_paused(
        db_session, tenant_id="acme", diagnosis_id=uuid.uuid4(), decision="approved", reviewer="u"
    )
    assert again is False and unknown is False


async def test_paused_approval_survives_a_new_graph_instance(db_session: AsyncSession, monkeypatch):
    """The thread id is the diagnosis id and state lives in the checkpointer, so a fresh process
    (a new graph object over the same store) can resume a pause it never created."""

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
    graph = supervised._graph(
        db_session, "acme", None, await supervised.get_checkpointer(db_session)
    )
    state = await graph.aget_state({"configurable": {"thread_id": str(diagnosis.id)}})
    assert state.next == ("approval_gate",)


async def test_supervisor_path_emits_run_tool_specialist_and_diagnosis_metrics(
    db_session: AsyncSession, monkeypatch
):
    from app.observability import metrics as m

    async def fake_execute(name, tool_input, ctx):
        return ToolExecutionResult(
            output={}, citations=[CITE], evidence=[{"type": "document_chunk", "citation": CITE}]
        )

    monkeypatch.setattr(supervised, "execute_tool", fake_execute)

    tool = m.agent_tool_calls_total.labels(tool="search_technical_documents", status="success")
    runs = m.agent_run_duration_seconds.labels(orchestrator="supervisor", status="completed")
    spec = m.agent_specialist_duration_seconds.labels(specialist="documents")
    done = m.diagnoses_total.labels(status="completed", severity="high")
    before = (tool._value.get(), runs._sum.get(), spec._sum.get(), done._value.get())

    await supervised.run_supervised_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="Why hot?",
        model_call=FakeModel(["documents", "synthesize"]),
    )
    assert tool._value.get() == before[0] + 1
    assert runs._sum.get() > before[1] and spec._sum.get() > before[2]
    assert done._value.get() == before[3] + 1


async def test_checkpointer_choice_follows_the_live_database_not_the_url_setting(
    db_session: AsyncSession, monkeypatch
):
    """Regression: tests run on SQLite while DATABASE_URL points at an unreachable Postgres. The
    checkpointer must be chosen from the session's own dialect, so no connection is attempted."""
    from langgraph.checkpoint.memory import MemorySaver

    from app.agents import checkpointing

    settings = checkpointing.get_settings()
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://x:y@127.0.0.1:1/none")
    monkeypatch.setattr(settings, "checkpoint_backend", "auto")
    checkpointing._savers.clear()
    saver = await checkpointing.get_checkpointer(db_session)
    assert isinstance(saver, MemorySaver)
    checkpointing._savers.clear()
