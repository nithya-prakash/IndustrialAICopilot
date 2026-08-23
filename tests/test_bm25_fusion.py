from app.rag.bm25 import bm25_search
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
