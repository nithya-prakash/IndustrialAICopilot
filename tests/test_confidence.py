from app.agents.confidence import (
    MAX_CONFIDENCE,
    MIN_CONFIDENCE,
    EvidenceSignals,
    calculate_confidence,
    normalize_severity,
    requires_human_approval,
)


def test_no_evidence_at_all_gives_low_confidence() -> None:
    score = calculate_confidence(EvidenceSignals())
    assert score < 0.5


def test_full_evidence_gives_high_confidence() -> None:
    signals = EvidenceSignals(
        has_document_evidence=True,
        has_sensor_evidence=True,
        has_image_evidence=True,
        cited_cause_count=3,
    )
    score = calculate_confidence(signals)
    assert score > 0.8


def test_confidence_never_exceeds_max() -> None:
    signals = EvidenceSignals(
        has_document_evidence=True,
        has_sensor_evidence=True,
        has_image_evidence=True,
        cited_cause_count=50,
    )
    assert calculate_confidence(signals) == MAX_CONFIDENCE


def test_confidence_never_goes_below_min() -> None:
    signals = EvidenceSignals(tool_error_count=100)
    assert calculate_confidence(signals) == MIN_CONFIDENCE


def test_tool_errors_reduce_confidence() -> None:
    base = EvidenceSignals(has_document_evidence=True)
    with_errors = EvidenceSignals(has_document_evidence=True, tool_error_count=2)
    assert calculate_confidence(with_errors) < calculate_confidence(base)


def test_more_evidence_types_increase_confidence() -> None:
    one_source = EvidenceSignals(has_document_evidence=True)
    two_sources = EvidenceSignals(has_document_evidence=True, has_sensor_evidence=True)
    assert calculate_confidence(two_sources) > calculate_confidence(one_source)


def test_normalize_severity_valid_value_passes_through() -> None:
    assert normalize_severity("high") == "high"


def test_normalize_severity_case_insensitive() -> None:
    assert normalize_severity("HIGH") == "high"
    assert normalize_severity("  Medium  ") == "medium"


def test_normalize_severity_invalid_defaults_to_low() -> None:
    assert normalize_severity("catastrophic") == "low"
    assert normalize_severity(None) == "low"
    assert normalize_severity(123) == "low"  # type: ignore[arg-type]


def test_normalize_severity_escalation_floor_applies() -> None:
    assert normalize_severity("low", escalate_to_at_least="medium") == "medium"


def test_normalize_severity_escalation_does_not_downgrade() -> None:
    assert normalize_severity("critical", escalate_to_at_least="medium") == "critical"


def test_normalize_severity_no_escalation_when_none() -> None:
    assert normalize_severity("low", escalate_to_at_least=None) == "low"


def test_requires_approval_below_threshold() -> None:
    assert requires_human_approval(confidence=0.5, severity="low", approval_threshold=0.75) is True


def test_requires_approval_above_threshold_low_severity() -> None:
    result = requires_human_approval(confidence=0.9, severity="low", approval_threshold=0.75)
    assert result is False


def test_requires_approval_high_severity_overrides_confidence() -> None:
    result = requires_human_approval(confidence=0.95, severity="high", approval_threshold=0.75)
    assert result is True


def test_requires_approval_critical_severity_overrides_confidence() -> None:
    result = requires_human_approval(confidence=0.99, severity="critical", approval_threshold=0.75)
    assert result is True


def test_requires_approval_medium_severity_with_high_confidence_does_not_require() -> None:
    result = requires_human_approval(confidence=0.9, severity="medium", approval_threshold=0.75)
    assert result is False
