"""Oversized client input is rejected with a 422 before it reaches an LLM
prompt (billed per token) or a fixed-width DB column (which used to fail
as a Postgres error instead)."""
import io

import pytest
from httpx import AsyncClient
from PIL import Image

from app.schemas.limits import (
    EQUIPMENT_FIELD_MAX_CHARS,
    MAX_SENSOR_READINGS,
    QUESTION_MAX_CHARS,
    SENSOR_METRIC_MAX_CHARS,
)
from tests.helpers import create_user_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.document_service.process_document_version_task.delay",
        lambda *args, **kwargs: None,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"question": "x" * (QUESTION_MAX_CHARS + 1)},
        {"question": "   "},
        {"equipment_id": "M" * (EQUIPMENT_FIELD_MAX_CHARS + 1)},
        {"equipment_type": "t" * (EQUIPMENT_FIELD_MAX_CHARS + 1)},
        {"sensor_readings": {f"m{i}": 1.0 for i in range(MAX_SENSOR_READINGS + 1)}},
        {"sensor_readings": {"t" * (SENSOR_METRIC_MAX_CHARS + 1): 1.0}},
    ],
)
async def test_copilot_query_rejects_oversized_input(client: AsyncClient, overrides) -> None:
    token = await create_user_token(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/copilot/query",
        headers=_auth(token),
        json={"question": "Why is the motor hot?", **overrides},
    )
    assert response.status_code == 422


async def test_copilot_query_at_the_limit_is_accepted(client: AsyncClient) -> None:
    token = await create_user_token(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/copilot/query",
        headers=_auth(token),
        json={
            "question": "x" * QUESTION_MAX_CHARS,
            "equipment_id": "M" * EQUIPMENT_FIELD_MAX_CHARS,
            "sensor_readings": {f"m{i}": 1.0 for i in range(MAX_SENSOR_READINGS)},
        },
    )
    # No API key in tests, so the diagnosis itself fails cleanly — the point
    # is that the input passed validation.
    assert response.status_code == 200


async def test_sensor_upload_rejects_nan_and_oversized_fields(client: AsyncClient) -> None:
    token = await create_user_token(client, "tech_a", "acme")
    for body in (
        {"equipment_id": "M1", "readings": {"temperature": float("nan")}},
        {"equipment_id": "M1", "readings": {"temperature": float("inf")}},
        {"equipment_id": "M" * (EQUIPMENT_FIELD_MAX_CHARS + 1), "readings": {"t": 1.0}},
        {"equipment_id": "M1", "equipment_type": "t" * 200, "readings": {"t": 1.0}},
    ):
        response = await client.post(
            "/api/v1/sensors/upload",
            headers={**_auth(token), "Content-Type": "application/json"},
            # Python's json module writes NaN/Infinity literals, as a naive
            # client would; the API must still refuse them.
            content=__import__("json").dumps(body),
        )
        assert response.status_code == 422, body


async def test_image_analyze_rejects_oversized_question(client: AsyncClient) -> None:
    token = await create_user_token(client, "tech_a", "acme")
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, format="JPEG")
    response = await client.post(
        "/api/v1/images/analyze",
        headers=_auth(token),
        files={"file": ("photo.jpg", buf.getvalue(), "image/jpeg")},
        data={"question": "x" * (QUESTION_MAX_CHARS + 1)},
    )
    assert response.status_code == 422


async def test_document_upload_rejects_oversized_equipment_id(client: AsyncClient) -> None:
    token = await create_user_token(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/documents/upload",
        headers=_auth(token),
        files={"file": ("m.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"equipment_id": "M" * (EQUIPMENT_FIELD_MAX_CHARS + 1)},
    )
    assert response.status_code == 422
