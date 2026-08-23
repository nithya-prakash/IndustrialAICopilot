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
    """Uploads write real files (not mocked) — point storage at a tmp dir so
    test runs don't leave PDFs behind in the real data/manuals/ directory."""
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


async def test_upload_rejects_non_pdf_content_type(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


async def test_upload_rejects_content_not_matching_pdf_magic_bytes(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("fake.pdf", b"not actually a pdf", "application/pdf")},
    )
    assert response.status_code == 400


async def test_upload_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("manual.pdf", MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 401


async def test_successful_upload_creates_document_in_uploaded_status(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("manual.pdf", MINIMAL_PDF, "application/pdf")},
        data={"equipment_type": "electric_motor", "equipment_id": "MOTOR-001"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["version_number"] == 1
    assert body["equipment_type"] == "electric_motor"
    assert body["equipment_id"] == "MOTOR-001"


async def test_document_isolated_across_tenants(client: AsyncClient) -> None:
    token_a = await _register(client, "tech_a", "acme")
    token_b = await _register(client, "tech_b", "globex")

    await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("manual.pdf", MINIMAL_PDF, "application/pdf")},
    )

    response_a = await client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token_a}"}
    )
    response_b = await client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token_b}"}
    )

    assert len(response_a.json()["documents"]) == 1
    assert len(response_b.json()["documents"]) == 0


async def test_same_tenant_users_share_documents(client: AsyncClient) -> None:
    token_a = await _register(client, "tech_a", "acme")
    token_c = await _register(client, "tech_c", "acme")

    await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("manual.pdf", MINIMAL_PDF, "application/pdf")},
    )

    response_c = await client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token_c}"}
    )
    assert len(response_c.json()["documents"]) == 1


async def test_delete_requires_matching_tenant(client: AsyncClient) -> None:
    token_a = await _register(client, "tech_a", "acme")
    token_b = await _register(client, "tech_b", "globex")

    upload = await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("manual.pdf", MINIMAL_PDF, "application/pdf")},
    )
    document_id = upload.json()["id"]

    cross_tenant_delete = await client.delete(
        f"/api/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert cross_tenant_delete.status_code == 404

    same_tenant_delete = await client.delete(
        f"/api/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert same_tenant_delete.status_code == 204
