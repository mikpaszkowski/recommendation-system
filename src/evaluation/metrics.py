"""
Information Retrieval (IR) and Ranking Metrics Engine for CRS Evaluation.

Provides exact mathematical formulations for:
- Normalized Discounted Cumulative Gain at K (NDCG@K) with binary and graded relevance
- Hit Rate at K (HR@K)
- Mean Reciprocal Rank at K (MRR@K)
- Precision at K (P@K)
- Recall at K (R@K)
- Average Precision at K (AP@K / MAP@K)
- Batch retrieval evaluation across cutoff horizons K with rank-preserving deduplication
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set, Union
import numpy as np


def compute_ndcg_at_k(
    retrieved_ids: Sequence[str],
    ground_truth_ids: Union[Set[str], Sequence[str], Dict[str, float]],
    k: int,
) -> float:
    """
    Computes Normalized Discounted Cumulative Gain at K (NDCG@K).

    Formulation:
        DCG@K = sum_{i=1}^K (2^{rel_i} - 1) / log2(i + 1)
        IDCG@K = sum_{i=1}^{min(K, |REL|)} (2^{rel*_i} - 1) / log2(i + 1)
        NDCG@K = DCG@K / IDCG@K

    Enforces rank-preserving candidate deduplication: duplicate occurrences of an item
    are ignored after its first occurrence so an item is only scored once.
    Clamped strictly to the closed interval [0.0, 1.0].
    """
    try:
        k = int(k)
    except (ValueError, TypeError):
        return 0.0

    if k <= 0 or not retrieved_ids or not ground_truth_ids:
        return 0.0

    # Build relevance lookup map and sorted ideal relevance list
    if isinstance(ground_truth_ids, (set, list, tuple)):
        unique_gt = set(ground_truth_ids)
        rel_map: Dict[str, float] = {item_id: 1.0 for item_id in unique_gt}
        all_rel_values = sorted([1.0] * len(unique_gt), reverse=True)
    elif isinstance(ground_truth_ids, dict):
        rel_map = ground_truth_ids
        all_rel_values = sorted([float(v) for v in ground_truth_ids.values() if float(v) > 0.0], reverse=True)
    else:
        return 0.0

    if not all_rel_values or max(all_rel_values) <= 0.0:
        return 0.0

    # Compute DCG@K with rank-preserving candidate deduplication
    dcg = 0.0
    seen_items: Set[str] = set()
    cutoff = min(k, len(retrieved_ids))
    for i in range(cutoff):
        item_id = retrieved_ids[i]
        if item_id in seen_items:
            continue
        seen_items.add(item_id)
        rel = rel_map.get(item_id, 0.0)
        if rel > 0.0:
            dcg += (math.pow(2.0, rel) - 1.0) / math.log2(i + 2.0)

    # Compute Ideal DCG@K (IDCG@K)
    idcg = 0.0
    ideal_cutoff = min(k, len(all_rel_values))
    for i in range(ideal_cutoff):
        rel = all_rel_values[i]
        if rel > 0.0:
            idcg += (math.pow(2.0, rel) - 1.0) / math.log2(i + 2.0)

    if idcg == 0.0:
        return 0.0

    return float(min(1.0, max(0.0, dcg / idcg)))


def compute_hit_rate_at_k(
    retrieved_ids: Sequence[str],
    ground_truth_ids: Union[Set[str], Sequence[str]],
    k: int,
) -> float:
    """
    Computes Hit Rate at K (HR@K).

    Returns 1.0 if any ground truth item is present in top-K retrieved items, else 0.0.
    """
    try:
        k = int(k)
    except (ValueError, TypeError):
        return 0.0

    if k <= 0 or not retrieved_ids or not ground_truth_ids:
        return 0.0

    gt_set = set(ground_truth_ids)
    top_k = retrieved_ids[:k]
    return 1.0 if any(item in gt_set for item in top_k) else 0.0


def compute_mrr_at_k(
    retrieved_ids: Sequence[str],
    ground_truth_ids: Union[Set[str], Sequence[str]],
    k: int,
) -> float:
    """
    Computes Mean Reciprocal Rank at K (MRR@K).

    Returns 1 / rank of first relevant item in top-K, or 0.0 if none found.
    """
    try:
        k = int(k)
    except (ValueError, TypeError):
        return 0.0

    if k <= 0 or not retrieved_ids or not ground_truth_ids:
        return 0.0

    gt_set = set(ground_truth_ids)
    cutoff = min(k, len(retrieved_ids))
    for i in range(cutoff):
        if retrieved_ids[i] in gt_set:
            return float(1.0 / (i + 1.0))
    return 0.0


def compute_precision_at_k(
    retrieved_ids: Sequence[str],
    ground_truth_ids: Union[Set[str], Sequence[str]],
    k: int,
) -> float:
    """
    Computes Precision at K (P@K).

    Number of unique relevant items in top-K divided by K. Strictly bounded in [0.0, 1.0].
    """
    try:
        k = int(k)
    except (ValueError, TypeError):
        return 0.0

    if k <= 0 or not retrieved_ids or not ground_truth_ids:
        return 0.0

    gt_set = set(ground_truth_ids)
    top_k = retrieved_ids[:k]
    hits = len(set(top_k) & gt_set)
    return float(min(1.0, max(0.0, hits / k)))


def compute_recall_at_k(
    retrieved_ids: Sequence[str],
    ground_truth_ids: Union[Set[str], Sequence[str]],
    k: int,
) -> float:
    """
    Computes Recall at K (R@K).

    Number of unique relevant items in top-K divided by total ground truth items.
    Strictly bounded in [0.0, 1.0].
    """
    try:
        k = int(k)
    except (ValueError, TypeError):
        return 0.0

    if k <= 0 or not retrieved_ids or not ground_truth_ids:
        return 0.0

    gt_set = set(ground_truth_ids)
    if not gt_set:
        return 0.0

    top_k = retrieved_ids[:k]
    hits = len(set(top_k) & gt_set)
    return float(min(1.0, max(0.0, hits / len(gt_set))))


def compute_average_precision_at_k(
    retrieved_ids: Sequence[str],
    ground_truth_ids: Union[Set[str], Sequence[str]],
    k: int,
) -> float:
    """
    Computes Average Precision at K (AP@K).

    Formulation:
        AP@K = (1 / min(K, |REL|)) * sum_{i=1}^K Precision@i * I(item_i in REL)
    """
    try:
        k = int(k)
    except (ValueError, TypeError):
        return 0.0

    if k <= 0 or not retrieved_ids or not ground_truth_ids:
        return 0.0

    gt_set = set(ground_truth_ids)
    if not gt_set:
        return 0.0

    cutoff = min(k, len(retrieved_ids))
    num_hits = 0
    running_sum = 0.0
    seen: Set[str] = set()

    for i in range(cutoff):
        item = retrieved_ids[i]
        if item in seen:
            continue
        seen.add(item)
        if item in gt_set:
            num_hits += 1
            running_sum += num_hits / (i + 1.0)

    denominator = min(k, len(gt_set))
    if denominator == 0:
        return 0.0

    return float(min(1.0, max(0.0, running_sum / denominator)))


def evaluate_retrieval_batch(
    predictions: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
    k_values: Sequence[int] = (1, 3, 5, 10, 20),
) -> Dict[str, Any]:
    """
    Evaluates a batch of retrieval predictions against ground truth queries.

    Args:
        predictions: List of dicts with keys 'query_id' (or 'id'), 'candidate_asins', 'strategy', 'latency_ms'
        ground_truth: List of dicts with keys 'query_id' (or 'id'), 'ground_truth_asins', 'graded_relevance', 'utterance'
        k_values: Sequence of cutoff horizons K

    Returns:
        Dict with 'aggregates' and 'per_query_results'.
    """
    gt_by_id: Dict[str, Dict[str, Any]] = {}
    for item in ground_truth:
        qid = str(item.get("query_id") or item.get("id") or "")
        if qid:
            gt_by_id[qid] = item

    per_query_results: List[Dict[str, Any]] = []
    aggregates: Dict[str, float] = {}

    for pred in predictions:
        qid = str(pred.get("query_id") or pred.get("id") or "")
        gt = gt_by_id.get(qid, {})

        target_asins = gt.get("ground_truth_asins", [])
        if not target_asins and gt.get("target_asin"):
            target_asins = [gt["target_asin"]]

        graded_rel = gt.get("graded_relevance")
        retrieved_asins = pred.get("candidate_asins", [])
        strategy = pred.get("strategy", "hybrid")
        utterance = gt.get("utterance", pred.get("utterance", pred.get("query", "")))
        latency_ms = pred.get("latency_ms", 12.5)

        res_entry: Dict[str, Any] = {
            "query_id": qid,
            "utterance": utterance,
            "strategy": strategy,
            "candidate_asins": retrieved_asins,
            "target_asins": target_asins,
            "latency_ms": latency_ms,
        }

        # For NDCG, prefer graded relevance if provided, else target_asins
        ndcg_target = graded_rel if graded_rel else target_asins

        for k in k_values:
            res_entry[f"ndcg@{k}"] = compute_ndcg_at_k(retrieved_asins, ndcg_target, k)
            res_entry[f"hit@{k}"] = int(compute_hit_rate_at_k(retrieved_asins, target_asins, k))
            res_entry[f"precision@{k}"] = compute_precision_at_k(retrieved_asins, target_asins, k)
            res_entry[f"recall@{k}"] = compute_recall_at_k(retrieved_asins, target_asins, k)
            res_entry[f"ap@{k}"] = compute_average_precision_at_k(retrieved_asins, target_asins, k)

        max_k = max(int(k) for k in k_values) if k_values else 10
        res_entry["mrr"] = compute_mrr_at_k(retrieved_asins, target_asins, max_k)
        per_query_results.append(res_entry)

    if per_query_results:
        for k in k_values:
            aggregates[f"mean_ndcg@{k}"] = float(np.mean([r[f"ndcg@{k}"] for r in per_query_results]))
            aggregates[f"mean_hr@{k}"] = float(np.mean([r[f"hit@{k}"] for r in per_query_results]))
            aggregates[f"mean_precision@{k}"] = float(np.mean([r[f"precision@{k}"] for r in per_query_results]))
            aggregates[f"mean_recall@{k}"] = float(np.mean([r[f"recall@{k}"] for r in per_query_results]))
            aggregates[f"mean_ap@{k}"] = float(np.mean([r[f"ap@{k}"] for r in per_query_results]))
        aggregates["mean_mrr"] = float(np.mean([r["mrr"] for r in per_query_results]))

    return {"aggregates": aggregates, "per_query_results": per_query_results}


def compute_critic_gain(raw_ndcg: float, post_critic_ndcg: float) -> float:
    """Critic Ranking Gain: Delta NDCG between pre-critic retrieval and post-critic rerank."""
    return float(post_critic_ndcg - raw_ndcg)


def compute_cver(raw_violations_count: int, post_violations_count: int) -> float:
    """
    Constraint Violation Elimination Rate (CVER).
    Measures proportion of raw constraint violations successfully pruned by CriticAgent.
    """
    if raw_violations_count <= 0:
        return 1.0 if post_violations_count == 0 else 0.0
    eliminated = raw_violations_count - post_violations_count
    return float(max(0.0, min(1.0, eliminated / raw_violations_count)))


def compute_catalog_validity_rate(
    evaluated_asins: Sequence[str],
    valid_asins_set: Set[str],
) -> float:
    """
    Catalog Validity Rate (Zero-Hallucination Rate).
    Fraction of evaluated/recommended ASINs that exist in the live database.
    """
    if not evaluated_asins:
        return 1.0
    valid_count = sum(1 for asin in evaluated_asins if asin in valid_asins_set)
    return float(valid_count / len(evaluated_asins))

