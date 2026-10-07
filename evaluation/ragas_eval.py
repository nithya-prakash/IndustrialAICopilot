"""RAGAS evaluation of the RAG answers, with an optional Langfuse score export.

Two stages so each runs in the environment it needs:

    python -m evaluation.ragas_eval collect   # app venv + Postgres/Qdrant: contexts + answer
    python -m evaluation.ragas_eval score     # eval venv (requirements-eval.txt): RAGAS metrics

The judge is any OpenAI-compatible endpoint (default: local Ollama,
JUDGE_BASE_URL=http://localhost:11434/v1, JUDGE_MODEL=qwen2.5:7b). Metrics are
reference-free (faithfulness, context precision) because the labeled set holds
expected sources, not reference answers. A small local judge is a noisy grader;
treat scores as relative, not absolute. Langfuse export only runs when
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are set.
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

RESULTS_DIR = Path("data/evaluation/results")
RECORDS_PATH = RESULTS_DIR / "ragas_records.json"
QUESTIONS_PATH = Path("data/evaluation/rag_questions.json")

ANSWER_SYSTEM = (
    "Answer the maintenance question using ONLY the provided context. "
    "If the context does not contain the answer, say so."
)


async def collect() -> list[dict]:
    from app.database import AsyncSessionLocal
    from app.rag.generation import call_model
    from app.rag.retrieval import hybrid_search
    from evaluation.run import EVAL_TENANT, _ensure_eval_user, _ensure_sample_manual_indexed

    records = []
    async with AsyncSessionLocal() as db:
        user = await _ensure_eval_user(db)
        await _ensure_sample_manual_indexed(db, user)
        for item in json.loads(QUESTIONS_PATH.read_text()):
            chunks = await hybrid_search(db, item["question"], tenant_id=EVAL_TENANT, top_k=5)
            contexts = [c.content for c in chunks]
            prompt = "Context:\n" + "\n---\n".join(contexts) + f"\n\nQuestion: {item['question']}"
            turn = await call_model(
                [{"role": "user", "content": prompt}], ANSWER_SYSTEM, use_tools=False
            )
            records.append(
                {"question": item["question"], "contexts": contexts, "answer": turn.text.strip()}
            )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RECORDS_PATH.write_text(json.dumps(records, indent=2))
    return records


def score(records: list[dict]) -> dict:
    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference
    from ragas.run_config import RunConfig

    llm = LangchainLLMWrapper(
        ChatOpenAI(
            base_url=os.getenv("JUDGE_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.getenv("JUDGE_API_KEY", "ollama"),
            model=os.getenv("JUDGE_MODEL", "qwen2.5:7b"),
            temperature=0,
        )
    )
    dataset = EvaluationDataset(
        samples=[
            SingleTurnSample(
                user_input=r["question"], retrieved_contexts=r["contexts"], response=r["answer"]
            )
            for r in records
        ]
    )
    result = evaluate(
        dataset,
        metrics=[Faithfulness(llm=llm), LLMContextPrecisionWithoutReference(llm=llm)],
        run_config=RunConfig(timeout=900, max_workers=1),  # a local 7B judge is slow
        raise_exceptions=False,
    )
    df = result.to_pandas()
    metric_cols = [
        c for c in df.columns if c in ("faithfulness", "llm_context_precision_without_reference")
    ]
    summary = {c: round(float(df[c].mean()), 3) for c in metric_cols}  # NaN rows are skipped
    scored = {c: int(df[c].notna().sum()) for c in metric_cols}
    report = {
        "judge": os.getenv("JUDGE_MODEL", "qwen2.5:7b"),
        "summary": summary,
        "scored_samples": scored,
        "num_records": len(records),
        "per_question": json.loads(df.to_json(orient="records")),
    }
    report["langfuse_traces"] = _export_to_langfuse(report, records)
    return report


def _export_to_langfuse(report: dict, records: list[dict]) -> int:
    """One Langfuse trace per question (input, retrieved contexts, answer) with its RAGAS
    scores attached, plus run-level mean scores on a summary trace. Only runs when
    LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY (and LANGFUSE_HOST) are set.
    Returns the number of traces written."""
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return 0
    from langfuse import Langfuse

    client = Langfuse()
    metrics = [m for m in report["summary"]]
    for rec, row in zip(records, report["per_question"], strict=True):
        with client.start_as_current_observation(
            name="rag-answer",
            as_type="span",
            input=rec["question"],
            output=rec["answer"],
            metadata={"contexts": rec["contexts"], "judge": report["judge"]},
        ):
            trace_id = client.get_current_trace_id()
        for m in metrics:
            value = row.get(m)
            if value is not None and value == value:  # skip NaN
                client.create_score(trace_id=trace_id, name=f"ragas_{m}", value=float(value))
    with client.start_as_current_observation(
        name="ragas-run-summary", as_type="span", output=report["summary"]
    ):
        trace_id = client.get_current_trace_id()
    for m, v in report["summary"].items():
        if v == v:
            client.create_score(trace_id=trace_id, name=f"ragas_mean_{m}", value=float(v))
    client.flush()
    return len(records) + 1


def main() -> None:
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "collect":
        records = asyncio.run(collect())
        print(f"Collected {len(records)} records -> {RECORDS_PATH}")
    elif stage == "export-langfuse":  # re-export an existing report without re-scoring
        report = json.loads(Path(sys.argv[2]).read_text())
        n = _export_to_langfuse(report, json.loads(RECORDS_PATH.read_text()))
        print(f"Langfuse: {n} traces written" if n else "Langfuse keys not set; nothing exported")
    elif stage == "score":
        if not RECORDS_PATH.exists():
            sys.exit(f"{RECORDS_PATH} missing — run the collect stage first.")
        report = score(json.loads(RECORDS_PATH.read_text()))
        out = RESULTS_DIR / f"ragas_eval_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
        out.write_text(json.dumps(report, indent=2))
        print(json.dumps({k: report[k] for k in ("judge", "summary", "scored_samples")}, indent=2))
        print(f"Report: {out}")
    else:
        sys.exit(
            "usage: python -m evaluation.ragas_eval [collect|score|export-langfuse REPORT.json]"
        )


if __name__ == "__main__":
    main()
