import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.mcp_server.server import ToolFailedError, list_tool_specs, run_tool
from app.tools.definitions import TOOL_DEFINITIONS


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    class _Ctx:
        async def __aenter__(self) -> AsyncSession:
            return session

        async def __aexit__(self, *exc: object) -> None:
            return None

    return lambda: _Ctx()  # type: ignore[return-value]


def test_exposes_every_agent_tool_with_its_schema() -> None:
    specs = list_tool_specs()
    assert [s.name for s in specs] == [t["name"] for t in TOOL_DEFINITIONS]
    assert len(specs) == 7
    for spec, tool in zip(specs, TOOL_DEFINITIONS, strict=True):
        assert spec.inputSchema == tool["input_schema"]


async def test_call_tool_returns_json_output(db_session: AsyncSession) -> None:
    result = await run_tool(
        "calculate", {"expression": "6 * 7"}, tenant_id="acme", session_factory=_factory(db_session)
    )
    assert json.loads(result[0].text) == {"output": {"result": 42}, "citations": []}


async def test_tool_error_raises_for_sdk_to_flag(db_session: AsyncSession) -> None:
    with pytest.raises(ToolFailedError):
        await run_tool(
            "calculate",
            {"expression": "__import__('os')"},
            tenant_id="acme",
            session_factory=_factory(db_session),
        )


async def test_unknown_tool_is_error(db_session: AsyncSession) -> None:
    with pytest.raises(ToolFailedError, match="Unknown tool"):
        await run_tool("nope", {}, tenant_id="acme", session_factory=_factory(db_session))
