"""The generation step the diagnosis agent's tool-calling loop calls into.

Tool-calling-capable (passes `tools=` so the model can request
`search_technical_documents`, `query_sensor_history`, etc.), which is why
this is a separate, direct provider-SDK call rather than going through
`app.llm.client`'s (now-removed) provider-agnostic helper — that client was
plain-text-only, with no tool-calling support, so it couldn't carry the
agent loop's tool-use messages. `app.agents.diagnosis_agent.run_diagnosis`
drives the loop (multi-turn tool dispatch, citation validation against
actually-gathered evidence, confidence/severity computation, persistence)
and calls `call_model` here for each turn; `call_model` is a free function
(not looked up by string) so tests inject a fake in its place — see
tests/test_diagnosis_agent.py.

Supports both Anthropic and OpenAI (`LLM_PROVIDER=anthropic|openai`). The
agent loop's own message list is always built in Anthropic's shape
(`{"role":..., "content": [...blocks...]}}`, see
app.agents.diagnosis_agent.run_diagnosis) regardless of which provider is
configured — `_call_openai` translates that shape into OpenAI's Chat
Completions format at the call boundary, and translates the response back
into the same provider-agnostic `ModelTurn`/`ModelToolCall` the loop
already consumes. This keeps the translation confined to one function
instead of making the loop itself provider-aware.
"""
import json
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.core.retry import call_with_retry, is_transient_llm_error
from app.llm.client import LLMError
from app.observability.metrics import record_llm_call
from app.tools.definitions import TOOL_DEFINITIONS


@dataclass
class ModelToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelTurn:
    stop_reason: str  # "tool_use" | "end_turn" | anything else counts as end_turn
    text: str = ""
    tool_calls: list[ModelToolCall] = field(default_factory=list)


async def _call_anthropic(messages: list[dict], system: str) -> ModelTurn:
    settings = get_settings()
    if not settings.resolved_llm_api_key:
        raise LLMError("No Anthropic API key configured (set ANTHROPIC_API_KEY or LLM_API_KEY)")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.resolved_llm_api_key)
    start = time.perf_counter()
    try:
        response = await call_with_retry(
            "llm_agent",
            is_transient_llm_error,
            client.messages.create,
            model=settings.llm_model,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=TOOL_DEFINITIONS,
        )
    except Exception as exc:
        record_llm_call(
            provider="anthropic",
            model=settings.llm_model,
            operation="agent",
            status="error",
            duration_seconds=time.perf_counter() - start,
        )
        # Wrapped as LLMError (preserving the original message) rather than
        # left as a raw SDK exception, so run_diagnosis's existing
        # `except (LLMError, AgentError)` handler persists a clean "failed"
        # diagnosis with a real error message instead of leaking an
        # unhandled 500 once retries (see app/core/retry.py) are exhausted.
        raise LLMError(f"LLM call failed: {exc}") from exc
    record_llm_call(
        provider="anthropic",
        model=settings.llm_model,
        operation="agent",
        status="success",
        duration_seconds=time.perf_counter() - start,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    tool_calls = [
        ModelToolCall(id=block.id, name=block.name, input=block.input)
        for block in response.content
        if block.type == "tool_use"
    ]
    return ModelTurn(stop_reason=response.stop_reason, text=text, tool_calls=tool_calls)


def _openai_tool_definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in TOOL_DEFINITIONS
    ]


def _anthropic_messages_to_openai(messages: list[dict], system: str) -> list[dict]:
    """Translates the agent loop's Anthropic-shaped message list into
    OpenAI's Chat Completions format. The loop only ever produces three
    shapes (see run_diagnosis): a plain-string user message (the initial
    turn), an assistant message whose content is a list of text/tool_use
    blocks, and a user message whose content is a list of tool_result
    blocks — each tool_result becomes its own `role: tool` message, since
    OpenAI has no equivalent of bundling several tool results into one
    message. Anthropic's per-result `is_error` flag has no OpenAI
    counterpart; folded into the content text instead so the model still
    sees which results failed."""
    openai_messages: list[dict] = [{"role": "system", "content": system}]

    for message in messages:
        role = message["role"]
        content = message["content"]

        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text_parts = [b["text"] for b in content if b["type"] == "text"]
            tool_use_blocks = [b for b in content if b["type"] == "tool_use"]
            entry: dict = {"role": "assistant", "content": "\n".join(text_parts) or None}
            if tool_use_blocks:
                entry["tool_calls"] = [
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    }
                    for block in tool_use_blocks
                ]
            openai_messages.append(entry)
            continue

        # role == "user" with tool_result blocks
        for block in content:
            result_text = block["content"]
            if block.get("is_error"):
                result_text = f"ERROR: {result_text}"
            openai_messages.append(
                {"role": "tool", "tool_call_id": block["tool_use_id"], "content": result_text}
            )

    return openai_messages


async def _call_openai(messages: list[dict], system: str) -> ModelTurn:
    settings = get_settings()
    if not settings.resolved_llm_api_key and not settings.llm_base_url:
        raise LLMError(
            "No OpenAI-compatible API key configured (set OPENAI_API_KEY or LLM_API_KEY), "
            "and no LLM_BASE_URL set for a local server"
        )

    import openai

    client = openai.AsyncOpenAI(
        api_key=settings.resolved_llm_api_key or "not-needed-for-local-server",
        base_url=settings.llm_base_url or None,
    )
    openai_messages = _anthropic_messages_to_openai(messages, system)
    start = time.perf_counter()
    try:
        response = await call_with_retry(
            "llm_agent",
            is_transient_llm_error,
            client.chat.completions.create,
            model=settings.llm_model,
            max_tokens=2048,
            messages=openai_messages,
            tools=_openai_tool_definitions(),
        )
    except Exception as exc:
        record_llm_call(
            provider="openai",
            model=settings.llm_model,
            operation="agent",
            status="error",
            duration_seconds=time.perf_counter() - start,
        )
        raise LLMError(f"LLM call failed: {exc}") from exc

    usage = response.usage
    record_llm_call(
        provider="openai",
        model=settings.llm_model,
        operation="agent",
        status="success",
        duration_seconds=time.perf_counter() - start,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
    )

    choice = response.choices[0].message
    tool_calls = [
        ModelToolCall(
            id=call.id, name=call.function.name, input=json.loads(call.function.arguments)
        )
        for call in (choice.tool_calls or [])
    ]
    stop_reason = "tool_use" if tool_calls else "end_turn"
    return ModelTurn(stop_reason=stop_reason, text=choice.content or "", tool_calls=tool_calls)


async def call_model(messages: list[dict], system: str) -> ModelTurn:
    settings = get_settings()
    if settings.llm_provider == "anthropic":
        return await _call_anthropic(messages, system)
    if settings.llm_provider == "openai":
        return await _call_openai(messages, system)
    raise LLMError(f"Unsupported LLM_PROVIDER for agent tool-calling: {settings.llm_provider!r}")
