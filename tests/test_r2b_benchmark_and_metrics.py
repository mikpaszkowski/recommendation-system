"""
Unit and verification tests for Release R2b:
- RS-21 Stratified Benchmark v2 (`benchmark_v2.json`, split assignment, leakage & TF-IDF gates)
- G-9 Query-time review masking (`mask_review_asins` in `GraphSearchTool` & `AgentOrchestrator`)
- C-8..C-11 Redefined bias metrics (`review_cap_bias@k`, `head_popularity_bias@k`, `by_stratum`)
- AC-R2B-05 Test-split guard (`--split test` requires `--confirm-test`) and audit logging
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from scripts.evaluate_retrieval import run_retrieval_evaluation
from src.agents.orchestrator import AgentOrchestrator
from src.evaluation.benchmark_v2 import (
    BENCHMARK_V2_SALT,
    assign_split,
    build_ambiguous_benchmark_items,
    check_query_leakage,
    compute_tfidf_target_rank,
    extract_model_codes,
    filter_benchmark_by_split,
    log_test_split_access,
)
from src.evaluation.constraint_satisfaction import validate_gold_annotations
from src.evaluation.metrics import (
    METRIC_LABELS,
    compute_head_popularity_bias_at_k,
    compute_review_cap_bias_at_k,
    evaluate_retrieval_batch,
)
from src.tools.graph_search_tool import GraphSearchTool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_V2_PATH = PROJECT_ROOT / "evaluations" / "benchmarks" / "benchmark_v2.json"
BENCHMARK_V2_MANIFEST_PATH = PROJECT_ROOT / "evaluations" / "benchmarks" / "benchmark_v2_manifest.json"
R2B_TUNING_REPORT_PATH = PROJECT_ROOT / "evaluations" / "benchmarks" / "r2b_tuning_report.json"


class TestSplitAndLeakageGates:
    def test_assign_split_is_deterministic_and_balanced(self):
        keys = [f"B00TEST{i:04d}" for i in range(500)]
        first = [assign_split(k, salt=BENCHMARK_V2_SALT) for k in keys]
        second = [assign_split(k, salt=BENCHMARK_V2_SALT) for k in keys]
        assert first == second
        test_share = sum(1 for s in first if s == "test") / len(first)
        # Expected ~0.60 within binomial sampling tolerance
        assert 0.50 <= test_share <= 0.70

    def test_extract_model_codes_distinguishes_skus_from_units(self):
        title = "Sony WH-1000XM5 Wireless 1080p 5GHz 64GB USB-C Headphones B09XS7JWHH"
        codes = extract_model_codes(title, brand="Sony")
        assert "wh-1000xm5" in codes or "1000xm5" in codes
        assert "b09xs7jwhh" in codes
        for generic in ("1080p", "5ghz", "64gb", "usb-c", "usbc"):
            assert generic not in codes

    def test_check_query_leakage_catches_model_brand_and_trivial_tfidf(self):
        pool = {
            "ASIN1": "Anker Soundcore Q30 Active Noise Cancelling Bluetooth Headphones",
            "ASIN2": "JBL Tune 760NC Over-Ear Wireless Headphones Black",
            "ASIN3": "Sony WH-CH720N Noise Canceling Wireless Headphones",
        }
        # 1. Model code leak ("q30") + unflagged brand leak ("anker")
        bad = check_query_leakage(
            utterance="I want the Anker Q30 headphones under $90",
            target_asin="ASIN1",
            target_title=pool["ASIN1"],
            target_brand="Anker",
            product_type="Headphones",
            pool_titles=pool,
            brand_anchored=False,
        )
        assert bad["model_code_leak"] is True
        assert bad["unflagged_brand_leak"] is True
        assert bad["passed"] is False

        # 2. Clean paraphrased utterance where ASIN1 is NOT TF-IDF rank 1
        clean = check_query_leakage(
            utterance="Looking for over-ear headphones in black for travel under $100",
            target_asin="ASIN1",
            target_title=pool["ASIN1"],
            target_brand="Anker",
            product_type="Headphones",
            pool_titles=pool,
            brand_anchored=False,
        )
        assert clean["model_code_leak"] is False
        assert clean["unflagged_brand_leak"] is False
        assert clean["title_token_overlap"] <= 0.30
        assert clean["tfidf_target_rank"] > 1
        assert clean["passed"] is True

    def test_filter_benchmark_by_split_and_access_log(self, tmp_path: Path):
        items = [
            {"query_id": "q1", "split": "tuning", "stratum": "S0"},
            {"query_id": "q2", "split": "test", "stratum": "S1"},
            {"query_id": "q3", "split": "tuning", "stratum": "legacy"},
        ]
        assert [i["query_id"] for i in filter_benchmark_by_split(items, "tuning")] == ["q1", "q3"]
        assert [i["query_id"] for i in filter_benchmark_by_split(items, "test")] == ["q2"]
        assert [i["query_id"] for i in filter_benchmark_by_split(items, "legacy")] == ["q3"]
        assert len(filter_benchmark_by_split(items, "all")) == 3

        log_file = tmp_path / "test_split_access_log.jsonl"
        log_test_split_access(log_file, Path("benchmark_v2.json"), "test", 120, ["hybrid"], "abc1234")
        lines = log_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["split"] == "test"
        assert payload["query_count"] == 120
        assert payload["git_commit"] == "abc1234"


class TestQueryTimeReviewMasking:
    def test_graph_search_tool_masks_target_reviews_in_channel_and_attributes(self):
        connector = MagicMock()
        session_cm = MagicMock()
        session = MagicMock()
        session_cm.__enter__.return_value = session
        connector.session.return_value = session_cm

        embedding = MagicMock()
        embedding.generate_embedding.return_value = [0.1] * 384
        resolver = MagicMock()

        recorded_calls: List[tuple[str, Dict[str, Any]]] = []

        def fake_run(query: str, params: Dict[str, Any] | None = None, **kwargs: Any):
            merged_params = dict(params or {})
            merged_params.update(kwargs)
            recorded_calls.append((query, merged_params))
            if "product_embedding_index" in query:
                return [{"asin": "B00COLD1", "similarity": 0.88, "reason": "Product Title Match"}, {"asin": "B00OTHER", "similarity": 0.82, "reason": "Product Title Match"}]
            if "attribute_embedding_index" in query:
                return [{"asin": "B00COLD1", "similarity": 0.85, "reason": "Attr Match"}]
            if "review_embedding_index" in query:
                masked = set(merged_params.get("mask_review_asins") or [])
                rows = [
                    {"asin": "B00COLD1", "similarity": 0.95, "reason": "Review Match"},
                    {"asin": "B00OTHER", "similarity": 0.79, "reason": "Review Match"},
                ]
                return [r for r in rows if r["asin"] not in masked]
            if "RETURN node.parent_asin AS asin" in query:
                return [
                    {
                        "asin": "B00COLD1",
                        "title": "Cold Start Product",
                        "brand": "Acme",
                        "price": 49.99,
                        "avg_rating": 4.5,
                        "category": ["Electronics"],
                        "features": ["f1"],
                        "details_text": "d1",
                        "description": "desc",
                        "id": "1",
                    },
                    {
                        "asin": "B00OTHER",
                        "title": "Other Product",
                        "brand": "Beta",
                        "price": 59.99,
                        "avg_rating": 4.2,
                        "category": ["Electronics"],
                        "features": ["f2"],
                        "details_text": "d2",
                        "description": "desc2",
                        "id": "2",
                    },
                ]
            if "AS source" in query and "user_review" in query:
                asins_arg = set(merged_params.get("asins") or [])
                rows = [
                    {"asin": "B00COLD1", "name": "Great", "value": "Loved it", "source": "user_review"},
                    {"asin": "B00OTHER", "name": "Solid", "value": "Works well", "source": "user_review"},
                ]
                return [r for r in rows if r["asin"] in asins_arg]
            return []

        session.run.side_effect = fake_run
        tool = GraphSearchTool(connector, embedding, resolver)

        res = tool.search(
            semantic_query="dependable device",
            structured_filters={"price_max": 100.0},
            limit=5,
            mask_review_asins=["B00COLD1"],
        )
        channel_hits = res["metadata"]["channel_hits"]
        review_hit_asins = [h["asin"] for h in channel_hits["review"]]
        assert "B00COLD1" not in review_hit_asins
        assert "B00OTHER" in review_hit_asins

        # Verify review channel query had NOT node.parent_asin IN $mask_review_asins (including MACS passes)
        review_calls = [(q, p) for q, p in recorded_calls if "review_embedding_index" in q]
        assert len(review_calls) >= 1
        assert all("NOT node.parent_asin IN $mask_review_asins" in q for q, _ in review_calls)
        assert all(p["mask_review_asins"] == ["B00COLD1"] for _, p in review_calls)

        # Verify fetch_product_attributes also masks B00COLD1 reviews
        attr_map = tool.fetch_product_attributes(["B00COLD1", "B00OTHER"], mask_review_asins=["B00COLD1"])
        assert all(a["source"] != "user_review" for a in attr_map["B00COLD1"])
        assert any(a["source"] == "user_review" for a in attr_map["B00OTHER"])


class TestRedefinedBiasMetricsAndTestSplitGuard:
    def test_bias_metrics_and_stratum_slices(self):
        # Backward compatibility check for R2a test contract
        assert METRIC_LABELS["popularity_bias"] == (
            "review-coverage-bias@K: share of top-K from products with >= 1 embedded review (not popularity)"
        )
        assert "review_cap_bias" in METRIC_LABELS
        assert "head_popularity_bias" in METRIC_LABELS

        assert compute_review_cap_bias_at_k(["A", "B", "C", "D"], {"A", "C"}, 4) == pytest.approx(0.5)
        assert compute_head_popularity_bias_at_k(["A", "B", "C", "D"], {"A"}, 4) == pytest.approx(0.25)
        assert compute_review_cap_bias_at_k([], {"A"}, 5) is None

        gt = [
            {"query_id": "q_s0", "target_asin": "A", "stratum": "S0", "split": "tuning"},
            {"query_id": "q_s1", "target_asin": "B", "stratum": "S1", "split": "tuning"},
        ]
        preds = [
            {"query_id": "q_s0", "strategy": "hybrid", "candidate_asins": ["A", "C"]},
            {"query_id": "q_s1", "strategy": "hybrid", "candidate_asins": ["B", "D"]},
        ]
        out = evaluate_retrieval_batch(
            preds,
            gt,
            k_values=(5, 10, 20),
            popular_asins={"A", "B", "C"},
            review_cap_asins={"A", "C"},
            head_popular_asins={"A"},
        )
        strat_agg = out["aggregates_by_strategy"]["hybrid"]
        assert strat_agg["mean_review_cap_bias@5"] == pytest.approx(0.5)
        assert strat_agg["mean_head_popularity_bias@5"] == pytest.approx(0.25)
        assert "S0" in strat_agg["by_stratum"]
        assert "S1" in strat_agg["by_stratum"]
        assert strat_agg["by_target_review_cap"]["true"]["n"] == 1
        assert strat_agg["by_target_review_cap"]["false"]["n"] == 1

    def test_test_split_guard_blocks_unconfirmed_execution(self, tmp_path: Path):
        bench_file = tmp_path / "dummy_bench.json"
        bench_file.write_text(
            json.dumps([{"query_id": "q1", "utterance": "test", "target_asin": "A", "split": "test"}]),
            encoding="utf-8",
        )
        code = run_retrieval_evaluation(
            benchmark_path=bench_file,
            k_values=[5],
            strategies=["hybrid"],
            mode="mock",
            output_dir=str(tmp_path / "out"),
            split="test",
            confirm_test=False,
        )
        assert code == 2


@pytest.mark.skipif(not BENCHMARK_V2_PATH.exists(), reason="benchmark_v2.json not yet built")
class TestFrozenBenchmarkV2Artifact:
    def test_benchmark_v2_satisfies_all_r2b_acceptance_criteria(self):
        items = json.loads(BENCHMARK_V2_PATH.read_text(encoding="utf-8"))
        manifest = json.loads(BENCHMARK_V2_MANIFEST_PATH.read_text(encoding="utf-8"))

        # AC-R2B-01: 251 queries (40x5 S0..S4 + 30 A + 21 legacy)
        assert len(items) == 251
        assert manifest["total_queries"] == 251

        by_stratum: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            by_stratum.setdefault(item["stratum"], []).append(item)

        for st in ("S0", "S1", "S2", "S3", "S4"):
            assert len(by_stratum[st]) == 40, f"Stratum {st} count != 40"
        assert len(by_stratum["A"]) == 30
        assert len(by_stratum["legacy"]) == 21

        # Zero duplicate target_asins across all 221 retrieval queries
        retrieval_items = [i for i in items if i["stratum"] != "A"]
        target_asins = [i["target_asin"] for i in retrieval_items]
        assert len(target_asins) == 221
        assert len(set(target_asins)) == 221

        # >= 15 distinct categories/leaves across S0..S4
        s0_s4 = [i for i in items if i["stratum"] in ("S0", "S1", "S2", "S3", "S4")]
        leaves = {i.get("taxon_leaf") or i.get("category") for i in s0_s4}
        assert len(leaves) >= 15

        # AC-R2B-02: Leakage & lexical triviality gates on 100% of S0..S4
        for item in s0_s4:
            leak = item["leakage_audit"]
            assert leak["model_code_leak"] is False, f"Model code leak in {item['query_id']}"
            assert leak["unflagged_brand_leak"] is False, f"Brand leak in {item['query_id']}"
            assert leak["title_token_overlap"] <= 0.30, f"Overlap > 0.30 in {item['query_id']}"
            assert leak["tfidf_target_rank"] > 1, f"TF-IDF rank 1 in {item['query_id']}"

        # Stratum S1 review masking enabled on 100% of S1
        assert all(i["mask_target_reviews"] is True for i in by_stratum["S1"])
        # Stratum S3 accessory trap ratio > 0.50 on 100% of S3
        assert all(float(i["trap_out_of_taxon_ratio"]) > 0.50 for i in by_stratum["S3"])
        # Stratum A all CLARIFY gold
        assert all(i["gold_action"] == "CLARIFY" and i["type_explicit"] is False for i in by_stratum["A"])

        # Gold annotation schema validation passes with 0 errors
        assert validate_gold_annotations(items) == []

    @pytest.mark.skipif(not R2B_TUNING_REPORT_PATH.exists(), reason="r2b_tuning_report.json not yet built")
    def test_r2b_tuning_report_contract(self):
        report = json.loads(R2B_TUNING_REPORT_PATH.read_text(encoding="utf-8"))
        assert report["release"] == "R2b"
        assert report["split_evaluated"] == "tuning"
        assert report["test_split_touched"] is False
        assert report["query_counts"]["total_tuning"] == 115
        assert report["query_counts"]["retrieval_tuning"] == 105
        assert "rrf3" in report["pre_registered_arms"]
        assert "rrf2" in report["pre_registered_arms"]
        assert "wrrf3" in report["pre_registered_arms"]
        assert "rs02_review_channel_attribution" in report
        assert "rs25_weighted_rrf_tuning" in report
        assert report["rs25_weighted_rrf_tuning"]["grid_size"] == 192
