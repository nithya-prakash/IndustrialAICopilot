import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.diagnosis_agent import run_diagnosis
from app.llm.client import LLMError
from app.models.conversation import Message, MessageRole
from app.models.diagnosis import DiagnosisStatus
from app.rag.generation import ModelToolCall, ModelTurn
from app.tools.executor import ToolExecutionResult

VALID_CITATION = "[electric_motor_manual.pdf, Troubleshooting > Overheating, p.1]"
SENSOR_CITATION = "[MOTOR-001 sensor history, temperature, 2026-08-01 to 2026-08-02]"


def _diagnosis_json(
    *,
    summary="Test.",
    causes=None,
    severity="low",
    limitations=None,
    recommended_action="Test action.",
) -> str:
    return json.dumps(
        {
            "summary": summary,
            "visual_observations": [],
            "sensor_findings": [],
            "possible_causes": causes or [],
            "recommended_checks": [],
            "recommended_action": recommended_action,
            "severity": severity,
            "limitations": limitations or [],
        }
    )


class ScriptedModel:
    """Injectable fake for run_diagnosis(model_call=...) — returns each
    scripted ModelTurn in sequence, one per loop iteration."""

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


def _end_turn(json_text: str) -> ModelTurn:
    return ModelTurn(stop_reason="end_turn", text=json_text)


def _tool_use(*calls: ModelToolCall) -> ModelTurn:
    return ModelTurn(stop_reason="tool_use", text="", tool_calls=list(calls))


def _fake_execute_tool_factory(responses: dict[str, ToolExecutionResult]):
    async def fake_execute_tool(name, tool_input, ctx):
        return responses.get(name, ToolExecutionResult(output={}, error=f"unmocked tool {name}"))

    return fake_execute_tool


DIAGNOSIS_JSON_NO_CITATIONS = _diagnosis_json(
    summary="Motor appears to be overheating based on the question alone.",
    causes=[{"cause": "Blocked ventilation", "rank": 1, "supporting_citations": []}],
    limitations=["No documentation or sensor data was consulted."],
)


async def test_no_tool_calls_produces_low_confidence_diagnosis(db_session: AsyncSession) -> None:
    model = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="Why is the motor overheating?",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.completed
    assert diagnosis.confidence < 0.5
    assert diagnosis.requires_human_approval is True
    assert diagnosis.possible_causes[0]["supporting_citations"] == []


DIAGNOSIS_JSON_WITH_VALID_CITATION = _diagnosis_json(
    summary="Documentation points to blocked ventilation as a likely cause.",
    causes=[
        {"cause": "Blocked ventilation", "rank": 1, "supporting_citations": [VALID_CITATION]}
    ],
    severity="medium",
)


async def test_tool_evidence_is_cited_and_boosts_confidence(
    db_session: AsyncSession, monkeypatch
) -> None:
    search_call = ModelToolCall(
        id="call_1", name="search_technical_documents", input={"query": "overheating"}
    )
    model = ScriptedModel(
        [
            _tool_use(search_call),
            _end_turn(DIAGNOSIS_JSON_WITH_VALID_CITATION),
        ]
    )
    fake_execute = _fake_execute_tool_factory(
        {
            "search_technical_documents": ToolExecutionResult(
                output={"results": [{"citation": VALID_CITATION, "excerpt": "..."}]},
                citations=[VALID_CITATION],
                evidence=[{"type": "document_chunk", "citation": VALID_CITATION, "detail": "..."}],
            )
        }
    )
    monkeypatch.setattr("app.agents.diagnosis_agent.execute_tool", fake_execute)

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="Why is the motor overheating?",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.completed
    assert diagnosis.possible_causes[0]["supporting_citations"] == [VALID_CITATION]
    assert diagnosis.evidence[0]["citation"] == VALID_CITATION
    # cited evidence should score meaningfully higher than the no-evidence case
    assert diagnosis.confidence > 0.5


HALLUCINATED_CITATION = "[nonexistent_manual.pdf, Fake Section, p.99]"
DIAGNOSIS_JSON_WITH_HALLUCINATED_CITATION = _diagnosis_json(
    causes=[{"cause": "Some cause", "rank": 1, "supporting_citations": [HALLUCINATED_CITATION]}],
)


async def test_hallucinated_citation_is_dropped_not_trusted(
    db_session: AsyncSession, monkeypatch
) -> None:
    search_call = ModelToolCall(
        id="call_1", name="search_technical_documents", input={"query": "x"}
    )
    model = ScriptedModel(
        [
            _tool_use(search_call),
            _end_turn(DIAGNOSIS_JSON_WITH_HALLUCINATED_CITATION),
        ]
    )
    fake_execute = _fake_execute_tool_factory(
        {
            "search_technical_documents": ToolExecutionResult(
                output={"results": [{"citation": VALID_CITATION, "excerpt": "..."}]},
                citations=[VALID_CITATION],
                evidence=[{"type": "document_chunk", "citation": VALID_CITATION, "detail": "..."}],
            )
        }
    )
    monkeypatch.setattr("app.agents.diagnosis_agent.execute_tool", fake_execute)

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.possible_causes[0]["supporting_citations"] == []
    assert any("did not match any evidence" in limitation for limitation in diagnosis.limitations)


async def test_malformed_final_json_marks_diagnosis_failed(db_session: AsyncSession) -> None:
    model = ScriptedModel([_end_turn("this is not JSON at all")])

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.failed
    assert diagnosis.error_message is not None
    assert diagnosis.confidence == 0.0
    assert diagnosis.requires_human_approval is True


async def test_failed_diagnosis_still_retains_evidence_gathered_before_the_failure(
    db_session: AsyncSession, monkeypatch
) -> None:
    """A malformed final response shouldn't discard the record of what the
    agent actually tried before failing — the technician needs to see that,
    not just an error message."""
    search_call = ModelToolCall(
        id="call_1", name="search_technical_documents", input={"query": "overheating"}
    )
    model = ScriptedModel(
        [
            _tool_use(search_call),
            _end_turn("not valid json"),
        ]
    )
    fake_execute = _fake_execute_tool_factory(
        {
            "search_technical_documents": ToolExecutionResult(
                output={"results": [{"citation": VALID_CITATION, "excerpt": "..."}]},
                citations=[VALID_CITATION],
                evidence=[{"type": "document_chunk", "citation": VALID_CITATION, "detail": "..."}],
            )
        }
    )
    monkeypatch.setattr("app.agents.diagnosis_agent.execute_tool", fake_execute)

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.failed
    assert diagnosis.evidence == [
        {"type": "document_chunk", "citation": VALID_CITATION, "detail": "..."}
    ]
    assert len(diagnosis.tool_calls) == 1
    assert diagnosis.tool_calls[0]["tool"] == "search_technical_documents"


async def test_llm_error_marks_diagnosis_failed_cleanly(db_session: AsyncSession) -> None:
    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=RaisingModel(),
    )

    assert diagnosis.status == DiagnosisStatus.failed
    assert "API key" in diagnosis.error_message
    assert diagnosis.requires_human_approval is True


async def test_max_iterations_exhausted_marks_failed(db_session: AsyncSession, monkeypatch) -> None:
    # A model that always wants to call another tool, never reaches end_turn.
    infinite_turns = [
        _tool_use(ModelToolCall(id=f"call_{i}", name="calculate", input={"expression": "1+1"}))
        for i in range(10)
    ]
    model = ScriptedModel(infinite_turns)
    monkeypatch.setattr(
        "app.agents.diagnosis_agent.execute_tool",
        _fake_execute_tool_factory({"calculate": ToolExecutionResult(output={"result": 2})}),
    )

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.failed


DIAGNOSIS_JSON_LOW_SEVERITY = _diagnosis_json(recommended_action="Monitor.", severity="low")


async def test_sensor_anomaly_escalates_severity_floor(
    db_session: AsyncSession, monkeypatch
) -> None:
    model = ScriptedModel(
        [
            _tool_use(
                ModelToolCall(
                    id="call_1",
                    name="query_sensor_history",
                    input={
                        "equipment_id": "MOTOR-001",
                        "metric": "temperature",
                        "start_time": "2026-08-01T00:00:00Z",
                        "end_time": "2026-08-02T00:00:00Z",
                    },
                )
            ),
            _end_turn(DIAGNOSIS_JSON_LOW_SEVERITY),
        ]
    )
    fake_execute = _fake_execute_tool_factory(
        {
            "query_sensor_history": ToolExecutionResult(
                output={"reading_count": 24, "anomaly_count": 3},
                citations=[SENSOR_CITATION],
                evidence=[{"type": "sensor_reading", "citation": SENSOR_CITATION, "detail": "..."}],
            )
        }
    )
    monkeypatch.setattr("app.agents.diagnosis_agent.execute_tool", fake_execute)

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    # model said "low", but objective anomaly evidence floors it to at least "medium"
    assert diagnosis.severity.value in ("medium", "high", "critical")
    assert diagnosis.severity.value != "low"


async def test_tool_error_lowers_confidence_relative_to_clean_run(
    db_session: AsyncSession, monkeypatch
) -> None:
    model_clean = ScriptedModel(
        [
            _tool_use(ModelToolCall(id="call_1", name="calculate", input={"expression": "1+1"})),
            _end_turn(DIAGNOSIS_JSON_NO_CITATIONS),
        ]
    )
    monkeypatch.setattr(
        "app.agents.diagnosis_agent.execute_tool",
        _fake_execute_tool_factory({"calculate": ToolExecutionResult(output={"result": 2})}),
    )
    clean = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model_clean,
    )

    model_erroring = ScriptedModel(
        [
            _tool_use(ModelToolCall(id="call_1", name="calculate", input={"expression": "bad"})),
            _end_turn(DIAGNOSIS_JSON_NO_CITATIONS),
        ]
    )
    monkeypatch.setattr(
        "app.agents.diagnosis_agent.execute_tool",
        _fake_execute_tool_factory(
            {"calculate": ToolExecutionResult(output={}, error="Invalid expression")}
        ),
    )
    erroring = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model_erroring,
    )

    assert erroring.confidence < clean.confidence


async def test_successful_diagnosis_is_audit_logged(db_session: AsyncSession) -> None:
    from app.models.audit_log import AuditLog

    model = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.resource_id == str(diagnosis.id))
    )
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].action == "diagnosis.created"
    assert logs[0].detail["confidence"] == diagnosis.confidence


async def test_conversation_and_messages_are_persisted(db_session: AsyncSession) -> None:
    model = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    user_id = uuid.uuid4()

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=user_id,
        conversation_id=None,
        question="Why is the motor overheating?",
        model_call=model,
    )

    result = await db_session.execute(
        select(Message).where(Message.conversation_id == diagnosis.conversation_id)
    )
    messages = result.scalars().all()
    assert len(messages) == 2
    roles = {m.role for m in messages}
    assert roles == {MessageRole.user, MessageRole.assistant}

    assistant_message = next(m for m in messages if m.role == MessageRole.assistant)
    assert assistant_message.diagnosis_id == diagnosis.id


async def test_existing_conversation_id_is_reused(db_session: AsyncSession) -> None:
    same_user_id = uuid.uuid4()
    model = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    first = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=same_user_id,
        conversation_id=None,
        question="First question",
        model_call=model,
    )

    model2 = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    second = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=same_user_id,
        conversation_id=first.conversation_id,
        question="Follow-up question",
        model_call=model2,
    )

    assert second.conversation_id == first.conversation_id

    result = await db_session.execute(
        select(Message).where(Message.conversation_id == first.conversation_id)
    )
    assert len(result.scalars().all()) == 4  # 2 user + 2 assistant across both turns


async def test_different_users_conversation_id_is_not_reused(db_session: AsyncSession) -> None:
    """A conversation is a private thread for the user who started it — a
    different user_id passing the same conversation_id must NOT be silently
    attached to it (would leak that user's prior Q&A into this one's
    follow-up context, see _fetch_recent_context)."""
    model = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    first = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="First question",
        model_call=model,
    )

    model2 = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    second = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),  # a different user
        conversation_id=first.conversation_id,
        question="Follow-up question",
        model_call=model2,
    )

    assert second.conversation_id != first.conversation_id


async def test_follow_up_question_receives_bounded_prior_context(db_session: AsyncSession) -> None:
    same_user_id = uuid.uuid4()
    first_diagnosis_json = _diagnosis_json(summary="Likely a blocked air filter.")
    first_model = ScriptedModel([_end_turn(first_diagnosis_json)])
    first = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=same_user_id,
        conversation_id=None,
        question="Why is the motor overheating?",
        model_call=first_model,
    )

    class SpyModelLocal:
        def __init__(self, turns):
            self._turns = turns
            self.received_messages = []

        async def __call__(self, messages, system):
            self.received_messages.append(messages)
            return self._turns[len(self.received_messages) - 1]

    second_model = SpyModelLocal([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=same_user_id,
        conversation_id=first.conversation_id,
        question="Does that also explain the noise?",
        model_call=second_model,
    )

    initial_message = second_model.received_messages[0][0]["content"]
    assert "Prior conversation context" in initial_message
    assert "Why is the motor overheating?" in initial_message
    assert "Likely a blocked air filter." in initial_message
    assert "Does that also explain the noise?" in initial_message
    # explicitly labeled as background, not trusted evidence for this turn
    assert "not verified evidence" in initial_message.lower()


async def test_first_question_in_a_conversation_has_no_prior_context(
    db_session: AsyncSession,
) -> None:
    class SpyModelLocal:
        def __init__(self, turns):
            self._turns = turns
            self.received_messages = []

        async def __call__(self, messages, system):
            self.received_messages.append(messages)
            return self._turns[len(self.received_messages) - 1]

    model = SpyModelLocal([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="First question ever",
        model_call=model,
    )

    initial_message = model.received_messages[0][0]["content"]
    assert "Prior conversation context" not in initial_message


async def test_unknown_conversation_id_creates_new_conversation(db_session: AsyncSession) -> None:
    model = ScriptedModel([_end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),  # does not exist
        question="test",
        model_call=model,
    )
    assert diagnosis.conversation_id is not None


class SpyModel:
    """Like ScriptedModel, but records every `messages` list it was called
    with, so a test can inspect exactly what the loop fed back to the model
    after a tool call — not just the final diagnosis."""

    def __init__(self, turns: list[ModelTurn]):
        self._turns = turns
        self.received_messages: list[list[dict]] = []

    async def __call__(self, messages: list[dict], system: str) -> ModelTurn:
        self.received_messages.append(messages)
        turn = self._turns[len(self.received_messages) - 1]
        return turn


async def test_tool_result_is_threaded_back_to_the_model(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Verifies the loop's tool_result message (result-returned-to-model)
    is correctly shaped and actually visible to the *next* model_call
    invocation — not just that a diagnosis eventually completes."""
    call = ModelToolCall(id="call_1", name="calculate", input={"expression": "6*7"})
    model = SpyModel([_tool_use(call), _end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    monkeypatch.setattr(
        "app.agents.diagnosis_agent.execute_tool",
        _fake_execute_tool_factory({"calculate": ToolExecutionResult(output={"result": 42})}),
    )

    await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert len(model.received_messages) == 2
    second_call_messages = model.received_messages[1]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["role"] == "user"
    tool_result_block = tool_result_message["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "call_1"
    assert tool_result_block["is_error"] is False
    assert json.loads(tool_result_block["content"]) == {"result": 42}


async def test_unknown_tool_at_loop_level_is_handled_gracefully(db_session: AsyncSession) -> None:
    """Exercises the REAL execute_tool (not mocked) — the loop must survive
    the model requesting a tool that doesn't exist."""
    bogus_call = ModelToolCall(id="call_1", name="not_a_real_tool", input={})
    model = ScriptedModel([_tool_use(bogus_call), _end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.completed
    assert diagnosis.tool_calls[0]["tool"] == "not_a_real_tool"
    assert "Unknown tool" in diagnosis.tool_calls[0]["summary"]


async def test_malformed_tool_arguments_at_loop_level_real_executor(
    db_session: AsyncSession,
) -> None:
    """Exercises the REAL execute_tool's own argument validation (not
    mocked) — a malformed document_id must not crash the loop."""
    bad_call = ModelToolCall(
        id="call_1",
        name="get_manual_section",
        input={"document_id": "not-a-uuid", "section": "Troubleshooting"},
    )
    model = ScriptedModel([_tool_use(bad_call), _end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.completed
    assert diagnosis.tool_calls[0]["tool"] == "get_manual_section"
    assert "Invalid document_id" in diagnosis.tool_calls[0]["summary"]


async def test_tool_exception_at_loop_level_does_not_crash_the_agent(
    db_session: AsyncSession, monkeypatch
) -> None:
    """A bug inside a real tool handler (not a mocked error result) must
    not propagate out of the loop — same guarantee as
    test_tool_exception_is_caught_not_raised in test_tool_executor.py, but
    proven end-to-end through run_diagnosis."""

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr("app.tools.executor.hybrid_search", _boom)

    search_call = ModelToolCall(
        id="call_1", name="search_technical_documents", input={"query": "x"}
    )
    model = ScriptedModel([_tool_use(search_call), _end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.completed
    assert "simulated bug" in diagnosis.tool_calls[0]["summary"]


_ALL_SEVEN_TOOLS_INPUTS = {
    "search_technical_documents": {"query": "overheating"},
    "get_manual_section": {"document_id": str(uuid.uuid4()), "section": "Troubleshooting"},
    "analyze_component_image": {"image_analysis_id": str(uuid.uuid4())},
    "query_sensor_history": {
        "equipment_id": "MOTOR-001",
        "metric": "temperature",
        "start_time": "2026-08-01T00:00:00Z",
        "end_time": "2026-08-02T00:00:00Z",
    },
    "get_maintenance_schedule": {"equipment_id": "MOTOR-001"},
    "calculate": {"expression": "1+1"},
    "generate_diagnostic_report": {"diagnosis_id": str(uuid.uuid4())},
}


@pytest.mark.parametrize("tool_name", list(_ALL_SEVEN_TOOLS_INPUTS))
async def test_agent_loop_dispatches_each_of_the_seven_tools(
    db_session: AsyncSession, monkeypatch, tool_name: str
) -> None:
    """A fake LLM explicitly requests each of the 7 tools in turn — proves
    the loop's dispatch, execution, and result-recording is uniform and
    correct across the full tool set, not just the 2-3 tools exercised by
    the scenario-focused tests above."""
    call = ModelToolCall(id="call_1", name=tool_name, input=_ALL_SEVEN_TOOLS_INPUTS[tool_name])
    model = ScriptedModel([_tool_use(call), _end_turn(DIAGNOSIS_JSON_NO_CITATIONS)])
    monkeypatch.setattr(
        "app.agents.diagnosis_agent.execute_tool",
        _fake_execute_tool_factory({tool_name: ToolExecutionResult(output={"ok": True})}),
    )

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert diagnosis.status == DiagnosisStatus.completed
    assert len(diagnosis.tool_calls) == 1
    assert diagnosis.tool_calls[0]["tool"] == tool_name
    assert diagnosis.tool_calls[0]["input"] == _ALL_SEVEN_TOOLS_INPUTS[tool_name]


@pytest.mark.parametrize("tool_name", ["query_sensor_history"])
async def test_diagnosis_tool_calls_are_logged(
    db_session: AsyncSession, monkeypatch, tool_name
) -> None:
    model = ScriptedModel(
        [
            _tool_use(
                ModelToolCall(
                    id="call_1",
                    name=tool_name,
                    input={
                        "equipment_id": "MOTOR-001",
                        "metric": "temperature",
                        "start_time": "2026-08-01T00:00:00Z",
                        "end_time": "2026-08-02T00:00:00Z",
                    },
                )
            ),
            _end_turn(DIAGNOSIS_JSON_NO_CITATIONS),
        ]
    )
    monkeypatch.setattr(
        "app.agents.diagnosis_agent.execute_tool",
        _fake_execute_tool_factory(
            {tool_name: ToolExecutionResult(output={"reading_count": 0, "anomaly_count": 0})}
        ),
    )

    diagnosis = await run_diagnosis(
        db_session,
        tenant_id="acme",
        user_id=uuid.uuid4(),
        conversation_id=None,
        question="test",
        model_call=model,
    )

    assert len(diagnosis.tool_calls) == 1
    assert diagnosis.tool_calls[0]["tool"] == tool_name
