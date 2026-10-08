"""Token and cost accounting for one diagnosis run.

Every model call made while a run is active adds its provider-reported token counts here (via a
context variable, so concurrent requests do not mix). The total is stored on the diagnosis row.
Cost uses the same optional per-1k-token rates as the Prometheus cost counter, so it is only an
estimate and is `None` unless real rates are configured (no price is hard-coded).
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from app.observability.metrics import estimate_cost_usd


@dataclass
class RunUsage:
    orchestrator: str
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    cost_usd: float = 0.0
    models: set[str] = field(default_factory=set)

    def add_call(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        self.llm_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += estimate_cost_usd(provider, input_tokens, output_tokens)
        self.models.add(f"{provider}/{model}")

    def as_dict(self) -> dict:
        return {
            "orchestrator": self.orchestrator,
            "models": sorted(self.models),
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.cost_usd, 6) if self.cost_usd else None,
        }


_current: ContextVar[RunUsage | None] = ContextVar("run_usage", default=None)


def start_run(orchestrator: str) -> tuple[RunUsage, Token]:
    usage = RunUsage(orchestrator)
    return usage, _current.set(usage)


def end_run(token: Token) -> None:
    _current.reset(token)


def record_call(provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
    usage = _current.get()
    if usage is not None:
        usage.add_call(provider, model, input_tokens, output_tokens)
