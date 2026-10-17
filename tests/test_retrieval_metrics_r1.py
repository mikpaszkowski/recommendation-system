"""
Unit tests for the R1 label-free retrieval metrics and per-strategy aggregates
(Technical Specification AC-013).
"""
import pytest

from src.evaluation.metrics import (
    compute_popularity_bias_at_k,
    compute_type_precision_at_k,
    evaluate_retrieval_batch,
)


def test_popularity_bias_share():
    """Share of the top-K that is in the popular set."""
    assert compute_popularity_bias_at_k(["A", "B", "C", "D"], {"A", "C"}, 2) == pytest.approx(0.5)
    assert compute_popularity_bias_at_k(["A", "B", "C", "D"], {"A", "C"}, 4) == pytest.approx(0.5)
    assert compute_popularity_bias_at_k(["B", "D"], {"A"}, 5) == pytest.approx(0.0)


def test_popularity_bias_short_list_uses_retrieved_count():
    """With fewer than K results the denominator is the number retrieved, not K."""
    assert compute_popularity_bias_at_k(["A"], {"A"}, 20) == pytest.approx(1.0)


def test_metrics_return_none_for_empty_input():
    """Nothing retrieved is not the same as unbiased or precise."""
    assert compute_popularity_bias_at_k([], {"A"}, 5) is None
    assert compute_type_precision_at_k([], {"A"}, 5) is None
    assert compute_type_precision_at_k(["A"], {"A"}, 0) is None


def test_duplicates_count_once():
    """Rank-preserving deduplication, like the other metrics."""
    assert compute_type_precision_at_k(["A", "A", "B"], {"A"}, 2) == pytest.approx(0.5)


def test_type_precision_share():
    """Share of the top-K satisfying the requested category."""
    assert compute_type_precision_at_k(["A", "B", "C"], {"A", "B"}, 3) == pytest.approx(2 / 3)


def _batch():
    ground_truth = [
        {"query_id": "q1", "target_asin": "A", "ground_truth_asins": ["A"]},
        {"query_id": "q2", "target_asin": "X", "ground_truth_asins": ["X"]},
    ]
    predictions = [
        {"query_id": "q1", "strategy": "hybrid", "candidate_asins": ["A", "B"], "latency_ms": 10.0},
        {"query_id": "q2", "strategy": "hybrid", "candidate_asins": [], "latency_ms": 30.0},
        {"query_id": "q1", "strategy": "hybrid@sum_legacy", "candidate_asins": ["B", "A"], "latency_ms": 5.0},
        {"query_id": "q2", "strategy": "hybrid@sum_legacy", "candidate_asins": ["P"], "latency_ms": 7.0},
    ]
    return predictions, ground_truth


def test_aggregates_by_strategy_and_skip_none():
    """One aggregate block per strategy; empty retrievals are skipped for the share metrics."""
    predictions, ground_truth = _batch()

    out = evaluate_retrieval_batch(
        predictions, ground_truth, k_values=(1, 2),
        popular_asins={"B", "P"},
        type_match={"q1": {"A"}, "q2": {"P"}},
    )

    by = out["aggregates_by_strategy"]
    assert list(by) == ["hybrid", "hybrid@sum_legacy"]
    assert by["hybrid"]["query_count"] == 2
    assert by["hybrid"]["mean_strict_hr@1"] == pytest.approx(0.5)
    assert by["hybrid@sum_legacy"]["mean_strict_hr@1"] == pytest.approx(0.0)
    assert by["hybrid@sum_legacy"]["mean_strict_hr@2"] == pytest.approx(0.5)
    # hybrid: q1 top-2 = [A, B] -> 0.5; q2 empty -> skipped
    assert by["hybrid"]["mean_popularity_bias@2"] == pytest.approx(0.5)
    # sum_legacy: q1 [B, A] -> 0.5; q2 [P] -> 1.0
    assert by["hybrid@sum_legacy"]["mean_popularity_bias@2"] == pytest.approx(0.75)
    assert by["hybrid@sum_legacy"]["mean_type_precision@1"] == pytest.approx(0.5)
    assert by["hybrid"]["p50_latency_ms"] == pytest.approx(20.0)
    # Pooled aggregates are unchanged in shape
    assert out["aggregates"]["mean_hr@1"] == pytest.approx(0.25)


def test_metrics_absent_without_inputs():
    """Without popular / type inputs the new keys are not emitted (backward compatible)."""
    predictions, ground_truth = _batch()

    out = evaluate_retrieval_batch(predictions, ground_truth, k_values=(1,))

    assert "popularity_bias@1" not in out["per_query_results"][0]
    assert "mean_popularity_bias@1" not in out["aggregates_by_strategy"]["hybrid"]
