"""Pure scoring functions for the diagnosis-agent evaluation harness
(evaluation/diagnosis_eval.py). Kept separate from that runner script, same
split as app/evaluation/metrics.py vs evaluation/run.py, so the scoring
logic itself is unit-testable without a live LLM call — see
tests/test_diagnosis_scoring.py.

These are deliberately structural/deterministic metrics, not a subjective
"quality score" from an LLM-as-judge: tool_recall and evidence_type_coverage
are checked against a human-labeled expectation per scenario (same category
of ground truth as the Phase 3 retrieval eval's expected_sources — a stated,
inspectable label, not something invented after the fact), and
citation_validity_rate / meets_severity_floor read off invariants the
diagnosis agent already enforces deterministically (Phase 6). Nothing here
asks a model to grade another model's output.
"""
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def tool_recall(tools_called: set[str], required_tools: set[str]) -> float:
    """Fraction of the scenario's required tools that were actually called.
    Undefined (1.0, vacuously) for a scenario that requires no tools."""
    if not required_tools:
        return 1.0
    return len(required_tools & tools_called) / len(required_tools)


def evidence_type_coverage(observed_types: set[str], expected_types: set[str]) -> float:
    """Fraction of the scenario's expected evidence categories
    (document_chunk / sensor_reading / image_observation / maintenance_record)
    that the diagnosis actually gathered at least one item of."""
    if not expected_types:
        return 1.0
    return len(expected_types & observed_types) / len(expected_types)


def citation_validity_rate(possible_causes: list[dict]) -> float:
    """Fraction of possible_causes that carry at least one citation. The
    citations themselves are already guaranteed valid by the agent loop's
    own validation (a cause's supporting_citations list only ever contains
    citations that matched real gathered evidence — see
    app/agents/diagnosis_agent.py:_validate_causes) — this just measures how
    many causes ended up with real supporting evidence attached, not whether
    a citation is fabricated."""
    if not possible_causes:
        return 0.0
    cited = sum(1 for cause in possible_causes if cause.get("supporting_citations"))
    return cited / len(possible_causes)


def meets_severity_floor(actual_severity: str, floor: str | None) -> bool | None:
    """None when the scenario doesn't specify a floor (not applicable);
    otherwise whether the diagnosis's severity is at least as high as the
    scenario's expected floor. Only meaningful for scenarios whose floor is
    grounded in a deterministic rule the agent already enforces (e.g. a
    seeded sensor anomaly forces at least "medium" — Phase 6's
    normalize_severity escalation), not a subjective judgment call."""
    if floor is None:
        return None
    return _SEVERITY_RANK[actual_severity] >= _SEVERITY_RANK[floor]
