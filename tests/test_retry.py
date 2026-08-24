"""Proves the shared retry policy (app/core/retry.py) actually retries
transient failures, gives up after a bounded number of attempts, and never
retries a permanent (non-transient) error — plus that the real call sites
(LLM agent call, vision call) are wired through it.
"""
import anthropic
import openai
import pytest
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.retry import (
    call_with_retry,
    call_with_retry_sync,
    is_transient_llm_error,
    is_transient_qdrant_error,
)
from app.observability.metrics import retry_attempts_total


def _fast_retry_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real production backoff is 1-8s; these tests would otherwise take
    several seconds per case. Same code path, just near-zero wait."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "retry_max_attempts", 3)
    monkeypatch.setattr(settings, "retry_wait_min_seconds", 0.001)
    monkeypatch.setattr(settings, "retry_wait_max_seconds", 0.002)


def _timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=object())


def _auth_error() -> anthropic.AuthenticationError:
    return anthropic.AuthenticationError(
        message="invalid api key",
        response=_fake_response(401),
        body=None,
    )


def _fake_response(status_code: int):
    class _Resp:
        def __init__(self, code: int) -> None:
            self.status_code = code
            self.headers = {}
            self.request = object()

    return _Resp(status_code)


async def test_transient_failure_then_success_retries_and_returns_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_retry_settings(monkeypatch)
    calls = {"count": 0}

    async def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise _timeout_error()
        return "ok"

    result = await call_with_retry("test_op", is_transient_llm_error, flaky)

    assert result == "ok"
    assert calls["count"] == 3


async def test_repeated_transient_failure_raises_original_error_after_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_retry_settings(monkeypatch)
    calls = {"count": 0}

    async def always_fails():
        calls["count"] += 1
        raise _timeout_error()

    with pytest.raises(anthropic.APITimeoutError):
        await call_with_retry("test_op", is_transient_llm_error, always_fails)

    # bounded: exactly retry_max_attempts total tries, not unbounded
    assert calls["count"] == 3


async def test_permanent_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry_settings(monkeypatch)
    calls = {"count": 0}

    async def bad_auth():
        calls["count"] += 1
        raise _auth_error()

    with pytest.raises(anthropic.AuthenticationError):
        await call_with_retry("test_op", is_transient_llm_error, bad_auth)

    # a single attempt only — validation/auth errors are never retried
    assert calls["count"] == 1


async def test_retrying_increments_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry_settings(monkeypatch)
    before = retry_attempts_total.labels(operation="metric_test", outcome="retrying")._value.get()
    calls = {"count": 0}

    async def flaky():
        calls["count"] += 1
        if calls["count"] < 2:
            raise _timeout_error()
        return "ok"

    await call_with_retry("metric_test", is_transient_llm_error, flaky)

    after = retry_attempts_total.labels(operation="metric_test", outcome="retrying")._value.get()
    assert after == before + 1  # one retry happened before success


def test_sync_variant_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry_settings(monkeypatch)
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 2:
            raise ResponseHandlingException(TimeoutError("connection reset"))
        return "ok"

    result = call_with_retry_sync("test_op", is_transient_qdrant_error, flaky)
    assert result == "ok"
    assert calls["count"] == 2


def test_qdrant_4xx_is_not_transient_and_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry_settings(monkeypatch)
    calls = {"count": 0}

    def bad_request():
        calls["count"] += 1
        raise UnexpectedResponse(
            status_code=400, reason_phrase="Bad Request", content=b"bad filter", headers={}
        )

    with pytest.raises(UnexpectedResponse):
        call_with_retry_sync("test_op", is_transient_qdrant_error, bad_request)
    assert calls["count"] == 1


def test_qdrant_5xx_is_transient() -> None:
    exc = UnexpectedResponse(
        status_code=503, reason_phrase="Service Unavailable", content=b"", headers={}
    )
    assert is_transient_qdrant_error(exc) is True


def test_qdrant_connection_error_is_transient() -> None:
    assert is_transient_qdrant_error(ResponseHandlingException(TimeoutError())) is True


async def test_openai_transient_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry_settings(monkeypatch)
    calls = {"count": 0}

    async def flaky():
        calls["count"] += 1
        if calls["count"] < 2:
            raise openai.APITimeoutError(request=object())
        return "ok"

    result = await call_with_retry("test_op", is_transient_llm_error, flaky)
    assert result == "ok"
    assert calls["count"] == 2


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeAnthropicResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]
        self.usage = _FakeUsage()
        self.stop_reason = "end_turn"


class _FakeAnthropicMessages:
    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def create(self, **kwargs):
        self.call_count += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeAnthropicClient:
    def __init__(self, responses: list, **kwargs) -> None:
        self.messages = _FakeAnthropicMessages(responses)


async def test_diagnosis_agent_call_model_retries_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real production call path (app.rag.generation.call_model), not
    just the generic retry helper — only the Anthropic SDK client is faked."""
    _fast_retry_settings(monkeypatch)
    from app.config import get_settings
    from app.rag.generation import call_model

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_provider", "anthropic")

    responses = [_timeout_error(), _FakeAnthropicResponse('{"summary": "ok"}')]
    fake_client = _FakeAnthropicClient(responses)
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic", lambda **kwargs: fake_client
    )

    turn = await call_model([{"role": "user", "content": "hi"}], "system prompt")

    assert turn.text == '{"summary": "ok"}'
    assert fake_client.messages.call_count == 2


async def test_vision_analyze_image_retries_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real production call path (app.vision.analyzer.analyze_image),
    only the Anthropic SDK client is faked — real preprocessing/parsing runs."""
    _fast_retry_settings(monkeypatch)
    from app.config import get_settings
    from app.vision.analyzer import analyze_image

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "vision_provider", "anthropic")

    valid_json = (
        '{"observations": [{"description": "visible rust", "confidence": 0.8}], '
        '"limitations": []}'
    )
    responses = [_timeout_error(), _FakeAnthropicResponse(valid_json)]
    fake_client = _FakeAnthropicClient(responses)
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic", lambda **kwargs: fake_client
    )

    result = await analyze_image(b"fake-image-bytes", "image/jpeg", question="what's wrong?")

    assert result.observations == [{"description": "visible rust", "confidence": 0.8}]
    assert fake_client.messages.call_count == 2


async def test_vision_analyze_image_final_error_after_exhausted_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After retries are exhausted, the raw SDK exception is wrapped as
    VisionError (message preserved) rather than left to leak as an
    unhandled 500 — see app.vision.analyzer._anthropic_vision."""
    _fast_retry_settings(monkeypatch)
    from app.config import get_settings
    from app.vision.analyzer import VisionError, analyze_image

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "vision_provider", "anthropic")

    responses = [_timeout_error(), _timeout_error(), _timeout_error()]
    fake_client = _FakeAnthropicClient(responses)
    monkeypatch.setattr(
        "anthropic.AsyncAnthropic", lambda **kwargs: fake_client
    )

    with pytest.raises(VisionError, match="timed out|Vision analysis failed"):
        await analyze_image(b"fake-image-bytes", "image/jpeg")

    assert fake_client.messages.call_count == 3  # bounded, matches retry_max_attempts
