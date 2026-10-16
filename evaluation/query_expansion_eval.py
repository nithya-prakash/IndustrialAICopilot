"""Does adding a model-written hypothetical passage to the dense query help retrieval?

    docker compose run --rm -v "$PWD/expansions.json:/expansions.json" backend \
        python -m evaluation.query_expansion_eval QUESTIONS.json [MORE.json ...]

Expansions come from scripts/generate_query_expansions.py (cached by question text). Compared
per question file, each variant with and without the cross-encoder rerank (production floor
applied):
  base                   current retrieval
  e1_dense_expanded      dense query = question + passage; BM25 and rerank use the question
                         (the shipped QUERY_EXPANSION=hyde behaviour)
  e2_dense+bm25_expanded dense and BM25 both use question + passage
  e3_orig+hyde           three lists fused: dense(question), dense(passage), BM25(question)
Reranking always scores against the user's own question.
"""

import asyncio
import json
import sys

import numpy as np

from app.config import get_settings
from app.evaluation.metrics import mean_reciprocal_rank, recall_at_k
from app.rag.bm25 import bm25_search
from app.rag.embeddings import embed_texts
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.qdrant_store import search as qdrant_dense_search
from app.rag.reranker import rerank
from evaluation.retrieval_ablation import (
    EVAL_TENANT,
    AsyncSessionLocal,
    _fetch_candidates,
    _keys_for_item,
)

EXPANSIONS = "/expansions.json"


async def main(paths: list[str]) -> None:
    expansions = json.load(open(EXPANSIONS))
    st = get_settings()
    async with AsyncSessionLocal() as db:
        rows = await _fetch_candidates(
            db, tenant_id=EVAL_TENANT, equipment_type=None, equipment_id=None, document_id=None
        )
    by = {str(r.id): r for r in rows}
    point_to_chunk = {r.qdrant_point_id: str(r.id) for r in rows if r.qdrant_point_id}
    corpus = [(str(r.id), r.content) for r in rows]

    def dense(text: str) -> list[str]:
        hits = qdrant_dense_search(
            embed_texts([text])[0], top_k=st.dense_top_k, tenant_id=EVAL_TENANT
        )
        return [point_to_chunk[p] for p, _, _ in hits if p in point_to_chunk]

    def bm25(text: str) -> list[str]:
        return [c.chunk_id for c in bm25_search(text, corpus, top_k=st.bm25_top_k)]

    def fuse(*lists: list[str]) -> list[str]:
        return [c for c, _ in reciprocal_rank_fusion(list(lists), k=st.rrf_k) if c in by]

    for path in paths:
        questions = json.load(open(path))
        out: dict[str, list] = {}
        for i, q in enumerate(questions):
            query = q["question"]
            passage = expansions[query]
            both = query + "\n" + passage
            variants = {
                "base": fuse(dense(query), bm25(query)),
                "e1_dense_expanded": fuse(dense(both), bm25(query)),
                "e2_dense+bm25_expanded": fuse(dense(both), bm25(both)),
                "e3_orig+hyde": fuse(dense(query), dense(passage), bm25(query)),
            }
            for name, fused in variants.items():
                scored = rerank(query, [(c, by[c].content) for c in fused])
                kept = [c for c, s in scored if s >= st.min_relevance_score][:10]
                for label, ids in ((name, kept), (name + " (no rerank)", fused[:10])):
                    out.setdefault(label, []).append(_keys_for_item([by[c] for c in ids], q, i))
        print(f"\n== {path.split('/')[-1]} ({len(questions)} questions)")
        print(f"{'variant':<40}{'mrr':>7}{'r@1':>7}{'r@3':>7}")
        for name, pairs in out.items():
            retrieved, relevant = [p[0] for p in pairs], [p[1] for p in pairs]
            r1 = np.mean([recall_at_k(r, rel, 1) for r, rel in pairs])
            r3 = np.mean([recall_at_k(r, rel, 3) for r, rel in pairs])
            mrr = mean_reciprocal_rank(retrieved, relevant)
            print(f"{name:<40}{mrr:>7.3f}{r1:>7.3f}{r3:>7.3f}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
