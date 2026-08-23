from httpx import AsyncClient

from app.core.security import decode_access_token


async def test_register_creates_user_and_returns_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
            "role": "technician",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["username"] == "tech_jane"
    assert body["user"]["role"] == "technician"
    assert "hashed_password" not in body["user"]

    payload = decode_access_token(body["access_token"])
    assert payload["sub"] == body["user"]["id"]
    assert payload["role"] == "technician"


async def test_register_rejects_duplicate_username(client: AsyncClient) -> None:
    payload = {
        "username": "tech_jane",
        "email": "jane@example.com",
        "password": "correct-horse-battery",
    }
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    duplicate = await client.post(
        "/api/v1/auth/register",
        json={**payload, "email": "someone-else@example.com"},
    )
    assert duplicate.status_code == 409


async def test_login_succeeds_with_correct_credentials(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
        },
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "tech_jane", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
        },
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "tech_jane", "password": "wrong-password"},
    )
    assert response.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_me_returns_current_user_with_valid_token(client: AsyncClient) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
        },
    )
    token = register.json()["access_token"]

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "tech_jane"
