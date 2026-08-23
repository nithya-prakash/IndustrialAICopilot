"""Lexical retrieval leg of hybrid search. Recomputed on demand over the
tenant/filter-scoped candidate set (fetched from Postgres, the system of
record for chunk text — see docs/architecture-decisions.md) rather than
maintained as a persistent index. At portfolio scale (hundreds of chunks per
tenant) this is sub-millisecond; a real deployment with a much larger corpus
would move this to a dedicated search engine (Elasticsearch/OpenSearch)
instead of recomputing BM25 statistics per query.
"""
import re
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
