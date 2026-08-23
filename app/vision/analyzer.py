"""VLM-based visual analysis with structured, bounded output.

The model is instructed never to state measurements, temperatures, or
internal-component condition — things a photo genuinely cannot establish —
and to report confidence per observation plus explicit limitations. That
instruction alone is not treated as sufficient: `_flag_suspected_measurements`
is a second, structural check that scans the model's own output for
measurement-like patterns (numbers with units) and surfaces them as a
limitation if the model claims one anyway, rather than silently trusting the
prompt to have worked. See docs/architecture-decisions.md.
"""
import base64
import json
import re
import time
from dataclasses import dataclass

from app.config import get_settings
from app.observability.metrics import record_llm_call

MEASUREMENT_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s*"
    r"(mm|cm|meters?|kg|grams?|g|°\s*[cf]|degrees?|psi|bar|rpm|"
    r"in(ch(es)?)?|volts?|\bv\b|amps?|\ba\b|hz|hertz)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You are a visual inspection assistant analyzing a photo of \
industrial equipment for a maintenance technician.

Describe ONLY what is visually observable in the image. For each distinct \
observation, provide a description and a confidence score from 0.0 to 1.0 \
reflecting how visually certain you are.

Rules:
- Do NOT state specific numeric measurements, dimensions, or temperatures — \
these cannot be determined from a photograph.
- Do NOT claim to know the internal condition of components, hidden parts, \
or anything not directly visible in the frame.
- If image quality, angle, lighting, or partial framing limits what can be \
assessed, say so explicitly in "limitations".
- Do not guess at a root cause or diagnosis — only describe what is visible. \
Diagnosis is a separate step performed elsewhere with additional evidence.

Respond with ONLY valid JSON matching this schema, no other text, no markdown \
code fences:
{"observations": [{"description": "...", "confidence": 0.0}], "limitations": ["..."]}"""


class VisionError(Exception):
    pass


@dataclass
class VisionAnalysisResult:
    observations: list[dict]
    limitations: list[str]
    raw_response: str


async def analyze_image(
    image_bytes: bytes, media_type: str, question: str | None = None
) -> VisionAnalysisResult:
    settings = get_settings()
    user_prompt = "Analyze this photo of industrial equipment."
    if question:
        user_prompt += f" The technician's question for context: {question}"

    if settings.vision_provider == "anthropic":
        raw = await _anthropic_vision(image_bytes, media_type, user_prompt)
    elif settings.vision_provider == "openai":
        raw = await _openai_vision(image_bytes, media_type, user_prompt)
    else:
        raise VisionError(f"Unsupported VISION_PROVIDER: {settings.vision_provider!r}")

    return _parse_response(raw)


async def _anthropic_vision(image_bytes: bytes, media_type: str, user_prompt: str) -> str:
    settings = get_settings()
    if not settings.resolved_vision_api_key:
        raise VisionError(
            "No Anthropic API key configured (set ANTHROPIC_API_KEY or VISION_API_KEY)"
        )

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.resolved_vision_api_key)
    encoded = base64.b64encode(image_bytes).decode()
    start = time.perf_counter()
    try:
        response = await client.messages.create(
            model=settings.vision_model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                }
            ],
        )
    except Exception:
        record_llm_call(
            provider="anthropic",
            model=settings.vision_model,
            operation="vision",
            status="error",
            duration_seconds=time.perf_counter() - start,
        )
        raise
    record_llm_call(
        provider="anthropic",
        model=settings.vision_model,
        operation="vision",
        status="success",
        duration_seconds=time.perf_counter() - start,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def _openai_vision(image_bytes: bytes, media_type: str, user_prompt: str) -> str:
    settings = get_settings()
    if not settings.resolved_vision_api_key:
        raise VisionError(
            "No OpenAI API key configured (set OPENAI_API_KEY or VISION_API_KEY)"
        )

    import openai

    client = openai.AsyncOpenAI(api_key=settings.resolved_vision_api_key)
    encoded = base64.b64encode(image_bytes).decode()
    data_url = f"data:{media_type};base64,{encoded}"
    start = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=settings.vision_model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        )
    except Exception:
        record_llm_call(
            provider="openai",
            model=settings.vision_model,
            operation="vision",
            status="error",
            duration_seconds=time.perf_counter() - start,
        )
        raise
    usage = response.usage
    record_llm_call(
        provider="openai",
        model=settings.vision_model,
        operation="vision",
        status="success",
        duration_seconds=time.perf_counter() - start,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
    )
    return response.choices[0].message.content or ""


def _parse_response(raw: str) -> VisionAnalysisResult:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VisionError(f"Model did not return valid JSON: {exc}") from exc

    observations = []
    for obs in data.get("observations", []):
        if not isinstance(obs, dict) or "description" not in obs:
            continue
        confidence = obs.get("confidence", 0.5)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5
        observations.append({"description": str(obs["description"]), "confidence": confidence})

    limitations = [str(x) for x in data.get("limitations", []) if isinstance(x, str)]
    limitations = _flag_suspected_measurements(observations, limitations)

    return VisionAnalysisResult(
        observations=observations, limitations=limitations, raw_response=raw
    )


def _flag_suspected_measurements(observations: list[dict], limitations: list[str]) -> list[str]:
    """The system prompt tells the model not to state measurements, but a
    prompt instruction is not a guarantee. This is the structural check: if
    an observation contains a number-with-unit pattern anyway, add an
    explicit limitation flagging it rather than silently trusting it."""
    flagged = any(MEASUREMENT_PATTERN.search(obs["description"]) for obs in observations)
    if flagged:
        warning = (
            "One or more observations mention a specific measurement or value; "
            "measurements cannot be reliably determined from a photograph and "
            "should be independently verified, not treated as fact."
        )
        if warning not in limitations:
            limitations = [*limitations, warning]
    return limitations
