"""
Information Retrieval (IR) and Ranking Metrics Engine for CRS Evaluation.

Provides exact mathematical formulations for:
- Normalized Discounted Cumulative Gain at K (NDCG@K) with binary and graded relevance
- Hit Rate at K (HR@K)
- Mean Reciprocal Rank at K (MRR@K)
- Precision at K (P@K)
- Recall at K (R@K)
- Average Precision at K (AP@K / MAP@K)
- Review-coverage bias at K (key `popularity_bias@k`: share of top-K from the review-embedded product set)
- Type precision at K (share of top-K satisfying the requested category)
- Constraint satisfaction at K (three-valued verdicts, see constraint_satisfaction.py)
- Batch retrieval evaluation across cutoff horizons K with rank-preserving deduplication,
  explicit denominators (all queries / SEARCH-only) and per-subset re-aggregation (R2a)
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union
import numpy as np

from src.evaluation.constraint_satisfaction import cs_scores_at_k

# R2a (FR-020) & R2b (FR-R2B-008): the legacy metric key popularity_bias@k keeps its exact label for R2a compatibility;
# Graph v2 adds review_cap_bias@k (20-review cap) and head_popularity_bias@k (top-10% catalogue review_count >= P90).
METRIC_LABELS: Dict[str, str] = {
    "popularity_bias": "review-coverage-bias@K: share of top-K from products with >= 1 embedded review (not popularity)",
    "review_cap_bias": "review-cap-bias@K (v2): share of top-K at the 20-review graph cap (5 embedded reviews)",
    "head_popularity_bias": "head-popularity-bias@K (v2): share of top-K in top-10% catalogue review_count >= P90",
}
# FR-023 / FR-024: CS aggregate names per flavour (gold: cs_*@k, request: cs_req_*@k)
CS_GOLD_KEYS: Dict[str, str] = {
    "cs_sat": "cs_sat", "cs_viol": "cs_viol", "cs_unk": "cs_unk", "cs_known": "cs_known",
    "violation_free": "violation_free", "cs_coverage": "cs_coverage",
}
CS_REQ_KEYS: Dict[str, str] = {
    "cs_sat": "cs_req_sat", "cs_viol": "cs_req_viol", "cs_unk": "cs_req_unk", "cs_known": "cs_req_known",
    "violation_free": "cs_req_violation_free", "cs_coverage": "cs_req_coverage",
}
SHARE_METRICS: Tuple[str, ...] = (
    ("popularity_bias", "review_cap_bias", "head_popularity_bias", "type_precision")
    + tuple(CS_GOLD_KEYS.values())
    + tuple(CS_REQ_KEYS.values())
)
REVIEW_SLICE_KS: Tuple[int, ...] = (5, 20)


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


def _share_in_set_at_k(retrieved_ids: Sequence[str], reference_ids: Set[str], k: int) -> Optional[float]:
    """Share of the (deduplicated) top-K retrieved IDs that belong to `reference_ids`; None if nothing was retrieved."""
    if k <= 0:
        return None
    top_k = list(dict.fromkeys(retrieved_ids))[:k]
    if not top_k:
        return None
    return float(sum(1 for asin in top_k if asin in reference_ids) / len(top_k))


def compute_popularity_bias_at_k(
    retrieved_ids: Sequence[str],
    popular_ids: Set[str],
    k: int,
) -> Optional[float]:
    """
    Computes review-coverage bias at K (reported as `RevCovBias@K`; key `popularity_bias@k`
    kept for compatibility): the share of the top-K candidates that belong to the set of
    products with at least one embedded review, i.e. the products the review channel can
    reach. It measures review-embedding coverage, not popularity.

    Formulation:
        RevCovBias@K = |top-K ∩ REVIEW_EMBEDDED| / |top-K|

    Compare against the catalogue base rate |REVIEW_EMBEDDED| / |CATALOGUE|. Most review-embedded
    products on the live graph are untitled "ghost" ParentProduct nodes, so the manifest also
    reports the titled-only base rate (`catalog_popular_share_titled`). Returns None when
    nothing was retrieved, so empty runs do not count as unbiased.
    """
    return _share_in_set_at_k(retrieved_ids, popular_ids, k)


def compute_review_cap_bias_at_k(
    retrieved_ids: Sequence[str],
    review_cap_ids: Set[str],
    k: int,
) -> Optional[float]:
    """
    Computes Graph Review-Cap Bias at K (R2b, FR-R2B-008): share of the deduplicated top-K
    candidates that sit at the 20-review ingestion cap (5 embedded reviews) on Graph v2
    (titled catalogue base rate = 0.519).
    """
    return _share_in_set_at_k(retrieved_ids, review_cap_ids, k)


def compute_head_popularity_bias_at_k(
    retrieved_ids: Sequence[str],
    head_popular_ids: Set[str],
    k: int,
) -> Optional[float]:
    """
    Computes Catalogue Bestseller Head Bias at K (R2b, FR-R2B-008): share of the deduplicated
    top-K candidates in the top decile of catalogue `p.review_count >= P90` (base rate = 0.100).
    """
    return _share_in_set_at_k(retrieved_ids, head_popular_ids, k)


def compute_type_precision_at_k(
    retrieved_ids: Sequence[str],
    in_type_ids: Set[str],
    k: int,
) -> Optional[float]:
    """
    Computes type precision at K: the share of the top-K candidates that satisfy the
    requested category / product type.

    Formulation:
        TypeP@K = |top-K ∩ IN_TYPE| / |top-K|

    Returns None when nothing was retrieved.
    """
    return _share_in_set_at_k(retrieved_ids, in_type_ids, k)


def _mean_skip_none(values: Sequence[Optional[float]]) -> Optional[float]:
    """Mean over the non-None values; None if there are none."""
    present = [v for v in values if v is not None]
    return float(np.mean(present)) if present else None


def _is_search(row: Mapping[str, Any]) -> bool:
    """Rows without an `action` (offline and legacy predictions) count as SEARCH."""
    action = row.get("action")
    return action is None or action == "SEARCH"


def _cs_entries(verdict_rows: Optional[Sequence[str]], k_values: Sequence[int], names: Dict[str, str]) -> Dict[str, Optional[float]]:
    """Per-K CS aggregates for one prediction, with None values when the query has no items or constraints."""
    entry: Dict[str, Optional[float]] = {}
    for k in k_values:
        scores = cs_scores_at_k(list(verdict_rows or []), int(k))
        for source_key, key in names.items():
            entry[f"{key}@{k}"] = scores.get(source_key) if scores else None
    return entry


def _slice_block(rows: Sequence[Mapping[str, Any]], k_values: Sequence[int]) -> Dict[str, Any]:
    """n, HR@{5,20}, MRR and strict NDCG@10 for a `by_target_review_embedded` slice."""
    block: Dict[str, Any] = {"n": len(rows)}
    for k in (5, 20):
        if k in k_values:
            block[f"mean_strict_hr@{k}"] = float(np.mean([r[f"strict_hit@{k}"] for r in rows])) if rows else None
    block["mean_mrr"] = float(np.mean([r["mrr"] for r in rows])) if rows else None
    if 10 in k_values:
        block["mean_strict_ndcg@10"] = float(np.mean([r["strict_ndcg@10"] for r in rows])) if rows else None
    return block


def _stratum_slice_block(rows: Sequence[Mapping[str, Any]], k_values: Sequence[int]) -> Dict[str, Any]:
    """Extended slice summary for `by_stratum` and `by_target_review_cap` in Release R2b."""
    search_rows = [r for r in rows if _is_search(r)]
    block = _slice_block(rows, k_values)
    block["n_all"] = len(rows)
    block["n_search"] = len(search_rows)
    if 10 in k_values:
        block["mean_strict_hr@10"] = float(np.mean([r["strict_hit@10"] for r in rows])) if rows else None
    for share_key in ("popularity_bias@5", "review_cap_bias@5", "head_popularity_bias@5", "type_precision@5", "cs_known@5", "violation_free@5"):
        if any(share_key in r for r in rows):
            block[f"mean_{share_key}"] = _mean_skip_none([r.get(share_key) for r in rows])
    return block


def aggregate_rows(rows: Sequence[Mapping[str, Any]], k_values: Sequence[int]) -> Dict[str, Any]:
    """
    Per-strategy aggregate block over any subset of per-query result rows (FR-019 d), e.g. the
    cross-run SEARCH intersection. Share metrics (review-coverage bias, type precision, CS@K)
    are averaged over non-None values and reported with their `n_<metric>@k` count; they appear
    only when the rows carry them. `search_only` repeats HR / NDCG / MRR / recall over SEARCH rows.
    """
    rows = list(rows)
    agg: Dict[str, Any] = {"query_count": len(rows), "n_all": len(rows)}
    if not rows:
        agg.update({"n_search": 0, "search_only": {"n": 0}})
        return agg
    search_rows = [r for r in rows if _is_search(r)]
    agg["n_search"] = len(search_rows)

    for k in k_values:
        agg[f"mean_strict_hr@{k}"] = float(np.mean([r[f"strict_hit@{k}"] for r in rows]))
        agg[f"mean_soft_hr@{k}"] = float(np.mean([r[f"soft_hit@{k}"] for r in rows]))
        agg[f"mean_strict_ndcg@{k}"] = float(np.mean([r[f"strict_ndcg@{k}"] for r in rows]))
        agg[f"mean_graded_ndcg@{k}"] = float(np.mean([r[f"graded_ndcg@{k}"] for r in rows]))
        agg[f"mean_recall@{k}"] = float(np.mean([r[f"recall@{k}"] for r in rows]))
        for metric in SHARE_METRICS:
            key = f"{metric}@{k}"
            if any(key in r for r in rows):
                values = [r.get(key) for r in rows]
                agg[f"mean_{key}"] = _mean_skip_none(values)
                agg[f"n_{key}"] = sum(1 for v in values if v is not None)
    agg["mean_mrr"] = float(np.mean([r["mrr"] for r in rows]))
    latencies = [r["latency_ms"] for r in rows if isinstance(r.get("latency_ms"), (int, float))]
    agg["p50_latency_ms"] = float(np.median(latencies)) if latencies else None

    search_only: Dict[str, Any] = {"n": len(search_rows)}
    for k in k_values:
        search_only[f"mean_strict_hr@{k}"] = float(np.mean([r[f"strict_hit@{k}"] for r in search_rows])) if search_rows else None
        search_only[f"mean_strict_ndcg@{k}"] = float(np.mean([r[f"strict_ndcg@{k}"] for r in search_rows])) if search_rows else None
        search_only[f"mean_recall@{k}"] = float(np.mean([r[f"recall@{k}"] for r in search_rows])) if search_rows else None
    search_only["mean_mrr"] = float(np.mean([r["mrr"] for r in search_rows])) if search_rows else None
    agg["search_only"] = search_only

    if any(r.get("target_review_embedded") is not None for r in rows):
        agg["by_target_review_embedded"] = {
            "true": _slice_block([r for r in rows if r.get("target_review_embedded") is True], k_values),
            "false": _slice_block([r for r in rows if r.get("target_review_embedded") is False], k_values),
        }
    if any(r.get("target_review_cap") is not None for r in rows):
        agg["by_target_review_cap"] = {
            "true": _stratum_slice_block([r for r in rows if r.get("target_review_cap") is True], k_values),
            "false": _stratum_slice_block([r for r in rows if r.get("target_review_cap") is False], k_values),
        }
    strata_present = [s for s in dict.fromkeys(r.get("stratum") for r in rows) if s]
    if strata_present:
        agg["by_stratum"] = {
            str(s): _stratum_slice_block([r for r in rows if r.get("stratum") == s], k_values)
            for s in strata_present
        }
    return agg


def evaluate_retrieval_batch(
    predictions: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
    k_values: Sequence[int] = (1, 3, 5, 10, 20),
    popular_asins: Optional[Set[str]] = None,
    type_match: Optional[Dict[str, Set[str]]] = None,
    review_cap_asins: Optional[Set[str]] = None,
    head_popular_asins: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Evaluates a batch of retrieval predictions against ground truth queries.

    Args:
        predictions: List of dicts with keys 'query_id' (or 'id'), 'candidate_asins', 'strategy', 'latency_ms';
            optionally 'action' (rows without it count as SEARCH), 'cs_gold_verdicts' and 'cs_req_verdicts'
            (one verdict string per deduplicated candidate, see constraint_satisfaction.verdict_matrix)
        ground_truth: List of dicts with keys 'query_id' (or 'id'), 'ground_truth_asins', 'graded_relevance', 'utterance';
            optionally 'gold_action', 'type_explicit', 'stratum', and 'split'
        k_values: Sequence of cutoff horizons K
        popular_asins: Optional review-embedded product set; enables popularity_bias@K (review-coverage bias)
            and the target_review_embedded tag
        type_match: Optional mapping query_id -> candidate ASINs satisfying the requested category; enables type_precision@K
        review_cap_asins: Optional 20-review cap product set on Graph v2; enables review_cap_bias@K
        head_popular_asins: Optional top-10% catalogue review_count >= P90 set; enables head_popularity_bias@K

    All-queries rule (FR-019 c): CLARIFY on a type-explicit query scores 0 (a miss). On a
    gold_action = "CLARIFY" query, hit@k / strict_hit@k, strict_ndcg@k and mrr are 1.0 if the
    action is CLARIFY and 0.0 otherwise (`scored_as: "clarify_gold"`).

    Returns:
        Dict with 'aggregates' (pooled over all strategies), 'aggregates_by_strategy' and 'per_query_results'.
    """
    gt_by_id: Dict[str, Dict[str, Any]] = {}
    for item in ground_truth:
        qid = str(item.get("query_id") or item.get("id") or "")
        if qid:
            gt_by_id[qid] = item

    per_query_results: List[Dict[str, Any]] = []
    aggregates: Dict[str, float] = {}
    max_k = max(int(k) for k in k_values) if k_values else 10

    for pred in predictions:
        qid = str(pred.get("query_id") or pred.get("id") or "")
        gt = gt_by_id.get(qid, {})

        target_asins = gt.get("ground_truth_asins", [])
        if not target_asins and gt.get("target_asin"):
            target_asins = [gt["target_asin"]]

        primary_target = gt.get("target_asin") or (target_asins[0] if target_asins else None)
        peer_asins = gt.get("peer_asins", [])
        strict_targets = [primary_target] if primary_target else target_asins
        soft_targets = list(dict.fromkeys(([primary_target] if primary_target else []) + list(target_asins) + list(peer_asins)))

        graded_rel = gt.get("graded_relevance")
        retrieved_asins = pred.get("candidate_asins", [])
        strategy = pred.get("strategy", "hybrid")
        utterance = gt.get("utterance", pred.get("utterance", pred.get("query", "")))
        latency_ms = pred.get("latency_ms", 12.5)
        action = pred.get("action")
        clarify_gold = gt.get("gold_action") == "CLARIFY"
        stratum = gt.get("stratum") or pred.get("stratum")
        split = gt.get("split") or pred.get("split")

        res_entry: Dict[str, Any] = {
            "query_id": qid,
            "utterance": utterance,
            "strategy": strategy,
            "stratum": stratum,
            "split": split,
            "candidate_asins": retrieved_asins,
            "target_asins": target_asins,
            "primary_target": primary_target,
            "peer_asins": peer_asins,
            "latency_ms": latency_ms,
            "action": action if action is not None else "SEARCH",
            "scored_as": "clarify_gold" if clarify_gold else "retrieval",
            "target_review_embedded": (primary_target in popular_asins) if popular_asins is not None and primary_target else None,
            "target_review_cap": (primary_target in review_cap_asins) if review_cap_asins is not None and primary_target else None,
            "target_head_popular": (primary_target in head_popular_asins) if head_popular_asins is not None and primary_target else None,
        }
        clarify_score = 1.0 if action == "CLARIFY" else 0.0

        # For NDCG, prefer graded relevance if provided, else target_asins
        ndcg_target = graded_rel if graded_rel else target_asins

        for k in k_values:
            strict_hit = int(compute_hit_rate_at_k(retrieved_asins, strict_targets, k))
            soft_hit = int(compute_hit_rate_at_k(retrieved_asins, soft_targets, k))
            strict_ndcg = compute_ndcg_at_k(retrieved_asins, strict_targets, k)
            graded_ndcg = compute_ndcg_at_k(retrieved_asins, ndcg_target, k)
            if clarify_gold:
                strict_hit = int(clarify_score)
                strict_ndcg = clarify_score

            res_entry[f"hit@{k}"] = strict_hit
            res_entry[f"strict_hit@{k}"] = strict_hit
            res_entry[f"soft_hit@{k}"] = soft_hit
            res_entry[f"ndcg@{k}"] = graded_ndcg
            res_entry[f"graded_ndcg@{k}"] = graded_ndcg
            res_entry[f"strict_ndcg@{k}"] = strict_ndcg
            res_entry[f"precision@{k}"] = compute_precision_at_k(retrieved_asins, target_asins, k)
            res_entry[f"recall@{k}"] = compute_recall_at_k(retrieved_asins, target_asins, k)
            res_entry[f"ap@{k}"] = compute_average_precision_at_k(retrieved_asins, target_asins, k)

            if popular_asins is not None:
                res_entry[f"popularity_bias@{k}"] = compute_popularity_bias_at_k(retrieved_asins, popular_asins, k)
            if review_cap_asins is not None:
                res_entry[f"review_cap_bias@{k}"] = compute_review_cap_bias_at_k(retrieved_asins, review_cap_asins, k)
            if head_popular_asins is not None:
                res_entry[f"head_popularity_bias@{k}"] = compute_head_popularity_bias_at_k(retrieved_asins, head_popular_asins, k)
            if type_match is not None:
                res_entry[f"type_precision@{k}"] = compute_type_precision_at_k(retrieved_asins, type_match.get(qid, set()), k)

        if "cs_gold_verdicts" in pred:
            res_entry.update(_cs_entries(pred.get("cs_gold_verdicts"), k_values, CS_GOLD_KEYS))
        if "cs_req_verdicts" in pred:
            res_entry.update(_cs_entries(pred.get("cs_req_verdicts"), k_values, CS_REQ_KEYS))

        res_entry["mrr"] = clarify_score if clarify_gold else compute_mrr_at_k(retrieved_asins, strict_targets, max_k)
        per_query_results.append(res_entry)

    if per_query_results:
        for k in k_values:
            aggregates[f"mean_ndcg@{k}"] = float(np.mean([r[f"ndcg@{k}"] for r in per_query_results]))
            aggregates[f"mean_graded_ndcg@{k}"] = float(np.mean([r[f"graded_ndcg@{k}"] for r in per_query_results]))
            aggregates[f"mean_strict_ndcg@{k}"] = float(np.mean([r[f"strict_ndcg@{k}"] for r in per_query_results]))
            aggregates[f"mean_hr@{k}"] = float(np.mean([r[f"hit@{k}"] for r in per_query_results]))
            aggregates[f"mean_strict_hr@{k}"] = float(np.mean([r[f"strict_hit@{k}"] for r in per_query_results]))
            aggregates[f"mean_soft_hr@{k}"] = float(np.mean([r[f"soft_hit@{k}"] for r in per_query_results]))
            aggregates[f"mean_precision@{k}"] = float(np.mean([r[f"precision@{k}"] for r in per_query_results]))
            aggregates[f"mean_recall@{k}"] = float(np.mean([r[f"recall@{k}"] for r in per_query_results]))
            aggregates[f"mean_ap@{k}"] = float(np.mean([r[f"ap@{k}"] for r in per_query_results]))
        aggregates["mean_mrr"] = float(np.mean([r["mrr"] for r in per_query_results]))

    aggregates_by_strategy: Dict[str, Dict[str, Any]] = {}
    for strategy in dict.fromkeys(r["strategy"] for r in per_query_results):
        rows = [r for r in per_query_results if r["strategy"] == strategy]
        aggregates_by_strategy[strategy] = aggregate_rows(rows, k_values)

    return {
        "aggregates": aggregates,
        "aggregates_by_strategy": aggregates_by_strategy,
        "per_query_results": per_query_results,
    }


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

