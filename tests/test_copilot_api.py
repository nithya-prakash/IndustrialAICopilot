from httpx import AsyncClient


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


async def test_query_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/copilot/query", json={"question": "test"})
    assert response.status_code == 401


async def test_query_without_api_key_returns_failed_diagnosis_not_500(client: AsyncClient) -> None:
    """No ANTHROPIC_API_KEY is configured in the test environment — this
    exercises the real failure path end-to-end through the HTTP layer
    (auth -> orchestrator -> clean failure), without mocking the LLM call."""
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/copilot/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "Why is the motor overheating?", "equipment_id": "MOTOR-001"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"]
    assert "API key" in body["error_message"]
    assert body["requires_human_approval"] is True


async def test_failed_diagnosis_is_audit_logged(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    create = await client.post(
        "/api/v1/copilot/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "test question"},
    )
    diagnosis_id = create.json()["id"]

    admin_response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "admin_a",
            "email": "admin_a@example.com",
            "password": "correct-horse-battery",
            "tenant_id": "acme",
            "role": "admin",
        },
    )
    admin_token = admin_response.json()["access_token"]

    logs = await client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"resource_type": "diagnosis", "resource_id": diagnosis_id},
    )
    assert logs.status_code == 200
    actions = [log["action"] for log in logs.json()]
    assert "diagnosis.failed" in actions


async def test_diagnoses_list_and_get_isolated_by_tenant(client: AsyncClient) -> None:
    token_a = await _register(client, "tech_a", "acme")
    token_b = await _register(client, "tech_b", "globex")

    create = await client.post(
        "/api/v1/copilot/query",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"question": "test question"},
    )
    diagnosis_id = create.json()["id"]

    list_a = await client.get("/api/v1/diagnoses", headers={"Authorization": f"Bearer {token_a}"})
    list_b = await client.get("/api/v1/diagnoses", headers={"Authorization": f"Bearer {token_b}"})
    assert len(list_a.json()) == 1
    assert len(list_b.json()) == 0

    get_a = await client.get(
        f"/api/v1/diagnoses/{diagnosis_id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    get_b = await client.get(
        f"/api/v1/diagnoses/{diagnosis_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert get_a.status_code == 200
    assert get_b.status_code == 404


async def test_diagnosis_report_endpoint(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    create = await client.post(
        "/api/v1/copilot/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "test question"},
    )
    diagnosis_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/diagnoses/{diagnosis_id}/report", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert "Diagnostic Report" in response.text


async def test_conversations_list_and_get_isolated_by_tenant(client: AsyncClient) -> None:
    token_a = await _register(client, "tech_a", "acme")
    token_b = await _register(client, "tech_b", "globex")

    await client.post(
        "/api/v1/copilot/query",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"question": "test question"},
    )

    list_a = await client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token_a}"}
    )
    list_b = await client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert len(list_a.json()) == 1
    assert len(list_b.json()) == 0

    conversation_id = list_a.json()[0]["id"]
    detail_a = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers={"Authorization": f"Bearer {token_a}"}
    )
    detail_b = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert detail_a.status_code == 200
    # only the user question — a failed diagnosis run has no assistant message
    assert len(detail_a.json()["messages"]) == 1
    assert detail_b.status_code == 404


async def test_conversation_not_found_returns_404(client: AsyncClient) -> None:
    import uuid

    token = await _register(client, "tech_a", "acme")
    response = await client.get(
        f"/api/v1/conversations/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
