"""Diagnosis-agent evaluation harness.

    python -m evaluation.diagnosis_eval

Runs the labeled scenario set (data/evaluation/diagnosis_scenarios.json)
through the REAL diagnosis agent loop (app/agents/diagnosis_agent.run_diagnosis,
with its default real model_call — not a scripted fake) against a live
Postgres+Qdrant, using the same self-seeded "evaluation" tenant as the
retrieval harness (evaluation/run.py): the sample manual, seeded sensor
history, and seeded equipment/maintenance data.

Requires ANTHROPIC_API_KEY (or LLM_API_KEY): this is the one evaluation
harness in this project that can't run against local-only infrastructure,
because it's evaluating the agent's actual tool-selection and reasoning
behavior, not a component that has a local stand-in. If no key is
configured, this exits cleanly with a message rather than fabricating a
report — the same honesty rule this project applies everywhere else (see
docs/architecture-decisions.md, Phase 10).

What's measured, and why it stops where it does: tool_recall and
evidence_type_coverage are checked against a human-labeled expectation per
scenario (data/evaluation/diagnosis_scenarios.json) — did the agent gather
the evidence a competent diagnostician would for this question.
citation_validity_rate and meets_severity_floor read off invariants the
agent already enforces deterministically (Phase 6's citation validation and
severity-escalation floor). This harness does NOT attempt automated
hallucination detection or an LLM-as-judge quality score on the diagnosis
text itself — grading free-text diagnosis quality with another LLM call
would itself be an unverified metric in an environment with no API key to
verify it against, and keyword-matching the summary for "did it make
something up" would be exactly the kind of fragile, easily-gamed heuristic
this project avoids elsewhere. See app/evaluation/diagnosis_scoring.py for
the scoring functions themselves.
"""
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.diagnosis_agent import run_diagnosis  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.evaluation.diagnosis_scoring import (  # noqa: E402
    citation_validity_rate,
    evidence_type_coverage,
    meets_severity_floor,
    tool_recall,
)
from app.models.diagnosis import DiagnosisStatus  # noqa: E402
from evaluation.run import (  # noqa: E402
    EVAL_TENANT,
    _ensure_eval_user,
    _ensure_sample_manual_indexed,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_PATH = _PROJECT_ROOT / "data" / "evaluation" / "diagnosis_scenarios.json"
RESULTS_DIR = _PROJECT_ROOT / "data" / "evaluation" / "results"


async def _ensure_supporting_data_seeded() -> None:
    """Self-contained like evaluation/run.py: seeds sensor + equipment data
    under EVAL_TENANT (idempotent — both scripts skip what already exists)
    so a fresh clone can run this after just `docker compose up`, no manual
    setup step."""
    from scripts.seed_equipment_data import main as seed_equipment
    from scripts.seed_sensor_data import main as seed_sensor

    await seed_sensor(EVAL_TENANT)
    await seed_equipment(EVAL_TENANT)


async def run() -> dict:
    scenarios = json.loads(SCENARIOS_PATH.read_text())

    async with AsyncSessionLocal() as db:
        user = await _ensure_eval_user(db)
        await _ensure_sample_manual_indexed(db, user)
    await _ensure_supporting_data_seeded()

    per_scenario = []
    for scenario in scenarios:
        async with AsyncSessionLocal() as db:
            diagnosis = await run_diagnosis(
                db,
                tenant_id=EVAL_TENANT,
                user_id=user.id,
                conversation_id=None,
                question=scenario["question"],
                equipment_id=scenario.get("equipment_id"),
                equipment_type=scenario.get("equipment_type"),
            )

        tools_called = {call["tool"] for call in (diagnosis.tool_calls or [])}
        observed_evidence_types = {item["type"] for item in (diagnosis.evidence or [])}
        required = set(scenario["required_tools"])

        result = {
            "id": scenario["id"],
            "question": scenario["question"],
            "status": diagnosis.status.value,
            "tools_called": sorted(tools_called),
            "required_tools": sorted(required),
            "tool_recall": round(tool_recall(tools_called, required), 3),
            "evidence_type_coverage": round(
                evidence_type_coverage(
                    observed_evidence_types, set(scenario["expected_evidence_types"])
                ),
                3,
            ),
            "confidence": round(diagnosis.confidence, 3),
            "severity": diagnosis.severity.value,
            "meets_severity_floor": meets_severity_floor(
                diagnosis.severity.value, scenario.get("min_severity")
            ),
        }
        if diagnosis.status == DiagnosisStatus.completed:
            result["citation_validity_rate"] = round(
                citation_validity_rate(diagnosis.possible_causes or []), 3
            )
        else:
            result["error_message"] = diagnosis.error_message

        per_scenario.append(result)

    completed = [r for r in per_scenario if r["status"] == "completed"]

    def _mean(key: str) -> float | None:
        values = [r[key] for r in completed if r.get(key) is not None]
        return round(sum(values) / len(values), 3) if values else None

    floor_checks = [
        r["meets_severity_floor"] for r in per_scenario if r["meets_severity_floor"] is not None
    ]
    floor_summary = f"{sum(floor_checks)}/{len(floor_checks)}" if floor_checks else "n/a"

    summary = {
        "num_scenarios": len(scenarios),
        "num_completed": len(completed),
        "num_failed": len(scenarios) - len(completed),
        "mean_tool_recall": _mean("tool_recall"),
        "mean_evidence_type_coverage": _mean("evidence_type_coverage"),
        "mean_citation_validity_rate": _mean("citation_validity_rate"),
        "mean_confidence": _mean("confidence"),
        "severity_floor_checks_passed": floor_summary,
    }

    return {"summary": summary, "per_scenario": per_scenario}


def main() -> None:
    settings = get_settings()
    if not settings.resolved_llm_api_key:
        print("NOT RUN — LIVE MODEL CREDENTIALS NOT CONFIGURED")
        print(
            "This harness exercises the real diagnosis agent loop, which needs a real "
            "model call — there's no local stand-in for it, unlike retrieval evaluation "
            "(`make eval`). Set ANTHROPIC_API_KEY (or LLM_API_KEY) in .env and re-run to "
            "get a real report."
        )
        return

    report = asyncio.run(run())

    print("\n=== Diagnosis Agent Evaluation ===")
    for key, value in report["summary"].items():
        print(f"  {key:>28}: {value}")

    print("\nPer-scenario:")
    for row in report["per_scenario"]:
        print(f"  - {row['id']} ({row['status']})")
        print(
            f"      tool_recall={row['tool_recall']} "
            f"evidence_coverage={row['evidence_type_coverage']} "
            f"confidence={row['confidence']} severity={row['severity']}"
        )
        if row["tool_recall"] < 1.0:
            print(f"      required: {row['required_tools']}  called: {row['tools_called']}")
        if row["meets_severity_floor"] is False:
            print("      WARNING: did not meet the scenario's expected severity floor")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"diagnosis_eval_{timestamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
