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
