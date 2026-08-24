"""Mocked VLM integration test — exercises the REAL pipeline (HTTP upload
-> content-type/magic-byte validation -> preprocessing -> vision analyzer
-> structured-result parsing -> DB persistence) through the actual FastAPI
app and a real JPEG. Only the Anthropic SDK network call is faked; nothing
about the analyzer, preprocessing, or persistence layer is mocked.

This proves the pipeline wiring is correct end-to-end. It does NOT prove
real model accuracy — that requires live provider credentials (see
tests/live/, added separately) and is never implied by these tests.
"""
import io

import pytest
from httpx import AsyncClient
from PIL import Image

from app.config import get_settings


def _jpeg_bytes(width: int = 200, height: int = 150) -> bytes:
    image = Image.new("RGB", (width, height), color=(80, 80, 80))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def anthropic_vision_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the API key check is bypassed; the actual network call is
    intercepted at the Anthropic SDK client boundary by each test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "vision_provider", "anthropic")


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]
        self.usage = _FakeUsage()
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, outcome) -> None:
        self._outcome = outcome
        self.call_count = 0

    async def create(self, **kwargs):
        self.call_count += 1
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _FakeAnthropicClient:
    def __init__(self, outcome, **kwargs) -> None:
        self.messages = _FakeMessages(outcome)


async def _register(client: AsyncClient, username: str, tenant_id: str = "acme") -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct-horse-battery",
            "tenant_id": tenant_id,
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


async def test_successful_provider_response_produces_ready_analysis(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    valid_json = (
        '{"observations": [{"description": "Visible surface corrosion on housing", '
        '"confidence": 0.82}], "limitations": ["Lighting is dim in the lower half."]}'
    )
    fake_client = _FakeAnthropicClient(_FakeResponse(valid_json))
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kwargs: fake_client)

    token = await _register(client, "vlm_success_tech")
    response = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("motor.jpg", _jpeg_bytes(), "image/jpeg")},
        data={"equipment_type": "electric_motor", "equipment_id": "MOTOR-001"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["observations"] == [
        {"description": "Visible surface corrosion on housing", "confidence": 0.82}
    ]
    assert body["limitations"] == ["Lighting is dim in the lower half."]
    assert fake_client.messages.call_count == 1

    # confirm it was really persisted, not just returned in the response
    fetched = await client.get(
        f"/api/v1/images/{body['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "ready"


async def test_malformed_provider_response_produces_failed_analysis_not_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_client = _FakeAnthropicClient(_FakeResponse("this is not JSON at all"))
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kwargs: fake_client)

    token = await _register(client, "vlm_malformed_tech")
    response = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("motor.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"]
    assert "valid JSON" in body["error_message"]
    assert body["observations"] == []


async def test_timeout_after_retries_exhausted_produces_failed_analysis_not_500(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw provider timeout is retried (app/core/retry.py), then — once
    exhausted — wrapped into a clean 'failed' record rather than leaking as
    an unhandled 500, matching the malformed-response case above."""
    import anthropic

    settings = get_settings()
    monkeypatch.setattr(settings, "retry_wait_min_seconds", 0.001)
    monkeypatch.setattr(settings, "retry_wait_max_seconds", 0.002)

    timeout_exc = anthropic.APITimeoutError(request=object())
    fake_client = _FakeAnthropicClient(timeout_exc)
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kwargs: fake_client)

    token = await _register(client, "vlm_timeout_tech")
    response = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("motor.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"]
    assert "timed out" in body["error_message"].lower() or "failed" in body["error_message"].lower()
    # retried up to the configured bound (default 3), not just attempted once
    assert fake_client.messages.call_count == settings.retry_max_attempts


async def test_rejects_invalid_image_before_ever_calling_the_provider(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validation happens before the provider call — corrupt bytes never
    reach the (mocked) network client at all."""
    fake_client = _FakeAnthropicClient(_FakeResponse('{"observations": [], "limitations": []}'))
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kwargs: fake_client)

    token = await _register(client, "vlm_invalid_tech")
    response = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.jpg", b"not actually a jpeg", "image/jpeg")},
    )

    assert response.status_code == 400
    assert fake_client.messages.call_count == 0
