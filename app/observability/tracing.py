"""Optional Langfuse tracing for diagnosis runs.

Active only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (plus LANGFUSE_HOST for a
self-hosted server); otherwise every helper is a no-op and nothing is imported. Structure of a
trace: one root span per diagnosis run, a "generation" per LLM call (model, token usage, latency)
and a span per tool call. Prompt, tool input/output and answer text are only recorded when
LANGFUSE_CAPTURE_CONTENT=true, because they contain user questions and manual excerpts; by default
only names, timings, token counts and outcomes leave the process.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def capture_content() -> bool:
    return os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"


def _client():
    from langfuse import get_client

    return get_client()


class _Noop:
    def update(self, **_: Any) -> None:
        return None


@contextmanager
def observation(name: str, *, as_type: str = "span", **kwargs: Any) -> Iterator[Any]:
    """Nested Langfuse observation (span / generation); yields an object with .update(...).
    Never raises into the caller: tracing problems are logged and ignored."""
    if not enabled():
        yield _Noop()
        return
    if not capture_content():
        kwargs.pop("input", None)
    try:
        cm = _client().start_as_current_observation(name=name, as_type=as_type, **kwargs)
        obs = cm.__enter__()
    except Exception:  # noqa: BLE001 - tracing must not break a diagnosis
        logger.warning("langfuse tracing unavailable", exc_info=True)
        yield _Noop()
        return
    safe = _Safe(obs)
    try:
        yield safe
    except BaseException as exc:
        safe.update(level="ERROR", status_message=str(exc)[:200])
        cm.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        cm.__exit__(None, None, None)


class _Safe:
    def __init__(self, obs: Any) -> None:
        self._obs = obs

    def update(self, **kwargs: Any) -> None:
        if not capture_content():
            kwargs.pop("output", None)
            kwargs.pop("input", None)
        try:
            self._obs.update(**kwargs)
        except Exception:  # noqa: BLE001
            logger.debug("langfuse update failed", exc_info=True)


def flush() -> None:
    if enabled():
        try:
            _client().flush()
        except Exception:  # noqa: BLE001
            logger.debug("langfuse flush failed", exc_info=True)
