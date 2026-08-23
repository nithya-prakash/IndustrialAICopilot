"""Provider-agnostic chat completion. LLM_PROVIDER switches the backend
without touching call sites — used by RAG generation now and the diagnosis
agent later. "openai" also covers Ollama or any OpenAI-compatible server via
LLM_BASE_URL, so local development never requires a paid key.
"""
import time

from app.config import get_settings
from app.observability.metrics import record_llm_call


class LLMError(Exception):
    pass


async def chat_completion(*, system: str, user: str, max_tokens: int = 1024) -> str:
    settings = get_settings()
    if settings.llm_provider == "anthropic":
        return await _anthropic_completion(system=system, user=user, max_tokens=max_tokens)
    if settings.llm_provider == "openai":
        return await _openai_completion(system=system, user=user, max_tokens=max_tokens)
    raise LLMError(f"Unsupported LLM_PROVIDER: {settings.llm_provider!r}")


async def _anthropic_completion(*, system: str, user: str, max_tokens: int) -> str:
    settings = get_settings()
    if not settings.resolved_llm_api_key:
        raise LLMError("No Anthropic API key configured (set ANTHROPIC_API_KEY or LLM_API_KEY)")

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.resolved_llm_api_key)
    start = time.perf_counter()
    try:
        response = await client.messages.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception:
        record_llm_call(
            provider="anthropic",
            model=settings.llm_model,
            operation="generation",
            status="error",
            duration_seconds=time.perf_counter() - start,
        )
        raise
    record_llm_call(
        provider="anthropic",
        model=settings.llm_model,
        operation="generation",
        status="success",
        duration_seconds=time.perf_counter() - start,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def _openai_completion(*, system: str, user: str, max_tokens: int) -> str:
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
    start = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except Exception:
        record_llm_call(
            provider="openai",
            model=settings.llm_model,
            operation="generation",
            status="error",
            duration_seconds=time.perf_counter() - start,
        )
        raise
    usage = response.usage
    record_llm_call(
        provider="openai",
        model=settings.llm_model,
        operation="generation",
        status="success",
        duration_seconds=time.perf_counter() - start,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
    )
    return response.choices[0].message.content or ""
