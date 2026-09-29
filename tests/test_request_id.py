import uuid

import pytest
from httpx import AsyncClient


async def test_valid_client_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc_123.4"})
    assert response.headers["X-Request-ID"] == "trace-abc_123.4"


@pytest.mark.parametrize(
    "bad_value",
    [
        "x" * 129,  # oversized
        "has space",
        "fake\tentry",  # control character (log injection)
        "a;b",
    ],
)
async def test_invalid_client_request_id_is_replaced(client: AsyncClient, bad_value: str) -> None:
    response = await client.get("/api/v1/health", headers={"X-Request-ID": bad_value})
    echoed = response.headers["X-Request-ID"]
    assert echoed != bad_value
    uuid.UUID(echoed)  # a freshly generated one instead


async def test_missing_request_id_is_generated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    uuid.UUID(response.headers["X-Request-ID"])
