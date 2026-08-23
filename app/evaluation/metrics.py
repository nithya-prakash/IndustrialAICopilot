"""Retrieval evaluation metrics. Pure functions over ranked lists of source
keys and a ground-truth relevant set — no framework dependency, so they're
usable from both the evaluation runner and unit tests.
"""
import math


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    return len(top_k & relevant) / len(relevant)


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for r in top_k if r in relevant)
    return hits / len(top_k)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for i, r in enumerate(retrieved, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def mean_reciprocal_rank(all_retrieved: list[list[str]], all_relevant: list[set[str]]) -> float:
    if not all_retrieved:
        return 0.0
    scores = [
        reciprocal_rank(retrieved, relevant)
        for retrieved, relevant in zip(all_retrieved, all_relevant, strict=True)
    ]
    return sum(scores) / len(scores)


def dcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    return sum(
        (1.0 if r in relevant else 0.0) / math.log2(i + 1)
        for i, r in enumerate(retrieved[:k], start=1)
    )


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    dcg = dcg_at_k(retrieved, relevant, k)
    # Ideal ranking: every relevant item first, in any order.
    ideal = list(relevant) + [r for r in retrieved if r not in relevant]
    idcg = dcg_at_k(ideal, relevant, k)
    return dcg / idcg if idcg > 0 else 0.0
