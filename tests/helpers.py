"""Shared test helpers for getting an authenticated user into a tenant.

Self-service /auth/register only ever creates a brand-new workspace (with
the caller as its admin) — the only way into an existing tenant, at any
role, is its admin calling POST /api/v1/users. Tests that need several
users in one tenant go through exactly that real path rather than seeding
users straight into the DB, so the helpers exercise the same boundary
production traffic does.
"""
from httpx import AsyncClient

PASSWORD = "correct-horse-battery"


def _workspace_admins(client: AsyncClient) -> dict[str, str]:
    """Each tenant's admin token, stored on the client object itself — every
    test gets a fresh client (and a fresh in-memory DB) from
    tests/conftest.py, so a tenant created in one test never leaks into
    another the way a module-level cache keyed on id(client) could once a
    garbage-collected client's id is reused."""
    if not hasattr(client, "_test_workspace_admins"):
        client._test_workspace_admins = {}
    return client._test_workspace_admins


async def register_workspace(client: AsyncClient, username: str, tenant_id: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
            "tenant_id": tenant_id,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    _workspace_admins(client)[tenant_id] = body["access_token"]
    return body


async def create_user(
    client: AsyncClient, username: str, tenant_id: str, role: str = "technician"
) -> dict:
    """Returns the /auth/login response body ({"access_token", "user", ...})
    for a new user with `role` in `tenant_id`, creating the tenant (via a
    separate `<tenant>_owner` admin) on first use."""
    admins = _workspace_admins(client)
    if tenant_id not in admins:
        if role == "admin":
            # The requested admin can simply be the workspace's creator.
            return await register_workspace(client, username, tenant_id)
        await register_workspace(client, f"{tenant_id}_owner", tenant_id)

    created = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admins[tenant_id]}"},
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
            "role": role,
        },
    )
    assert created.status_code == 201, created.text

    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return login.json()


async def create_user_token(
    client: AsyncClient, username: str, tenant_id: str = "acme", role: str = "technician"
) -> str:
    return (await create_user(client, username, tenant_id, role))["access_token"]
