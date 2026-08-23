from app.evaluation.diagnosis_scoring import (
    citation_validity_rate,
    evidence_type_coverage,
    meets_severity_floor,
    tool_recall,
)


def test_tool_recall_all_required_tools_called() -> None:
    assert tool_recall({"query_sensor_history", "calculate"}, {"query_sensor_history"}) == 1.0


def test_tool_recall_partial() -> None:
    required = {"search_technical_documents", "query_sensor_history"}
    called = {"search_technical_documents"}
    assert tool_recall(called, required) == 0.5


def test_tool_recall_none_called() -> None:
    assert tool_recall(set(), {"calculate"}) == 0.0


def test_tool_recall_no_required_tools_is_vacuously_one() -> None:
    assert tool_recall({"calculate"}, set()) == 1.0


def test_evidence_type_coverage_full_match() -> None:
    assert evidence_type_coverage({"document_chunk", "sensor_reading"}, {"document_chunk"}) == 1.0


def test_evidence_type_coverage_partial() -> None:
    expected = {"document_chunk", "maintenance_record"}
    observed = {"document_chunk"}
    assert evidence_type_coverage(observed, expected) == 0.5


def test_evidence_type_coverage_no_expected_is_vacuously_one() -> None:
    assert evidence_type_coverage(set(), set()) == 1.0


def test_citation_validity_rate_all_cited() -> None:
    causes = [
        {"cause": "a", "supporting_citations": ["[doc, sec, p.1]"]},
        {"cause": "b", "supporting_citations": ["[doc, sec, p.2]"]},
    ]
    assert citation_validity_rate(causes) == 1.0


def test_citation_validity_rate_partial() -> None:
    causes = [
        {"cause": "a", "supporting_citations": ["[doc, sec, p.1]"]},
        {"cause": "b", "supporting_citations": []},
    ]
    assert citation_validity_rate(causes) == 0.5


def test_citation_validity_rate_no_causes_is_zero() -> None:
    assert citation_validity_rate([]) == 0.0


def test_meets_severity_floor_none_when_no_floor_specified() -> None:
    assert meets_severity_floor("low", None) is None


def test_meets_severity_floor_true_when_exceeded() -> None:
    assert meets_severity_floor("high", "medium") is True


def test_meets_severity_floor_true_when_exactly_met() -> None:
    assert meets_severity_floor("medium", "medium") is True


def test_meets_severity_floor_false_when_below() -> None:
    assert meets_severity_floor("low", "medium") is False
