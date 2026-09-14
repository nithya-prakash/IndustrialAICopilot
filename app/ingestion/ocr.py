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

    first_page, last_page = min(page_numbers), max(page_numbers)
    images = convert_from_path(str(path), first_page=first_page, last_page=last_page)
    wanted = set(page_numbers)

    blocks: list[ExtractedBlock] = []
    for offset, image in enumerate(images):
        page_number = first_page + offset
        if page_number not in wanted:
            continue
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
