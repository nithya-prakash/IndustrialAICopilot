"""Choose the retrieval relevance cut-off on a TUNING split; report it on a HELD-OUT split.

    docker compose run --rm backend python -m evaluation.calibrate_cutoff   (needs Postgres, Qdrant)

Retrieval only, no LLM. For every question in data/evaluation/answer_eval.json it records the best
cross-encoder score the sample manual achieves; a cut-off t passes a question when score >= t.
Good: answerable questions pass and unanswerable ones are blocked. t is chosen on the tuning
questions with a fixed safety margin below the lowest answerable score, then scored once on
held-out.
"""

import asyncio
import json
import statistics
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.rag.retrieval import hybrid_search

DATA = Path("data/evaluation/answer_eval.json")
OUT = Path("data/evaluation/results/cutoff_calibration.json")
MARGIN = 3.0


async def best_scores(items):
    settings = get_settings()
    settings.min_relevance_score = -1e9  # observe raw scores, no gating
    async with AsyncSessionLocal() as db:
        tenant = (
            await db.execute(
                text(
                    "select tenant_id from documents where original_filename = "
                    "'electric_motor_manual.pdf' order by created_at desc limit 1"
                )
            )
        ).scalar()
        assert tenant, "upload electric_motor_manual.pdf to some workspace first"
        out = []
        for item in items:
            chunks = await hybrid_search(db, item["question"], tenant_id=tenant)
            out.append(max((c.score for c in chunks), default=-1e9))
        return out


def balanced_accuracy(rows, t):
    ans = [r for r in rows if r["answerable"]]
    un = [r for r in rows if not r["answerable"]]
    tpr = sum(r["best_score"] >= t for r in ans) / max(1, len(ans))
    tnr = sum(r["best_score"] < t for r in un) / max(1, len(un))
    return (tpr + tnr) / 2, tpr, tnr


def main():
    items = json.loads(DATA.read_text())["items"]
    scores = asyncio.run(best_scores(items))
    rows = [
        {
            "question": i["question"],
            "answerable": i["answerable"],
            "split": i["split"],
            "best_score": round(s, 3),
        }
        for i, s in zip(items, scores, strict=True)
    ]
    tuning = [r for r in rows if r["split"] == "tuning"]
    held = [r for r in rows if r["split"] == "heldout"]
    candidates = sorted({r["best_score"] for r in tuning})
    candidates = [(a + b) / 2 for a, b in zip(candidates, candidates[1:], strict=False)] + [
        candidates[0] - 1
    ]
    # Blocking relevant evidence is the worse error (the agent then answers without the manual), and
    # 11 tuning examples cannot show how low realistic answerable scores go. So the cut-off sits a
    # fixed MARGIN below the lowest tuning answerable score (about two standard deviations of the
    # answerable scores). The margin was fixed before looking at the held-out questions.
    lowest_answerable = min(r["best_score"] for r in tuning if r["answerable"])
    best = lowest_answerable - MARGIN
    result = {
        "chosen_cutoff": round(best, 2),
        "tuning": dict(
            zip(
                ("balanced_accuracy", "answerable_pass", "unanswerable_blocked"),
                map(lambda x: round(x, 3), balanced_accuracy(tuning, best)),
                strict=True,
            )
        ),
        "heldout": dict(
            zip(
                ("balanced_accuracy", "answerable_pass", "unanswerable_blocked"),
                map(lambda x: round(x, 3), balanced_accuracy(held, best)),
                strict=True,
            )
        ),
        "n_tuning": len(tuning),
        "n_heldout": len(held),
        "previous_cutoff_minus_4_0": {
            "tuning": round(balanced_accuracy(tuning, -4.0)[0], 3),
            "heldout": round(balanced_accuracy(held, -4.0)[0], 3),
        },
        "median_best_score": {
            "answerable": round(
                statistics.median(r["best_score"] for r in rows if r["answerable"]), 2
            ),
            "unanswerable": round(
                statistics.median(r["best_score"] for r in rows if not r["answerable"]), 2
            ),
        },
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
