"""Retrieval component ablation.

    python -m evaluation.retrieval_ablation

Answers "does each retrieval component actually contribute?" by running
the SAME ground-truth question set (data/evaluation/rag_questions.json)
through four configurations, each built from the real, unmodified
production pieces (app.rag.bm25, app.rag.qdrant_store, app.rag.fusion,
app.rag.reranker) — nothing here is a separate/duplicate retrieval
implementation, just those same pieces composed with different components
enabled/disabled:

    1. bm25_only       — lexical retrieval alone, no dense leg, no rerank
    2. dense_only       — dense (Qdrant) retrieval alone, no BM25, no rerank
    3. hybrid_rrf       — dense + BM25 fused via RRF, no rerank
    4. hybrid_reranked  — dense + BM25 + RRF + cross-encoder rerank
                          (this is exactly app.rag.retrieval.hybrid_search's
                          production configuration — included here as a
                          consistency check against evaluation/run.py's own
                          measured result, not a separate implementation)

Requires a live Postgres+Qdrant with the sample manual indexed under the
"evaluation" tenant — reuses evaluation/run.py's own self-seeding.
"""
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.evaluation.metrics import (  # noqa: E402
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from app.rag.bm25 import bm25_search  # noqa: E402
from app.rag.embeddings import embed_texts  # noqa: E402
from app.rag.fusion import reciprocal_rank_fusion  # noqa: E402
from app.rag.qdrant_store import search as qdrant_dense_search  # noqa: E402
from app.rag.reranker import rerank  # noqa: E402
from app.rag.retrieval import _fetch_candidates  # noqa: E402
from evaluation.run import (  # noqa: E402
    EVAL_TENANT,
    QUESTIONS_PATH,
    RESULTS_DIR,
    _ensure_eval_user,
    _ensure_sample_manual_indexed,
)

K_VALUES = (1, 3, 5)
TOP_K = 10

CONFIGS = {
    "bm25_only": {"use_dense": False, "use_bm25": True, "use_rerank": False},
    "dense_only": {"use_dense": True, "use_bm25": False, "use_rerank": False},
    "hybrid_rrf": {"use_dense": True, "use_bm25": True, "use_rerank": False},
    "hybrid_reranked": {"use_dense": True, "use_bm25": True, "use_rerank": True},
}


async def _retrieve(
    db, query: str, *, tenant_id: str, use_dense: bool, use_bm25: bool, use_rerank: bool
) -> list[str]:
    """Returns retrieved chunk source-keys, best-first — same composition
    app.rag.retrieval.hybrid_search uses, with each stage toggleable."""
    settings = get_settings()
    rows = await _fetch_candidates(
        db, tenant_id=tenant_id, equipment_type=None, equipment_id=None, document_id=None
    )
    rows_by_id = {str(row.id): row for row in rows}
    if not rows_by_id or not query.strip():
        return []

    # Same translation app.rag.retrieval.hybrid_search now does — Qdrant
    # point IDs are never the same value as DocumentChunk.id.
    chunk_id_by_point_id = {
        row.qdrant_point_id: str(row.id) for row in rows if row.qdrant_point_id
    }

    dense_ranked: list[str] = []
    if use_dense:
        query_vector = embed_texts([query])[0]
        dense_results = qdrant_dense_search(
            query_vector, top_k=settings.dense_top_k, tenant_id=tenant_id
        )
        dense_ranked = [
            chunk_id_by_point_id[point_id]
            for point_id, _score, _payload in dense_results
            if point_id in chunk_id_by_point_id
        ]

    bm25_ranked: list[str] = []
    if use_bm25:
        corpus = [(str(row.id), row.content) for row in rows]
        bm25_ranked = [sc.chunk_id for sc in bm25_search(query, corpus, top_k=settings.bm25_top_k)]

    if use_dense and use_bm25:
        fused = reciprocal_rank_fusion([dense_ranked, bm25_ranked], k=settings.rrf_k)
        candidate_ids = [cid for cid, _score in fused if cid in rows_by_id]
    elif use_dense:
        candidate_ids = [cid for cid in dense_ranked if cid in rows_by_id]
    else:
        candidate_ids = [cid for cid in bm25_ranked if cid in rows_by_id]

    if use_rerank:
        rerank_candidates = [(cid, rows_by_id[cid].content) for cid in candidate_ids]
        reranked = rerank(query, rerank_candidates)
        ordered_ids = [
            cid for cid, score in reranked if score >= settings.min_relevance_score
        ][:TOP_K]
    else:
        ordered_ids = candidate_ids[:TOP_K]

    return [_source_key_from_row(rows_by_id[cid]) for cid in ordered_ids]


def _source_key_from_row(row) -> str:
    heading = row.section or ""
    if row.subsection:
        heading = f"{heading} > {row.subsection}"
    return f"{row.original_filename}:{heading}"


async def run() -> dict:
    questions = json.loads(QUESTIONS_PATH.read_text())

    async with AsyncSessionLocal() as db:
        user = await _ensure_eval_user(db)
        await _ensure_sample_manual_indexed(db, user)

    results: dict[str, dict] = {}
    for config_name, flags in CONFIGS.items():
        all_retrieved: list[list[str]] = []
        all_relevant: list[set[str]] = []
        async with AsyncSessionLocal() as db:
            for item in questions:
                retrieved = await _retrieve(db, item["question"], tenant_id=EVAL_TENANT, **flags)
                all_retrieved.append(retrieved)
                all_relevant.append(set(item["expected_sources"]))

        pairs = list(zip(all_retrieved, all_relevant, strict=True))

        def _mean(metric_fn, k: int, pairs=pairs) -> float:
            return round(sum(metric_fn(r, rel, k) for r, rel in pairs) / len(pairs), 3)

        results[config_name] = {
            "config": flags,
            "mrr": round(mean_reciprocal_rank(all_retrieved, all_relevant), 3),
            **{f"recall_at_{k}": _mean(recall_at_k, k) for k in K_VALUES},
            **{f"precision_at_{k}": _mean(precision_at_k, k) for k in K_VALUES},
            "ndcg_at_5": _mean(ndcg_at_k, 5),
        }

    return {"num_questions": len(questions), "by_config": results}


def main() -> None:
    report = asyncio.run(run())

    print("\n=== Retrieval Component Ablation ===")
    print(f"Questions: {report['num_questions']}\n")
    header = (
        f"{'config':<18}{'mrr':>8}{'recall@1':>10}{'recall@3':>10}"
        f"{'recall@5':>10}{'ndcg@5':>10}"
    )
    print(header)
    for name, m in report["by_config"].items():
        print(
            f"{name:<18}{m['mrr']:>8}{m['recall_at_1']:>10}{m['recall_at_3']:>10}"
            f"{m['recall_at_5']:>10}{m['ndcg_at_5']:>10}"
        )

    consistency = report["by_config"]["hybrid_reranked"]["mrr"]
    print(
        f"\nConsistency check: hybrid_reranked MRR = {consistency} "
        "(should match evaluation/run.py's own measured MRR — same production config)"
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"retrieval_ablation_{timestamp}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
