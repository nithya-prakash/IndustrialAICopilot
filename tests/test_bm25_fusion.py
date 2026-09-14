from app.rag.bm25 import _index_cache, bm25_search, bm25_search_cached, invalidate_bm25_cache
from app.rag.fusion import reciprocal_rank_fusion


def test_bm25_ranks_exact_keyword_match_highest() -> None:
    corpus = [
        ("1", "Check the bearing for excessive vibration and misalignment."),
        ("2", "Clean the cooling fins to prevent overheating."),
        ("3", "Replace the coupling if wear is detected."),
    ]
    results = bm25_search("bearing vibration", corpus, top_k=3)

    assert results[0].chunk_id == "1"
    assert all(r.score > 0 for r in results)


def test_bm25_empty_query_returns_nothing() -> None:
    corpus = [("1", "some content")]
    assert bm25_search("", corpus, top_k=5) == []


def test_bm25_empty_corpus_returns_nothing() -> None:
    assert bm25_search("bearing", [], top_k=5) == []


def test_bm25_no_keyword_overlap_scores_zero_and_is_excluded() -> None:
    corpus = [("1", "completely unrelated content about lubrication schedules")]
    results = bm25_search("xyzabc123 nonexistent term", corpus, top_k=5)
    assert results == []


def test_bm25_respects_top_k() -> None:
    corpus = [(str(i), f"bearing bearing bearing text number {i}") for i in range(10)]
    results = bm25_search("bearing", corpus, top_k=3)
    assert len(results) == 3


def test_rrf_promotes_items_ranked_high_in_both_lists() -> None:
    dense = ["c", "a", "b"]
    bm25 = ["a", "b", "c"]
    fused = reciprocal_rank_fusion([dense, bm25], k=60)
    fused_ids = [chunk_id for chunk_id, _score in fused]
    # "a" is rank 2 in dense and rank 1 in bm25 -> best combined rank
    assert fused_ids[0] == "a"


def test_rrf_item_in_only_one_list_still_included() -> None:
    dense = ["a", "b"]
    bm25 = ["c"]
    fused = reciprocal_rank_fusion([dense, bm25], k=60)
    fused_ids = {chunk_id for chunk_id, _score in fused}
    assert fused_ids == {"a", "b", "c"}


def test_rrf_empty_lists_returns_empty() -> None:
    assert reciprocal_rank_fusion([[], []], k=60) == []


def test_rrf_scores_are_monotonically_decreasing() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"]], k=60)
    scores = [score for _chunk_id, score in fused]
    assert scores == sorted(scores, reverse=True)


def _clear_bm25_cache() -> None:
    _index_cache.clear()


# BM25's IDF is <= 0 (and so gets filtered out entirely — app/rag/bm25.py
# only keeps score > 0 results) when a query term appears in too few of
# too-small a corpus — a term in 1-of-2 documents scores exactly 0
# (log((N-freq+0.5)/(freq+0.5)) = log(1.5/1.5) = 0), and 1-of-1 scores
# negative. Every corpus below uses 3+ documents so the target term gets
# a genuinely positive score — the same lesson from the retrieval
# ablation harness (evaluation/retrieval_ablation.py) and E2E test
# (tests/test_e2e_diagnosis_pipeline_mocked.py) earlier in this project.
_DISTRACTOR_1 = ("d1", "Apply food-grade lubricant to the conveyor belt every 90 days.")
_DISTRACTOR_2 = ("d2", "Disconnect and lock out power before servicing any panel.")


def test_bm25_search_cached_returns_same_ranking_as_uncached() -> None:
    _clear_bm25_cache()
    corpus = [
        ("1", "Check the bearing for excessive vibration and misalignment."),
        _DISTRACTOR_1,
        _DISTRACTOR_2,
    ]
    cached = bm25_search_cached("bearing vibration", corpus, top_k=3, cache_key=("t1",))
    uncached = bm25_search("bearing vibration", corpus, top_k=3)
    assert [c.chunk_id for c in cached] == [c.chunk_id for c in uncached]
    assert [c.chunk_id for c in cached] == ["1"]


def test_bm25_search_cached_reuses_index_for_same_cache_key() -> None:
    """The whole point of caching: a second call with a *stale* corpus
    under the same cache_key still returns results from the originally
    cached index, not the new corpus — proving the index was actually
    reused rather than silently rebuilt every call."""
    _clear_bm25_cache()
    original_corpus = [("1", "bearing vibration misalignment"), _DISTRACTOR_1, _DISTRACTOR_2]
    bm25_search_cached("bearing", original_corpus, top_k=3, cache_key=("t2",))

    changed_corpus = [
        ("2", "completely different content, no bearing mention"),
        _DISTRACTOR_1,
        _DISTRACTOR_2,
    ]
    results = bm25_search_cached("bearing", changed_corpus, top_k=3, cache_key=("t2",))

    assert [c.chunk_id for c in results] == ["1"]


def test_bm25_search_cached_different_keys_do_not_share_index() -> None:
    _clear_bm25_cache()
    corpus_a = [("a1", "bearing vibration"), _DISTRACTOR_1, _DISTRACTOR_2]
    corpus_b = [("b1", "cooling fins overheating"), _DISTRACTOR_1, _DISTRACTOR_2]

    bm25_search_cached("bearing", corpus_a, top_k=3, cache_key=("tenant_a",))
    results_b = bm25_search_cached("cooling", corpus_b, top_k=3, cache_key=("tenant_b",))

    assert [c.chunk_id for c in results_b] == ["b1"]


def test_invalidate_bm25_cache_forces_rebuild() -> None:
    _clear_bm25_cache()
    original_corpus = [("1", "bearing vibration"), _DISTRACTOR_1, _DISTRACTOR_2]
    bm25_search_cached("bearing", original_corpus, top_k=3, cache_key=("t3",))

    invalidate_bm25_cache()

    new_corpus = [("2", "cooling fins overheating"), _DISTRACTOR_1, _DISTRACTOR_2]
    results = bm25_search_cached("cooling", new_corpus, top_k=3, cache_key=("t3",))
    assert [c.chunk_id for c in results] == ["2"]
