"""Deterministic, rule-based confidence scoring and severity handling.

Confidence is deliberately NOT the model's own self-reported number — LLMs
are notoriously uncalibrated at self-assessing certainty (a model will
happily say "0.9 confident" about a guess with zero supporting evidence).
Instead it's computed here from concrete, auditable signals: what evidence
was actually gathered, how many causes are backed by a citation, whether
any tool call failed. This is the direct mechanism behind "the system must
never present a low-confidence diagnosis as certain" — confidence isn't
asked for, it's calculated, the same way citation validity is checked
rather than trusted (see app/rag/generation.py) and measurement claims are
flagged rather than trusted (see app/vision/analyzer.py).

Severity comes from the model's assessment (it requires domain judgment
about the identified causes that a fixed rule can't replicate), but is
clamped to the known enum and has one deterministic escalation floor: any
severity claim below what the objective sensor evidence supports is not
honored — see requires_human_approval and normalize_severity.
"""
from dataclasses import dataclass

BASE_CONFIDENCE = 0.5
DOCUMENT_EVIDENCE_BONUS = 0.15
SENSOR_EVIDENCE_BONUS = 0.15
IMAGE_EVIDENCE_BONUS = 0.15
PER_CITED_CAUSE_BONUS = 0.03
MAX_CITED_CAUSE_BONUS = 0.15
NO_EVIDENCE_PENALTY = 0.30
TOOL_ERROR_PENALTY = 0.05
MAX_TOOL_ERROR_PENALTY = 0.15

MIN_CONFIDENCE = 0.05
MAX_CONFIDENCE = 0.95

ALLOWED_SEVERITIES = ("low", "medium", "high", "critical")
_SEVERITY_RANK = {s: i for i, s in enumerate(ALLOWED_SEVERITIES)}


@dataclass
class EvidenceSignals:
    has_document_evidence: bool = False
    has_sensor_evidence: bool = False
    has_image_evidence: bool = False
    cited_cause_count: int = 0
    tool_error_count: int = 0


def calculate_confidence(signals: EvidenceSignals) -> float:
    score = BASE_CONFIDENCE
    any_evidence = (
        signals.has_document_evidence or signals.has_sensor_evidence or signals.has_image_evidence
    )

    if signals.has_document_evidence:
        score += DOCUMENT_EVIDENCE_BONUS
    if signals.has_sensor_evidence:
        score += SENSOR_EVIDENCE_BONUS
    if signals.has_image_evidence:
        score += IMAGE_EVIDENCE_BONUS
    if not any_evidence:
        score -= NO_EVIDENCE_PENALTY

    score += min(signals.cited_cause_count * PER_CITED_CAUSE_BONUS, MAX_CITED_CAUSE_BONUS)
    score -= min(signals.tool_error_count * TOOL_ERROR_PENALTY, MAX_TOOL_ERROR_PENALTY)

    return round(max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, score)), 3)


def normalize_severity(raw: str | None, *, escalate_to_at_least: str | None = None) -> str:
    """Clamps an arbitrary model-provided string to the known enum
    (defaulting to "low" for anything unrecognized), then applies an
    optional deterministic floor — e.g. objective sensor threshold
    violations should never let the model quietly report "low"."""
    severity = raw.lower().strip() if isinstance(raw, str) else ""
    if severity not in _SEVERITY_RANK:
        severity = "low"

    if escalate_to_at_least in _SEVERITY_RANK:
        if _SEVERITY_RANK[escalate_to_at_least] > _SEVERITY_RANK[severity]:
            severity = escalate_to_at_least

    return severity


def requires_human_approval(*, confidence: float, severity: str, approval_threshold: float) -> bool:
    return confidence < approval_threshold or severity in ("high", "critical")
