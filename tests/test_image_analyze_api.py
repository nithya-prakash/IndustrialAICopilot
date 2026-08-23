import io
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image


def _make_jpeg_bytes(width: int = 200, height: int = 150) -> bytes:
    image = Image.new("RGB", (width, height), color=(80, 80, 80))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))


async def _register(client: AsyncClient, username: str, tenant_id: str) -> str:
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


async def test_analyze_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/images/analyze",
        files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 401


async def test_analyze_rejects_unsupported_content_type(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("doc.pdf", b"%PDF-1.4 fake pdf content", "application/pdf")},
    )
    assert response.status_code == 415


async def test_analyze_rejects_corrupt_image_bytes(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.jpg", b"not actually a jpeg", "image/jpeg")},
    )
    assert response.status_code == 400


async def test_analyze_without_api_key_stores_record_with_failed_status(
    client: AsyncClient,
) -> None:
    """No ANTHROPIC_API_KEY/VISION_API_KEY is configured in the test
    environment — this exercises the real failure path end-to-end (upload,
    validation, storage, DB persistence) without mocking the VLM call."""
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
        data={"equipment_type": "electric_motor", "equipment_id": "MOTOR-001"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"]
    assert "API key" in body["error_message"]
    assert body["equipment_type"] == "electric_motor"
    assert body["observations"] == []


async def test_get_analysis_isolated_across_tenants(client: AsyncClient) -> None:
    token_a = await _register(client, "tech_a", "acme")
    token_b = await _register(client, "tech_b", "globex")

    upload = await client.post(
        "/api/v1/images/analyze",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("photo.jpg", _make_jpeg_bytes(), "image/jpeg")},
    )
    analysis_id = upload.json()["id"]

    same_tenant = await client.get(
        f"/api/v1/images/{analysis_id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    other_tenant = await client.get(
        f"/api/v1/images/{analysis_id}", headers={"Authorization": f"Bearer {token_b}"}
    )

    assert same_tenant.status_code == 200
    assert other_tenant.status_code == 404
