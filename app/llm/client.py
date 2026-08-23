"""Provider-agnostic chat completion. LLM_PROVIDER switches the backend
without touching call sites — used by RAG generation now and the diagnosis
agent later. "openai" also covers Ollama or any OpenAI-compatible server via
LLM_BASE_URL, so local development never requires a paid key.
"""
from app.config import get_settings


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
    response = await client.messages.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
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
    response = await client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""
