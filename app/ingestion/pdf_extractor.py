"""PDF text + structure extraction.

Uses pdfplumber's per-character font metadata to detect headings by relative
size rather than a full document-layout model: the most common font size in
the document is treated as body text, and lines rendered notably larger are
treated as headings (the single largest heading size found = section, any
smaller heading size = subsection). This is a lightweight, dependency-free
heuristic — it works well on manuals with consistent styling.

A second, size-independent signal supplements it: numbered ("5.2
Troubleshooting") and short ALL-CAPS ("SAFETY") lines are read as headings
by convention regardless of font size — the same text-pattern heuristic
app/ingestion/ocr.py already uses for scanned pages with no font metadata
at all, applied here too so a heading that's bold-only or otherwise styled
the same size as body text (a real, common inconsistency, not just a
scanned-page problem) isn't missed entirely. Genuine layout-ML structure
detection is still a real, larger improvement this doesn't attempt — see
docs/architecture-decisions.md.

Multi-column pages (a sidebar beside the body, two-column articles) are read
column by column: pdfplumber's line grouping otherwise joins the left and
right column text that share a baseline into one line, interleaving two
unrelated sentences. `_find_column_bands` finds runs of text that share a
vertical gutter, and only those runs are split; full-width text (titles,
footers) and ordinary single-column pages take the original code path.

Publisher boilerplate (the "About DOE's Industrial Technologies Program" block and the "PLEASE
CONTACT"
panel that close every DOE tip sheet) is dropped before chunking: it names the same program and
contact
details on every sheet, so it matches almost any query about "program", "energy" or "information"
and crowds real content out of the top results.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from app.config import get_settings

HEADING_SIZE_RATIO = 1.15
MAX_HEADING_CHARS = 90
MAX_ALL_CAPS_HEADING_CHARS = 60

NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(\S.+)$")

# A block starting like this opens a publisher's closing panel (about-the-program text, contact
# details,
# slogans, report numbers). It and everything after it on the same page is dropped. Anchored to the
# start
# of a line and deliberately specific: a generic word such as "Contact" must never end a page's
# content.
BOILERPLATE_START_RE = re.compile(
    r"^(About DOE.s\b|PLEASE CONTACT\b|Energy Efficiency and Renewable Energy\s*$|DOE/GO-\d)",
    re.IGNORECASE,
)

# Column detection. A gutter is a vertical strip with no text across a run of
# lines. These are deliberately conservative: a false split reorders text,
# while a missed one only leaves the page as it was before this detection.
COLUMN_MIN_GUTTER_PT = 12.0  # wider than any word space or hanging bullet indent
COLUMN_MIN_LINES = 4  # each column must hold at least this many text lines ...
COLUMN_MIN_CHARS = 80  # ... and at least this many characters


def text_pattern_heading_level(text: str) -> int | None:
    """Numbered/ALL-CAPS heading convention, independent of any font-size
    signal — shared by both the text-layer path below and
    app/ingestion/ocr.py's scanned-page path, so there's one definition of
    "looks like a heading by text pattern," not two to keep in sync."""
    match = NUMBERED_HEADING_RE.match(text)
    if match and len(text) <= MAX_HEADING_CHARS:
        return 1 if match.group(1).count(".") == 0 else 2
    is_short_all_caps = len(text) <= MAX_ALL_CAPS_HEADING_CHARS and text.isupper()
    if is_short_all_caps and any(c.isalpha() for c in text):
        return 1
    return None


@dataclass
class ExtractedBlock:
    page_number: int
    block_type: str  # "heading" | "text"
    level: int  # 1 = section, 2 = subsection, 0 = body text
    text: str
    size: float = 0.0
    # "size" headings get their level re-derived by _assign_heading_levels
    # (which compares against the document's largest heading size);
    # "pattern" headings already have a real level from the numbered/
    # ALL-CAPS convention itself and must not be overwritten by a size
    # comparison that was never meaningful for them (their size is
    # ordinary body-text size by definition — that's why the pattern
    # check exists at all).
    level_source: str = "size"


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
            # pdfplumber keeps every parsed character; a 300-page guide needs gigabytes
            page.flush_cache()
            blocks.extend(page_blocks)
            chars_per_page[page_number] = char_count

        _drop_publisher_boilerplate(blocks)
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
    counts: Counter = Counter()
    for page in pdf.pages:
        counts.update(round(c["size"]) for c in page.chars if c.get("size"))
        page.flush_cache()
    if not counts:
        return 10.0
    return float(counts.most_common(1)[0][0])


def _extract_page_blocks(
    page, page_number: int, body_size: float
) -> tuple[list[ExtractedBlock], int]:
    lines = _page_text_lines(page)

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

        is_size_heading = (
            len(text) <= MAX_HEADING_CHARS and avg_size >= body_size * HEADING_SIZE_RATIO
        )
        if is_size_heading:
            blocks.append(
                ExtractedBlock(page_number, "heading", 1, text, avg_size, level_source="size")
            )
            continue

        pattern_level = text_pattern_heading_level(text)
        if pattern_level is not None:
            blocks.append(
                ExtractedBlock(
                    page_number, "heading", pattern_level, text, avg_size, level_source="pattern"
                )
            )
        else:
            blocks.append(ExtractedBlock(page_number, "text", 0, text, avg_size))

    return blocks, char_count


def _text_lines(page_or_crop) -> list[dict]:
    try:
        return page_or_crop.extract_text_lines(layout=False, strip=True) or []
    except Exception:
        return []


def _page_text_lines(page) -> list[dict]:
    """Text lines in reading order, splitting multi-column bands into columns."""
    try:
        bands = _find_column_bands(page)
    except Exception:
        bands = []
    if not bands:
        return _text_lines(page)

    x0, top, x1, bottom = page.bbox
    lines: list[dict] = []
    cursor = top
    for band_top, band_bottom, cuts in bands:
        if band_top > cursor:
            lines.extend(_text_lines(page.within_bbox((x0, cursor, x1, band_top))))
        edges = [x0, *cuts, x1]
        for left, right in zip(edges, edges[1:], strict=False):
            lines.extend(_text_lines(page.within_bbox((left, band_top, right, band_bottom))))
        cursor = band_bottom
    if cursor < bottom:
        lines.extend(_text_lines(page.within_bbox((x0, cursor, x1, bottom))))
    return lines


def _find_column_bands(page) -> list[tuple[float, float, list[float]]]:
    """Finds runs of text blocks that share vertical gutters.

    Returns (top, bottom, gutter x-positions) bands, top to bottom; empty when
    the page is a single column. Text is first cut into blocks at fully blank
    horizontal strips. A band is then the longest run of consecutive blocks
    whose combined footprint still leaves at least one gutter with real text
    on every side, so a full-width title or footer (which crosses the gutter)
    ends or precedes a band instead of joining it.
    """
    chars = [c for c in page.chars if c.get("text", "").strip()]
    if not chars:
        return []
    x_origin = min(c["x0"] for c in chars)
    blocks = _text_blocks(chars)
    masks = [_occupancy(block_chars, x_origin) for block_chars in blocks]
    extents = [(min(c["top"] for c in b), max(c["bottom"] for c in b)) for b in blocks]

    bands: list[tuple[float, float, list[float]]] = []
    i = 0
    while i < len(blocks):
        best_end, best_cuts = None, None
        footprint = 0
        for j in range(i, len(blocks)):
            footprint |= masks[j]
            cuts = _valid_gutters(footprint, [c for b in blocks[i : j + 1] for c in b], x_origin)
            if cuts:
                best_end, best_cuts = j, cuts
            elif best_end is not None or _no_gutter_possible(footprint):
                break
        if best_end is None:
            i += 1
            continue
        # Cut halfway through the blank strip on each side, so no character straddles an edge.
        band_top = extents[i][0]
        band_bottom = extents[best_end][1]
        above = extents[i - 1][1] if i > 0 else page.bbox[1]
        below = extents[best_end + 1][0] if best_end + 1 < len(blocks) else page.bbox[3]
        bands.append(((above + band_top) / 2, (band_bottom + below) / 2, best_cuts))
        i = best_end + 1
    return bands


def _no_gutter_possible(footprint: int) -> bool:
    """True once the combined footprint leaves no interior gap wide enough to be a gutter."""
    return not _gaps(footprint)


def _text_blocks(chars: list[dict]) -> list[list[dict]]:
    """Groups characters into blocks separated by fully blank horizontal strips."""
    ordered = sorted(chars, key=lambda c: c["top"])
    blocks: list[list[dict]] = []
    current: list[dict] = []
    current_bottom = float("-inf")
    for char in ordered:
        if current and char["top"] > current_bottom:
            blocks.append(current)
            current = []
            current_bottom = float("-inf")
        current.append(char)
        current_bottom = max(current_bottom, char["bottom"])
    if current:
        blocks.append(current)
    return blocks


def _occupancy(chars: list[dict], x_origin: float) -> int:
    """Bitmask with one bit per point of x that some character covers."""
    mask = 0
    for char in chars:
        left = max(int(char["x0"] - x_origin), 0)
        right = max(int(char["x1"] - x_origin) + 1, left + 1)
        mask |= ((1 << (right - left)) - 1) << left
    return mask


def _gaps(footprint: int) -> list[tuple[int, int]]:
    """Interior blank runs (start, end) of at least COLUMN_MIN_GUTTER_PT in the footprint."""
    if footprint == 0:
        return []
    width = footprint.bit_length()
    gaps: list[tuple[int, int]] = []
    run_start = None
    for x in range(width):
        if footprint >> x & 1:
            if run_start is not None and x - run_start >= COLUMN_MIN_GUTTER_PT:
                gaps.append((run_start, x))
            run_start = None
        elif run_start is None:
            run_start = x
    return [(a, b) for a, b in gaps if a > 0]


def _valid_gutters(footprint: int, chars: list[dict], x_origin: float) -> list[float]:
    """Gutter x-positions for which every resulting column holds real text lines.

    Starts from every gap in the footprint and drops the narrowest one until
    each column has COLUMN_MIN_LINES lines and COLUMN_MIN_CHARS characters.
    """
    gaps = _gaps(footprint)
    while gaps:
        cuts = [x_origin + (a + b) / 2 for a, b in gaps]
        edges = [float("-inf"), *cuts, float("inf")]
        columns = [
            [c for c in chars if c["x0"] >= left and c["x1"] <= right]
            for left, right in zip(edges, edges[1:], strict=False)
        ]
        if all(
            len(col) >= COLUMN_MIN_CHARS and len({round(c["top"]) for c in col}) >= COLUMN_MIN_LINES
            for col in columns
        ):
            return cuts
        gaps.remove(min(gaps, key=lambda g: g[1] - g[0]))
    return []


def _drop_publisher_boilerplate(blocks: list[ExtractedBlock]) -> None:
    """Remove each page's closing publisher panel: from the first block matching
    BOILERPLATE_START_RE to
    the end of that page. Text before the marker on the same page, and all other pages, are
    untouched."""
    dropped_from: dict[int, int] = {}
    for i, block in enumerate(blocks):
        if block.page_number not in dropped_from and BOILERPLATE_START_RE.match(block.text):
            dropped_from[block.page_number] = i
    if not dropped_from:
        return
    blocks[:] = [
        b
        for i, b in enumerate(blocks)
        if b.page_number not in dropped_from or i < dropped_from[b.page_number]
    ]


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
    Pattern-derived headings (level_source="pattern") never participate —
    a numbered/ALL-CAPS heading is never mistakable for an oversized title,
    since it was never classified as one by size in the first place."""
    heading_indices = [
        i for i, b in enumerate(blocks) if b.block_type == "heading" and b.level_source == "size"
    ]
    if not heading_indices or heading_indices[0] != 0:
        return

    all_heading_sizes = {
        b.size for b in blocks if b.block_type == "heading" and b.level_source == "size"
    }
    if len(all_heading_sizes) < 3:
        return

    first = blocks[0]
    other_sizes = [
        b.size
        for i, b in enumerate(blocks)
        if i != 0 and b.block_type == "heading" and b.level_source == "size"
    ]
    if not other_sizes or first.size > max(other_sizes):
        del blocks[0]


def _assign_heading_levels(blocks: list[ExtractedBlock]) -> None:
    heading_sizes = sorted(
        {b.size for b in blocks if b.block_type == "heading" and b.level_source == "size"},
        reverse=True,
    )
    if not heading_sizes:
        return
    level1_size = heading_sizes[0]
    for block in blocks:
        if block.block_type != "heading" or block.level_source != "size":
            continue
        block.level = 1 if block.size >= level1_size - 0.5 else 2
