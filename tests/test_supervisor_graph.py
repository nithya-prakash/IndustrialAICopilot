import json

import pytest

pytest.importorskip("langgraph")

from app.agents.supervisor_graph import Command, build_supervisor_graph  # noqa: E402
from app.rag.generation import ModelToolCall, ModelTurn  # noqa: E402
from app.tools.executor import ToolExecutionResult  # noqa: E402

CITE = "[manual.pdf, Overheating, p.1]"


def _final(severity="high", cite=CITE):
    return json.dumps(
        {
            "summary": "Bearing wear.",
            "possible_causes": [{"cause": "Bearing", "rank": 1, "supporting_citations": [cite]}],
            "recommended_action": "Replace bearing.",
            "severity": severity,
            "limitations": [],
        }
    )


class FakeModel:
    """Routes on the system prompt: supervisor / specialist / synthesis."""

    def __init__(self, route, severity="high"):
        self.route, self.severity, self.specialist_calls = list(route), severity, 0

    async def __call__(self, messages, system):
        if "route a maintenance diagnosis" in system:
            return ModelTurn(text=json.dumps({"next": self.route.pop(0)}), stop_reason="end_turn")
        if "specialist" in system:
            self.specialist_calls += 1
            if self.specialist_calls % 2 == 1:
                call = ModelToolCall(
                    id="t1", name="search_technical_documents", input={"query": "q"}
                )
                return ModelTurn(text="", stop_reason="tool_use", tool_calls=[call])
            return ModelTurn(text="done", stop_reason="end_turn")
        return ModelTurn(text=_final(self.severity), stop_reason="end_turn")


async def _run_tool(name, tool_input):
    return ToolExecutionResult(
        output={"ok": True},
        citations=[CITE],
        evidence=[{"type": "document_chunk", "citation": CITE}],
    )


def _graph(model):
    return build_supervisor_graph(model, _run_tool, approval_threshold=0.99)


STATE = {"question": "Why hot?", "request_context": "Technician question: Why hot?", "visited": []}


async def test_interrupt_pauses_then_resumes_with_decision():
    graph = _graph(FakeModel(["documents", "synthesize"]))
    cfg = {"configurable": {"thread_id": "t-1"}}
    paused = await graph.ainvoke(STATE, cfg)
    assert "__interrupt__" in paused
    assert paused["__interrupt__"][0].value["severity"] == "high"
    done = await graph.ainvoke(Command(resume={"decision": "approved", "reviewer": "u1"}), cfg)
    assert done["approval"]["decision"] == "approved"
    assert done["diagnosis"]["possible_causes"][0]["supporting_citations"] == [CITE]


async def test_forged_citation_is_discarded():
    model = FakeModel(["documents", "synthesize"])
    cfg = {"configurable": {"thread_id": "t-2"}}
    # Replace synthesis output with a citation never gathered.
    orig = model.__call__

    async def forged(messages, system):
        turn = await orig(messages, system)
        if "diagnosis assistant" in system:
            return ModelTurn(text=_final(cite="[invented.pdf]"), stop_reason="end_turn")
        return turn

    graph = _graph(forged)
    await graph.ainvoke(STATE, cfg)
    state = await graph.aget_state(cfg)
    diag = state.values["diagnosis"]
    assert diag["dropped_citations"] == 1
    assert diag["possible_causes"][0]["supporting_citations"] == []


async def test_vision_skipped_without_image():
    graph = _graph(FakeModel(["vision", "synthesize"]))
    cfg = {"configurable": {"thread_id": "t-3"}}
    await graph.ainvoke(STATE, cfg)
    state = await graph.aget_state(cfg)
    assert "vision" not in state.values.get("visited", [])


async def test_supervisor_cannot_skip_all_specialists():
    graph = _graph(FakeModel(["synthesize", "synthesize"]))
    cfg = {"configurable": {"thread_id": "t-4"}}
    await graph.ainvoke(STATE, cfg)
    state = await graph.aget_state(cfg)
    assert state.values["visited"] == ["documents"]


def _with_planner(plan_text):
    inner = FakeModel(["documents", "synthesize"], severity="medium")

    async def model(messages, system):
        if "maintenance planner" in system:
            return ModelTurn(text=plan_text, stop_reason="end_turn")
        return await inner(messages, system)

    return model


async def _diagnosis_after_planner(plan_text, thread):
    graph = build_supervisor_graph(
        _with_planner(plan_text), _run_tool, approval_threshold=0.0
    )  # threshold 0: approval only when the unsafe filter forces it
    cfg = {"configurable": {"thread_id": thread}}
    await graph.ainvoke(STATE, cfg)
    return (await graph.aget_state(cfg)).values["diagnosis"]


async def test_planner_output_becomes_the_recommendation():
    plan = json.dumps(
        {
            "recommended_action": "Lock out the motor, then inspect the bearings for play.",
            "recommended_checks": ["Check alignment", "Measure vibration RMS"],
            "urgency": "immediate",
            "safety_notes": ["Verify de-energized before touching terminals"],
        }
    )
    diag = await _diagnosis_after_planner(plan, "p-1")
    assert diag["recommended_action"].startswith("[Urgency: immediate] Lock out the motor")
    assert diag["recommended_checks"][0] == "Verify de-energized before touching terminals"
    assert "Check alignment" in diag["recommended_checks"] and diag["urgency"] == "immediate"
    assert diag["requires_human_approval"] is False and diag["unsafe_blocked"] == []


async def test_unsafe_planner_advice_is_blocked_and_forces_approval():
    plan = json.dumps(
        {
            "recommended_action": "Bypass the thermal protection and keep the motor running.",
            "recommended_checks": ["Silence the alarm and continue", "Check bearing play"],
            "urgency": "whenever",
        }
    )
    diag = await _diagnosis_after_planner(plan, "p-2")
    assert "withheld" in diag["recommended_action"] and "Bypass" not in diag["recommended_action"]
    assert diag["recommended_checks"] == ["Check bearing play"]
    assert diag["urgency"] == "soon"  # invalid urgency falls back
    assert set(diag["unsafe_blocked"]) == {"bypass_safety_device", "ignore_alarm"}
    assert diag["requires_human_approval"] is True


async def test_unparsable_planner_output_keeps_the_synthesis_recommendation():
    diag = await _diagnosis_after_planner("not json at all", "p-3")
    assert diag["recommended_action"] == "Replace bearing."
