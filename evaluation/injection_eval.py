"""Prompt-injection screens compared on one labelled set (real run).

    python -m evaluation.injection_eval            # regex screen
    python -m evaluation.injection_eval --llm-guard   # also llm-guard's PromptInjection scanner

Set: data/evaluation/injection_set_v2.json, built by scripts/generate_injection_set.py. Attacks
are synthetic (templates, fixed seed); benign texts are mostly real manual sentences plus tricky and
German maintenance sentences. Reports detection per attack kind and the false-positive rate, each
with a 95% Wilson interval, because a few hundred samples leave real uncertainty.
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from app.guardrails import scan_text

DATA = Path("data/evaluation")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(centre - half, 3), round(centre + half, 3)


def load_sets():
    data = json.loads((DATA / "injection_set_v2.json").read_text())
    return data["attacks"], data["benign"]


def evaluate(name, flag, attacks, benign):
    by_kind = defaultdict(lambda: [0, 0])
    for a in attacks:
        by_kind[a["kind"]][0] += bool(flag(a["text"]))
        by_kind[a["kind"]][1] += 1
    detected = sum(v[0] for v in by_kind.values())
    false_pos = [b for b in benign if flag(b["text"])]
    fp_by_kind = defaultdict(int)
    for b in false_pos:
        fp_by_kind[b["kind"]] += 1
    return {
        "method": name,
        "detected": detected,
        "attacks": len(attacks),
        "detection_rate": round(detected / len(attacks), 3),
        "detection_ci95": wilson(detected, len(attacks)),
        "by_kind": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_kind.items())},
        "false_positives": len(false_pos),
        "benign": len(benign),
        "false_positive_rate": round(len(false_pos) / len(benign), 3),
        "false_positive_ci95": wilson(len(false_pos), len(benign)),
        "false_positives_by_kind": dict(fp_by_kind),
        "false_positive_examples": [b["text"][:80] for b in false_pos[:3]],
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
    for r in results:
        print(
            f"{r['method']:28s} detected {r['detected']}/{r['attacks']} {r['detection_ci95']}"
            f" | false positives {r['false_positives']}/{r['benign']} {r['false_positive_ci95']}"
        )
