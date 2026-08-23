"""Prometheus metric definitions, shared across every instrumentation site
(HTTP middleware in app/main.py, provider calls in app/llm/client.py and
app/vision/analyzer.py, the agent loop in app/agents/diagnosis_agent.py,
diagnosis/approval creation in app/agents/diagnosis_agent.py and
app/services/approval_service.py). Defined once here rather than per-module
so /metrics exposes one coherent set of series, not duplicates.

Scope note: this covers the FastAPI backend process only. Document
ingestion runs in the Celery worker process, which doesn't serve HTTP and
isn't scraped here — instrumenting it would need either a second scrape
target with a multiprocess-safe registry (prometheus_client's
PROMETHEUS_MULTIPROC_DIR, needed because the worker runs multiple forked
processes) or a push gateway, both real added complexity for a phase whose
main value is the request/LLM/agent path. Documented as a scope cut, not
an oversight — see docs/architecture-decisions.md.
"""
from prometheus_client import Counter, Histogram

from app.config import get_settings

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM/VLM provider calls",
    ["provider", "model", "operation", "status"],
)
llm_call_duration_seconds = Histogram(
    "llm_call_duration_seconds",
    "LLM/VLM provider call duration in seconds",
    ["provider", "model", "operation"],
)
llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total tokens consumed by LLM/VLM calls, as reported by the provider's own usage field",
    ["provider", "model", "operation", "token_type"],
)
llm_cost_usd_total = Counter(
    "llm_cost_usd_total",
    "Estimated USD cost of LLM/VLM calls. Stays at zero unless "
    "*_COST_PER_1K_USD is configured with a real rate (see app/config.py) — "
    "no price is guessed or hard-coded.",
    ["provider", "model", "operation"],
)

agent_tool_calls_total = Counter(
    "agent_tool_calls_total",
    "Total diagnosis-agent tool invocations",
    ["tool", "status"],
)
agent_tool_call_duration_seconds = Histogram(
    "agent_tool_call_duration_seconds",
    "Diagnosis-agent tool call duration in seconds",
    ["tool"],
)

diagnoses_total = Counter(
    "diagnoses_total",
    "Total diagnoses created",
    ["status", "severity"],
)
diagnosis_confidence = Histogram(
    "diagnosis_confidence",
    "Confidence score of completed diagnoses",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0),
)
approvals_total = Counter(
    "approvals_total",
    "Total supervisor approval decisions",
    ["decision"],
)


def record_llm_call(
    *,
    provider: str,
    model: str,
    operation: str,
    status: str,
    duration_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Single call site for every LLM/VLM provider call's metrics — used by
    app/llm/client.py (operation="generation"), app/vision/analyzer.py
    (operation="vision"), and app/agents/diagnosis_agent.py
    (operation="agent") so the label set and cost calculation live in one
    place instead of being reimplemented per call site."""
    llm_calls_total.labels(
        provider=provider, model=model, operation=operation, status=status
    ).inc()
    llm_call_duration_seconds.labels(
        provider=provider, model=model, operation=operation
    ).observe(duration_seconds)

    if input_tokens:
        llm_tokens_total.labels(
            provider=provider, model=model, operation=operation, token_type="input"
        ).inc(input_tokens)
    if output_tokens:
        llm_tokens_total.labels(
            provider=provider, model=model, operation=operation, token_type="output"
        ).inc(output_tokens)

    settings = get_settings()
    if provider == "anthropic":
        input_rate = settings.anthropic_input_cost_per_1k_usd
        output_rate = settings.anthropic_output_cost_per_1k_usd
    elif provider == "openai":
        input_rate = settings.openai_input_cost_per_1k_usd
        output_rate = settings.openai_output_cost_per_1k_usd
    else:
        input_rate = output_rate = 0.0

    cost = (input_tokens / 1000) * input_rate + (output_tokens / 1000) * output_rate
    if cost:
        llm_cost_usd_total.labels(provider=provider, model=model, operation=operation).inc(cost)
