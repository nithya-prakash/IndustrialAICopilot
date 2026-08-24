import json
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.diagnosis_agent import run_diagnosis
from app.config import Settings
from app.llm.client import LLMError
from app.models.approval import ApprovalDecision
from app.models.conversation import Conversation
from app.models.diagnosis import Diagnosis, DiagnosisSeverity, DiagnosisStatus
from app.observability.metrics import (
    agent_tool_calls_total,
    approvals_total,
    diagnoses_total,
    llm_calls_total,
    llm_cost_usd_total,
    llm_tokens_total,
    record_llm_call,
)
from app.rag.generation import ModelToolCall, ModelTurn
from app.services.approval_service import approve_diagnosis
from app.tools.executor import ToolExecutionResult


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


async def test_metrics_endpoint_exposes_http_metrics(client: AsyncClient) -> None:
    await client.get("/api/v1/health")
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    # the health check itself should show up under its route template, not
    # a raw/unmatched path
    assert '/api/v1/health' in body


def test_record_llm_call_increments_calls_and_tokens() -> None:
    before_calls = _counter_value(
        llm_calls_total,
        provider="anthropic",
        model="test-model",
        operation="generation",
        status="success",
    )
    before_tokens_in = _counter_value(
        llm_tokens_total,
        provider="anthropic",
        model="test-model",
        operation="generation",
        token_type="input",
    )

    record_llm_call(
        provider="anthropic",
        model="test-model",
        operation="generation",
        status="success",
        duration_seconds=0.5,
        input_tokens=100,
        output_tokens=40,
    )

    assert (
        _counter_value(
            llm_calls_total,
            provider="anthropic",
            model="test-model",
            operation="generation",
            status="success",
        )
        == before_calls + 1
    )
    assert (
        _counter_value(
            llm_tokens_total,
            provider="anthropic",
            model="test-model",
            operation="generation",
            token_type="input",
        )
        == before_tokens_in + 100
    )


def test_record_llm_call_cost_is_zero_by_default() -> None:
    before = _counter_value(
        llm_cost_usd_total, provider="anthropic", model="no-cost-configured", operation="generation"
    )

    record_llm_call(
        provider="anthropic",
        model="no-cost-configured",
        operation="generation",
        status="success",
        duration_seconds=0.1,
        input_tokens=1000,
        output_tokens=1000,
    )

    # settings default *_cost_per_1k_usd to 0.0, so cost tracking is a no-op
    # unless a real rate is configured — see app/config.py.
    assert (
        _counter_value(
            llm_cost_usd_total,
            provider="anthropic",
            model="no-cost-configured",
            operation="generation",
        )
        == before
    )


def test_record_llm_call_computes_cost_when_configured(monkeypatch) -> None:
    configured = Settings(
        anthropic_input_cost_per_1k_usd=1.0, anthropic_output_cost_per_1k_usd=2.0
    )
    monkeypatch.setattr("app.observability.metrics.get_settings", lambda: configured)

    before = _counter_value(
        llm_cost_usd_total, provider="anthropic", model="priced-model", operation="generation"
    )

    record_llm_call(
        provider="anthropic",
        model="priced-model",
        operation="generation",
        status="success",
        duration_seconds=0.1,
        input_tokens=1000,
        output_tokens=1000,
    )

    # 1000 input tokens @ $1.0/1k + 1000 output tokens @ $2.0/1k = $3.00
    after = _counter_value(
        llm_cost_usd_total, provider="anthropic", model="priced-model", operation="generation"
    )
    assert after == before + 3.0


def _diagnosis_json(*, causes=None, severity="low") -> str:
    return json.dumps(
        {
            "summary": "Test summary.",
            "visual_observations": [],
            "sensor_findings": [],
            "possible_causes": causes or [],
            "recommended_checks": [],
            "recommended_action": "Test action.",
            "severity": severity,
            "limitations": [],
        }
    )


class ScriptedModel:
    def __init__(self, turns: list[ModelTurn]):
        self._turns = turns
        self.call_count = 0

    async def __call__(self, messages: list[dict], system: str) -> ModelTurn:
        turn = self._turns[self.call_count]
        self.call_count += 1
        return turn


class RaisingModel:
    async def __call__(self, messages: list[dict], system: str) -> ModelTurn:
        raise LLMError("No Anthropic API key configured")


async def test_run_diagnosis_records_tool_call_and_diagnosis_metrics(
    db_session: AsyncSession, monkeypatch
) -> None:
    tool_call = ModelToolCall(id="call_1", name="calculate", input={"expression": "1+1"})
    model = ScriptedModel(
        [
            ModelTurn(stop_reason="tool_use", text="", tool_calls=[tool_call]),
            ModelTurn(stop_reason="end_turn", text=_diagnosis_json()),
        ]
    )

    async def fake_execute_tool(name, tool_input, ctx):
        return ToolExecutionResult(output={"result": 2})

    monkeypatch.setattr("app.agents.diagnosis_agent.execute_tool", fake_execute_tool)

    before_tool_calls = _counter_value(agent_tool_calls_total, tool="calculate", status="success")
    before_diagnoses = _counter_value(diagnoses_total, status="completed", severity="low")

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="Why is the motor overheating?",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.completed
    assert (
        _counter_value(agent_tool_calls_total, tool="calculate", status="success")
        == before_tool_calls + 1
    )
    assert (
        _counter_value(diagnoses_total, status="completed", severity="low") == before_diagnoses + 1
    )


async def test_run_diagnosis_failure_records_failed_diagnosis_metric(
    db_session: AsyncSession,
) -> None:
    before = _counter_value(diagnoses_total, status="failed", severity="low")

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="Why is the motor overheating?",
        model_call=RaisingModel(),
    )

    assert diagnosis.status == DiagnosisStatus.failed
    assert _counter_value(diagnoses_total, status="failed", severity="low") == before + 1


async def test_approve_diagnosis_records_approval_metric(db_session: AsyncSession) -> None:
    conversation = Conversation(tenant_id="acme", user_id=uuid.uuid4(), title="test")
    db_session.add(conversation)
    await db_session.flush()

    diagnosis = Diagnosis(
        tenant_id="acme",
        conversation_id=conversation.id,
        user_id=uuid.uuid4(),
        question="Why is it hot?",
        status=DiagnosisStatus.completed,
        summary="Test summary",
        confidence=0.6,
        severity=DiagnosisSeverity.high,
        requires_human_approval=True,
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5-20251001",
    )
    db_session.add(diagnosis)
    await db_session.commit()
    await db_session.refresh(diagnosis)

    before = _counter_value(approvals_total, decision=ApprovalDecision.approved.value)

    await approve_diagnosis(
        db_session,
        tenant_id="acme",
        diagnosis_id=diagnosis.id,
        supervisor_id=uuid.uuid4(),
        comments="Confirmed.",
    )

    assert _counter_value(approvals_total, decision=ApprovalDecision.approved.value) == before + 1
