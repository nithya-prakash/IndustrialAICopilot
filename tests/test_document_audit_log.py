from pathlib import Path

import pytest
from httpx import AsyncClient

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


@pytest.fixture(autouse=True)
def no_celery_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.document_service.process_document_version_task.delay",
        lambda *args, **kwargs: None,
    )


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))


async def _register(client: AsyncClient, username: str, tenant_id: str, role: str = "admin") -> str:
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
    return response.json()["access_token"]


async def test_document_upload_and_delete_produce_audit_log_entries(client: AsyncClient) -> None:
    token = await _register(client, "admin_a", "acme")
    headers = {"Authorization": f"Bearer {token}"}

    upload = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"file": ("manual.pdf", MINIMAL_PDF, "application/pdf")},
    )
    document_id = upload.json()["id"]

    await client.delete(f"/api/v1/documents/{document_id}", headers=headers)

    logs = await client.get(
        "/api/v1/audit-logs", headers=headers, params={"resource_type": "document"}
    )
    assert logs.status_code == 200
    actions = [log["action"] for log in logs.json()]
    assert "document.uploaded" in actions
    assert "document.deleted" in actions
    assert all(log["resource_id"] == document_id for log in logs.json())
