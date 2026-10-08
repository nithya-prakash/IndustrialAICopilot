"""Quantization benchmark on Ollama: same model, different precision.

    python -m evaluation.quantization_benchmark qwen2.5:3b-instruct-q4_K_M qwen2.5:3b-instruct-q8_0

For each model it asks the 24 questions of data/evaluation/answer_eval.json with the top-3 BM25
passages (over the sample and synthetic manuals) as context, temperature 0, and reports:
  speed   - generation tokens/s and prompt tokens/s from Ollama's own counters, mean latency per
            answer, resident model size (`ollama ps`)
  quality - required-fact coverage on answerable questions; abstention rate on unanswerable ones
            (the answer says the manual does not cover it); share of answers containing a number
            that is not in the supplied context (invented specifics)
Deterministic scoring, no judge model; 24 questions is small, so quality differences of a few
points are noise. Needs Ollama running locally and the app's Python dependencies.
"""

import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from app.config import get_settings
from app.ingestion.chunker import chunk_blocks
from app.ingestion.pdf_extractor import extract_pdf
from app.rag.bm25 import bm25_search

OLLAMA = "http://localhost:11434"
DATA = Path("data/evaluation")
SYSTEM = (
    "Answer the maintenance question using ONLY the context. Be concise (at most three sentences). "
    "If the context does not contain the answer, reply exactly: The manual does not cover this."
)
NUMBER = re.compile(r"\d+\.\d+|\d{2,}")
ABSTAIN = re.compile(
    r"does not cover|not (?:covered|mentioned|specified|provided|contain)|no information", re.I
)


def build_corpus() -> list[tuple[str, str]]:
    from scripts import generate_eval_manuals, generate_sample_manual

    folder = Path(tempfile.mkdtemp())
    generate_sample_manual.OUTPUT_PATH = folder / "electric_motor_manual.pdf"
    generate_sample_manual.build_pdf()
    generate_eval_manuals.PDF_DIR = folder
    for name, (title, sections) in generate_eval_manuals.MANUALS.items():
        generate_eval_manuals.build_pdf(name, title, sections)
    settings, corpus = get_settings(), []
    for pdf in sorted(folder.glob("*.pdf")):
        for c in chunk_blocks(
            extract_pdf(pdf).blocks, settings.chunk_target_chars, settings.chunk_overlap_chars
        ):
            corpus.append((f"{pdf.name}", c.content))
    return corpus


def generate(model: str, prompt: str) -> dict:
    body = json.dumps(
        {
            "model": model,
            "system": SYSTEM,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 160},
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=body, headers={"content-type": "application/json"}
    )
    return json.load(urllib.request.urlopen(req, timeout=600))


def resident_size(model: str) -> str:
    out = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.splitlines()
    for line in out[1:]:
        if line.startswith(model):
            return " ".join(line.split()[2:4])
    return "unknown"


def run(model: str, items: list[dict], corpus: list[tuple[str, str]]) -> dict:
    generate(model, "Say OK.")  # load the model, excluded from timings
    gen_tokens = gen_ns = prompt_tokens = prompt_ns = 0
    latencies, facts_found, facts_total, abstained, unanswerable, invented = [], 0, 0, 0, 0, 0
    for item in items:
        hits = bm25_search(item["question"], corpus, top_k=3)
        by_id = dict(corpus)
        context = "\n\n".join(by_id[h.chunk_id] for h in hits)
        t0 = time.perf_counter()
        r = generate(model, f"Context:\n{context}\n\nQuestion: {item['question']}")
        latencies.append(time.perf_counter() - t0)
        gen_tokens += r.get("eval_count", 0)
        gen_ns += r.get("eval_duration", 0)
        prompt_tokens += r.get("prompt_eval_count", 0)
        prompt_ns += r.get("prompt_eval_duration", 0)
        answer = r["response"].lower()
        if item["answerable"]:
            for alternatives in item["required_facts"]:
                facts_total += 1
                facts_found += any(a in answer for a in alternatives)
        else:
            unanswerable += 1
            abstained += bool(ABSTAIN.search(answer))
        known = (context + " " + item["question"]).lower()
        invented += any(n not in known for n in NUMBER.findall(answer))
    return {
        "model": model,
        "resident_size": resident_size(model),
        "generation_tokens_per_s": round(gen_tokens / (gen_ns / 1e9), 1),
        "prompt_tokens_per_s": round(prompt_tokens / (prompt_ns / 1e9), 1),
        "mean_latency_s": round(sum(latencies) / len(latencies), 2),
        "fact_coverage": round(facts_found / facts_total, 3),
        "abstention_on_unanswerable": f"{abstained}/{unanswerable}",
        "answers_with_invented_numbers": f"{invented}/{len(items)}",
    }


def main() -> None:
    models = sys.argv[1:]
    items = json.loads((DATA / "answer_eval.json").read_text())["items"]
    corpus = [(f"{i}:{name}", content) for i, (name, content) in enumerate(build_corpus())]
    results = []
    for model in models:
        results.append(run(model, items, corpus))
        subprocess.run(["ollama", "stop", model], capture_output=True)
        print(json.dumps(results[-1]), flush=True)
    (DATA / "results" / "quantization_benchmark.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
