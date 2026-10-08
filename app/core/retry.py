"""Shared tenacity retry policy for transient failures against external
services — Anthropic/OpenAI LLM+VLM calls and Qdrant.

Retries only errors that are genuinely transient (timeouts, connection
failures, rate limits, 5xx server errors) — never validation, auth, or
malformed-request errors, since retrying those can't fix them and would
just delay a real failure for no benefit. Bounded attempt count and
exponential backoff, both configurable via RETRY_MAX_ATTEMPTS /
RETRY_WAIT_MIN_SECONDS / RETRY_WAIT_MAX_SECONDS (see app/config.py). Every
retried attempt increments `retry_attempts_total` and logs a warning.

Applied at the single external call, not the whole surrounding function —
e.g. just `client.messages.create(...)`, not response parsing — so a bug in
parsing a successful response can never be mistaken for a transient failure
and retried pointlessly.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

import anthropic
import openai
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.observability.metrics import retry_attempts_total

logger = logging.getLogger("app.retry")

T = TypeVar("T")

_TRANSIENT_LLM_EXCEPTIONS = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


# A provider hint longer than this (or any "per day" limit) cannot be waited out inside one request.
MAX_HONORED_RETRY_AFTER = 60.0
_TRY_AGAIN = re.compile(
    r"try again in (?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?", re.I
)


def retry_after_seconds(exc: BaseException) -> float | None:
    """The provider's wait hint: a Retry-After header, else 'try again in 4m57.6s' in the text."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        value = headers.get("retry-after")
        try:
            if value is not None:
                return float(value)
        except ValueError:
            pass
    match = _TRY_AGAIN.search(str(exc))
    if match and any(match.groups()):
        hours, minutes, seconds = (float(g) if g else 0.0 for g in match.groups())
        return hours * 3600 + minutes * 60 + seconds
    return None


def is_quota_exhausted(exc: BaseException) -> bool:
    """A rate limit that backing off for a few seconds cannot fix (daily quota, long wait)."""
    if not isinstance(exc, openai.RateLimitError | anthropic.RateLimitError):
        return False
    hint = retry_after_seconds(exc)
    return "per day" in str(exc).lower() or (hint is not None and hint > MAX_HONORED_RETRY_AFTER)


def is_transient_llm_error(exc: BaseException) -> bool:
    return isinstance(exc, _TRANSIENT_LLM_EXCEPTIONS) and not is_quota_exhausted(exc)


def describe_llm_failure(exc: BaseException) -> str:
    """User-facing reason for a failed model call, instead of a raw provider payload."""
    if is_quota_exhausted(exc):
        hint = retry_after_seconds(exc)
        when = f" Try again in about {round(hint / 60)} minute(s)." if hint else ""
        return f"The model provider's usage limit was reached.{when}"
    if isinstance(exc, openai.RateLimitError | anthropic.RateLimitError):
        return "The model provider is rate limiting requests; please retry shortly."
    return f"LLM call failed: {exc}"


def _wait_with_hint(settings) -> Callable[[object], float]:
    """Exponential backoff, raised to the provider's Retry-After hint when it gives one."""
    exponential = wait_exponential(
        multiplier=1, min=settings.retry_wait_min_seconds, max=settings.retry_wait_max_seconds
    )

    def wait(retry_state) -> float:
        delay = exponential(retry_state)
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        hint = retry_after_seconds(exc) if exc is not None else None
        if hint is not None:
            delay = max(delay, min(hint, MAX_HONORED_RETRY_AFTER))
        return delay

    return wait


def is_transient_qdrant_error(exc: BaseException) -> bool:
    if isinstance(exc, ResponseHandlingException):
        return True
    if isinstance(exc, UnexpectedResponse):
        return exc.status_code is not None and exc.status_code >= 500
    return False


def _before_sleep(operation: str) -> Callable[[object], None]:
    def _callback(retry_state) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        retry_attempts_total.labels(operation=operation, outcome="retrying").inc()
        logger.warning(
            "retrying transient failure: operation=%s attempt=%d error=%s",
            operation,
            retry_state.attempt_number,
            exc,
        )

    return _callback


async def call_with_retry(
    operation: str,
    is_transient: Callable[[BaseException], bool],
    func: Callable[..., Awaitable[T]],
    *args,
    **kwargs,
) -> T:
    """Awaits func(*args, **kwargs), retrying only on is_transient(exc)
    errors with bounded exponential backoff. Re-raises the original
    exception (not a wrapped RetryError) once attempts are exhausted, or
    immediately for any non-transient error."""
    settings = get_settings()
    retrying = AsyncRetrying(
        retry=retry_if_exception(is_transient),
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=_wait_with_hint(settings),
        before_sleep=_before_sleep(operation),
        reraise=True,
    )
    async for attempt in retrying:
        with attempt:
            return await func(*args, **kwargs)
    raise AssertionError("unreachable: AsyncRetrying always returns or raises")


def call_with_retry_sync(
    operation: str,
    is_transient: Callable[[BaseException], bool],
    func: Callable[..., T],
    *args,
    **kwargs,
) -> T:
    """Synchronous counterpart of call_with_retry, for the sync QdrantClient."""
    settings = get_settings()
    retrying = Retrying(
        retry=retry_if_exception(is_transient),
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=1,
            min=settings.retry_wait_min_seconds,
            max=settings.retry_wait_max_seconds,
        ),
        before_sleep=_before_sleep(operation),
        reraise=True,
    )
    for attempt in retrying:
        with attempt:
            return func(*args, **kwargs)
    raise AssertionError("unreachable: Retrying always returns or raises")
