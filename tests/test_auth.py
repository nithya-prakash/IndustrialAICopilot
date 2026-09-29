from httpx import AsyncClient

from app.core.security import decode_access_token


async def test_register_creates_user_and_returns_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
            "tenant_id": "jane_co",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["username"] == "tech_jane"
    # Signing up creates a new workspace; its creator is that workspace's admin.
    assert body["user"]["role"] == "admin"
    assert body["user"]["tenant_id"] == "jane_co"
    assert "hashed_password" not in body["user"]

    payload = decode_access_token(body["access_token"])
    assert payload["sub"] == body["user"]["id"]
    assert payload["role"] == "admin"


async def test_register_rejects_duplicate_username(client: AsyncClient) -> None:
    payload = {
        "username": "tech_jane",
        "email": "jane@example.com",
        "password": "correct-horse-battery",
    }
    first = await client.post("/api/v1/auth/register", json={**payload, "tenant_id": "co_1"})
    assert first.status_code == 201

    duplicate = await client.post(
        "/api/v1/auth/register",
        json={**payload, "email": "someone-else@example.com", "tenant_id": "co_2"},
    )
    assert duplicate.status_code == 409


async def test_login_succeeds_with_correct_credentials(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
            "tenant_id": "tech_jane_co",
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
            "tenant_id": "tech_jane_co",
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
            "tenant_id": "tech_jane_co",
        },
    )
    token = register.json()["access_token"]

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "tech_jane"


async def test_logout_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 401


async def test_logout_revokes_token_so_it_cannot_be_used_again(client: AsyncClient) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
            "tenant_id": "tech_jane_co",
        },
    )
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    before = await client.get("/api/v1/auth/me", headers=headers)
    assert before.status_code == 200

    logout = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 204

    after = await client.get("/api/v1/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["detail"] == "Token has been revoked"


async def test_logging_out_one_users_token_does_not_affect_another(
    client: AsyncClient,
) -> None:
    register_a = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_a",
            "email": "a@example.com",
            "password": "correct-horse-battery",
            "tenant_id": "tech_a_co",
        },
    )
    register_b = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_b",
            "email": "b@example.com",
            "password": "correct-horse-battery",
            "tenant_id": "tech_b_co",
        },
    )
    token_a = register_a.json()["access_token"]
    token_b = register_b.json()["access_token"]

    await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token_a}"})

    still_valid = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert still_valid.status_code == 200
    assert still_valid.json()["username"] == "tech_b"


async def test_unknown_user_login_costs_the_same_bcrypt_work_as_a_wrong_password(
    client: AsyncClient, monkeypatch
) -> None:
    """Unknown usernames used to skip bcrypt entirely and answer faster than
    a wrong password, revealing which usernames exist. Now every failed login
    runs exactly one bcrypt verification and gets the identical 401."""
    from app.core import security

    bcrypt_checks = {"n": 0}
    real_verify = security._pwd_context.verify

    def counting_verify(*args, **kwargs):
        bcrypt_checks["n"] += 1
        return real_verify(*args, **kwargs)

    # passlib's dummy_verify() also goes through verify(), so this counts both.
    monkeypatch.setattr(security._pwd_context, "verify", counting_verify)

    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "tech_jane",
            "email": "jane@example.com",
            "password": "correct-horse-battery",
            "tenant_id": "tech_jane_co",
        },
    )

    async def failed_login(username: str, password: str):
        bcrypt_checks["n"] = 0
        response = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        return response, bcrypt_checks["n"]

    unknown, unknown_checks = await failed_login("nobody", "whatever-123")
    wrong, wrong_checks = await failed_login("tech_jane", "wrong-password")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert unknown_checks == wrong_checks == 1
