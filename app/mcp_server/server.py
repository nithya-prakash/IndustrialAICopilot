"""Standalone MCP server exposing the Copilot's diagnostic tools (including past-incident search).

Reuses TOOL_DEFINITIONS and execute_tool unchanged, so any MCP client hits exactly
the code path the in-app agent uses, including tenant scoping and citation strings.
Runs as its own process over stdio, as an authenticated service account:

    MCP_USERNAME=mcp_service MCP_PASSWORD=... python -m app.mcp_server.server

The tenant is the account's own; clients cannot choose one. Each call re-checks that the account
is still active, is rate limited (60/min), and is written to the audit log as `mcp.tool_call`
(tool name and argument names only, never argument values).
"""

import asyncio
import json
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User
from app.services.audit_service import log_event
from app.services.auth_service import InvalidCredentialsError, authenticate_user
from app.tools.definitions import TOOL_DEFINITIONS
from app.tools.executor import ToolContext, execute_tool

SERVER_NAME = "industrial-copilot"


def list_tool_specs() -> list[types.Tool]:
    return [
        types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"])
        for t in TOOL_DEFINITIONS
    ]


class ToolFailedError(Exception):
    """Raised for a failed tool call; the MCP SDK turns it into an isError result."""


@dataclass(frozen=True)
class McpIdentity:
    """The authenticated service account the server acts as. The tenant always comes from this
    user, never from a client-supplied or free-form setting."""

    user_id: uuid.UUID
    tenant_id: str
    username: str


class RateLimiter:
    """Sliding-window limit on tool calls for this process (a runaway or injected client cannot
    hammer the database or the embedding model)."""

    def __init__(self, max_calls: int = 60, window_seconds: float = 60.0) -> None:
        self.max_calls, self.window = max_calls, window_seconds
        self._calls: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > self.window:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            return False
        self._calls.append(now)
        return True


async def _audit(db, identity: McpIdentity, name: str, arguments: dict, outcome: str) -> None:
    # Argument names only, never values: arguments can contain free-text from the model.
    await log_event(
        db,
        tenant_id=identity.tenant_id,
        actor_user_id=identity.user_id,
        action="mcp.tool_call",
        resource_type="mcp_tool",
        resource_id=name,
        detail={"tool": name, "argument_names": sorted(arguments), "outcome": outcome},
    )
    await db.commit()


async def run_tool(
    name: str,
    arguments: dict,
    *,
    identity: McpIdentity,
    session_factory: async_sessionmaker[AsyncSession],
    limiter: RateLimiter | None = None,
) -> list[types.TextContent]:
    arguments = arguments or {}
    async with session_factory() as db:
        user = await db.get(User, identity.user_id)
        if user is None or not user.is_active or user.tenant_id != identity.tenant_id:
            raise ToolFailedError("The MCP service account is no longer active")
        if limiter is not None and not limiter.allow():
            await _audit(db, identity, name, arguments, "rate_limited")
            raise ToolFailedError("Rate limit exceeded; slow down tool calls")
        result = await execute_tool(
            name, arguments, ToolContext(db=db, tenant_id=identity.tenant_id)
        )
        await _audit(db, identity, name, arguments, "error" if result.error else "ok")

    if result.error:
        raise ToolFailedError(result.error)
    payload = {"output": result.output, "citations": result.citations}
    return [types.TextContent(type="text", text=json.dumps(payload, default=str))]


def build_server(
    identity: McpIdentity,
    session_factory: async_sessionmaker[AsyncSession],
    limiter: RateLimiter | None = None,
) -> Server:
    server: Server = Server(SERVER_NAME)
    limiter = limiter or RateLimiter()

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return list_tool_specs()

    @server.call_tool(validate_input=True)
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        return await run_tool(
            name, arguments, identity=identity, session_factory=session_factory, limiter=limiter
        )

    return server


async def authenticate(session_factory: async_sessionmaker[AsyncSession]) -> McpIdentity:
    """Logs in the service account named by MCP_USERNAME / MCP_PASSWORD (a normal user, ideally a
    dedicated technician-role account created by a workspace admin)."""
    username, password = os.environ.get("MCP_USERNAME"), os.environ.get("MCP_PASSWORD")
    if not username or not password:
        raise SystemExit("MCP_USERNAME and MCP_PASSWORD must be set (a workspace service account).")
    async with session_factory() as db:
        try:
            user = await authenticate_user(db, username=username, password=password)
        except InvalidCredentialsError:
            raise SystemExit("MCP authentication failed: invalid or deactivated account.") from None
    return McpIdentity(user_id=user.id, tenant_id=user.tenant_id, username=user.username)


async def main() -> None:
    from app.database import AsyncSessionLocal  # deferred: needs DATABASE_URL at import

    identity = await authenticate(AsyncSessionLocal)
    server = build_server(identity, AsyncSessionLocal)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
