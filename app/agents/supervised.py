"""Runs the LangGraph supervisor and persists its result as a Diagnosis.

The graph's approval `interrupt()` is paired with the existing DB approval
flow: a paused graph is stored under a thread id keyed by diagnosis id, and the
supervisor's approve/reject call resumes (and so completes) that thread.
The graph thread id IS the diagnosis id, and checkpoints are kept in Postgres
(see checkpointing.py), so a restart does not lose a paused approval.
"""

import time
import uuid
from functools import partial

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.checkpointing import get_checkpointer
from app.agents.diagnosis_agent import (
    _build_initial_message,
    _get_or_create_conversation,
    _persist_failed_diagnosis,
    _summarize_tool_output,
)
from app.agents.supervisor_graph import build_supervisor_graph
from app.config import get_settings
from app.models.conversation import Message, MessageRole
from app.models.diagnosis import Diagnosis, DiagnosisSeverity, DiagnosisStatus
from app.observability import tracing, usage
from app.observability.metrics import (
    agent_run_duration_seconds,
    agent_tool_call_duration_seconds,
    agent_tool_calls_total,
    diagnoses_total,
    diagnosis_confidence,
)
from app.rag.generation import call_model
from app.services.audit_service import log_event
from app.tools.executor import ToolContext, execute_tool


async def _instrumented_tool(name: str, tool_input: dict, ctx: ToolContext):
    """execute_tool plus the same per-tool metrics the tool-loop agent records."""
    start = time.perf_counter()
    with tracing.observation(f"tool:{name}", input=tool_input) as tool_span:
        result = await execute_tool(name, tool_input, ctx)
        tool_span.update(
            output=_summarize_tool_output(result),
            metadata={"citations": len(result.citations), "error": bool(result.error)},
        )
    agent_tool_call_duration_seconds.labels(tool=name).observe(time.perf_counter() - start)
    agent_tool_calls_total.labels(tool=name, status="error" if result.error else "success").inc()
    return result


def _graph(db: AsyncSession, tenant_id: str, model_call, checkpointer):
    ctx = ToolContext(db=db, tenant_id=tenant_id)
    return build_supervisor_graph(
        model_call,
        lambda name, inp: _instrumented_tool(name, inp, ctx),
        approval_threshold=get_settings().confidence_approval_threshold,
        checkpointer=checkpointer,
        plain_call=partial(model_call, use_tools=False) if model_call is call_model else None,
    )


async def _run_supervised_diagnosis(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    question: str,
    equipment_id: str | None = None,
    equipment_type: str | None = None,
    image_analysis_id: uuid.UUID | None = None,
    sensor_snapshot: dict[str, float] | None = None,
    model_call=call_model,
) -> Diagnosis:
    settings = get_settings()
    conversation = await _get_or_create_conversation(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        equipment_id=equipment_id,
        question=question,
    )
    diagnosis_id = uuid.uuid4()
    thread_id = str(diagnosis_id)
    graph = _graph(db, tenant_id, model_call, await get_checkpointer(db))
    await graph.ainvoke(
        {
            "question": question,
            "request_context": _build_initial_message(
                question=question,
                equipment_id=equipment_id,
                equipment_type=equipment_type,
                image_analysis_id=image_analysis_id,
                sensor_snapshot=sensor_snapshot,
            ),
            "image_analysis_id": str(image_analysis_id) if image_analysis_id else None,
            "visited": [],
        },
        {"configurable": {"thread_id": thread_id}},
    )
    final = (await graph.aget_state({"configurable": {"thread_id": thread_id}})).values
    result = final.get("diagnosis") or {}
    if result.get("status") != "completed":
        return await _persist_failed_diagnosis(
            db,
            conversation=conversation,
            tenant_id=tenant_id,
            user_id=user_id,
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            question=question,
            error_message=result.get("error", "Supervisor produced no diagnosis"),
            evidence=final.get("evidence"),
            tool_call_log=final.get("tool_calls"),
        )

    diagnosis = Diagnosis(
        id=diagnosis_id,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        user_id=user_id,
        equipment_id=equipment_id,
        equipment_type=equipment_type,
        question=question,
        status=DiagnosisStatus.completed,
        summary=result["summary"] or "(no summary provided)",
        possible_causes=result["possible_causes"],
        recommended_action=result["recommended_action"],
        recommended_checks=result.get("recommended_checks", []),
        sensor_findings=result.get("sensor_findings", []),
        confidence=result["confidence"],
        severity=DiagnosisSeverity(result["severity"]),
        requires_human_approval=result["requires_human_approval"],
        evidence=final.get("evidence", []),
        tool_calls=final.get("tool_calls", []),
        limitations=(
            [
                f"{result['dropped_citations']} citation(s) did not match gathered evidence "
                "and were discarded."
            ]
            if result["dropped_citations"]
            else []
        )
        + (
            [
                "Part of the model's advice conflicted with basic safety rules ("
                + ", ".join(result["unsafe_blocked"])
                + ") and was withheld; a supervisor must review this diagnosis."
            ]
            if result.get("unsafe_blocked")
            else []
        )
        + (
            [
                f"{result['dropped_sensor_findings']} sensor finding(s) were discarded because "
                "their "
                "metric or stated values did not match the retrieved sensor data."
            ]
            if result.get("dropped_sensor_findings")
            else []
        ),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
    )
    db.add(diagnosis)
    await db.flush()
    diagnoses_total.labels(status="completed", severity=result["severity"]).inc()
    diagnosis_confidence.observe(result["confidence"])
    paused = bool(final.get("approval") is None and result["requires_human_approval"])
    db.add(Message(conversation_id=conversation.id, role=MessageRole.user, content=question))
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.assistant,
            content=diagnosis.summary,
            diagnosis_id=diagnosis.id,
        )
    )
    await log_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        action="diagnosis.created",
        resource_type="diagnosis",
        resource_id=diagnosis.id,
        detail={
            "orchestrator": "langgraph_supervisor",
            "paused_for_approval": paused,
            "specialists": final.get("visited", []),
        },
    )
    await db.commit()
    await db.refresh(diagnosis)
    return diagnosis


async def resume_if_paused(
    db: AsyncSession, *, tenant_id: str, diagnosis_id: uuid.UUID, decision: str, reviewer: str
) -> bool:
    """Completes a paused graph thread with the reviewer's decision. No-op (False) for
    diagnoses that were never paused (tool-loop, no approval needed) or were already resumed."""
    config = {"configurable": {"thread_id": str(diagnosis_id)}}
    graph = _graph(db, tenant_id, call_model, await get_checkpointer(db))
    state = await graph.aget_state(config)
    if not state.next:
        return False
    await graph.ainvoke(Command(resume={"decision": decision, "reviewer": reviewer}), config)
    return True


async def run_supervised_diagnosis(*args, **kwargs) -> Diagnosis:
    """Runs the supervisor graph (see `_run_supervised_diagnosis`) and records its duration."""
    start = time.perf_counter()
    with tracing.observation(
        "diagnosis", metadata={"orchestrator": "supervisor", "tenant_id": kwargs.get("tenant_id")}
    ) as root:
        run_usage, usage_token = usage.start_run("supervisor")
        try:
            diagnosis = await _run_supervised_diagnosis(*args, **kwargs)
        finally:
            usage.end_run(usage_token)
        diagnosis.usage = run_usage.as_dict()
        await args[0].commit()
        root.update(
            output={"status": diagnosis.status.value, "confidence": diagnosis.confidence},
            metadata={"diagnosis_id": str(diagnosis.id), "severity": diagnosis.severity.value},
        )
    agent_run_duration_seconds.labels(
        orchestrator="supervisor", status=diagnosis.status.value
    ).observe(time.perf_counter() - start)
    return diagnosis
