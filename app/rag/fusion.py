"""Reciprocal Rank Fusion — combines the dense and BM25 rankings without
needing to normalize scores onto a common scale (cosine similarity is
bounded [0,1], BM25 is unbounded and corpus-dependent; RRF only looks at
rank position, sidestepping that entirely). Standard, well-understood
technique for hybrid search fusion.
"""


def reciprocal_rank_fusion(ranked_lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """ranked_lists: each a list of chunk_ids best-first. Returns
    (chunk_id, fused_score) sorted best-first."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
