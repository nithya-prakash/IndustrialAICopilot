"""Prompt-injection screens compared on one labelled set (real run).

    python -m evaluation.injection_eval        # regex screen (always available)
    python -m evaluation.injection_eval --llm-guard   # also llm-guard's PromptInjection scanner

Attacks: data/evaluation/injection_attacks.json (hand-written, synthetic).
Benign: the real manual excerpts the retriever returned during the RAGAS run
(data/evaluation/results/ragas_records.json) plus 15 synthetic tricky-benign sentences.
Reports detection rate per attack kind
and the false-positive rate; small sets, so read the numbers as indicative only.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from app.guardrails import scan_text

DATA = Path("data/evaluation")


def load_sets():
    attacks = json.loads((DATA / "injection_attacks.json").read_text())["attacks"]
    records = json.loads((DATA / "results" / "ragas_records.json").read_text())
    real = sorted({c for r in records for c in r["contexts"]})
    synthetic = json.loads((DATA / "injection_attacks.json").read_text())["benign_synthetic"]
    return attacks, real + synthetic


def evaluate(name, flag, attacks, benign):
    by_kind = defaultdict(lambda: [0, 0])
    for a in attacks:
        hit = flag(a["text"])
        by_kind[a["kind"]][0] += hit
        by_kind[a["kind"]][1] += 1
    fp = [b for b in benign if flag(b)]
    return {
        "method": name,
        "detected": sum(v[0] for v in by_kind.values()),
        "attacks": len(attacks),
        "by_kind": {k: f"{v[0]}/{v[1]}" for k, v in by_kind.items()},
        "false_positives": len(fp),
        "benign": len(benign),
        "false_positive_examples": [f[:80] for f in fp[:3]],
    }


def llm_guard_flag():
    from llm_guard.input_scanners import PromptInjection

    scanner = PromptInjection(threshold=0.5)
    return lambda text: not scanner.scan(text)[1]


if __name__ == "__main__":
    attacks, benign = load_sets()
    results = [evaluate("regex (app/guardrails.py)", lambda t: bool(scan_text(t)), attacks, benign)]
    if "--llm-guard" in sys.argv:
        lg = llm_guard_flag()
        results.append(evaluate("llm-guard PromptInjection", lg, attacks, benign))
        results.append(
            evaluate("regex OR llm-guard", lambda t: bool(scan_text(t)) or lg(t), attacks, benign)
        )
    out = DATA / "results" / "injection_eval.json"
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
