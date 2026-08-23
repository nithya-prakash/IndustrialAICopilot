import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import Diagnosis, DiagnosisSeverity, DiagnosisStatus
from app.models.image_analysis import ImageAnalysis, ImageAnalysisStatus
from app.models.sensor import SensorReading
from app.tools.executor import ToolContext, execute_tool


async def test_search_technical_documents_no_results_on_empty_db(db_session: AsyncSession) -> None:
    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool("search_technical_documents", {"query": "anything"}, ctx)
    assert result.error is None
    assert result.output["results"] == []
    assert result.citations == []


async def test_unknown_tool_returns_error(db_session: AsyncSession) -> None:
    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool("not_a_real_tool", {}, ctx)
    assert result.error == "Unknown tool: not_a_real_tool"


async def test_calculate_tool_success(db_session: AsyncSession) -> None:
    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool("calculate", {"expression": "6 * 7"}, ctx)
    assert result.error is None
    assert result.output["result"] == 42


async def test_calculate_tool_invalid_expression_returns_error_not_raise(
    db_session: AsyncSession,
) -> None:
    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool("calculate", {"expression": "__import__('os')"}, ctx)
    assert result.error is not None


async def test_query_sensor_history_tool_returns_summary_and_citation(
    db_session: AsyncSession,
) -> None:
    owner_id = uuid.uuid4()
    base = datetime(2026, 8, 10, tzinfo=UTC)
    db_session.add_all(
        [
            SensorReading(
                tenant_id="acme",
                owner_id=owner_id,
                equipment_id="MOTOR-001",
                equipment_type="electric_motor",
                metric="temperature",
                value=60.0 + i,
                recorded_at=base + timedelta(hours=i),
            )
            for i in range(5)
        ]
    )
    await db_session.commit()

    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool(
        "query_sensor_history",
        {
            "equipment_id": "MOTOR-001",
            "metric": "temperature",
            "start_time": "2026-08-10T00:00:00Z",
            "end_time": "2026-08-11T00:00:00Z",
        },
        ctx,
    )

    assert result.error is None
    assert result.output["reading_count"] == 5
    assert len(result.citations) == 1
    assert result.evidence[0]["type"] == "sensor_reading"


async def test_query_sensor_history_tool_invalid_time_range_returns_error(
    db_session: AsyncSession,
) -> None:
    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool(
        "query_sensor_history",
        {
            "equipment_id": "MOTOR-001",
            "metric": "temperature",
            "start_time": "not-a-date",
            "end_time": "2026-08-11T00:00:00Z",
        },
        ctx,
    )
    assert result.error is not None


async def test_get_maintenance_schedule_tool_no_tasks(db_session: AsyncSession) -> None:
    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool("get_maintenance_schedule", {"equipment_id": "NOPE-001"}, ctx)
    assert result.error is None
    assert result.output["tasks"] == []


async def test_analyze_component_image_tool_returns_stored_observations(
    db_session: AsyncSession,
) -> None:
    owner_id = uuid.uuid4()
    analysis = ImageAnalysis(
        tenant_id="acme",
        owner_id=owner_id,
        storage_path="/tmp/fake.jpg",
        content_type="image/jpeg",
        file_size_bytes=100,
        vision_provider="anthropic",
        vision_model="claude-haiku-4-5-20251001",
        status=ImageAnalysisStatus.ready,
        observations=[{"description": "Visible scratch", "confidence": 0.8}],
        limitations=[],
    )
    db_session.add(analysis)
    await db_session.commit()
    await db_session.refresh(analysis)

    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool(
        "analyze_component_image", {"image_analysis_id": str(analysis.id)}, ctx
    )

    assert result.error is None
    assert result.output["observations"][0]["description"] == "Visible scratch"
    assert len(result.citations) == 1


async def test_analyze_component_image_tool_not_found_returns_error(
    db_session: AsyncSession,
) -> None:
    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool(
        "analyze_component_image", {"image_analysis_id": str(uuid.uuid4())}, ctx
    )
    assert result.error is not None


async def test_analyze_component_image_tool_cross_tenant_returns_error(
    db_session: AsyncSession,
) -> None:
    analysis = ImageAnalysis(
        tenant_id="globex",
        owner_id=uuid.uuid4(),
        storage_path="/tmp/fake.jpg",
        content_type="image/jpeg",
        file_size_bytes=100,
        vision_provider="anthropic",
        vision_model="claude-haiku-4-5-20251001",
        status=ImageAnalysisStatus.ready,
        observations=[],
        limitations=[],
    )
    db_session.add(analysis)
    await db_session.commit()
    await db_session.refresh(analysis)

    ctx = ToolContext(db=db_session, tenant_id="acme")  # different tenant
    result = await execute_tool(
        "analyze_component_image", {"image_analysis_id": str(analysis.id)}, ctx
    )
    assert result.error is not None


async def test_generate_diagnostic_report_tool_formats_existing_diagnosis(
    db_session: AsyncSession,
) -> None:
    from app.models.conversation import Conversation

    conversation = Conversation(tenant_id="acme", user_id=uuid.uuid4(), title="test")
    db_session.add(conversation)
    await db_session.flush()

    diagnosis = Diagnosis(
        tenant_id="acme",
        conversation_id=conversation.id,
        user_id=uuid.uuid4(),
        question="Why is it hot?",
        status=DiagnosisStatus.completed,
        summary="Likely blocked ventilation.",
        confidence=0.7,
        severity=DiagnosisSeverity.medium,
        requires_human_approval=False,
        llm_provider="anthropic",
        llm_model="claude-haiku-4-5-20251001",
    )
    db_session.add(diagnosis)
    await db_session.commit()
    await db_session.refresh(diagnosis)

    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool(
        "generate_diagnostic_report", {"diagnosis_id": str(diagnosis.id)}, ctx
    )

    assert result.error is None
    assert "Likely blocked ventilation." in result.output["report"]


async def test_tool_exception_is_caught_not_raised(db_session: AsyncSession, monkeypatch) -> None:
    """A bug inside a tool handler must not crash the agent loop — it
    becomes a graceful error result instead."""

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr("app.tools.executor.hybrid_search", _boom)

    ctx = ToolContext(db=db_session, tenant_id="acme")
    result = await execute_tool("search_technical_documents", {"query": "x"}, ctx)
    assert result.error is not None
    assert "simulated bug" in result.error
