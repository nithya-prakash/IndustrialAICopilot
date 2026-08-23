"""Dispatches one tool call to its underlying service function.

Every tool that returns citable evidence attaches real citation strings
(built from actual DB/analytics data, never invented) to the result. The
orchestrator collects these across all tool calls into a session-wide
citation set, and validates the model's final supporting_citations against
that set — the same "don't trust, verify against what was actually
retrieved" pattern as Phase 3's citation-marker validation, applied here to
every evidence type (documents, sensors, images, maintenance), not just
document chunks.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.sensors import (
    SensorPoint,
    detect_anomalies_statistical,
    detect_trend,
    statistical_summary,
)
from app.models.diagnosis import Diagnosis
from app.rag.retrieval import get_manual_section as fetch_manual_section
from app.rag.retrieval import hybrid_search
from app.services.equipment_service import (
    get_maintenance_schedule as fetch_maintenance_schedule,
)
from app.services.image_service import get_image_analysis
from app.services.report_service import format_diagnostic_report
from app.services.sensor_service import query_sensor_history as fetch_sensor_history
from app.tools.calculator import CalculationError, safe_calculate


@dataclass
class ToolExecutionResult:
    output: dict
    citations: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class ToolContext:
    db: AsyncSession
    tenant_id: str


async def execute_tool(name: str, tool_input: dict, ctx: ToolContext) -> ToolExecutionResult:
    handlers = {
        "search_technical_documents": _search_technical_documents,
        "get_manual_section": _get_manual_section,
        "analyze_component_image": _analyze_component_image,
        "query_sensor_history": _query_sensor_history,
        "get_maintenance_schedule": _get_maintenance_schedule,
        "calculate": _calculate,
        "generate_diagnostic_report": _generate_diagnostic_report,
    }
    handler = handlers.get(name)
    if handler is None:
        return ToolExecutionResult(output={}, error=f"Unknown tool: {name}")

    try:
        return await handler(tool_input, ctx)
    except Exception as exc:  # noqa: BLE001 - a tool failure must not crash the agent loop;
        # it becomes a graceful error result the model (and confidence scoring) can react to.
        return ToolExecutionResult(output={}, error=f"Tool execution failed: {exc}")


async def _search_technical_documents(tool_input: dict, ctx: ToolContext) -> ToolExecutionResult:
    query = tool_input.get("query", "")
    chunks = await hybrid_search(ctx.db, query, tenant_id=ctx.tenant_id)
    if not chunks:
        return ToolExecutionResult(
            output={"results": [], "message": "No relevant documentation found."}
        )

    results = [{"citation": c.citation, "excerpt": c.content} for c in chunks]
    return ToolExecutionResult(
        output={"results": results},
        citations=[c.citation for c in chunks],
        evidence=[
            {"type": "document_chunk", "citation": c.citation, "detail": c.content[:500]}
            for c in chunks
        ],
    )


async def _get_manual_section(tool_input: dict, ctx: ToolContext) -> ToolExecutionResult:
    try:
        document_id = uuid.UUID(tool_input["document_id"])
    except (KeyError, ValueError):
        return ToolExecutionResult(output={}, error="Invalid document_id")

    chunks = await fetch_manual_section(
        ctx.db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        section=tool_input.get("section", ""),
    )
    if not chunks:
        return ToolExecutionResult(output={"results": [], "message": "Section not found."})

    results = [{"citation": c.citation, "excerpt": c.content} for c in chunks]
    return ToolExecutionResult(
        output={"results": results},
        citations=[c.citation for c in chunks],
        evidence=[
            {"type": "document_chunk", "citation": c.citation, "detail": c.content[:500]}
            for c in chunks
        ],
    )


async def _analyze_component_image(tool_input: dict, ctx: ToolContext) -> ToolExecutionResult:
    try:
        analysis_id = uuid.UUID(tool_input["image_analysis_id"])
    except (KeyError, ValueError):
        return ToolExecutionResult(output={}, error="Invalid image_analysis_id")

    record = await get_image_analysis(ctx.db, analysis_id=analysis_id, tenant_id=ctx.tenant_id)
    if record is None:
        return ToolExecutionResult(output={}, error="Image analysis not found")
    if record.status.value != "ready":
        return ToolExecutionResult(
            output={"status": record.status.value, "error_message": record.error_message}
        )

    citation = f"[Image analysis {record.id}]"
    return ToolExecutionResult(
        output={"observations": record.observations, "limitations": record.limitations},
        citations=[citation],
        evidence=[
            {
                "type": "image_observation",
                "citation": citation,
                "detail": "; ".join(o.get("description", "") for o in (record.observations or [])),
            }
        ],
    )


def _summarize_sensor_finding(metric, summary, trend, anomalies) -> str:
    if summary is None:
        return f"No {metric} readings found in the requested range."
    value_range = f"[{summary.min_value:.2f}, {summary.max_value:.2f}]"
    parts = [f"{metric}: mean={summary.mean:.2f}, range={value_range}"]
    if trend and trend.direction != "stable":
        trend_desc = f"{trend.direction} ({trend.slope_per_hour:+.3f}/hr, R²={trend.r_squared})"
        parts.append(f"trend is {trend_desc}")
    if anomalies:
        noun = "anomaly" if len(anomalies) == 1 else "anomalies"
        parts.append(f"{len(anomalies)} statistical {noun} detected")
    return "; ".join(parts)


async def _query_sensor_history(tool_input: dict, ctx: ToolContext) -> ToolExecutionResult:
    try:
        start_time = datetime.fromisoformat(tool_input["start_time"])
        end_time = datetime.fromisoformat(tool_input["end_time"])
    except (KeyError, ValueError) as exc:
        return ToolExecutionResult(output={}, error=f"Invalid time range: {exc}")

    equipment_id = tool_input.get("equipment_id", "")
    metric = tool_input.get("metric", "")
    readings = await fetch_sensor_history(
        ctx.db,
        tenant_id=ctx.tenant_id,
        equipment_id=equipment_id,
        metric=metric,
        start_time=start_time,
        end_time=end_time,
    )
    if not readings:
        return ToolExecutionResult(
            output={"readings": [], "message": "No readings found for that range."}
        )

    points = [SensorPoint(recorded_at=r.recorded_at, value=r.value) for r in readings]
    summary = statistical_summary(points)
    trend = detect_trend(points)
    anomalies = detect_anomalies_statistical(points)

    time_range = f"{tool_input['start_time']} to {tool_input['end_time']}"
    citation = f"[{equipment_id} sensor history, {metric}, {time_range}]"
    finding_text = _summarize_sensor_finding(metric, summary, trend, anomalies)
    output = {
        "reading_count": len(readings),
        "summary": summary.__dict__ if summary else None,
        "trend": trend.__dict__ if trend else None,
        "anomaly_count": len(anomalies),
        "anomalies": [
            {"recorded_at": a.recorded_at.isoformat(), "value": a.value, "score": a.score}
            for a in anomalies[:10]
        ],
    }
    return ToolExecutionResult(
        output=output,
        citations=[citation],
        evidence=[{"type": "sensor_reading", "citation": citation, "detail": finding_text}],
    )


async def _get_maintenance_schedule(tool_input: dict, ctx: ToolContext) -> ToolExecutionResult:
    equipment_id = tool_input.get("equipment_id", "")
    statuses = await fetch_maintenance_schedule(
        ctx.db, tenant_id=ctx.tenant_id, equipment_id=equipment_id
    )
    if not statuses:
        return ToolExecutionResult(
            output={"tasks": [], "message": "No maintenance schedule found for this equipment."}
        )

    tasks = []
    evidence = []
    for s in statuses:
        citation = f"[Maintenance schedule, {equipment_id}, {s.task_name}]"
        last_performed = s.last_performed_at.isoformat() if s.last_performed_at else None
        tasks.append(
            {
                "task_name": s.task_name,
                "interval_days": s.interval_days,
                "last_performed_at": last_performed,
                "days_until_due": s.days_until_due,
                "is_overdue": s.is_overdue,
            }
        )
        status_text = "overdue" if s.is_overdue else "on schedule"
        evidence.append(
            {
                "type": "maintenance_record",
                "citation": citation,
                "detail": f"{s.task_name}: {status_text}",
            }
        )

    return ToolExecutionResult(
        output={"tasks": tasks}, citations=[e["citation"] for e in evidence], evidence=evidence
    )


async def _calculate(tool_input: dict, _ctx: ToolContext) -> ToolExecutionResult:
    expression = tool_input.get("expression", "")
    try:
        result = safe_calculate(expression)
    except CalculationError as exc:
        return ToolExecutionResult(output={}, error=str(exc))
    return ToolExecutionResult(output={"result": result})


async def _generate_diagnostic_report(tool_input: dict, ctx: ToolContext) -> ToolExecutionResult:
    try:
        diagnosis_id = uuid.UUID(tool_input["diagnosis_id"])
    except (KeyError, ValueError):
        return ToolExecutionResult(output={}, error="Invalid diagnosis_id")

    result = await ctx.db.execute(
        select(Diagnosis).where(
            Diagnosis.id == diagnosis_id, Diagnosis.tenant_id == ctx.tenant_id
        )
    )
    diagnosis = result.scalar_one_or_none()
    if diagnosis is None:
        return ToolExecutionResult(output={}, error="Diagnosis not found")

    return ToolExecutionResult(output={"report": format_diagnostic_report(diagnosis)})
