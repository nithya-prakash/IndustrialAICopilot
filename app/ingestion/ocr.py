"""OCR fallback for scanned pages with no embedded text layer.

Font metadata isn't available from OCR output, so heading detection here
falls back to text patterns: numbered headings ("5.2 Troubleshooting") and
short ALL-CAPS lines. Less reliable than the font-size heuristic used for
text-layer PDFs (app/ingestion/pdf_extractor.py) — a known limitation for
scanned documents with inconsistent heading conventions.
"""
import re
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path

from app.ingestion.pdf_extractor import ExtractedBlock

NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(\S.+)$")
MAX_HEADING_CHARS = 90


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

        match = NUMBERED_HEADING_RE.match(line)
        if match and len(line) <= MAX_HEADING_CHARS:
            level = 1 if match.group(1).count(".") == 0 else 2
            blocks.append(ExtractedBlock(page_number, "heading", level, line))
        elif len(line) <= 60 and line.isupper() and any(c.isalpha() for c in line):
            blocks.append(ExtractedBlock(page_number, "heading", 1, line))
        else:
            blocks.append(ExtractedBlock(page_number, "text", 0, line))
    return blocks
