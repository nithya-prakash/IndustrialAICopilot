from app.evaluation.metrics import (
    dcg_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_finds_relevant_item_within_k() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = {"c"}
    assert recall_at_k(retrieved, relevant, k=3) == 1.0
    assert recall_at_k(retrieved, relevant, k=2) == 0.0


def test_recall_at_k_with_multiple_relevant_items() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = {"b", "d"}
    assert recall_at_k(retrieved, relevant, k=4) == 1.0
    assert recall_at_k(retrieved, relevant, k=2) == 0.5


def test_recall_at_k_no_relevant_items_is_zero_not_divide_by_zero() -> None:
    assert recall_at_k(["a", "b"], set(), k=3) == 0.0


def test_precision_at_k() -> None:
    retrieved = ["a", "b", "c"]
    relevant = {"a", "c"}
    assert precision_at_k(retrieved, relevant, k=3) == 2 / 3
    assert precision_at_k(retrieved, relevant, k=1) == 1.0


def test_precision_at_k_empty_retrieved_is_zero() -> None:
    assert precision_at_k([], {"a"}, k=3) == 0.0


def test_reciprocal_rank_first_hit_position() -> None:
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == 1 / 3
    assert reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0
    assert reciprocal_rank(["a", "b", "c"], {"z"}) == 0.0


def test_mean_reciprocal_rank_averages_across_queries() -> None:
    all_retrieved = [["a", "b"], ["x", "y"]]
    all_relevant = [{"a"}, {"y"}]
    # query 1: rank 1 -> RR=1.0 ; query 2: rank 2 -> RR=0.5
    assert mean_reciprocal_rank(all_retrieved, all_relevant) == 0.75


def test_ndcg_perfect_ranking_is_one() -> None:
    retrieved = ["a", "b", "c"]
    relevant = {"a", "b"}
    assert ndcg_at_k(retrieved, relevant, k=3) == 1.0


def test_ndcg_worse_ranking_is_less_than_one() -> None:
    retrieved = ["c", "b", "a"]  # relevant items pushed to the back
    relevant = {"a", "b"}
    score = ndcg_at_k(retrieved, relevant, k=3)
    assert 0.0 < score < 1.0


def test_ndcg_no_relevant_found_is_zero() -> None:
    assert ndcg_at_k(["a", "b"], {"z"}, k=2) == 0.0


def test_dcg_rewards_earlier_relevant_items() -> None:
    early = dcg_at_k(["a", "b"], {"a"}, k=2)
    late = dcg_at_k(["b", "a"], {"a"}, k=2)
    assert early > late
