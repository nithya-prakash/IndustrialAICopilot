"""Cross-encoder reranker. Runs locally (no API key) — a cross-encoder
scores the (query, chunk) pair jointly, which is more accurate than the
bi-encoder cosine similarity used for initial retrieval but too slow to run
over the whole corpus, hence: cheap bi-encoder/BM25 retrieval first to get a
candidate set, then this reranks just that candidate set.
"""
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.config import get_settings


@lru_cache
def get_reranker() -> CrossEncoder:
    settings = get_settings()
    return CrossEncoder(settings.rerank_model)


def rerank(query: str, candidates: list[tuple[str, str]]) -> list[tuple[str, float]]:
    """candidates: list of (chunk_id, content). Returns (chunk_id, score)
    sorted best-first."""
    if not candidates:
        return []

    model = get_reranker()
    pairs = [[query, content] for _, content in candidates]
    scores = model.predict(pairs)

    ranked = sorted(
        zip((cid for cid, _ in candidates), scores, strict=True),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [(cid, float(score)) for cid, score in ranked]
