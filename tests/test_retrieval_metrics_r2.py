"""
tests/test_retrieval_metrics_r2.py

R2a denominators, all-queries rule, review-coverage label and CS aggregation in
evaluate_retrieval_batch (Technical Specification AC-014, AC-016, FR-019 … FR-024).
"""
from __future__ import annotations

import pytest

from src.evaluation.metrics import METRIC_LABELS, evaluate_retrieval_batch


def _gt():
    return [
        {"query_id": "q1", "target_asin": "A", "type_explicit": True, "gold_action": "SEARCH"},
        {"query_id": "q2", "target_asin": "B", "type_explicit": True, "gold_action": "SEARCH"},
        {"query_id": "q3", "target_asin": "C", "type_explicit": False, "gold_action": "CLARIFY"},
        {"query_id": "q4", "target_asin": "D", "type_explicit": False, "gold_action": "CLARIFY"},
    ]


def _preds():
    return [
        {"query_id": "q1", "strategy": "hybrid", "candidate_asins": ["A", "X"], "action": "SEARCH",
         "cs_gold_verdicts": ["SV", "UU"], "cs_req_verdicts": ["S", "S"]},
        {"query_id": "q2", "strategy": "hybrid", "candidate_asins": [], "action": "CLARIFY",
         "cs_gold_verdicts": [], "cs_req_verdicts": []},
        {"query_id": "q3", "strategy": "hybrid", "candidate_asins": [], "action": "CLARIFY"},
        {"query_id": "q4", "strategy": "hybrid", "candidate_asins": ["D"], "action": "SEARCH"},
    ]


class TestDenominators:
    """AC-014."""

    def test_search_only_and_all_queries_rule(self):
        out = evaluate_retrieval_batch(_preds(), _gt(), k_values=(1, 5))
        rows = {r["query_id"]: r for r in out["per_query_results"]}
        assert rows["q2"]["strict_hit@1"] == 0 and rows["q2"]["scored_as"] == "retrieval"
        assert rows["q3"]["scored_as"] == "clarify_gold"
        assert rows["q3"]["hit@1"] == 1 and rows["q3"]["strict_ndcg@5"] == 1.0 and rows["q3"]["mrr"] == 1.0
        # SEARCH on a gold-CLARIFY query is wrong even if the target was retrieved
        assert rows["q4"]["hit@1"] == 0 and rows["q4"]["mrr"] == 0.0

        block = out["aggregates_by_strategy"]["hybrid"]
        assert block["n_all"] == 4 and block["query_count"] == 4
        assert block["n_search"] == 2
        assert block["search_only"]["n"] == 2
        assert block["mean_strict_hr@1"] == pytest.approx((1 + 0 + 1 + 0) / 4)
        assert block["search_only"]["mean_strict_hr@1"] == pytest.approx((1 + 0) / 2)

    def test_rows_without_action_count_as_search(self):
        out = evaluate_retrieval_batch(
            [{"query_id": "q1", "strategy": "hybrid", "candidate_asins": ["A"]}],
            [{"query_id": "q1", "target_asin": "A"}], k_values=(1,))
        assert out["per_query_results"][0]["action"] == "SEARCH"
        assert out["aggregates_by_strategy"]["hybrid"]["n_search"] == 1

    def test_share_metric_counts(self):
        out = evaluate_retrieval_batch(_preds(), _gt(), k_values=(1, 5), popular_asins={"A"}, type_match={"q1": {"A"}})
        block = out["aggregates_by_strategy"]["hybrid"]
        # q1 and q4 retrieved something; q2, q3 are None
        assert block["n_popularity_bias@5"] == 2
        assert block["mean_popularity_bias@5"] == pytest.approx((0.5 + 0.0) / 2)
        assert block["n_type_precision@1"] == 2


class TestConstraintSatisfactionAggregation:
    def test_cs_keys_and_means(self):
        out = evaluate_retrieval_batch(_preds(), _gt(), k_values=(1, 5))
        q1 = next(r for r in out["per_query_results"] if r["query_id"] == "q1")
        assert q1["cs_sat@1"] == pytest.approx(0.5) and q1["cs_viol@1"] == pytest.approx(0.5)
        assert q1["cs_known@5"] == pytest.approx(0.5)
        assert q1["violation_free@5"] == pytest.approx(0.5)
        assert q1["cs_coverage@5"] == pytest.approx(0.5)
        assert q1["cs_req_sat@5"] == pytest.approx(1.0)
        assert q1["cs_req_violation_free@5"] == pytest.approx(1.0)
        q2 = next(r for r in out["per_query_results"] if r["query_id"] == "q2")
        assert q2["cs_sat@5"] is None
        q3 = next(r for r in out["per_query_results"] if r["query_id"] == "q3")
        assert "cs_sat@5" not in q3

        block = out["aggregates_by_strategy"]["hybrid"]
        assert block["n_cs_sat@5"] == 1
        assert block["mean_cs_known@5"] == pytest.approx(0.5)
        assert block["mean_cs_req_coverage@5"] == pytest.approx(1.0)


class TestReviewCoverage:
    """AC-016."""

    def test_label_and_key(self):
        assert METRIC_LABELS["popularity_bias"] == (
            "review-coverage-bias@K: share of top-K from products with >= 1 embedded review (not popularity)"
        )
        out = evaluate_retrieval_batch(_preds(), _gt(), k_values=(5,), popular_asins={"A"})
        assert "popularity_bias@5" in out["per_query_results"][0]

    def test_target_review_embedded_slices(self):
        gt = [{"query_id": f"q{i}", "target_asin": t} for i, t in enumerate(["A", "B", "C"])]
        preds = [
            {"query_id": "q0", "strategy": "hybrid", "candidate_asins": ["A"]},
            {"query_id": "q1", "strategy": "hybrid", "candidate_asins": ["X"]},
            {"query_id": "q2", "strategy": "hybrid", "candidate_asins": ["C"]},
        ]
        out = evaluate_retrieval_batch(preds, gt, k_values=(5, 10, 20), popular_asins={"A", "B"})
        rows = out["per_query_results"]
        assert [r["target_review_embedded"] for r in rows] == [True, True, False]
        slices = out["aggregates_by_strategy"]["hybrid"]["by_target_review_embedded"]
        assert slices["true"]["n"] == 2 and slices["true"]["mean_strict_hr@5"] == pytest.approx(0.5)
        assert slices["false"]["n"] == 1 and slices["false"]["mean_strict_hr@20"] == pytest.approx(1.0)
        assert slices["false"]["mean_strict_ndcg@10"] == pytest.approx(1.0)
        assert set(slices["true"]) == {"n", "mean_strict_hr@5", "mean_strict_hr@20", "mean_mrr", "mean_strict_ndcg@10"}

    def test_slices_absent_without_popular_set(self):
        out = evaluate_retrieval_batch(_preds(), _gt(), k_values=(5,))
        assert out["per_query_results"][0]["target_review_embedded"] is None
        assert "by_target_review_embedded" not in out["aggregates_by_strategy"]["hybrid"]
