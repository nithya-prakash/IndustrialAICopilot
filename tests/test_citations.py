import uuid

from app.rag.generation import extract_citations
from app.rag.retrieval import RetrievedChunk


def _chunk(section: str, subsection: str | None = None, page: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        content="irrelevant body text",
        score=1.0,
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        filename="electric_motor_manual.pdf",
        page_number=page,
        section=section,
        subsection=subsection,
        equipment_type="electric_motor",
        equipment_id="MOTOR-001",
    )


def test_citation_property_formats_section_and_subsection() -> None:
    chunk = _chunk("Troubleshooting", "Unusual noise", page=3)
    assert chunk.citation == "[electric_motor_manual.pdf, Troubleshooting > Unusual noise, p.3]"


def test_citation_property_omits_missing_subsection() -> None:
    chunk = _chunk("Safety", subsection=None, page=1)
    assert chunk.citation == "[electric_motor_manual.pdf, Safety, p.1]"


def test_extract_citations_maps_valid_markers_to_real_sources() -> None:
    sources = [_chunk("Safety"), _chunk("Installation")]
    answer = "Disconnect power first [1]. Then align the shaft during mounting [2]."

    citations, invalid = extract_citations(answer, sources)

    assert citations == [sources[0].citation, sources[1].citation]
    assert invalid == []


def test_extract_citations_flags_out_of_range_marker_as_invalid() -> None:
    sources = [_chunk("Safety")]
    answer = "This claim cites a source that was never retrieved [4]."

    citations, invalid = extract_citations(answer, sources)

    assert citations == []
    assert invalid == ["[4]"]


def test_extract_citations_dedupes_repeated_markers() -> None:
    sources = [_chunk("Safety")]
    answer = "First point [1]. Second point, same source [1]."

    citations, invalid = extract_citations(answer, sources)

    assert citations == [sources[0].citation]
    assert invalid == []


def test_extract_citations_no_markers_returns_empty() -> None:
    sources = [_chunk("Safety")]
    citations, invalid = extract_citations("A plain answer with no citations.", sources)
    assert citations == []
    assert invalid == []


def test_extract_citations_mix_of_valid_and_invalid() -> None:
    sources = [_chunk("Safety"), _chunk("Installation")]
    answer = "Valid claim [1]. Fabricated claim [99]. Another valid one [2]."

    citations, invalid = extract_citations(answer, sources)

    assert citations == [sources[0].citation, sources[1].citation]
    assert invalid == ["[99]"]
