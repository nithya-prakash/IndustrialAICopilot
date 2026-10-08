import pytest

from app.observability import tracing
from app.rag import generation
from app.rag.generation import ModelTurn


class FakeObservation:
    def __init__(self, record, kwargs):
        self.record, self.kwargs, self.updates = record, kwargs, []
        record.append(self)

    def update(self, **kw):
        self.updates.append(kw)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


class FakeClient:
    def __init__(self):
        self.observations = []

    def start_as_current_observation(self, **kwargs):
        return FakeObservation(self.observations, kwargs)


@pytest.fixture
def fake_langfuse(monkeypatch):
    client = FakeClient()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(tracing, "_client", lambda: client)
    return client


def test_disabled_without_keys_is_a_noop(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    with tracing.observation("x", input="secret") as obs:
        obs.update(output="secret")  # must not raise or import langfuse


def test_content_is_dropped_unless_capture_is_enabled(fake_langfuse, monkeypatch):
    monkeypatch.delenv("LANGFUSE_CAPTURE_CONTENT", raising=False)
    with tracing.observation("tool:x", input={"q": "private"}) as obs:
        obs.update(output="private", metadata={"citations": 2})
    recorded = fake_langfuse.observations[0]
    assert "input" not in recorded.kwargs and recorded.updates == [{"metadata": {"citations": 2}}]

    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", "true")
    with tracing.observation("tool:y", input={"q": "kept"}) as obs:
        obs.update(output="kept")
    assert fake_langfuse.observations[1].kwargs["input"] == {"q": "kept"}
    assert fake_langfuse.observations[1].updates == [{"output": "kept"}]


def test_errors_are_marked_and_reraised(fake_langfuse):
    with pytest.raises(ValueError), tracing.observation("boom"):
        raise ValueError("bad tool")
    assert fake_langfuse.observations[0].updates[0]["level"] == "ERROR"


def test_tracing_failure_never_breaks_the_caller(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    def broken():
        raise RuntimeError("langfuse down")

    monkeypatch.setattr(tracing, "_client", broken)
    with tracing.observation("x") as obs:
        obs.update(output="ok")


async def test_llm_call_is_recorded_as_a_generation_with_token_usage(fake_langfuse, monkeypatch):
    async def fake_dispatch(messages, system, use_tools):
        return ModelTurn(stop_reason="end_turn", text="hello", input_tokens=120, output_tokens=7)

    monkeypatch.setattr(generation, "_dispatch", fake_dispatch)
    turn = await generation.call_model([{"role": "user", "content": "hi"}], "sys")
    assert turn.text == "hello"
    obs = fake_langfuse.observations[0]
    assert obs.kwargs["as_type"] == "generation"
    assert obs.updates[0]["usage_details"] == {"input": 120, "output": 7}
    assert obs.updates[0]["metadata"]["use_tools"] is True
