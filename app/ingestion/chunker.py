"""Structure-aware chunking: splits on heading boundaries first, and only
falls back to size-based splitting within a section/subsection that runs
long. Each chunk carries the section/subsection it belongs to, so citations
can point at "Troubleshooting > Unusual noise" rather than a raw page
number.
"""
from dataclasses import dataclass

from app.ingestion.pdf_extractor import ExtractedBlock


@dataclass
class Chunk:
    chunk_index: int
    content: str
    page_number: int | None
    section: str | None
    subsection: str | None


def chunk_blocks(
    blocks: list[ExtractedBlock], target_chars: int, overlap_chars: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    section: str | None = None
    subsection: str | None = None
    buffer = ""
    buffer_page: int | None = None

    def flush() -> None:
        nonlocal buffer, buffer_page
        text = buffer.strip()
        if text:
            chunks.append(Chunk(len(chunks), text, buffer_page, section, subsection))
        buffer = ""
        buffer_page = None

    for block in blocks:
        if block.block_type == "heading":
            flush()
            if block.level == 1:
                section = block.text
                subsection = None
            else:
                subsection = block.text
            continue

        if buffer_page is None:
            buffer_page = block.page_number

        candidate = f"{buffer} {block.text}".strip() if buffer else block.text
        if len(candidate) <= target_chars:
            buffer = candidate
            continue

        flush()
        tail = chunks[-1].content[-overlap_chars:] if chunks and overlap_chars else ""
        buffer = f"{tail} {block.text}".strip() if tail else block.text
        buffer_page = block.page_number

    flush()
    return chunks
