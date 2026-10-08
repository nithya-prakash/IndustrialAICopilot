import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.mcp_server.server import (
    McpIdentity,
    RateLimiter,
    ToolFailedError,
    authenticate,
    list_tool_specs,
    run_tool,
)
from app.models.audit_log import AuditLog
from app.services.auth_service import register_workspace
from app.tools.definitions import TOOL_DEFINITIONS


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    class _Ctx:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *exc: object) -> None:
            return None

    return lambda: _Ctx()  # type: ignore[return-value]


async def _identity(db: AsyncSession, tenant: str = "acme") -> McpIdentity:
    user = await register_workspace(
        db,
        username=f"svc_{tenant}",
        email=f"{tenant}@example.com",
        password="Passw0rd-123",
        tenant_id=tenant,
    )
    return McpIdentity(user_id=user.id, tenant_id=user.tenant_id, username=user.username)


def test_exposes_every_agent_tool_with_its_schema() -> None:
    specs = list_tool_specs()
    assert [s.name for s in specs] == [t["name"] for t in TOOL_DEFINITIONS]
    for spec, tool in zip(specs, TOOL_DEFINITIONS, strict=True):
        assert spec.inputSchema == tool["input_schema"]


async def test_call_tool_returns_json_output_and_writes_an_audit_entry(db_session: AsyncSession):
    identity = await _identity(db_session)
    result = await run_tool(
        "calculate",
        {"expression": "6 * 7"},
        identity=identity,
        session_factory=_factory(db_session),
    )
    assert json.loads(result[0].text) == {"output": {"result": 42}, "citations": []}
    entry = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "mcp.tool_call"))
    ).scalar_one()
    assert entry.actor_user_id == identity.user_id and entry.tenant_id == "acme"
    assert entry.detail == {"tool": "calculate", "argument_names": ["expression"], "outcome": "ok"}
    assert "42" not in json.dumps(entry.detail) and "6 * 7" not in json.dumps(entry.detail)


async def test_tool_errors_are_flagged_and_audited(db_session: AsyncSession):
    identity = await _identity(db_session)
    with pytest.raises(ToolFailedError):
        await run_tool(
            "calculate",
            {"expression": "__import__('os')"},
            identity=identity,
            session_factory=_factory(db_session),
        )
    with pytest.raises(ToolFailedError, match="Unknown tool"):
        await run_tool("nope", {}, identity=identity, session_factory=_factory(db_session))
    rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "mcp.tool_call"))
    ).scalars()
    assert [r.detail["outcome"] for r in rows] == ["error", "error"]


async def test_invalid_arguments_are_rejected_by_central_validation(db_session: AsyncSession):
    identity = await _identity(db_session)
    with pytest.raises(ToolFailedError, match="Unknown argument"):
        await run_tool(
            "calculate",
            {"expression": "1+1", "sneaky": "x"},
            identity=identity,
            session_factory=_factory(db_session),
        )


async def test_deactivated_service_account_is_locked_out(db_session: AsyncSession):
    identity = await _identity(db_session)
    from app.models.user import User

    user = await db_session.get(User, identity.user_id)
    user.is_active = False
    await db_session.commit()
    with pytest.raises(ToolFailedError, match="no longer active"):
        await run_tool(
            "calculate",
            {"expression": "1+1"},
            identity=identity,
            session_factory=_factory(db_session),
        )


async def test_rate_limit_blocks_and_is_audited(db_session: AsyncSession):
    identity = await _identity(db_session)
    limiter = RateLimiter(max_calls=2, window_seconds=60)
    for _ in range(2):
        await run_tool(
            "calculate",
            {"expression": "1+1"},
            identity=identity,
            session_factory=_factory(db_session),
            limiter=limiter,
        )
    with pytest.raises(ToolFailedError, match="Rate limit"):
        await run_tool(
            "calculate",
            {"expression": "1+1"},
            identity=identity,
            session_factory=_factory(db_session),
            limiter=limiter,
        )
    rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "mcp.tool_call"))
    ).scalars()
    assert [r.detail["outcome"] for r in rows] == ["ok", "ok", "rate_limited"]


async def test_authenticate_derives_tenant_from_the_account(db_session: AsyncSession, monkeypatch):
    await register_workspace(
        db_session,
        username="svc_acme",
        email="a@example.com",
        password="Passw0rd-123",
        tenant_id="acme",
    )
    monkeypatch.setenv("MCP_USERNAME", "svc_acme")
    monkeypatch.setenv("MCP_PASSWORD", "Passw0rd-123")
    identity = await authenticate(_factory(db_session))
    assert identity.tenant_id == "acme" and identity.username == "svc_acme"

    monkeypatch.setenv("MCP_PASSWORD", "wrong-password")
    with pytest.raises(SystemExit, match="authentication failed"):
        await authenticate(_factory(db_session))
    monkeypatch.delenv("MCP_USERNAME")
    with pytest.raises(SystemExit, match="must be set"):
        await authenticate(_factory(db_session))
