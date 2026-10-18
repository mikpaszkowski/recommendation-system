"""
tests/test_dialogue_metrics.py

Dialogue metrics for RS-23 (Technical Specification AC-012, AC-013, AC-015).
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from src.evaluation.dialogue_metrics import (
    annotate_target_admission,
    build_query_record,
    category_from_hard_constraints,
    compute_dialogue_metrics,
    format_share,
    search_intersection,
)
from src.evaluation.metrics import aggregate_rows, evaluate_retrieval_batch


def _rec(qid: str, action: str = "SEARCH", **kw: Any) -> Dict[str, Any]:
    base = {"query_id": qid, "action": action, "type_explicit": True, "gold_action": "SEARCH",
            "parser_category": "x", "pipeline_category": "x", "clarify_reason": None,
            "category_source": "parser", "recovery_attempted": False, "applied_category": None,
            "target_admitted": None, "category_dropped_by_macs": False}
    base.update(kw)
    return base


class TestShares:
    """AC-012."""

    def test_cer_spurious_clarify_and_clarification(self):
        records = [
            _rec("q1"),
            _rec("q2", parser_category=None, pipeline_category="wall charger", category_source="search_params", recovery_attempted=True),
            _rec("q3", action="CLARIFY", parser_category=None, pipeline_category=None, clarify_reason="recovery_failed",
                 category_source=None, recovery_attempted=True),
            _rec("q4", action="CLARIFY", parser_category=None, pipeline_category=None, clarify_reason="router", category_source=None),
            _rec("q5", action="ANSWER", parser_category=None, pipeline_category=None, category_source=None),
            _rec("a1", action="CLARIFY", type_explicit=False, gold_action="CLARIFY", parser_category=None,
                 pipeline_category=None, clarify_reason="router", category_source=None),
            _rec("a2", action="SEARCH", type_explicit=False, gold_action="CLARIFY", parser_category=None,
                 pipeline_category="gadget", category_source="search_params", recovery_attempted=True),
            {"query_id": "unannotated", "action": "CLARIFY"},
        ]
        m = compute_dialogue_metrics(records)
        assert m["n_queries"] == 8
        assert m["cer_parser"] == {"value": pytest.approx(1 / 5), "numerator": 1, "n": 5}
        assert m["cer_pipeline"] == {"value": pytest.approx(2 / 5), "numerator": 2, "n": 5}
        assert m["spurious_clarify"]["numerator"] == 2 and m["spurious_clarify"]["n"] == 5
        assert m["spurious_clarify"]["query_ids"] == ["q3", "q4"]
        assert m["spurious_clarify"]["by_reason"] == {"recovery_failed": 1, "router": 1}
        assert m["type_explicit_non_search"] == {"numerator": 1, "n": 5, "query_ids": ["q5"]}
        assert m["clarification_recall"] == {"value": pytest.approx(0.5), "numerator": 1, "n": 2}
        # CLARIFY actions among annotated records: q3, q4, a1 -> one is gold CLARIFY
        assert m["clarification_precision"] == {"value": pytest.approx(1 / 3), "numerator": 1, "n": 3}
        assert m["category_source_counts"] == {"parser": 1, "search_params": 2}
        assert m["recovery_calls"] == 3

    def test_zero_denominators_are_none(self):
        m = compute_dialogue_metrics([_rec("q1")])
        assert m["clarification_recall"] == {"value": None, "numerator": 0, "n": 0}
        assert m["clarification_precision"]["value"] is None
        assert m["target_admitting_category"]["value"] is None
        assert format_share(m["clarification_recall"]) == "n/a (n=0)"
        assert format_share(m["cer_parser"]) == "1.000 (1/1)"
        assert compute_dialogue_metrics([])["spurious_clarify"] == {
            "value": None, "numerator": 0, "n": 0, "query_ids": [], "by_reason": {}}


class TestTargetAdmission:
    """AC-013 (evaluation side)."""

    def test_match_category_called_with_normalized_and_raw(self):
        tool = MagicMock()
        tool.match_category.return_value = {"T"}
        record = _rec("q1", target_asin="T", applied_category={"normalized": "Chargers", "raw": "wall charger"})
        assert annotate_target_admission(record, tool) is True
        tool.match_category.assert_called_once_with(["T"], "Chargers", raw_category="wall charger")

    def test_rate_excludes_queries_without_category_and_counts_macs_drops(self):
        tool = MagicMock()
        tool.match_category.side_effect = lambda asins, cat, raw_category=None: set() if raw_category == "mouse" else set(asins)
        records = [
            _rec("q1", target_asin="T1", applied_category={"normalized": "Mice", "raw": "mouse"}, category_dropped_by_macs=True),
            _rec("q2", target_asin="T2", applied_category={"normalized": "Webcams", "raw": "webcam"}),
            _rec("q3", target_asin="T3", applied_category=None),
            _rec("q4", action="CLARIFY", target_asin="T4", applied_category={"normalized": "x", "raw": "x"}),
        ]
        for r in records:
            annotate_target_admission(r, tool)
        assert records[2]["target_admitted"] is None and records[3]["target_admitted"] is None
        block = compute_dialogue_metrics(records)["target_admitting_category"]
        assert block == {"value": pytest.approx(0.5), "numerator": 1, "n": 2, "category_dropped_by_macs": 1}
        assert tool.match_category.call_count == 2


class TestBuildQueryRecord:
    def _result(self, **trace: Any) -> Dict[str, Any]:
        eval_trace = {
            "clarify_reason": None,
            "category_resolution": {"parser_category": None, "category": "wall charger", "source": "search_params",
                                    "guardrail_triggered": True, "recovery_attempted": True, "recovery_outcome": "found"},
            "search_request": {"structured_filters": {"category": "wall charger", "price_max": 60}},
            "search_metadata": {"normalized_filters": {"category": "Chargers", "price_max": 60.0}},
            "relaxed_constraints": ["Widened budget ceiling by 15%", "Dropped explicit category constraint (relying purely on vector search)"],
            "raw_candidates": [{"asin": "X"}, {"asin": "T", "fusion": {"channels": {"product": {"rank": 3}}}}],
        }
        eval_trace.update(trace)
        return {"action": "SEARCH", "eval_trace": eval_trace,
                "session_context": {"extracted_parameters": {"hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 60}]}}}

    def test_recovered_search(self):
        item = {"query_id": "q", "target_asin": "T", "type_explicit": True, "gold_action": "SEARCH", "gold_product_type": "wall charger"}
        r = build_query_record(item, self._result(), 812.5)
        assert r["parser_category"] is None
        assert r["pipeline_category"] == "wall charger" and r["category_source"] == "search_params"
        assert r["recovery_outcome"] == "found" and r["recovery_attempted"] is True
        assert r["applied_category"] == {"normalized": "Chargers", "raw": "wall charger"}
        assert r["category_dropped_by_macs"] is True
        assert r["target_channel_ranks"] == {"product": 3, "attribute": None, "review": None}
        assert r["latency_ms"] == 812.5 and r["legacy_reconstructed"] is False

    def test_search_request_fallback_and_missing_target(self):
        item = {"query_id": "q", "target_asin": "MISSING"}
        res = self._result(category_resolution={"category": None, "source": None})
        r = build_query_record(item, res, 1.0)
        assert r["pipeline_category"] == "wall charger" and r["category_source"] == "search_request"
        assert r["target_channel_ranks"] is None
        assert r["type_explicit"] is None

    def test_clarify_and_empty_result(self):
        r = build_query_record({"query_id": "q"}, {"action": "CLARIFY", "eval_trace": {"clarify_reason": "router"}}, 0.0)
        assert r["action"] == "CLARIFY" and r["clarify_reason"] == "router" and r["applied_category"] is None
        assert build_query_record({"query_id": "q"}, None, 0.0)["action"] == "UNKNOWN"

    def test_category_from_hard_constraints(self):
        assert category_from_hard_constraints([{"attribute": "price", "value": 5},
                                               {"attribute": "category", "operator": "include", "value": "mouse"}]) == "mouse"
        assert category_from_hard_constraints([{"attribute": "category", "operator": "exclude", "value": "x"}]) is None
        assert category_from_hard_constraints(None) is None


class TestIntersection:
    """AC-015."""

    def test_search_intersection_and_aggregate(self):
        run1 = [{"query_id": "a", "action": "SEARCH"}, {"query_id": "b", "action": "CLARIFY"}, {"query_id": "c"}]
        run2 = [{"query_id": "a", "action": "SEARCH"}, {"query_id": "b", "action": "SEARCH"}, {"query_id": "c", "action": "SEARCH"}]
        common = search_intersection({"r1": run1, "r2": run2})
        assert common == {"a", "c"}
        assert search_intersection({}) == set()

        gt = [{"query_id": q, "target_asin": "T"} for q in "abc"]
        preds = [
            {"query_id": "a", "strategy": "hybrid", "candidate_asins": ["X", "T"], "action": "SEARCH"},
            {"query_id": "b", "strategy": "hybrid", "candidate_asins": [], "action": "CLARIFY"},
            {"query_id": "c", "strategy": "hybrid", "candidate_asins": ["T"], "action": "SEARCH"},
        ]
        rows = evaluate_retrieval_batch(preds, gt, k_values=(1, 5))["per_query_results"]
        subset = aggregate_rows([r for r in rows if r["query_id"] in common], (1, 5))
        assert subset["n_all"] == 2 and subset["n_search"] == 2
        assert subset["mean_strict_hr@1"] == pytest.approx(0.5)
        assert subset["mean_strict_hr@5"] == pytest.approx(1.0)
        assert subset["mean_mrr"] == pytest.approx((0.5 + 1.0) / 2)
