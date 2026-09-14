from pathlib import Path

import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

from app.ingestion.pdf_extractor import extract_pdf


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=20)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)

    path = tmp_path / "sample.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    doc.build(
        [
            Paragraph("Troubleshooting", h1),
            Paragraph("Unusual noise", h2),
            Paragraph(
                "A grinding noise usually indicates bearing damage that requires inspection.",
                body,
            ),
        ]
    )
    return path


def test_extract_pdf_detects_headings_by_font_size(sample_pdf: Path) -> None:
    result = extract_pdf(sample_pdf)

    heading_texts = [b.text for b in result.blocks if b.block_type == "heading"]
    assert "Troubleshooting" in heading_texts
    assert "Unusual noise" in heading_texts

    section_heading = next(b for b in result.blocks if b.text == "Troubleshooting")
    subsection_heading = next(b for b in result.blocks if b.text == "Unusual noise")
    assert section_heading.level == 1
    assert subsection_heading.level == 2


def test_extract_pdf_captures_body_text(sample_pdf: Path) -> None:
    result = extract_pdf(sample_pdf)
    body_blocks = [b.text for b in result.blocks if b.block_type == "text"]
    assert any("grinding noise" in t for t in body_blocks)


def test_extract_pdf_page_count(sample_pdf: Path) -> None:
    result = extract_pdf(sample_pdf)
    assert result.page_count == 1
    assert result.low_text_pages == []


@pytest.fixture
def titled_sample_pdf(tmp_path: Path) -> Path:
    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title", parent=styles["Title"], fontSize=24)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)

    path = tmp_path / "titled.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    doc.build(
        [
            Paragraph("Electric Motor Maintenance Manual", title),
            Paragraph("Troubleshooting", h1),
            Paragraph("Unusual noise", h2),
            Paragraph("A grinding noise indicates bearing damage.", body),
        ]
    )
    return path


def test_document_title_is_dropped_not_treated_as_a_section(titled_sample_pdf: Path) -> None:
    result = extract_pdf(titled_sample_pdf)

    heading_texts = [b.text for b in result.blocks if b.block_type == "heading"]
    assert "Electric Motor Maintenance Manual" not in heading_texts

    section_heading = next(b for b in result.blocks if b.text == "Troubleshooting")
    subsection_heading = next(b for b in result.blocks if b.text == "Unusual noise")
    assert section_heading.level == 1
    assert subsection_heading.level == 2


@pytest.fixture
def same_size_heading_pdf(tmp_path: Path) -> Path:
    """A heading styled the same font size as body text (bold-only, or just
    inconsistently authored) — the font-size heuristic alone can't see
    this at all; only the text-pattern fallback (numbered/ALL-CAPS) can."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)

    path = tmp_path / "same_size.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    doc.build(
        [
            Paragraph("SAFETY", body),
            Paragraph("Disconnect power before servicing the unit.", body),
            Paragraph("5.2 Troubleshooting", body),
            Paragraph("Check the bearing if vibration increases.", body),
        ]
    )
    return path


def test_extract_pdf_detects_all_caps_heading_at_body_font_size(
    same_size_heading_pdf: Path,
) -> None:
    result = extract_pdf(same_size_heading_pdf)
    heading = next(b for b in result.blocks if b.text == "SAFETY")
    assert heading.block_type == "heading"
    assert heading.level == 1
    assert heading.level_source == "pattern"


def test_extract_pdf_detects_numbered_heading_at_body_font_size(
    same_size_heading_pdf: Path,
) -> None:
    result = extract_pdf(same_size_heading_pdf)
    heading = next(b for b in result.blocks if b.text == "5.2 Troubleshooting")
    assert heading.block_type == "heading"
    assert heading.level == 2  # one dot in "5.2" -> subsection
    assert heading.level_source == "pattern"


def test_extract_pdf_body_text_between_pattern_headings_stays_text(
    same_size_heading_pdf: Path,
) -> None:
    result = extract_pdf(same_size_heading_pdf)
    body_texts = [b.text for b in result.blocks if b.block_type == "text"]
    assert "Disconnect power before servicing the unit." in body_texts
    assert "Check the bearing if vibration increases." in body_texts


def test_pattern_heading_level_not_overridden_by_unrelated_size_headings(
    tmp_path: Path,
) -> None:
    """A document with BOTH size-based headings (large font) and a
    pattern-based heading (body-sized, numbered) — the pattern heading's
    level must come from its own numbering convention, not get
    re-classified by _assign_heading_levels' size comparison, which was
    never meaningful for it."""
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=20)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)

    path = tmp_path / "mixed.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=LETTER)
    doc.build(
        [
            Paragraph("Troubleshooting", h1),
            Paragraph("A general troubleshooting overview.", body),
            Paragraph("5.2 Bearing wear", body),
            Paragraph("Inspect the bearing surface for pitting.", body),
        ]
    )

    result = extract_pdf(path)
    size_heading = next(b for b in result.blocks if b.text == "Troubleshooting")
    pattern_heading = next(b for b in result.blocks if b.text == "5.2 Bearing wear")
    assert size_heading.level == 1
    assert pattern_heading.level == 2
    assert pattern_heading.level_source == "pattern"
