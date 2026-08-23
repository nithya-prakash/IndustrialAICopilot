from app.ingestion.chunker import chunk_blocks
from app.ingestion.pdf_extractor import ExtractedBlock


def test_single_section_short_text_becomes_one_chunk() -> None:
    blocks = [
        ExtractedBlock(1, "heading", 1, "Safety"),
        ExtractedBlock(1, "text", 0, "Disconnect power before servicing."),
        ExtractedBlock(1, "text", 0, "Allow the housing to cool first."),
    ]
    chunks = chunk_blocks(blocks, target_chars=1000, overlap_chars=150)

    assert len(chunks) == 1
    assert chunks[0].section == "Safety"
    assert chunks[0].subsection is None
    assert "Disconnect power" in chunks[0].content
    assert "cool first" in chunks[0].content


def test_new_heading_starts_a_new_chunk() -> None:
    blocks = [
        ExtractedBlock(1, "heading", 1, "Safety"),
        ExtractedBlock(1, "text", 0, "Text about safety."),
        ExtractedBlock(1, "heading", 1, "Installation"),
        ExtractedBlock(1, "text", 0, "Text about installation."),
    ]
    chunks = chunk_blocks(blocks, target_chars=1000, overlap_chars=150)

    assert len(chunks) == 2
    assert chunks[0].section == "Safety"
    assert chunks[1].section == "Installation"


def test_subsection_tracked_under_section() -> None:
    blocks = [
        ExtractedBlock(2, "heading", 1, "Troubleshooting"),
        ExtractedBlock(2, "heading", 2, "Unusual noise"),
        ExtractedBlock(2, "text", 0, "A grinding noise indicates bearing damage."),
        ExtractedBlock(2, "heading", 2, "Overheating"),
        ExtractedBlock(3, "text", 0, "Check for blocked ventilation."),
    ]
    chunks = chunk_blocks(blocks, target_chars=1000, overlap_chars=150)

    assert len(chunks) == 2
    assert chunks[0].section == "Troubleshooting"
    assert chunks[0].subsection == "Unusual noise"
    assert chunks[1].section == "Troubleshooting"
    assert chunks[1].subsection == "Overheating"
    assert chunks[1].page_number == 3


def test_long_section_splits_with_overlap() -> None:
    blocks = [
        ExtractedBlock(1, "heading", 1, "Maintenance"),
        ExtractedBlock(1, "text", 0, "A" * 60),
        ExtractedBlock(1, "text", 0, "B" * 60),
        ExtractedBlock(1, "text", 0, "C" * 60),
    ]
    chunks = chunk_blocks(blocks, target_chars=100, overlap_chars=20)

    assert len(chunks) > 1
    # every chunk after the first should start with the overlap tail of the previous chunk
    assert chunks[1].content.startswith(chunks[0].content[-20:])
    for chunk in chunks:
        assert chunk.section == "Maintenance"


def test_empty_blocks_produce_no_chunks() -> None:
    assert chunk_blocks([], target_chars=1000, overlap_chars=150) == []


def test_chunk_index_is_sequential() -> None:
    blocks = [
        ExtractedBlock(1, "heading", 1, "A"),
        ExtractedBlock(1, "text", 0, "one"),
        ExtractedBlock(1, "heading", 1, "B"),
        ExtractedBlock(1, "text", 0, "two"),
        ExtractedBlock(1, "heading", 1, "C"),
        ExtractedBlock(1, "text", 0, "three"),
    ]
    chunks = chunk_blocks(blocks, target_chars=1000, overlap_chars=150)
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
