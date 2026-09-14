"""Tests for the OpenAI tool-calling path added to app/rag/generation.py —
message-format translation (pure functions, no network) plus a call-site
test proving call_model dispatches correctly when LLM_PROVIDER=openai,
with only the openai SDK client mocked."""
import json

import pytest

from app.rag.generation import (
    ModelToolCall,
    _anthropic_messages_to_openai,
    _openai_tool_definitions,
    call_model,
)
from app.tools.definitions import TOOL_DEFINITIONS


def test_openai_tool_definitions_match_anthropic_tool_count_and_names() -> None:
    openai_tools = _openai_tool_definitions()
    assert len(openai_tools) == len(TOOL_DEFINITIONS)
    assert {t["function"]["name"] for t in openai_tools} == {
        t["name"] for t in TOOL_DEFINITIONS
    }


def test_openai_tool_definitions_wrap_input_schema_as_parameters() -> None:
    openai_tools = _openai_tool_definitions()
    calculate = next(t for t in openai_tools if t["function"]["name"] == "calculate")
    anthropic_calculate = next(t for t in TOOL_DEFINITIONS if t["name"] == "calculate")
    assert calculate["type"] == "function"
    assert calculate["function"]["parameters"] == anthropic_calculate["input_schema"]


def test_translate_initial_string_message() -> None:
    messages = [{"role": "user", "content": "Why is the motor overheating?"}]
    result = _anthropic_messages_to_openai(messages, "system prompt")
    assert result[0] == {"role": "system", "content": "system prompt"}
    assert result[1] == {"role": "user", "content": "Why is the motor overheating?"}


def test_translate_assistant_tool_use_block() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check."},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "calculate",
                    "input": {"expression": "1+1"},
                },
            ],
        }
    ]
    result = _anthropic_messages_to_openai(messages, "system")
    assistant_msg = result[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "Let me check."
    assert assistant_msg["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "calculate", "arguments": json.dumps({"expression": "1+1"})},
        }
    ]


def test_translate_assistant_tool_use_with_no_text_has_none_content() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "calculate",
                    "input": {"expression": "1+1"},
                }
            ],
        }
    ]
    result = _anthropic_messages_to_openai(messages, "system")
    assert result[1]["content"] is None


def test_translate_tool_result_becomes_role_tool_message() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "42", "is_error": False}
            ],
        }
    ]
    result = _anthropic_messages_to_openai(messages, "system")
    assert result[1] == {"role": "tool", "tool_call_id": "call_1", "content": "42"}


def test_translate_tool_result_error_flag_folds_into_content() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": "division by zero",
                    "is_error": True,
                }
            ],
        }
    ]
    result = _anthropic_messages_to_openai(messages, "system")
    assert result[1]["content"] == "ERROR: division by zero"


def test_translate_multiple_tool_results_become_separate_messages() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "a", "is_error": False},
                {"type": "tool_result", "tool_use_id": "call_2", "content": "b", "is_error": False},
            ],
        }
    ]
    result = _anthropic_messages_to_openai(messages, "system")
    tool_messages = [m for m in result if m["role"] == "tool"]
    assert len(tool_messages) == 2
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert tool_messages[1]["tool_call_id"] == "call_2"


# --- call-site: call_model dispatches to OpenAI, only the SDK client mocked ---


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: dict) -> None:
        self.id = id
        self.function = _FakeFunction(name, json.dumps(arguments))


class _FakeMessage:
    def __init__(self, content: str | None, tool_calls: list | None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5


class _FakeOpenAIResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, response: _FakeOpenAIResponse) -> None:
        self._response = response
        self.call_count = 0
        self.last_kwargs: dict = {}

    async def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        return self._response


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, response: _FakeOpenAIResponse, **kwargs) -> None:
        self.chat = _FakeChat(_FakeCompletions(response))


async def test_call_model_dispatches_to_openai_and_parses_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    fake_message = _FakeMessage(
        content=None,
        tool_calls=[_FakeToolCall("call_1", "calculate", {"expression": "6*7"})],
    )
    fake_client = _FakeOpenAIClient(_FakeOpenAIResponse(fake_message))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: fake_client)

    turn = await call_model([{"role": "user", "content": "What is 6*7?"}], "system prompt")

    assert turn.stop_reason == "tool_use"
    assert turn.tool_calls == [
        ModelToolCall(id="call_1", name="calculate", input={"expression": "6*7"})
    ]
    assert fake_client.chat.completions.call_count == 1
    # tools were translated to OpenAI's function-calling shape
    assert fake_client.chat.completions.last_kwargs["tools"][0]["type"] == "function"


async def test_call_model_dispatches_to_openai_end_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    fake_message = _FakeMessage(content='{"summary": "done"}', tool_calls=None)
    fake_client = _FakeOpenAIClient(_FakeOpenAIResponse(fake_message))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: fake_client)

    turn = await call_model([{"role": "user", "content": "test"}], "system prompt")

    assert turn.stop_reason == "end_turn"
    assert turn.text == '{"summary": "done"}'
    assert turn.tool_calls == []


async def test_call_model_unsupported_provider_raises_llm_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.llm.client import LLMError

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "not-a-real-provider")

    with pytest.raises(LLMError, match="Unsupported LLM_PROVIDER"):
        await call_model([{"role": "user", "content": "test"}], "system prompt")
