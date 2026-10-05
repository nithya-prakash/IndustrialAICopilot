"""Standalone MCP server exposing the Copilot's seven diagnostic tools.

Reuses TOOL_DEFINITIONS and execute_tool unchanged, so any MCP client hits exactly
the code path the in-app agent uses, including tenant scoping and citation strings.
Runs as its own process over stdio:

    MCP_TENANT_ID=acme python -m app.mcp_server.server

Every call is scoped to MCP_TENANT_ID; clients cannot choose a tenant.
"""
import asyncio
import json
import os

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


async def run_tool(
    name: str,
    arguments: dict,
    *,
    tenant_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> list[types.TextContent]:
    async with session_factory() as db:
        result = await execute_tool(name, arguments or {}, ToolContext(db=db, tenant_id=tenant_id))

    if result.error:
        raise ToolFailedError(result.error)
    payload = {"output": result.output, "citations": result.citations}
    return [types.TextContent(type="text", text=json.dumps(payload, default=str))]


def build_server(
    tenant_id: str, session_factory: async_sessionmaker[AsyncSession]
) -> Server:
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return list_tool_specs()

    @server.call_tool(validate_input=True)
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        return await run_tool(
            name, arguments, tenant_id=tenant_id, session_factory=session_factory
        )

    return server


async def main() -> None:
    tenant_id = os.environ.get("MCP_TENANT_ID")
    if not tenant_id:
        raise SystemExit("MCP_TENANT_ID must be set: the MCP server is scoped to one tenant.")

    from app.database import AsyncSessionLocal  # deferred: needs DATABASE_URL at import

    server = build_server(tenant_id, AsyncSessionLocal)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
