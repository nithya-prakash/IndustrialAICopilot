"""Proves rate limits are genuinely enforced (real 429s from real request
sequences against the test client), not just configured-but-inert.

Each `@limiter.limit(...)`-decorated route (auth register/login, document
upload, image analyze, copilot query) is driven past its configured
threshold and must start returning 429. Health/metrics stay unrestricted
by design (no decorator) and must not 429 no matter how many requests.
"""
import io

import pytest
from httpx import AsyncClient
from PIL import Image

from app.config import get_settings
from app.observability.metrics import rate_limit_exceeded_total

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


def _limit_count(limit: str) -> int:
    """'10/minute' -> 10"""
    return int(limit.split("/")[0])


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (64, 64), color=(80, 80, 80))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def no_celery_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.document_service.process_document_version_task.delay",
        lambda *args, **kwargs: None,
    )


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


async def test_login_rate_limit_returns_429_after_threshold(client: AsyncClient) -> None:
    limit = _limit_count(get_settings().rate_limit_auth)
    payload = {"username": "nobody", "password": "wrong-password"}

    statuses = []
    for _ in range(limit + 1):
        response = await client.post("/api/v1/auth/login", json=payload)
        statuses.append(response.status_code)

    # every attempt below the threshold reaches the handler (invalid creds -> 401)
    assert all(status == 401 for status in statuses[:limit])
    # the one that pushes past the threshold is rejected before the handler runs
    assert statuses[limit] == 429
    assert "rate limit" in response.text.lower()


async def test_register_rate_limit_returns_429_after_threshold(client: AsyncClient) -> None:
    limit = _limit_count(get_settings().rate_limit_auth)

    statuses = []
    for i in range(limit + 1):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": f"flood_{i}",
                "email": f"flood_{i}@example.com",
                "password": "correct-horse-battery",
            },
        )
        statuses.append(response.status_code)

    assert all(status == 201 for status in statuses[:limit])
    assert statuses[limit] == 429


async def test_upload_rate_limit_returns_429_after_threshold(client: AsyncClient) -> None:
    limit = _limit_count(get_settings().rate_limit_upload)
    token = await _register(client, "tech_upload")
    headers = {"Authorization": f"Bearer {token}"}

    statuses = []
    for _ in range(limit + 1):
        response = await client.post(
            "/api/v1/documents/upload",
            headers=headers,
            files={"file": ("manual.pdf", MINIMAL_PDF, "application/pdf")},
        )
        statuses.append(response.status_code)

    assert all(status == 201 for status in statuses[:limit])
    assert statuses[limit] == 429


async def test_image_analyze_rate_limit_returns_429_after_threshold(client: AsyncClient) -> None:
    limit = _limit_count(get_settings().rate_limit_ai)
    token = await _register(client, "tech_image")
    headers = {"Authorization": f"Bearer {token}"}

    statuses = []
    for _ in range(limit + 1):
        response = await client.post(
            "/api/v1/images/analyze",
            headers=headers,
            files={"file": ("photo.jpg", _jpeg_bytes(), "image/jpeg")},
        )
        statuses.append(response.status_code)

    # no API key configured in the test env -> 201 with a failed-status body,
    # not a rate-limit rejection, for every request under the threshold
    assert all(status == 201 for status in statuses[:limit])
    assert statuses[limit] == 429


async def test_copilot_query_rate_limit_returns_429_after_threshold(client: AsyncClient) -> None:
    limit = _limit_count(get_settings().rate_limit_ai)
    token = await _register(client, "tech_copilot")
    headers = {"Authorization": f"Bearer {token}"}

    statuses = []
    for _ in range(limit + 1):
        response = await client.post(
            "/api/v1/copilot/query",
            headers=headers,
            json={"question": "Why is the motor overheating?"},
        )
        statuses.append(response.status_code)

    assert all(status == 200 for status in statuses[:limit])
    assert statuses[limit] == 429


async def test_rate_limit_exceeded_increments_metric(client: AsyncClient) -> None:
    limit = _limit_count(get_settings().rate_limit_auth)
    before = rate_limit_exceeded_total.labels(path="/api/v1/auth/login")._value.get()

    for _ in range(limit + 1):
        response = await client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "wrong"}
        )

    after = rate_limit_exceeded_total.labels(path="/api/v1/auth/login")._value.get()
    assert response.status_code == 429
    assert after == before + 1


async def test_health_and_metrics_endpoints_are_never_rate_limited(client: AsyncClient) -> None:
    limit = _limit_count(get_settings().rate_limit_default)

    for _ in range(limit + 5):
        health = await client.get("/api/v1/health")
        assert health.status_code == 200

    metrics_response = await client.get("/metrics")
    assert metrics_response.status_code == 200
