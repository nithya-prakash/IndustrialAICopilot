from app.agents.sensor_validation import validate_sensor_findings

EVIDENCE = [
    {
        "type": "sensor_reading",
        "citation": "[MOTOR-001 sensor history, temperature, 2026-08-01 to 2026-08-02]",
        "detail": "temperature: mean 62.4, max 91.5, 3 anomalies, rising trend",
    },
    {"type": "document_chunk", "citation": "[manual.pdf, Overheating, p.1]", "detail": "ignore"},
]


def keep(finding, known=""):
    return validate_sensor_findings([finding], EVIDENCE, known)


def test_finding_matching_retrieved_data_is_kept():
    kept, dropped = keep({"metric": "temperature", "finding": "Peaked at 91.5 with 3 anomalies."})
    assert len(kept) == 1 and dropped == 0


def test_rounding_is_tolerated():
    kept, _ = keep({"metric": "temperature", "finding": "Maximum around 91.4 degrees."})
    assert len(kept) == 1


def test_invented_number_is_dropped():
    kept, dropped = keep({"metric": "temperature", "finding": "Peaked at 118.0 degrees."})
    assert kept == [] and dropped == 1


def test_metric_never_queried_is_dropped():
    kept, dropped = keep({"metric": "vibration_rms", "finding": "Vibration was high."})
    assert kept == [] and dropped == 1


def test_metric_supplied_by_the_technician_counts_as_known():
    kept, _ = keep(
        {"metric": "vibration_rms", "finding": "Reported value 5.2 is high."},
        known='{"vibration_rms": 5.2}',
    )
    assert len(kept) == 1


def test_baseline_claim_without_baseline_evidence_is_dropped():
    evidence = [
        {
            "type": "sensor_reading",
            "citation": "[M sensor history, rpm, r]",
            "detail": "rpm: max 1490",
        }
    ]
    kept, dropped = validate_sensor_findings(
        [{"metric": "rpm", "finding": "Reading is above baseline."}], evidence
    )
    assert kept == [] and dropped == 1


def test_baseline_claim_is_allowed_when_the_evidence_has_statistics():
    kept, dropped = keep({"metric": "temperature", "finding": "Max is well above the usual level."})
    assert (
        len(kept) == 1 and dropped == 0
    )  # the evidence includes a mean, so a baseline is grounded


def test_malformed_findings_are_dropped_and_non_lists_ignored():
    kept, dropped = validate_sensor_findings(
        ["text", {"metric": "", "finding": "x"}, {"finding": "y"}], EVIDENCE
    )
    assert kept == [] and dropped == 3
    assert validate_sensor_findings(None, EVIDENCE) == ([], 0)
    assert validate_sensor_findings({"a": 1}, EVIDENCE) == ([], 0)
