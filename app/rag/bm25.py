"""Lexical retrieval leg of hybrid search.

`bm25_search` is a pure function: recomputed on demand over whatever
candidate set is passed in, no caching, no side effects — directly
testable and used as-is by tests/test_bm25_fusion.py and the retrieval
ablation harness. `bm25_search_cached` is the one production
(app/rag/retrieval.py) actually calls: it reuses a previously-built
BM25Okapi index (term-frequency/IDF statistics, the expensive part —
scoring one query against an already-built index is cheap) across calls
that share the same cache_key, instead of rebuilding from scratch on
every single retrieval call. See its own docstring for why a TTL, not
event-based invalidation.
"""
import re
import time
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class ScoredChunk:
    chunk_id: str
    score: float


def bm25_search(query: str, corpus: list[tuple[str, str]], top_k: int) -> list[ScoredChunk]:
    """corpus: list of (chunk_id, content). Returns chunks with score > 0,
    best first."""
    if not corpus or not query.strip():
        return []

    tokenized_corpus = [_tokenize(content) for _, content in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(query))

    ranked = sorted(
        ((chunk_id, float(score)) for (chunk_id, _), score in zip(corpus, scores, strict=True)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [ScoredChunk(chunk_id=cid, score=score) for cid, score in ranked if score > 0][:top_k]


_INDEX_CACHE_TTL_SECONDS = 60
_index_cache: dict[tuple, tuple[float, BM25Okapi, list[str]]] = {}


def bm25_search_cached(
    query: str, corpus: list[tuple[str, str]], top_k: int, cache_key: tuple
) -> list[ScoredChunk]:
    """Same ranking as bm25_search, but reuses a cached BM25Okapi index
    across calls sharing the same cache_key instead of rebuilding it from
    scratch on every query. Expires after a short TTL rather than being
    invalidated on document changes: chunk ingestion completes in the
    Celery worker (app/services/ingestion_service.py), a separate process
    from the one holding this cache, which can't directly signal it
    without new cross-process plumbing — a short TTL is a simple, honest
    bound on staleness (at most _INDEX_CACHE_TTL_SECONDS old) instead.
    delete_document (app/services/document_service.py, same process as
    this cache) also proactively clears it for faster same-process
    freshness on deletes. cache_key should scope exactly what the corpus
    was filtered by, e.g. (tenant_id, equipment_type, equipment_id,
    document_id)."""
    if not corpus or not query.strip():
        return []

    now = time.monotonic()
    cached = _index_cache.get(cache_key)
    if cached is not None and now - cached[0] < _INDEX_CACHE_TTL_SECONDS:
        _, bm25, chunk_ids = cached
    else:
        chunk_ids = [cid for cid, _content in corpus]
        tokenized_corpus = [_tokenize(content) for _cid, content in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        _index_cache[cache_key] = (now, bm25, chunk_ids)

    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(
        zip(chunk_ids, (float(s) for s in scores), strict=True),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [ScoredChunk(chunk_id=cid, score=score) for cid, score in ranked if score > 0][:top_k]


def invalidate_bm25_cache() -> None:
    _index_cache.clear()
