"""Runs the LangGraph supervisor and persists its result as a Diagnosis.

The graph's approval `interrupt()` is paired with the existing DB approval
flow: a paused graph is stored under a thread id keyed by diagnosis id, and the
supervisor's approve/reject call resumes (and so completes) that thread.
Checkpoints are in-memory (MemorySaver): a restart drops paused threads, but
the Diagnosis row and its DB approval flow are unaffected.
"""
import uuid
from functools import partial

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.diagnosis_agent import (
    _build_initial_message,
    _get_or_create_conversation,
    _persist_failed_diagnosis,
)
from app.agents.supervisor_graph import build_supervisor_graph
from app.config import get_settings
from app.models.conversation import Message, MessageRole
from app.models.diagnosis import Diagnosis, DiagnosisSeverity, DiagnosisStatus
from app.rag.generation import call_model
from app.services.audit_service import log_event
from app.tools.executor import ToolContext, execute_tool

_checkpointer = MemorySaver()
_paused_threads: dict[uuid.UUID, str] = {}


def _graph(db: AsyncSession, tenant_id: str, model_call):
    ctx = ToolContext(db=db, tenant_id=tenant_id)
    return build_supervisor_graph(
        model_call,
        lambda name, inp: execute_tool(name, inp, ctx),
        approval_threshold=get_settings().confidence_approval_threshold,
        checkpointer=_checkpointer,
        plain_call=partial(model_call, use_tools=False) if model_call is call_model else None,
    )


async def run_supervised_diagnosis(
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
        db, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id,
        equipment_id=equipment_id, question=question,
    )
    thread_id = str(uuid.uuid4())
    graph = _graph(db, tenant_id, model_call)
    state = await graph.ainvoke(
        {
            "question": question,
            "request_context": _build_initial_message(
                question=question, equipment_id=equipment_id, equipment_type=equipment_type,
                image_analysis_id=image_analysis_id, sensor_snapshot=sensor_snapshot,
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
            db, conversation=conversation, tenant_id=tenant_id, user_id=user_id,
            equipment_id=equipment_id, equipment_type=equipment_type, question=question,
            error_message=result.get("error", "Supervisor produced no diagnosis"),
            evidence=final.get("evidence"), tool_call_log=final.get("tool_calls"),
        )

    diagnosis = Diagnosis(
        tenant_id=tenant_id, conversation_id=conversation.id, user_id=user_id,
        equipment_id=equipment_id, equipment_type=equipment_type, question=question,
        status=DiagnosisStatus.completed, summary=result["summary"] or "(no summary provided)",
        possible_causes=result["possible_causes"],
        recommended_action=result["recommended_action"],
        confidence=result["confidence"], severity=DiagnosisSeverity(result["severity"]),
        requires_human_approval=result["requires_human_approval"],
        evidence=final.get("evidence", []), tool_calls=final.get("tool_calls", []),
        limitations=(
            [f"{result['dropped_citations']} citation(s) did not match gathered evidence "
             "and were discarded."] if result["dropped_citations"] else []
        ),
        llm_provider=settings.llm_provider, llm_model=settings.llm_model,
    )
    db.add(diagnosis)
    await db.flush()
    paused = bool(final.get("approval") is None and result["requires_human_approval"])
    if paused:
        _paused_threads[diagnosis.id] = thread_id
    db.add(Message(conversation_id=conversation.id, role=MessageRole.user, content=question))
    db.add(Message(conversation_id=conversation.id, role=MessageRole.assistant,
                   content=diagnosis.summary, diagnosis_id=diagnosis.id))
    await log_event(
        db, tenant_id=tenant_id, actor_user_id=user_id, action="diagnosis.created",
        resource_type="diagnosis", resource_id=diagnosis.id,
        detail={"orchestrator": "langgraph_supervisor", "paused_for_approval": paused,
                "specialists": final.get("visited", [])},
    )
    await db.commit()
    await db.refresh(diagnosis)
    return diagnosis


async def resume_if_paused(
    db: AsyncSession, *, tenant_id: str, diagnosis_id: uuid.UUID, decision: str, reviewer: str
) -> bool:
    """Completes a paused graph thread with the reviewer's decision. No-op (False)
    for diagnoses that never paused, or whose checkpoint was lost on restart."""
    thread_id = _paused_threads.pop(diagnosis_id, None)
    if thread_id is None:
        return False
    graph = _graph(db, tenant_id, call_model)
    await graph.ainvoke(
        Command(resume={"decision": decision, "reviewer": reviewer}),
        {"configurable": {"thread_id": thread_id}},
    )
    return True
