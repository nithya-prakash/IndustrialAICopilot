"""Does the system still decline unanswerable questions, and how does the relevance floor change
that?

    docker compose run --rm -e OLLAMA_URL=http://host.docker.internal:11434 backend \\
        python -m evaluation.abstention_eval qwen2.5:7b -4.0 -10.0

For each floor value, the 24 questions of data/evaluation/answer_eval.json (16 answerable, 8 not)
go through
the production retrieval pipeline (dense + BM25 + RRF + cross-encoder rerank + floor) over the
whole evaluation
workspace, which also holds six real documents the questions were not written for. The top 3
passages go to
a local Ollama model at temperature 0 with an instruction to answer only from them. Reported per
floor:
  answerable   - passages returned, required-fact coverage
  unanswerable - declined by retrieval (nothing passed the floor) or by the model ("does not cover
  this")
                 versus answered anyway
  invented     - answers containing a number that is not in the supplied passages or the question
Deterministic scoring, no judge model. 24 questions is small: one question is about 4 points.
"""

import asyncio
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from app.config import get_settings
from app.rag.retrieval import hybrid_search
from evaluation.retrieval_ablation import EVAL_TENANT, AsyncSessionLocal

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DATA = Path("data/evaluation")
SYSTEM = (
    "Answer the maintenance question using ONLY the context. Be concise (at most three sentences). "
    "If the context does not contain the answer, reply exactly: The manual does not cover this."
)
NUMBER = re.compile(r"\d+\.\d+|\d{2,}")
ABSTAIN = re.compile(
    r"does not cover|not (?:covered|mentioned|specified|provided|contain)|no information", re.I
)


def generate(model: str, prompt: str) -> str:
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
    return json.load(urllib.request.urlopen(req, timeout=900))["response"]


async def run_floor(model: str, floor: float, items: list[dict]) -> dict:
    get_settings().min_relevance_score = floor
    stats = {
        "answerable_with_passages": 0,
        "facts_found": 0,
        "facts_total": 0,
        "unanswerable_declined_by_retrieval": 0,
        "unanswerable_declined_by_model": 0,
        "unanswerable_answered_anyway": 0,
        "invented_numbers": 0,
    }
    n_answerable = sum(i["answerable"] for i in items)
    async with AsyncSessionLocal() as db:
        for item in items:
            chunks = await hybrid_search(db, item["question"], tenant_id=EVAL_TENANT, top_k=3)
            if not chunks:
                answer, context = "", ""
            else:
                context = "\n\n".join(c.content for c in chunks)
                prompt = f"Context:\n{context}\n\nQuestion: {item['question']}"
                answer = generate(model, prompt).lower()
            if item["answerable"]:
                stats["answerable_with_passages"] += bool(chunks)
                for alternatives in item["required_facts"]:
                    stats["facts_total"] += 1
                    stats["facts_found"] += any(a in answer for a in alternatives)
            elif not chunks:
                stats["unanswerable_declined_by_retrieval"] += 1
            elif ABSTAIN.search(answer):
                stats["unanswerable_declined_by_model"] += 1
            else:
                stats["unanswerable_answered_anyway"] += 1
            known = (context + " " + item["question"]).lower()
            stats["invented_numbers"] += any(n not in known for n in NUMBER.findall(answer))
    return {
        "floor": floor,
        "answerable": f"{stats['answerable_with_passages']}/{n_answerable} got passages, "
        f"fact coverage {stats['facts_found'] / max(stats['facts_total'], 1):.3f}",
        "unanswerable": {
            "declined_by_retrieval": stats["unanswerable_declined_by_retrieval"],
            "declined_by_model": stats["unanswerable_declined_by_model"],
            "answered_anyway": stats["unanswerable_answered_anyway"],
        },
        "answers_with_invented_numbers": f"{stats['invented_numbers']}/{len(items)}",
    }


async def run_all(model: str, floors: list[float], items: list[dict]) -> list[dict]:
    results = []
    for floor in floors:
        results.append({"model": model, **await run_floor(model, floor, items)})
        print(json.dumps(results[-1]), flush=True)
    return results


def main() -> None:
    model, floors = sys.argv[1], [float(f) for f in sys.argv[2:]]
    items = json.loads((DATA / "answer_eval.json").read_text())["items"]
    generate(model, "Say OK.")  # load the model
    results = asyncio.run(run_all(model, floors, items))
    out = DATA / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "abstention_eval.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
