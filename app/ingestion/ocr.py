"""OCR fallback for scanned pages with no embedded text layer.

Font metadata isn't available from OCR output, so heading detection here
relies entirely on the text-pattern heuristic (numbered headings, short
ALL-CAPS lines) defined once in app/ingestion/pdf_extractor.py and shared
with the text-layer path there — less reliable than that path's font-size
signal (which OCR output has no equivalent of), a known limitation for
scanned documents with inconsistent heading conventions.
"""

from pathlib import Path

import pytesseract
from pdf2image import convert_from_path

from app.ingestion.pdf_extractor import ExtractedBlock, text_pattern_heading_level


def ocr_pages(path: Path, page_numbers: list[int]) -> list[ExtractedBlock]:
    if not page_numbers:
        return []

    # One page at a time: rendering the whole span from the first to the last scanned page held
    # every
    # page in between as an image, which ran a 321-page guide with scanned pages 4 and 321 out of
    # memory.
    blocks: list[ExtractedBlock] = []
    for page_number in sorted(set(page_numbers)):
        images = convert_from_path(str(path), first_page=page_number, last_page=page_number)
        for image in images:
            text = pytesseract.image_to_string(image)
            blocks.extend(_classify_lines(text, page_number))
    return blocks


def _classify_lines(text: str, page_number: int) -> list[ExtractedBlock]:
    blocks: list[ExtractedBlock] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        level = text_pattern_heading_level(line)
        if level is not None:
            blocks.append(
                ExtractedBlock(page_number, "heading", level, line, level_source="pattern")
            )
        else:
            blocks.append(ExtractedBlock(page_number, "text", 0, line))
    return blocks
