import pytest
from httpx import AsyncClient

from app.main import settings

TOKEN = "t" * 40


async def test_metrics_open_when_no_token_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_token", "")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "python_info" in response.text


@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong-token", f"Basic {TOKEN}", f"Bearer {TOKEN}x"]
)
async def test_metrics_rejects_missing_or_wrong_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, authorization
) -> None:
    monkeypatch.setattr(settings, "metrics_token", TOKEN)
    headers = {"Authorization": authorization} if authorization else {}
    response = await client.get("/metrics", headers=headers)
    assert response.status_code == 401
    assert "python_info" not in response.text


async def test_metrics_accepts_the_configured_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_token", TOKEN)
    response = await client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert "python_info" in response.text
