import uuid

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
