"""Full mocked end-to-end integration test for the complete diagnosis
pipeline: auth -> tenant validation -> vision -> sensor analytics ->
hybrid RAG (real BM25 + RRF + real cross-encoder rerank, dense Qdrant leg
mocked to keep the test hermetic and avoid writing into the shared Qdrant
collection) -> agent tool calling -> structured diagnosis -> citation
validation -> confidence -> approval workflow -> audit record.

Only two things are mocked: the Anthropic SDK client (both the vision call
and the diagnosis agent's tool-calling call) and the Qdrant dense-search
leg. Everything else — real HTTP routes, real Postgres-backed BM25
retrieval, real RRF fusion, real cross-encoder reranking, real citation
validation, real confidence/severity computation, real approval workflow,
real audit logging — runs for real, using realistic fixtures.

This proves the pipeline is wired together correctly. It does NOT prove
real model accuracy — that requires live provider credentials (see
tests/live/) and is never implied by this test.
"""
import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from PIL import Image

from app.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentStatus, DocumentVersion
from app.models.sensor import SensorReading

DOC_FILENAME = "electric_motor_manual.pdf"
DOC_SECTION = "Troubleshooting"
DOC_SUBSECTION = "Overheating"
DOC_PAGE = 12
DOC_CONTENT = (
    "Check the cooling fan and clear any blocked ventilation slots to reduce "
    "motor overheating. A blocked vent is the most common root cause."
)
DOC_CITATION = f"[{DOC_FILENAME}, {DOC_SECTION} > {DOC_SUBSECTION}, p.{DOC_PAGE}]"

SENSOR_EQUIPMENT_ID = "MOTOR-001"
SENSOR_METRIC = "temperature"
SENSOR_START = "2026-08-01T00:00:00+00:00"
SENSOR_END = "2026-08-02T00:00:00+00:00"
SENSOR_CITATION = (
    f"[{SENSOR_EQUIPMENT_ID} sensor history, {SENSOR_METRIC}, {SENSOR_START} to {SENSOR_END}]"
)


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (200, 150), color=(80, 80, 80))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def providers_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "vision_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_provider", "anthropic")


@pytest.fixture(autouse=True)
def mocked_qdrant_dense_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the Qdrant network call is mocked (returns no dense hits) — BM25
    retrieval, RRF fusion, and cross-encoder reranking all run for real
    against the seeded Postgres chunk below."""
    monkeypatch.setattr("app.rag.retrieval.qdrant_dense_search", lambda *a, **kw: [])


class _TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id: str, name: str, input: dict) -> None:
        self.id = id
        self.name = name
        self.input = input


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeAnthropicResponse:
    def __init__(self, content: list, stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeMessages:
    """Routes by presence of `tools=` — agent tool-calling turns pass
    tools=TOOL_DEFINITIONS, vision calls never do — so one fake client can
    stand in for both real call sites without conflating their scripts."""

    def __init__(self, vision_response_text: str, agent_turns: list) -> None:
        self._vision_text = vision_response_text
        self._agent_turns = list(agent_turns)
        self.vision_call_count = 0
        self.agent_call_count = 0

    async def create(self, **kwargs):
        if "tools" in kwargs:
            turn = self._agent_turns[self.agent_call_count]
            self.agent_call_count += 1
            return turn
        self.vision_call_count += 1
        return _FakeAnthropicResponse([_TextBlock(self._vision_text)], "end_turn")


class _FakeAnthropicClient:
    def __init__(self, vision_response_text: str, agent_turns: list, **kwargs) -> None:
        self.messages = _FakeMessages(vision_response_text, agent_turns)


async def _register(
    client: AsyncClient, username: str, tenant_id: str, role: str = "technician"
) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct-horse-battery",
            "tenant_id": tenant_id,
            "role": role,
        },
    )
    assert response.status_code == 201
    return response.json()


async def _seed_document_chunk(db_session) -> None:
    """Seeds the target chunk plus an unrelated distractor chunk. BM25's IDF
    weighting is degenerate over a single-document corpus (a term present
    in 100% of documents scores <= 0 and gets filtered out entirely, per
    app/rag/bm25.py) — a second, topically distinct chunk is required for
    the query terms to carry any positive signal at all, exactly as a real
    multi-document corpus would."""
    document = Document(
        tenant_id="acme",
        owner_id=uuid.uuid4(),
        original_filename=DOC_FILENAME,
        equipment_type="electric_motor",
        equipment_id=SENSOR_EQUIPMENT_ID,
    )
    db_session.add(document)
    await db_session.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        storage_path="/tmp/fake.pdf",
        content_type="application/pdf",
        file_size_bytes=1000,
        status=DocumentStatus.ready,
        is_current=True,
    )
    db_session.add(version)
    await db_session.flush()

    chunk = DocumentChunk(
        document_version_id=version.id,
        chunk_index=0,
        page_number=DOC_PAGE,
        section=DOC_SECTION,
        subsection=DOC_SUBSECTION,
        content=DOC_CONTENT,
    )
    # Two distractors, not one: BM25's IDF is exactly zero when a term
    # appears in exactly 1 of 2 documents (log((N-freq+0.5)/(freq+0.5)) =
    # log(1.5/1.5) = 0 at N=2), which silently filters out even a perfect
    # keyword match (app/rag/bm25.py keeps only score > 0). A 3rd,
    # topically distinct document is the minimum for the target terms to
    # get a positive IDF weight.
    distractor_chunk_1 = DocumentChunk(
        document_version_id=version.id,
        chunk_index=1,
        page_number=3,
        section="Lubrication",
        subsection="Conveyor belts",
        content=(
            "Apply food-grade lubricant to the conveyor belt bearings every "
            "90 days per the maintenance schedule."
        ),
    )
    distractor_chunk_2 = DocumentChunk(
        document_version_id=version.id,
        chunk_index=2,
        page_number=5,
        section="Electrical safety",
        subsection="Lockout tagout",
        content=(
            "Always disconnect and lock out the main power supply before "
            "servicing any electrical panel or control cabinet."
        ),
    )
    db_session.add_all([chunk, distractor_chunk_1, distractor_chunk_2])
    await db_session.commit()


async def _seed_sensor_readings(db_session, owner_id: uuid.UUID) -> None:
    base = datetime(2026, 8, 1, 6, tzinfo=UTC)
    readings = [
        SensorReading(
            tenant_id="acme",
            owner_id=owner_id,
            equipment_id=SENSOR_EQUIPMENT_ID,
            equipment_type="electric_motor",
            metric=SENSOR_METRIC,
            value=60.0,
            recorded_at=base + timedelta(hours=i),
        )
        for i in range(10)
    ]
    # a clear anomaly the statistical detector should flag
    readings.append(
        SensorReading(
            tenant_id="acme",
            owner_id=owner_id,
            equipment_id=SENSOR_EQUIPMENT_ID,
            equipment_type="electric_motor",
            metric=SENSOR_METRIC,
            value=180.0,
            recorded_at=base + timedelta(hours=11),
        )
    )
    db_session.add_all(readings)
    await db_session.commit()


async def test_full_diagnosis_pipeline_end_to_end(
    client: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --- auth + tenant setup ---
    technician = await _register(client, "e2e_tech", "acme", role="technician")
    tech_token = technician["access_token"]
    tech_headers = {"Authorization": f"Bearer {tech_token}"}

    # --- real hybrid-RAG fixture data (Postgres-backed) ---
    await _seed_document_chunk(db_session)
    await _seed_sensor_readings(db_session, owner_id=uuid.UUID(technician["user"]["id"]))

    # --- vision: real HTTP upload, mocked provider ---
    vision_json = (
        '{"observations": [{"description": "Visible corrosion near housing vents", '
        '"confidence": 0.8}], "limitations": []}'
    )
    fake_client = _FakeAnthropicClient(vision_json, agent_turns=[])
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kwargs: fake_client)

    image_response = await client.post(
        "/api/v1/images/analyze",
        headers=tech_headers,
        files={"file": ("motor.jpg", _jpeg_bytes(), "image/jpeg")},
        data={"equipment_type": "electric_motor", "equipment_id": SENSOR_EQUIPMENT_ID},
    )
    assert image_response.status_code == 201
    image_body = image_response.json()
    assert image_body["status"] == "ready"
    image_analysis_id = image_body["id"]
    image_citation = f"[Image analysis {image_analysis_id}]"

    # --- diagnosis agent: scripted multi-turn tool-calling loop ---
    diagnosis_json = json.dumps(
        {
            "summary": (
                "Motor overheating is likely caused by blocked ventilation, "
                "corroborated by a sensor temperature spike and visible "
                "corrosion near the vents."
            ),
            "visual_observations": [
                {"description": "Visible corrosion near housing vents", "confidence": 0.8}
            ],
            "sensor_findings": [
                {"metric": "temperature", "finding": "Spike detected in the requested range"}
            ],
            "possible_causes": [
                {
                    "cause": "Blocked ventilation",
                    "rank": 1,
                    "supporting_citations": [DOC_CITATION, SENSOR_CITATION, image_citation],
                }
            ],
            "recommended_checks": ["Inspect ventilation slots", "Verify sensor calibration"],
            "recommended_action": "Clean ventilation slots and monitor temperature for 24 hours.",
            "severity": "high",
            "limitations": [],
        }
    )
    agent_turns = [
        _FakeAnthropicResponse(
            [
                _ToolUseBlock(
                    "call_1", "search_technical_documents", {"query": "overheating ventilation"}
                )
            ],
            "tool_use",
        ),
        _FakeAnthropicResponse(
            [
                _ToolUseBlock(
                    "call_2",
                    "query_sensor_history",
                    {
                        "equipment_id": SENSOR_EQUIPMENT_ID,
                        "metric": SENSOR_METRIC,
                        "start_time": SENSOR_START,
                        "end_time": SENSOR_END,
                    },
                )
            ],
            "tool_use",
        ),
        _FakeAnthropicResponse(
            [
                _ToolUseBlock(
                    "call_3",
                    "analyze_component_image",
                    {"image_analysis_id": image_analysis_id},
                )
            ],
            "tool_use",
        ),
        _FakeAnthropicResponse([_TextBlock(diagnosis_json)], "end_turn"),
    ]
    fake_client.messages._agent_turns = agent_turns

    diagnosis_response = await client.post(
        "/api/v1/copilot/query",
        headers=tech_headers,
        json={
            "question": "Why is the motor overheating?",
            "equipment_id": SENSOR_EQUIPMENT_ID,
            "equipment_type": "electric_motor",
            "image_analysis_id": image_analysis_id,
        },
    )
    assert diagnosis_response.status_code == 200
    diagnosis_body = diagnosis_response.json()

    # --- structured diagnosis + citation validation ---
    assert diagnosis_body["status"] == "completed"
    assert fake_client.messages.agent_call_count == 4
    cause = diagnosis_body["possible_causes"][0]
    assert cause["cause"] == "Blocked ventilation"
    assert set(cause["supporting_citations"]) == {DOC_CITATION, SENSOR_CITATION, image_citation}

    evidence_types = {e["type"] for e in diagnosis_body["evidence"]}
    assert evidence_types == {"document_chunk", "sensor_reading", "image_observation"}

    # --- confidence + severity + approval-required ---
    assert diagnosis_body["confidence"] > 0.75  # 3 evidence types + 1 cited cause, no tool errors
    assert diagnosis_body["severity"] == "high"
    assert diagnosis_body["requires_human_approval"] is True
    diagnosis_id = diagnosis_body["id"]

    # --- approval workflow: technician cannot approve, supervisor can ---
    tech_approve = await client.post(
        f"/api/v1/diagnoses/{diagnosis_id}/approve", headers=tech_headers, json={"comments": "x"}
    )
    assert tech_approve.status_code == 403

    supervisor = await _register(client, "e2e_supervisor", "acme", role="supervisor")
    supervisor_headers = {"Authorization": f"Bearer {supervisor['access_token']}"}
    approve_response = await client.post(
        f"/api/v1/diagnoses/{diagnosis_id}/approve",
        headers=supervisor_headers,
        json={"comments": "Confirmed via manual + sensor + visual evidence."},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["approval"]["decision"] == "approved"

    # --- audit record ---
    admin = await _register(client, "e2e_admin", "acme", role="admin")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
    audit_response = await client.get(
        "/api/v1/audit-logs",
        headers=admin_headers,
        params={"resource_type": "diagnosis", "resource_id": diagnosis_id},
    )
    assert audit_response.status_code == 200
    actions = [log["action"] for log in audit_response.json()]
    assert "diagnosis.created" in actions

    # --- tenant validation: a different tenant cannot see any of this ---
    other_tenant = await _register(client, "e2e_other", "globex", role="technician")
    other_headers = {"Authorization": f"Bearer {other_tenant['access_token']}"}
    cross_tenant_get = await client.get(
        f"/api/v1/diagnoses/{diagnosis_id}", headers=other_headers
    )
    assert cross_tenant_get.status_code == 404
    cross_tenant_image = await client.get(
        f"/api/v1/images/{image_analysis_id}", headers=other_headers
    )
    assert cross_tenant_image.status_code == 404
