"""Regression tests for the self-registration privilege-escalation hole:
/auth/register used to accept `role` and `tenant_id` from the request body,
so anyone could sign up as `admin` inside any existing company's tenant.
Sign-up now only creates a new workspace; joining one is admin-only."""
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from tests.helpers import PASSWORD, create_user, create_user_token, register_workspace


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_register_rejects_self_assigned_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "mallory",
            "email": "mallory@example.com",
            "password": PASSWORD,
            "tenant_id": "mallory_co",
            "role": "admin",
        },
    )
    assert response.status_code == 422


async def test_register_cannot_join_an_existing_tenant(client: AsyncClient) -> None:
    await register_workspace(client, "acme_admin", "acme")

    intruder = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "mallory",
            "email": "mallory@example.com",
            "password": PASSWORD,
            "tenant_id": "acme",
        },
    )
    assert intruder.status_code == 409
    assert "admin" in intruder.json()["detail"]

    # And the failed attempt left no account behind to log in with.
    login = await client.post(
        "/api/v1/auth/login", json={"username": "mallory", "password": PASSWORD}
    )
    assert login.status_code == 401


async def test_register_requires_tenant_id(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "nobody", "email": "nobody@example.com", "password": PASSWORD},
    )
    assert response.status_code == 422


async def test_tenant_backfilled_before_this_change_still_blocks_sign_up(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Mirrors the migration's backfill: a tenant row that exists without
    having been created through /auth/register still can't be claimed."""
    db_session.add(Tenant(id="legacy_co"))
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "late_signup",
            "email": "late@example.com",
            "password": PASSWORD,
            "tenant_id": "legacy_co",
        },
    )
    assert response.status_code == 409


async def test_admin_creates_user_in_own_tenant_with_role(client: AsyncClient) -> None:
    admin = await register_workspace(client, "acme_admin", "acme")

    created = await client.post(
        "/api/v1/users",
        headers=_auth(admin["access_token"]),
        json={
            "username": "sup_a",
            "email": "sup_a@example.com",
            "password": PASSWORD,
            "role": "supervisor",
        },
    )
    assert created.status_code == 201
    assert created.json()["role"] == "supervisor"
    assert created.json()["tenant_id"] == "acme"

    login = await client.post(
        "/api/v1/auth/login", json={"username": "sup_a", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["user"]["tenant_id"] == "acme"


async def test_create_user_rejects_a_tenant_field(client: AsyncClient) -> None:
    """An admin can't use user creation to plant an account in a different
    tenant either — the tenant always comes from the admin's own record."""
    admin = await register_workspace(client, "acme_admin", "acme")
    response = await client.post(
        "/api/v1/users",
        headers=_auth(admin["access_token"]),
        json={
            "username": "planted",
            "email": "planted@example.com",
            "password": PASSWORD,
            "tenant_id": "globex",
        },
    )
    assert response.status_code == 422


async def test_non_admins_cannot_manage_users(client: AsyncClient) -> None:
    for role in ("technician", "supervisor"):
        token = await create_user_token(client, f"{role}_a", "acme", role=role)
        create = await client.post(
            "/api/v1/users",
            headers=_auth(token),
            json={
                "username": f"made_by_{role}",
                "email": f"made_by_{role}@example.com",
                "password": PASSWORD,
                "role": "admin",
            },
        )
        assert create.status_code == 403
        listing = await client.get("/api/v1/users", headers=_auth(token))
        assert listing.status_code == 403


async def test_user_list_is_tenant_scoped(client: AsyncClient) -> None:
    acme_admin = await register_workspace(client, "acme_admin", "acme")
    await create_user(client, "tech_a", "acme")
    await create_user(client, "tech_b", "globex")

    response = await client.get("/api/v1/users", headers=_auth(acme_admin["access_token"]))
    assert response.status_code == 200
    assert {u["username"] for u in response.json()} == {"acme_admin", "tech_a"}


async def test_admin_can_change_role_and_deactivate(client: AsyncClient) -> None:
    admin = await register_workspace(client, "acme_admin", "acme")
    tech = await create_user(client, "tech_a", "acme")
    user_id = tech["user"]["id"]

    promoted = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=_auth(admin["access_token"]),
        json={"role": "supervisor"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "supervisor"

    deactivated = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=_auth(admin["access_token"]),
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    # The deactivated user's still-unexpired token stops working immediately.
    me = await client.get("/api/v1/auth/me", headers=_auth(tech["access_token"]))
    assert me.status_code == 401

    logs = await client.get(
        "/api/v1/audit-logs",
        headers=_auth(admin["access_token"]),
        params={"resource_type": "user", "resource_id": user_id},
    )
    actions = [log["action"] for log in logs.json()]
    assert actions.count("user.updated") == 2
    assert "user.created" in actions


async def test_admin_cannot_manage_another_tenants_user(client: AsyncClient) -> None:
    acme_admin = await register_workspace(client, "acme_admin", "acme")
    globex_tech = await create_user(client, "tech_g", "globex")

    response = await client.patch(
        f"/api/v1/users/{globex_tech['user']['id']}",
        headers=_auth(acme_admin["access_token"]),
        json={"role": "admin"},
    )
    assert response.status_code == 404


async def test_admin_cannot_lock_themselves_out(client: AsyncClient) -> None:
    admin = await register_workspace(client, "acme_admin", "acme")
    admin_id = admin["user"]["id"]

    for change in ({"role": "technician"}, {"is_active": False}):
        response = await client.patch(
            f"/api/v1/users/{admin_id}", headers=_auth(admin["access_token"]), json=change
        )
        assert response.status_code == 400

    me = await client.get("/api/v1/auth/me", headers=_auth(admin["access_token"]))
    assert me.json()["role"] == "admin"


async def test_create_user_rejects_duplicate_username(client: AsyncClient) -> None:
    admin = await register_workspace(client, "acme_admin", "acme")
    response = await client.post(
        "/api/v1/users",
        headers=_auth(admin["access_token"]),
        json={"username": "acme_admin", "email": "other@example.com", "password": PASSWORD},
    )
    assert response.status_code == 409
