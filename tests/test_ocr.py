from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.ingestion.ocr import ocr_pages
from app.ingestion.pdf_extractor import extract_pdf


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    """A PDF with only a rasterized image of text — no embedded text layer,
    simulating a scanned document."""
    image = Image.new("RGB", (1200, 400), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 48)
    except OSError:
        font = ImageFont.load_default(size=48)
    draw.text((40, 40), "5.2 Unusual noise", fill="black", font=font)
    draw.text(
        (40, 140), "Check the bearing for damage before disassembly.", fill="black", font=font
    )
    image_path = tmp_path / "scan.png"
    image.save(image_path)

    pdf_path = tmp_path / "scanned.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=LETTER)
    c.drawImage(str(image_path), 50, 500, width=500, height=167)
    c.save()
    return pdf_path


def test_scanned_page_is_flagged_for_ocr(scanned_pdf: Path) -> None:
    result = extract_pdf(scanned_pdf)
    assert result.low_text_pages == [1]


def test_ocr_extracts_readable_text_and_heading(scanned_pdf: Path) -> None:
    blocks = ocr_pages(scanned_pdf, [1])
    all_text = " ".join(b.text for b in blocks)

    assert "bearing" in all_text.lower()

    heading_blocks = [b for b in blocks if b.block_type == "heading"]
    assert any("Unusual noise" in b.text for b in heading_blocks)
    assert any(b.level == 2 for b in heading_blocks if "Unusual noise" in b.text)
