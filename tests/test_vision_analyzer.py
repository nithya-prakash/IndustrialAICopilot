import json

import pytest

from app.vision.analyzer import VisionError, _parse_response


def _raw(observations: list[dict], limitations: list[str] | None = None) -> str:
    return json.dumps({"observations": observations, "limitations": limitations or []})


def test_parses_valid_json_response() -> None:
    raw = _raw(
        [{"description": "Visible surface scratch", "confidence": 0.91}],
        ["Internal damage cannot be determined from the image."],
    )
    result = _parse_response(raw)

    assert result.observations == [
        {"description": "Visible surface scratch", "confidence": 0.91}
    ]
    assert result.limitations == ["Internal damage cannot be determined from the image."]
    assert result.raw_response == raw


def test_strips_markdown_code_fence_wrapper() -> None:
    raw = f"```json\n{_raw([])}\n```"
    result = _parse_response(raw)
    assert result.observations == []


def test_malformed_json_raises_vision_error() -> None:
    with pytest.raises(VisionError):
        _parse_response("this is not json at all")


def test_confidence_is_clamped_to_zero_one_range() -> None:
    raw = _raw(
        [
            {"description": "a", "confidence": 1.7},
            {"description": "b", "confidence": -0.3},
        ]
    )
    result = _parse_response(raw)
    assert result.observations[0]["confidence"] == 1.0
    assert result.observations[1]["confidence"] == 0.0


def test_missing_confidence_defaults_to_midpoint() -> None:
    raw = _raw([{"description": "no confidence given"}])
    result = _parse_response(raw)
    assert result.observations[0]["confidence"] == 0.5


def test_malformed_confidence_value_defaults_to_midpoint() -> None:
    raw = _raw([{"description": "a", "confidence": "not a number"}])
    result = _parse_response(raw)
    assert result.observations[0]["confidence"] == 0.5


def test_observation_missing_description_is_dropped() -> None:
    raw = _raw([{"confidence": 0.8}, {"description": "kept", "confidence": 0.5}])
    result = _parse_response(raw)
    assert result.observations == [{"description": "kept", "confidence": 0.5}]


def test_measurement_in_observation_is_flagged_as_limitation() -> None:
    raw = _raw([{"description": "Gap appears to be about 5mm wide", "confidence": 0.6}])
    result = _parse_response(raw)
    assert any("measurement" in limitation.lower() for limitation in result.limitations)


def test_no_measurement_does_not_add_flag() -> None:
    raw = _raw([{"description": "Surface appears discolored", "confidence": 0.6}])
    result = _parse_response(raw)
    assert result.limitations == []


def test_temperature_measurement_is_flagged() -> None:
    raw = _raw([{"description": "Surface reads approximately 85 degrees"}])
    result = _parse_response(raw)
    assert any("measurement" in limitation.lower() for limitation in result.limitations)


def test_flag_not_duplicated_if_already_present() -> None:
    warning = (
        "One or more observations mention a specific measurement or value; "
        "measurements cannot be reliably determined from a photograph and "
        "should be independently verified, not treated as fact."
    )
    raw = _raw(
        [{"description": "About 10mm of wear visible", "confidence": 0.5}],
        [warning],
    )
    result = _parse_response(raw)
    assert result.limitations.count(warning) == 1
