"""Validation of the model's sensor findings against the sensor data it actually retrieved.

The final JSON asks the model for `sensor_findings: [{"metric", "finding"}]`. Observed failure: a
model asserted a reading was "above baseline" when no baseline had been retrieved. A finding is
kept only if
  - its metric was queried (it appears in a sensor_reading citation) or supplied by the technician,
  - every number it states matches a number in the retrieved sensor evidence or the technician's
    input (small rounding allowed), and
  - it does not talk about a baseline or average when none was retrieved.
Anything else is dropped and counted, so the diagnosis can say it did so.
"""

import re

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_BASELINE_WORDS = re.compile(r"\b(baseline|historical average|usual level|normal range)\b", re.I)
_EVIDENCE_BASELINE_WORDS = re.compile(r"\b(baseline|mean|average|std|normal range)\b", re.I)


def _numbers(text: str) -> list[float]:
    return [float(n) for n in _NUMBER.findall(text or "")]


def _matches(value: float, known: list[float]) -> bool:
    return any(abs(value - k) <= max(0.051, abs(k) * 0.01) for k in known)


def validate_sensor_findings(
    findings: object, evidence: list[dict], known_input_text: str = ""
) -> tuple[list[dict], int]:
    """Returns (kept findings, number dropped)."""
    if not isinstance(findings, list):
        return [], 0
    sensor_items = [e for e in evidence if e.get("type") == "sensor_reading"]
    evidence_text = " ".join(f"{e.get('citation', '')} {e.get('detail', '')}" for e in sensor_items)
    known_numbers = _numbers(evidence_text) + _numbers(known_input_text)
    queried = evidence_text.lower() + " " + known_input_text.lower()
    has_baseline_evidence = bool(_EVIDENCE_BASELINE_WORDS.search(evidence_text))

    kept, dropped = [], 0
    for finding in findings:
        if not (
            isinstance(finding, dict)
            and isinstance(finding.get("metric"), str)
            and isinstance(finding.get("finding"), str)
            and finding["metric"].strip()
            and finding["finding"].strip()
        ):
            dropped += 1
            continue
        metric, text = finding["metric"].strip(), finding["finding"].strip()
        stated = [n for n in _numbers(text) if abs(n) >= 10 or "." in str(n)[:-2] or n != int(n)]
        if (
            metric.lower() not in queried
            or any(not _matches(n, known_numbers) for n in stated)
            or (_BASELINE_WORDS.search(text) and not has_baseline_evidence)
        ):
            dropped += 1
            continue
        kept.append({"metric": metric, "finding": text})
    return kept, dropped
