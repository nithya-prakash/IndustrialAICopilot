"""End-to-end answer quality of the diagnosis agent, scored deterministically (no LLM judge).

    API_URL=http://localhost:8000 python -m evaluation.answer_eval [--supervised]

Registers a throwaway workspace, uploads the sample manual, then asks every question in
data/evaluation/answer_eval.json through the real API. Reports, over answerable questions:
  - fact coverage: share of required reference facts present in the answer text;
  - citation precision / recall: do the kept citations point at the expected manual section;
over unanswerable questions (the manual has no answer):
  - overconfident rate: confidence >= 0.6 anyway;
over all questions:
  - unsupported-number rate: answers containing a number (2+ digits or a decimal) that appears in
    neither the question nor any retrieved evidence, a cheap proxy for invented specifics.
Small, self-written set: it shows whether the pipeline behaves, not general accuracy.
"""

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = __import__("os").environ.get("API_URL", "http://localhost:8000").rstrip("/") + "/api/v1"
DATA = Path("data/evaluation")
NUMBER = re.compile(r"\d+\.\d+|\d{2,}")


def call(path, data=None, token=None, retries=4):
    for attempt in range(retries):
        req = urllib.request.Request(
            API + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={
                "content-type": "application/json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        try:
            return json.load(urllib.request.urlopen(req, timeout=300))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(20)
                continue
            raise


def answer_text(d: dict) -> str:
    parts = [d.get("summary") or "", d.get("recommended_action") or ""]
    parts += [c["cause"] for c in d.get("possible_causes", [])] + d.get("recommended_checks", [])
    return " ".join(parts).lower()


def score(item: dict, d: dict) -> dict:
    text = answer_text(d)
    evidence = (
        json.dumps(d.get("evidence", [])).lower() + " " + item["question"].lower() + " motor-001"
    )
    unsupported = [n for n in NUMBER.findall(text) if n not in evidence]
    row = {
        "question": item["question"],
        "answerable": item["answerable"],
        "status": d["status"],
        "confidence": d["confidence"],
        "unsupported_numbers": unsupported,
    }
    if item["answerable"]:
        facts = item["required_facts"]
        row["facts_found"] = sum(any(a in text for a in alts) for alts in facts)
        row["facts_total"] = len(facts)
        cited = [c for cause in d.get("possible_causes", []) for c in cause["supporting_citations"]]
        hits = [c for c in cited if item["expected_source"].lower() in c.lower()]
        row["citations"] = len(cited)
        row["citations_correct"] = len(hits)
        row["expected_source_cited"] = bool(hits)
    else:
        row["overconfident"] = d["confidence"] >= 0.6
    return row


def main() -> None:
    supervised = "--supervised" in sys.argv
    endpoint = "/copilot/query/supervised" if supervised else "/copilot/query"
    items = json.loads((DATA / "answer_eval.json").read_text())["items"]
    pw, tenant = "Tmp-" + uuid.uuid4().hex[:10] + "!Aa1", "ev" + uuid.uuid4().hex[:6]
    token = call(
        "/auth/register",
        {
            "username": "u_" + tenant,
            "email": f"{tenant}@example.com",
            "password": pw,
            "tenant_id": tenant,
        },
    )["access_token"]
    subprocess.run(
        [
            "curl",
            "-s",
            "-o",
            "/dev/null",
            "-X",
            "POST",
            API + "/documents/upload",
            "-H",
            f"Authorization: Bearer {token}",
            "-F",
            "file=@data/manuals/electric_motor_manual.pdf",
        ],
        check=True,
    )
    time.sleep(30)
    rows = []
    for item in items:
        for _ in range(3):  # provider rate limits are infrastructure noise: wait and ask again
            d = call(endpoint, {"question": item["question"], "equipment_id": "MOTOR-001"}, token)
            if d["status"] == "completed" or "429" not in (d.get("error_message") or ""):
                break
            time.sleep(65)
        rows.append(score(item, d))
        print(
            f"{'A' if item['answerable'] else 'U'} {d['status']:9s} "
            f"conf={d['confidence']:.2f} {item['question'][:60]}",
            flush=True,
        )
        time.sleep(6)
    ok = [r for r in rows if r["status"] == "completed"]
    ans = [r for r in ok if r["answerable"]]
    un = [r for r in ok if not r["answerable"]]
    cited = sum(r["citations"] for r in ans)
    summary = {
        "endpoint": endpoint,
        "questions": len(rows),
        "completed": len(ok),
        "answerable_completed": len(ans),
        "fact_coverage": round(
            sum(r["facts_found"] for r in ans) / max(1, sum(r["facts_total"] for r in ans)), 3
        ),
        "citation_precision": round(sum(r["citations_correct"] for r in ans) / max(1, cited), 3),
        "expected_source_cited_rate": round(
            sum(r["expected_source_cited"] for r in ans) / max(1, len(ans)), 3
        ),
        "unanswerable_completed": len(un),
        "overconfident_rate_unanswerable": round(
            sum(r["overconfident"] for r in un) / max(1, len(un)), 3
        ),
        "unsupported_number_rate": round(
            sum(bool(r["unsupported_numbers"]) for r in ok) / max(1, len(ok)), 3
        ),
    }
    out = DATA / "results" / f"answer_eval_{'supervised' if supervised else 'tool_loop'}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
