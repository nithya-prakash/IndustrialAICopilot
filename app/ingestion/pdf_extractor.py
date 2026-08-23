"""PDF text + structure extraction.

Uses pdfplumber's per-character font metadata to detect headings by relative
size rather than a full document-layout model: the most common font size in
the document is treated as body text, and lines rendered notably larger are
treated as headings (the single largest heading size found = section, any
smaller heading size = subsection). This is a lightweight, dependency-free
heuristic — it works well on manuals with consistent styling but can miss
structure in inconsistently formatted documents, a known limitation.
"""
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from app.config import get_settings

HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 90


@dataclass
class ExtractedBlock:
    page_number: int
    block_type: str  # "heading" | "text"
    level: int  # 1 = section, 2 = subsection, 0 = body text
    text: str
    size: float = 0.0


@dataclass
class ExtractionResult:
    blocks: list[ExtractedBlock]
    low_text_pages: list[int]
    page_count: int
    chars_per_page: dict[int, int] = field(default_factory=dict)


def extract_pdf(path: Path) -> ExtractionResult:
    settings = get_settings()
    with pdfplumber.open(str(path)) as pdf:
        body_size = _detect_body_font_size(pdf)
        blocks: list[ExtractedBlock] = []
        chars_per_page: dict[int, int] = {}

        for page_number, page in enumerate(pdf.pages, start=1):
            page_blocks, char_count = _extract_page_blocks(page, page_number, body_size)
            blocks.extend(page_blocks)
            chars_per_page[page_number] = char_count

        _drop_document_title(blocks)
        _assign_heading_levels(blocks)

        low_text_pages = [
            page_number
            for page_number, char_count in chars_per_page.items()
            if char_count < settings.ocr_page_text_threshold
        ]

        return ExtractionResult(
            blocks=blocks,
            low_text_pages=low_text_pages,
            page_count=len(pdf.pages),
            chars_per_page=chars_per_page,
        )


def _detect_body_font_size(pdf) -> float:
    sizes = [round(c["size"]) for page in pdf.pages for c in page.chars if c.get("size")]
    if not sizes:
        return 10.0
    return float(Counter(sizes).most_common(1)[0][0])


def _extract_page_blocks(
    page, page_number: int, body_size: float
) -> tuple[list[ExtractedBlock], int]:
    try:
        lines = page.extract_text_lines(layout=False, strip=True) or []
    except Exception:
        lines = []

    blocks: list[ExtractedBlock] = []
    char_count = 0

    for line in lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        char_count += len(text)

        chars = line.get("chars") or []
        sizes = [round(c["size"]) for c in chars if c.get("size")]
        avg_size = sum(sizes) / len(sizes) if sizes else body_size

        is_heading_like = (
            len(text) <= MAX_HEADING_CHARS and avg_size >= body_size * HEADING_SIZE_RATIO
        )
        if is_heading_like:
            blocks.append(ExtractedBlock(page_number, "heading", 1, text, avg_size))
        else:
            blocks.append(ExtractedBlock(page_number, "text", 0, text, avg_size))

    return blocks, char_count


def _drop_document_title(blocks: list[ExtractedBlock]) -> None:
    """A manual's title (e.g. "Electric Motor Maintenance Manual") is often
    the single largest heading in the document, appearing once at the very
    start. Left in the block stream it would be classified as the sole
    level-1 heading, pushing every real section down into "subsection" and
    losing section names entirely — so it's dropped before level assignment
    instead of chunked as a heading.

    Only fires when there are 3+ distinct heading sizes (title/section/
    subsection tiers). With only 2 sizes there's no reliable way to tell a
    genuine title from a document whose first section simply happens to be
    the largest heading — collapsing that case would drop a real section.
    """
    heading_indices = [i for i, b in enumerate(blocks) if b.block_type == "heading"]
    if not heading_indices or heading_indices[0] != 0:
        return

    all_heading_sizes = {b.size for i, b in enumerate(blocks) if b.block_type == "heading"}
    if len(all_heading_sizes) < 3:
        return

    first = blocks[0]
    other_sizes = [
        b.size for i, b in enumerate(blocks) if i != 0 and b.block_type == "heading"
    ]
    if not other_sizes or first.size > max(other_sizes):
        del blocks[0]


def _assign_heading_levels(blocks: list[ExtractedBlock]) -> None:
    heading_sizes = sorted({b.size for b in blocks if b.block_type == "heading"}, reverse=True)
    if not heading_sizes:
        return
    level1_size = heading_sizes[0]
    for block in blocks:
        if block.block_type != "heading":
            continue
        block.level = 1 if block.size >= level1_size - 0.5 else 2
