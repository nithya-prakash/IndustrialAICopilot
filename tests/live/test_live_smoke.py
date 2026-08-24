"""Live smoke tests against the REAL Anthropic API — the only tests in this
repository that make a real, billed network call to an external provider.
Every other AI-pipeline test (tests/test_retry.py, test_vision_integration_mocked.py,
test_diagnosis_agent.py, test_e2e_diagnosis_pipeline_mocked.py, ...) mocks
the provider call; these two prove the real thing actually authenticates
and responds.

Not correctness or accuracy tests — just "does a real call round-trip."
Diagnosis-quality evaluation against real API responses lives separately in
evaluation/diagnosis_eval.py (`python -m evaluation.diagnosis_eval`).

With no credentials configured, both tests SKIP (not pass, not fail) —
pytest reports them as SKIPPED so a run without credentials can never be
read as "verified." Run explicitly with:

    docker compose run --rm backend python -m pytest tests/live -v

or select by marker from the full suite:

    docker compose run --rm backend python -m pytest -m live -v
"""
import io

import pytest
from PIL import Image

from app.config import get_settings

pytestmark = pytest.mark.live


def _require_llm_credentials() -> None:
    if not get_settings().resolved_llm_api_key:
        pytest.skip("SKIPPED — no API credentials configured")


def _require_vision_credentials() -> None:
    if not get_settings().resolved_vision_api_key:
        pytest.skip("SKIPPED — no API credentials configured")


async def test_live_llm_agent_call_returns_a_real_response() -> None:
    """Proves ANTHROPIC_API_KEY (or LLM_API_KEY) actually authenticates and
    the model responds — real network call, real provider."""
    _require_llm_credentials()
    from app.rag.generation import call_model

    turn = await call_model(
        [{"role": "user", "content": "Reply with exactly the word: pong"}],
        "You are a terse test assistant. Follow instructions exactly.",
    )
    assert turn.text.strip()
    print(f"\nLive LLM smoke test — model responded: {turn.text.strip()[:200]!r}")


async def test_live_vision_call_returns_structured_observations() -> None:
    """Proves the configured vision provider actually authenticates and
    returns a parseable structured result against a real (trivial) image."""
    _require_vision_credentials()
    from app.vision.analyzer import analyze_image

    image = Image.new("RGB", (64, 64), color=(120, 60, 20))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")

    result = await analyze_image(buf.getvalue(), "image/jpeg")
    assert isinstance(result.observations, list)
    print(f"\nLive vision smoke test — {len(result.observations)} observation(s) returned")
