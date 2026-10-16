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


# --- Multi-column layouts -------------------------------------------------------------------

LEFT_SENTENCE = (
    "Check the shaft alignment before restarting the motor, because even a small angular error "
    "will overload the bearings and shorten their service life considerably."
)
RIGHT_SENTENCE = (
    "Record the inlet pressure at every shift change, since a gradual drop usually points to a "
    "partly blocked strainer long before the pump starts to cavitate audibly."
)


def _two_column_pdf(path: Path, *, with_full_width_title: bool) -> Path:
    from reportlab.platypus import BaseDocTemplate, Frame, FrameBreak, PageTemplate

    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)
    width, height = LETTER
    margin, gap = 50, 30
    column_width = (width - 2 * margin - gap) / 2
    body_top = height - margin - (60 if with_full_width_title else 0)
    frames = [
        Frame(margin, margin, column_width, body_top - margin, id="left"),
        Frame(margin + column_width + gap, margin, column_width, body_top - margin, id="right"),
    ]
    doc = BaseDocTemplate(str(path), pagesize=LETTER)
    doc.addPageTemplates([PageTemplate(id="two", frames=frames)])

    story = []
    if with_full_width_title:
        # A title that spans both columns sits above the frames, drawn on the canvas.
        def draw_title(canvas, _doc) -> None:
            canvas.setFont("Helvetica-Bold", 20)
            canvas.drawString(margin, height - margin - 20, "Maintenance Tip Sheet")

        doc.pageTemplates[0].onPage = draw_title
    story += [Paragraph(LEFT_SENTENCE + " " + LEFT_SENTENCE, body), FrameBreak()]
    story += [Paragraph(RIGHT_SENTENCE + " " + RIGHT_SENTENCE, body)]
    doc.build(story)
    return path


def _joined_text(result) -> str:
    return " ".join(b.text for b in result.blocks)


def test_two_column_page_is_read_column_by_column(tmp_path: Path) -> None:
    result = extract_pdf(_two_column_pdf(tmp_path / "cols.pdf", with_full_width_title=False))
    text = _joined_text(result)
    # Each sentence survives intact, i.e. the columns were not interleaved line by line.
    assert LEFT_SENTENCE in text
    assert RIGHT_SENTENCE in text
    assert text.index(LEFT_SENTENCE) < text.index(RIGHT_SENTENCE)


def test_full_width_title_stays_before_the_columns(tmp_path: Path) -> None:
    result = extract_pdf(_two_column_pdf(tmp_path / "cols_title.pdf", with_full_width_title=True))
    text = _joined_text(result)
    assert text.index("Maintenance Tip Sheet") < text.index(LEFT_SENTENCE)
    assert LEFT_SENTENCE in text
    assert RIGHT_SENTENCE in text


def test_hanging_indent_bullets_are_not_split_into_columns(tmp_path: Path) -> None:
    styles = getSampleStyleSheet()
    bullet = ParagraphStyle(
        "Bullet", parent=styles["BodyText"], fontSize=10, leftIndent=30, bulletIndent=0
    )
    path = tmp_path / "bullets.pdf"
    SimpleDocTemplate(str(path), pagesize=LETTER).build(
        [
            Paragraph(
                f"Step number {n} requires isolating the supply and tagging the valve.",
                bullet,
                bulletText="•",
            )
            for n in range(12)
        ]
    )
    texts = [b.text for b in extract_pdf(path).blocks if b.block_type == "text"]
    assert len(texts) == 12
    assert all("isolating the supply and tagging the valve" in t for t in texts)


def test_a_wide_gap_with_too_little_text_is_not_a_column(tmp_path: Path) -> None:
    # A short right-hand note beside a long paragraph must not turn the page into two columns.
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)
    path = tmp_path / "note.pdf"
    SimpleDocTemplate(str(path), pagesize=LETTER, rightMargin=250).build(
        [Paragraph(LEFT_SENTENCE + " " + LEFT_SENTENCE, body)]
    )
    assert LEFT_SENTENCE in _joined_text(extract_pdf(path))


def _boilerplate_pdf(path: Path, closing_heading: str) -> Path:
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10)
    SimpleDocTemplate(str(path), pagesize=LETTER).build(
        [
            Paragraph("Check the pump seal weekly for leaks and record what you find.", body),
            Paragraph(closing_heading, body),
            Paragraph("Call the information center at 1-877-000-0000 or visit www.example.gov.",
            body),
            Paragraph("DOE/GO-102005-2160", body),
        ]
    )
    return path


def test_publisher_closing_panel_is_dropped(tmp_path: Path) -> None:
    pdf = _boilerplate_pdf(tmp_path / "doe.pdf", "About DOE's Industrial Technologies Program")
    result = extract_pdf(pdf)
    text = _joined_text(result)
    assert "pump seal weekly" in text
    assert "information center" not in text
    assert "DOE/GO-102005-2160" not in text
    assert "About DOE" not in text


def test_please_contact_panel_is_dropped(tmp_path: Path) -> None:
    result = extract_pdf(_boilerplate_pdf(tmp_path / "contact.pdf", "PLEASE CONTACT:"))
    assert "pump seal weekly" in _joined_text(result)
    assert "1-877" not in _joined_text(result)


def test_ordinary_contact_text_is_kept(tmp_path: Path) -> None:
    result = extract_pdf(_boilerplate_pdf(tmp_path / "plain.pdf", "Technician notes"))
    text = _joined_text(result)
    assert "information center" in text


def test_report_number_footer_is_dropped(tmp_path: Path) -> None:
    pdf = _boilerplate_pdf(tmp_path / "report.pdf", "DOE/GO-102012-3735 - November 2012")
    result = extract_pdf(pdf)
    text = _joined_text(result)
    assert "pump seal weekly" in text
    assert "information center" not in text
