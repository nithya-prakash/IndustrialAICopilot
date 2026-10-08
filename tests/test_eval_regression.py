"""Regression gate: model-free evaluations whose scores must not silently drop.

Both run in plain pytest (no database, no model download), so CI fails when a change makes the
injection screen or keyword retrieval measurably worse. Thresholds sit slightly below today's
values (injection regex: 50/116 caught, 4/105 false positives; BM25 on 53 questions: MRR 0.94,
recall@5 0.98); raise them when the scores improve. Dense/hybrid/rerank retrieval and the LLM
evaluations need Qdrant, models or a provider, so they are run by hand (see the README).
"""

import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.guardrails import scan_text
from app.ingestion.chunker import chunk_blocks
from app.ingestion.pdf_extractor import extract_pdf
from app.rag.bm25 import bm25_search

DATA = Path("data/evaluation")


def test_injection_set_is_still_large_enough():
    data = json.loads((DATA / "injection_set_v2.json").read_text())
    assert len(data["attacks"]) >= 100 and len(data["benign"]) >= 100


def test_regex_injection_screen_detection_and_false_positive_rates(monkeypatch):
    monkeypatch.setattr(get_settings(), "injection_scanner", "regex")
    data = json.loads((DATA / "injection_set_v2.json").read_text())
    detected = sum(bool(scan_text(a["text"])) for a in data["attacks"]) / len(data["attacks"])
    false_positives = sum(bool(scan_text(b["text"])) for b in data["benign"]) / len(data["benign"])
    assert detected >= 0.40, f"detection fell to {detected:.3f}"
    assert false_positives <= 0.06, f"false-positive rate rose to {false_positives:.3f}"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> list[tuple[str, str]]:
    from scripts import generate_eval_manuals, generate_sample_manual

    folder = tmp_path_factory.mktemp("manuals")
    generate_sample_manual.OUTPUT_PATH = folder / "electric_motor_manual.pdf"
    generate_sample_manual.build_pdf()
    generate_eval_manuals.PDF_DIR = folder
    for name, (title, sections) in generate_eval_manuals.MANUALS.items():
        generate_eval_manuals.build_pdf(name, title, sections)

    settings = get_settings()
    entries = []
    for pdf in sorted(folder.glob("*.pdf")):
        blocks = extract_pdf(pdf).blocks
        for chunk in chunk_blocks(
            blocks, settings.chunk_target_chars, settings.chunk_overlap_chars
        ):
            heading = chunk.section or ""
            if chunk.subsection:
                heading = f"{heading} > {chunk.subsection}"
            entries.append((f"{pdf.name}:{heading}", chunk.content))
    return entries


def test_bm25_retrieval_quality_on_the_53_question_set(corpus):
    questions = json.loads((DATA / "rag_questions.json").read_text())
    assert len(questions) >= 50 and len(corpus) >= 40
    reciprocal, hits_at_5 = [], 0
    for q in questions:
        ids = [c.chunk_id for c in bm25_search(q["question"], corpus, top_k=5)]
        expected = set(q["expected_sources"])
        rank = next((i for i, cid in enumerate(ids, 1) if cid in expected), None)
        reciprocal.append(1 / rank if rank else 0.0)
        hits_at_5 += rank is not None
    mrr = sum(reciprocal) / len(questions)
    assert mrr >= 0.90, f"BM25 MRR fell to {mrr:.3f}"
    assert (
        hits_at_5 / len(questions) >= 0.95
    ), f"BM25 recall@5 fell to {hits_at_5 / len(questions):.3f}"
