"""The generation step the diagnosis agent's tool-calling loop calls into.

This is Anthropic-only and tool-calling-capable (passes `tools=` so the
model can request `search_technical_documents`, `query_sensor_history`,
etc.), which is why it's a separate, direct Anthropic SDK call rather than
going through `app.llm.client.chat_completion` — that client is
provider-agnostic (Anthropic/OpenAI/local-Ollama) but plain-text-only, with
no tool-calling support, so it can't carry the agent loop's tool-use
messages. `app.agents.diagnosis_agent.run_diagnosis` drives the loop
(multi-turn tool dispatch, citation validation against actually-gathered
evidence, confidence/severity computation, persistence) and calls
`call_model` here for each turn; `call_model` is a free function (not
looked up by string) so tests inject a fake in its place — see
tests/test_diagnosis_agent.py.
"""
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


async def call_model(messages: list[dict], system: str) -> ModelTurn:
    settings = get_settings()
    if settings.llm_provider != "anthropic":
        raise LLMError(
            f"Agent tool-calling currently only supports LLM_PROVIDER=anthropic "
            f"(got {settings.llm_provider!r})"
        )
    return await _call_anthropic(messages, system)
