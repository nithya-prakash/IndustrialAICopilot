import pytest

from app.config import get_settings
from app.rag import query_expansion
from app.rag.generation import ModelTurn


@pytest.fixture
def hyde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "query_expansion", "hyde")


async def test_off_by_default_makes_no_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("the model must not be called when expansion is off")

    monkeypatch.setattr(query_expansion, "call_model", boom)
    assert get_settings().query_expansion == "off"
    assert await query_expansion.expand_query("why is it shaking?") == ""


async def test_returns_the_models_passage_trimmed(
    hyde: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = {}

    async def fake(messages, system, use_tools=True):
        seen.update(messages=messages, system=system, use_tools=use_tools)
        text = "  Excessive vibration is caused by misalignment.  "
        return ModelTurn(stop_reason="end_turn", text=text)

    monkeypatch.setattr(query_expansion, "call_model", fake)
    out = await query_expansion.expand_query("the machine is shaking")
    assert out == "Excessive vibration is caused by misalignment."
    assert seen["use_tools"] is False
    assert seen["messages"][0]["content"][0]["text"] == "the machine is shaking"


async def test_long_answers_are_capped(hyde: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(messages, system, use_tools=True):
        return ModelTurn(stop_reason="end_turn", text="x" * 5000)

    monkeypatch.setattr(query_expansion, "call_model", fake)
    assert len(await query_expansion.expand_query("q")) == query_expansion.MAX_CHARS


async def test_failure_and_timeout_fall_back_to_the_plain_query(
    hyde: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(messages, system, use_tools=True):
        raise RuntimeError("provider down")

    monkeypatch.setattr(query_expansion, "call_model", broken)
    assert await query_expansion.expand_query("q") == ""

    async def slow(messages, system, use_tools=True):
        import asyncio

        await asyncio.sleep(5)
        return ModelTurn(stop_reason="end_turn", text="late")

    monkeypatch.setattr(query_expansion, "call_model", slow)
    monkeypatch.setattr(get_settings(), "query_expansion_timeout_seconds", 0.05)
    assert await query_expansion.expand_query("q") == ""


async def test_blank_query_is_not_sent(hyde: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("no call for a blank query")

    monkeypatch.setattr(query_expansion, "call_model", boom)
    assert await query_expansion.expand_query("   ") == ""
