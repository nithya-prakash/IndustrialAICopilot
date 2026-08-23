"""Retrieval evaluation harness.

    python -m evaluation.run

Runs the ground-truth question set (data/evaluation/rag_questions.json)
through the real hybrid retrieval pipeline against a live Postgres+Qdrant,
computing Recall@K / Precision@K / MRR / nDCG@K from actual retrieval
results — nothing here is a hard-coded or assumed metric. Requires the app
stack's DB/Qdrant to be reachable (run inside the backend container via
`docker compose run --rm backend python -m evaluation.run`, or `make eval`).

Self-contained: if the synthetic sample manual isn't indexed yet under the
"evaluation" tenant, this generates and indexes it first, so a fresh clone
can run this with just `docker compose up` beforehand — no manual upload
step required.
"""
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import hash_password  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.evaluation.metrics import (  # noqa: E402
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from app.models.document import Document, DocumentStatus  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.rag.retrieval import RetrievedChunk, hybrid_search  # noqa: E402
from app.services.document_service import create_document_version  # noqa: E402
from app.services.ingestion_service import process_document_version  # noqa: E402

EVAL_TENANT = "evaluation"
EVAL_USERNAME = "eval-runner"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
QUESTIONS_PATH = _DATA_DIR / "evaluation" / "rag_questions.json"
MANUAL_PATH = _DATA_DIR / "manuals" / "electric_motor_manual.pdf"
RESULTS_DIR = _DATA_DIR / "evaluation" / "results"
K_VALUES = (1, 3, 5)


def _source_key(chunk: RetrievedChunk) -> str:
    heading = chunk.section or ""
    if chunk.subsection:
        heading = f"{heading} > {chunk.subsection}"
    return f"{chunk.filename}:{heading}"


async def _ensure_eval_user(db) -> User:
    result = await db.execute(select(User).where(User.username == EVAL_USERNAME))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        username=EVAL_USERNAME,
        email="eval-runner@example.com",
        hashed_password=hash_password(str(uuid.uuid4())),
        role=UserRole.admin,
        tenant_id=EVAL_TENANT,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _ensure_sample_manual_indexed(db, owner: User) -> None:
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.versions))
        .where(
            Document.tenant_id == EVAL_TENANT,
            Document.original_filename == "electric_motor_manual.pdf",
        )
    )
    document = result.scalar_one_or_none()
    if document is not None:
        current = next((v for v in document.versions if v.is_current), None)
        if current is not None and current.status == DocumentStatus.ready:
            return

    if not MANUAL_PATH.exists():
        from scripts.generate_sample_manual import build_pdf

        build_pdf()

    print("Indexing sample manual for evaluation (first run only)...")
    _, version = await create_document_version(
        db,
        owner_id=owner.id,
        tenant_id=EVAL_TENANT,
        filename="electric_motor_manual.pdf",
        content_type="application/pdf",
        content=MANUAL_PATH.read_bytes(),
        equipment_type="electric_motor",
        equipment_id="MOTOR-001",
        document_id=document.id if document is not None else None,
        dispatch_processing=False,
    )
    await process_document_version(version.id)


async def run() -> dict:
    questions = json.loads(QUESTIONS_PATH.read_text())

    async with AsyncSessionLocal() as db:
        user = await _ensure_eval_user(db)
        await _ensure_sample_manual_indexed(db, user)

    per_question_results = []
    all_retrieved: list[list[str]] = []
    all_relevant: list[set[str]] = []

    async with AsyncSessionLocal() as db:
        for item in questions:
            chunks = await hybrid_search(
                db, item["question"], tenant_id=EVAL_TENANT, top_k=10
            )
            retrieved_keys = [_source_key(c) for c in chunks]
            relevant = set(item["expected_sources"])

            all_retrieved.append(retrieved_keys)
            all_relevant.append(relevant)

            per_question_results.append(
                {
                    "question": item["question"],
                    "expected_sources": sorted(relevant),
                    "retrieved_sources": retrieved_keys,
                    "recall_at_3": round(recall_at_k(retrieved_keys, relevant, 3), 3),
                    "precision_at_3": round(precision_at_k(retrieved_keys, relevant, 3), 3),
                    "ndcg_at_5": round(ndcg_at_k(retrieved_keys, relevant, 5), 3),
                }
            )

    pairs = list(zip(all_retrieved, all_relevant, strict=True))

    def _mean(metric_fn, k: int) -> float:
        return round(sum(metric_fn(r, rel, k) for r, rel in pairs) / len(pairs), 3)

    summary = {
        "mrr": round(mean_reciprocal_rank(all_retrieved, all_relevant), 3),
        **{f"recall_at_{k}": _mean(recall_at_k, k) for k in K_VALUES},
        **{f"precision_at_{k}": _mean(precision_at_k, k) for k in K_VALUES},
        "ndcg_at_5": _mean(ndcg_at_k, 5),
        "num_questions": len(questions),
    }

    return {"summary": summary, "per_question": per_question_results}


def main() -> None:
    report = asyncio.run(run())

    print("\n=== RAG Retrieval Evaluation ===")
    print(f"Questions evaluated: {report['summary']['num_questions']}")
    for key, value in report["summary"].items():
        if key == "num_questions":
            continue
        print(f"  {key:>16}: {value}")

    print("\nPer-question:")
    for row in report["per_question"]:
        print(f"  - {row['question']}")
        print(
            f"      recall@3={row['recall_at_3']} precision@3={row['precision_at_3']} "
            f"ndcg@5={row['ndcg_at_5']}"
        )
        if row["recall_at_3"] < 1.0:
            print(f"      expected: {row['expected_sources']}")
            print(f"      got:      {row['retrieved_sources']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"rag_eval_{timestamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
