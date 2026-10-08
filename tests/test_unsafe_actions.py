import pytest

from app.guardrails import (
    UNSAFE_ACTION_FALLBACK,
    sanitize_recommendations,
    unsafe_action_categories,
)
from app.tools.validation import validate_tool_input

UNSAFE = [
    ("Bypass the thermal protection and keep the motor running.", "bypass_safety_device"),
    (
        "Remove the guard so you can reach the coupling while it keeps turning.",
        "bypass_safety_device",
    ),
    ("You can inspect the terminals without locking out the supply.", "skip_isolation"),
    ("There is no need to de-energize the motor first.", "skip_isolation"),
    ("Grease the bearings while the motor is running.", "work_on_live_equipment"),
    ("Run the motor at 120% load until the temperature drops.", "exceed_ratings"),
    ("Operate it above the nameplate current for an hour.", "exceed_ratings"),
    ("Silence the overtemperature alarm and continue production.", "ignore_alarm"),
]
SAFE = [
    "Disconnect and lock out electrical power before any inspection.",
    "Confirm the load current does not exceed the nameplate full-load amperage.",
    "Do not bypass the interlock; call a supervisor.",
    "Never operate the motor with the guards removed.",
    "Do not proceed without lockout and tagout.",
    "Check the bearings for play and replace them in pairs.",
    "Clear dust from the cooling fins and fan shroud.",
    "Schedule an inspection if winding temperature is 40C above ambient.",
    "Verify the circuit is de-energized with a calibrated meter.",
]


@pytest.mark.parametrize(("text", "category"), UNSAFE)
def test_unsafe_advice_is_flagged(text, category):
    assert category in unsafe_action_categories(text)


@pytest.mark.parametrize("text", SAFE)
def test_normal_and_negated_safety_advice_is_not_flagged(text):
    assert unsafe_action_categories(text) == []


def test_sanitize_replaces_unsafe_action_and_drops_unsafe_checks():
    action, checks, blocked = sanitize_recommendations(
        "Bypass the thermal protection and keep running.",
        ["Check bearing play.", "Silence the alarm and continue.", "Clear the fan shroud."],
    )
    assert action == UNSAFE_ACTION_FALLBACK
    assert checks == ["Check bearing play.", "Clear the fan shroud."]
    assert blocked == ["bypass_safety_device", "ignore_alarm"]


def test_sanitize_keeps_safe_recommendations_unchanged():
    assert sanitize_recommendations("Replace the bearings in pairs.", ["Check alignment."]) == (
        "Replace the bearings in pairs.",
        ["Check alignment."],
        [],
    )


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("search_technical_documents", {"query": "overheating"}, None),
        ("search_technical_documents", {}, "Missing required"),
        ("search_technical_documents", {"query": "x", "extra": 1}, "Unknown argument"),
        ("search_technical_documents", {"query": 5}, "must be a string"),
        ("search_technical_documents", {"query": "x" * 501}, "too long"),
        ("calculate", {"expression": "1+" * 101}, "too long"),
        ("get_manual_section", {"document_id": "not-a-uuid", "section": "s"}, "UUID"),
        (
            "query_sensor_history",
            {
                "equipment_id": "M",
                "metric": "t",
                "start_time": "yesterday",
                "end_time": "2026-01-01",
            },
            "ISO 8601",
        ),
        (
            "query_sensor_history",
            {
                "equipment_id": "M",
                "metric": "t",
                "start_time": "2026-01-01T00:00:00Z",
                "end_time": "2026-01-02T00:00:00+00:00",
            },
            None,
        ),
        ("not_a_tool", {}, "Unknown tool"),
        ("calculate", "1+1", "JSON object"),
    ],
)
def test_tool_input_validation(name, args, expected):
    error = validate_tool_input(name, args)
    assert (error is None) if expected is None else (error is not None and expected in error)
