from datetime import UTC, datetime

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


async def test_upload_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sensors/upload",
        json={"equipment_id": "MOTOR-001", "readings": {"temperature": 82.3}},
    )
    assert response.status_code == 401


async def test_upload_rejects_empty_readings(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/sensors/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={"equipment_id": "MOTOR-001", "readings": {}},
    )
    assert response.status_code == 422  # pydantic min_length=1 on the dict


async def test_upload_creates_one_row_per_metric(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.post(
        "/api/v1/sensors/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "equipment_id": "MOTOR-001",
            "equipment_type": "electric_motor",
            "readings": {"temperature": 82.3, "vibration_rms": 4.72, "rpm": 1480, "pressure": 2.1},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["readings"]) == 4
    metrics = {r["metric"] for r in body["readings"]}
    assert metrics == {"temperature", "vibration_rms", "rpm", "pressure"}


async def test_history_returns_only_requested_metric_and_range(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    await client.post(
        "/api/v1/sensors/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "equipment_id": "MOTOR-001",
            "readings": {"temperature": 60.0, "vibration_rms": 2.0},
            "recorded_at": "2026-08-10T12:00:00Z",
        },
    )
    await client.post(
        "/api/v1/sensors/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "equipment_id": "MOTOR-001",
            "readings": {"temperature": 61.0},
            "recorded_at": "2026-08-20T12:00:00Z",  # outside the queried range
        },
    )

    response = await client.get(
        "/api/v1/sensors/MOTOR-001/history",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "metric": "temperature",
            "start_time": "2026-08-01T00:00:00Z",
            "end_time": "2026-08-15T00:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["readings"]) == 1
    assert body["readings"][0]["value"] == 60.0


async def test_history_isolated_across_tenants(client: AsyncClient) -> None:
    token_a = await _register(client, "tech_a", "acme")
    token_b = await _register(client, "tech_b", "globex")

    await client.post(
        "/api/v1/sensors/upload",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "equipment_id": "MOTOR-001",
            "readings": {"temperature": 60.0},
            "recorded_at": "2026-08-10T12:00:00Z",
        },
    )

    params = {
        "metric": "temperature",
        "start_time": "2026-08-01T00:00:00Z",
        "end_time": "2026-08-15T00:00:00Z",
    }
    response_a = await client.get(
        "/api/v1/sensors/MOTOR-001/history",
        headers={"Authorization": f"Bearer {token_a}"},
        params=params,
    )
    response_b = await client.get(
        "/api/v1/sensors/MOTOR-001/history",
        headers={"Authorization": f"Bearer {token_b}"},
        params=params,
    )
    assert len(response_a.json()["readings"]) == 1
    assert len(response_b.json()["readings"]) == 0


async def test_analysis_flags_vibration_above_manual_threshold(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    base = datetime(2026, 8, 10, tzinfo=UTC)
    for i in range(5):
        await client.post(
            "/api/v1/sensors/upload",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "equipment_id": "MOTOR-001",
                "readings": {"vibration_rms": 2.0 if i < 4 else 6.0},
                "recorded_at": base.replace(hour=i).isoformat(),
            },
        )

    response = await client.get(
        "/api/v1/sensors/MOTOR-001/analysis",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "metric": "vibration_rms",
            "start_time": "2026-08-10T00:00:00Z",
            "end_time": "2026-08-10T23:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reading_count"] == 5
    assert len(body["threshold_violations"]) == 1
    assert body["threshold_violations"][0]["value"] == 6.0
    assert "manual" in body["threshold_violations"][0]["source"]


async def test_analysis_with_no_readings_returns_empty_report(client: AsyncClient) -> None:
    token = await _register(client, "tech_a", "acme")
    response = await client.get(
        "/api/v1/sensors/NONEXISTENT/analysis",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "metric": "temperature",
            "start_time": "2026-08-01T00:00:00Z",
            "end_time": "2026-08-15T00:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reading_count"] == 0
    assert body["summary"] is None
    assert body["trend"] is None
