#!/usr/bin/env python3
"""
Release R2b Fusion Tuning & Review-Channel Attribution Protocol (RS-02 & RS-25).

Evaluates ONLY the `tuning` split of `evaluations/benchmarks/benchmark_v2.json` (never touches `test`):
1. Executes live 3-channel vector + graph retrieval (`GraphSearchTool.search`) on all tuning
   retrieval queries (honoring `mask_review_asins` on Stratum S1 cold-start queries).
2. Captures raw per-channel hits (`product`, `attribute`, `review`) per query.
3. RS-02 Attribution: Compares `rrf2` (w_rev=0) vs `rrf3` (w_rev=1) with paired bootstrap
   95% CIs on HR@20, HR@5, NDCG@10, MRR, plus unique review-channel target rescues and
   RevCapBias@5 / HeadPopBias@5 shift.
4. RS-25 Grid Search: Sweeps (w_prod, w_attr, w_rev) and RRF k in {20, 40, 60, 100} on the
   tuning split, reporting overall and per-stratum (S0..S4, legacy) metrics and applying the
   pre-registered decision rule before any `test`-split run.
"""
from __future__ import annotations

import argparse
import datetime
import itertools
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.benchmark_v2 import filter_benchmark_by_split
from src.evaluation.metrics import (
    compute_head_popularity_bias_at_k,
    compute_hit_rate_at_k,
    compute_mrr_at_k,
    compute_ndcg_at_k,
    compute_popularity_bias_at_k,
    compute_review_cap_bias_at_k,
)
from src.evaluation.stats import paired_bootstrap_ci, paired_randomization_test
from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
from src.knowledge_graph.graphdb.resolver_service import ResolverService
from src.tools.graph_search_tool import GraphSearchTool
from src.tools.score_fusion import CHANNELS, FUSION_ARMS, ChannelHit, FusionConfig, fuse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tune_fusion_r2b")


def score_fused_candidates(
    candidate_asins: Sequence[str],
    target_asin: str,
    popular_asins: set[str],
    review_cap_asins: set[str],
    head_popular_asins: set[str],
) -> Dict[str, Any]:
    targets = [target_asin] if target_asin else []
    return {
        "strict_hit@1": int(compute_hit_rate_at_k(candidate_asins, targets, 1)),
        "strict_hit@5": int(compute_hit_rate_at_k(candidate_asins, targets, 5)),
        "strict_hit@10": int(compute_hit_rate_at_k(candidate_asins, targets, 10)),
        "strict_hit@20": int(compute_hit_rate_at_k(candidate_asins, targets, 20)),
        "strict_ndcg@5": float(compute_ndcg_at_k(candidate_asins, targets, 5)),
        "strict_ndcg@10": float(compute_ndcg_at_k(candidate_asins, targets, 10)),
        "strict_ndcg@20": float(compute_ndcg_at_k(candidate_asins, targets, 20)),
        "mrr": float(compute_mrr_at_k(candidate_asins, targets, 20)),
        "popularity_bias@5": compute_popularity_bias_at_k(candidate_asins, popular_asins, 5),
        "review_cap_bias@5": compute_review_cap_bias_at_k(candidate_asins, review_cap_asins, 5),
        "head_popularity_bias@5": compute_head_popularity_bias_at_k(candidate_asins, head_popular_asins, 5),
    }


def summarize_query_scores(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"n": 0}
    out: Dict[str, Any] = {"n": len(rows)}
    for m in (
        "strict_hit@1",
        "strict_hit@5",
        "strict_hit@10",
        "strict_hit@20",
        "strict_ndcg@5",
        "strict_ndcg@10",
        "strict_ndcg@20",
        "mrr",
    ):
        out[f"mean_{m}"] = round(float(np.mean([r[m] for r in rows])), 4)
    for b in ("popularity_bias@5", "review_cap_bias@5", "head_popularity_bias@5"):
        vals = [r[b] for r in rows if r.get(b) is not None]
        out[f"mean_{b}"] = round(float(np.mean(vals)), 4) if vals else None
    return out


def evaluate_config_on_cache(
    config: FusionConfig,
    cached_queries: Sequence[Dict[str, Any]],
    popular_asins: set[str],
    review_cap_asins: set[str],
    head_popular_asins: set[str],
    top_k: int = 20,
) -> Dict[str, Any]:
    per_query: List[Dict[str, Any]] = []
    for q in cached_queries:
        channel_hits: Dict[str, List[ChannelHit]] = q["channel_hits"]
        fused = fuse(channel_hits, config)[:top_k]
        asins = [fc.asin for fc in fused]
        scores = score_fused_candidates(
            asins,
            target_asin=q["target_asin"],
            popular_asins=popular_asins,
            review_cap_asins=review_cap_asins,
            head_popular_asins=head_popular_asins,
        )
        scores["query_id"] = q["query_id"]
        scores["stratum"] = q["stratum"]
        scores["candidate_asins"] = asins
        per_query.append(scores)

    overall = summarize_query_scores(per_query)
    s0_s4_rows = [r for r in per_query if r["stratum"] in ("S0", "S1", "S2", "S3", "S4")]
    by_stratum: Dict[str, Any] = {}
    for st in ("S0", "S1", "S2", "S3", "S4", "legacy"):
        st_rows = [r for r in per_query if r["stratum"] == st]
        if st_rows:
            by_stratum[st] = summarize_query_scores(st_rows)

    return {
        "config": config.to_dict(),
        "overall_tuning": overall,
        "s0_s4_tuning": summarize_query_scores(s0_s4_rows),
        "by_stratum": by_stratum,
        "per_query": per_query,
    }


def compare_two_runs(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    metric: str,
    seed: int = 42,
) -> Dict[str, Any]:
    by_q_a = {r["query_id"]: float(r[metric]) for r in rows_a if r.get(metric) is not None}
    by_q_b = {r["query_id"]: float(r[metric]) for r in rows_b if r.get(metric) is not None}
    shared = sorted(set(by_q_a) & set(by_q_b))
    a_vals = [by_q_a[qid] for qid in shared]
    b_vals = [by_q_b[qid] for qid in shared]
    boot = paired_bootstrap_ci(a_vals, b_vals, n_resamples=5000, seed=seed)
    rand = paired_randomization_test(a_vals, b_vals, n_resamples=5000, seed=seed)
    return {
        "metric": metric,
        "n": len(shared),
        "mean_a": round(float(np.mean(a_vals)), 4) if a_vals else 0.0,
        "mean_b": round(float(np.mean(b_vals)), 4) if b_vals else 0.0,
        "mean_diff_a_minus_b": round(float(boot.mean_diff), 4),
        "ci95_low": round(float(boot.low), 4),
        "ci95_high": round(float(boot.high), 4),
        "p_value": round(float(rand.p_value), 4),
        "ci_excludes_zero": bool(boot.low > 0.0 or boot.high < 0.0),
    }


def run_tuning(benchmark_path: Path, output_path: Path) -> Dict[str, Any]:
    with open(benchmark_path, "r", encoding="utf-8") as f:
        full_benchmark = json.load(f)

    tuning_items = filter_benchmark_by_split(full_benchmark, "tuning")
    retrieval_tuning_items = [
        item for item in tuning_items if item.get("gold_action", "SEARCH") != "CLARIFY" and item.get("target_asin")
    ]
    logger.info(
        "Loaded %d total benchmark items -> %d tuning items (%d retrieval tuning items).",
        len(full_benchmark),
        len(tuning_items),
        len(retrieval_tuning_items),
    )

    connector = Neo4jConnector()
    connector.connect()
    try:
        embedding_service = EmbeddingService()
        resolver = ResolverService(connector, embedding_service)
        graph_tool = GraphSearchTool(connector, embedding_service, resolver)

        # Memoize category/brand normalization across tuning queries to avoid redundant embeddings
        _cat_cache: Dict[str, str] = {}
        _orig_norm_cat = graph_tool._normalize_single_category
        def _cached_norm_cat(raw_val: str) -> str:
            if raw_val not in _cat_cache:
                _cat_cache[raw_val] = _orig_norm_cat(raw_val)
            return _cat_cache[raw_val]
        graph_tool._normalize_single_category = _cached_norm_cat  # type: ignore[method-assign]

        _brand_cache: Dict[str, str] = {}
        _orig_norm_brand = graph_tool._normalize_single_brand
        def _cached_norm_brand(raw_val: str, key_label: str = "brand") -> str:
            if raw_val not in _brand_cache:
                _brand_cache[raw_val] = _orig_norm_brand(raw_val, key_label)
            return _brand_cache[raw_val]
        graph_tool._normalize_single_brand = _cached_norm_brand  # type: ignore[method-assign]

        popular_asins = graph_tool.fetch_review_embedded_asins()
        review_cap_asins = graph_tool.fetch_review_cap_asins(20)
        head_popular_asins, head_threshold = graph_tool.fetch_head_popular_asins(0.90)

        cached_queries: List[Dict[str, Any]] = []
        t0 = time.perf_counter()
        for idx, item in enumerate(retrieval_tuning_items, start=1):
            qid = str(item.get("query_id") or item.get("id"))
            target_asin = str(item["target_asin"])
            stratum = str(item.get("stratum") or "legacy")
            mask_asins = [target_asin] if item.get("mask_target_reviews") else None

            res = graph_tool.search(
                semantic_query=item["utterance"],
                structured_filters=dict(item.get("structured_filters") or {}),
                soft_preferences=list(item.get("soft_preferences") or []),
                limit=20,
                mask_review_asins=mask_asins,
            )
            raw_channel_hits = (res.get("metadata") or {}).get("channel_hits") or {}
            channel_hits: Dict[str, List[ChannelHit]] = {
                ch: [
                    h if isinstance(h, ChannelHit) else ChannelHit(asin=h["asin"], similarity=float(h["similarity"]), reason=h.get("reason", ""))
                    for h in (raw_channel_hits.get(ch) or [])
                ]
                for ch in ("product", "attribute", "review")
            }
            cached_queries.append({
                "query_id": qid,
                "stratum": stratum,
                "target_asin": target_asin,
                "mask_target_reviews": bool(item.get("mask_target_reviews")),
                "channel_hits": channel_hits,
            })
            if idx % 20 == 0 or idx == len(retrieval_tuning_items):
                logger.info("Cached channel hits for %d/%d tuning queries (%.1fs)", idx, len(retrieval_tuning_items), time.perf_counter() - t0)

        # Evaluate pre-registered rank/score FUSION_ARMS supported by fuse() (rrf3, rrf2, wrrf3, cc3)
        arm_evals: Dict[str, Any] = {}
        for arm_name, cfg in FUSION_ARMS.items():
            if cfg.method not in ("rrf", "cc"):
                continue
            arm_evals[arm_name] = evaluate_config_on_cache(
                cfg,
                cached_queries,
                popular_asins=popular_asins,
                review_cap_asins=review_cap_asins,
                head_popular_asins=head_popular_asins,
            )

        # RS-02: Review-channel attribution (rrf3 vs rrf2)
        rrf3_rows = arm_evals["rrf3"]["per_query"]
        rrf2_rows = arm_evals["rrf2"]["per_query"]
        wrrf3_rows = arm_evals["wrrf3"]["per_query"]

        # Count unique review channel rescues (target in review channel hits, missed by product+attribute top-20)
        review_channel_target_hits: List[str] = []
        review_unique_rescues_at_20: List[str] = []
        review_demotions_at_20: List[str] = []
        rrf2_by_q = {r["query_id"]: r for r in rrf2_rows}
        rrf3_by_q = {r["query_id"]: r for r in rrf3_rows}

        for q in cached_queries:
            qid = q["query_id"]
            target = q["target_asin"]
            rev_asins = {h.asin for h in q["channel_hits"].get("review", [])}
            if target in rev_asins:
                review_channel_target_hits.append(qid)
            hit2 = rrf2_by_q[qid]["strict_hit@20"]
            hit3 = rrf3_by_q[qid]["strict_hit@20"]
            if hit3 > hit2:
                review_unique_rescues_at_20.append(qid)
            elif hit2 > hit3:
                review_demotions_at_20.append(qid)

        rs02_comparisons = {
            m: compare_two_runs(rrf3_rows, rrf2_rows, m)
            for m in ("strict_hit@20", "strict_hit@5", "strict_ndcg@10", "mrr", "review_cap_bias@5", "head_popularity_bias@5")
        }

        rs25_wrrf3_vs_rrf3 = {
            m: compare_two_runs(wrrf3_rows, rrf3_rows, m)
            for m in ("strict_hit@20", "strict_hit@5", "strict_ndcg@10", "mrr", "review_cap_bias@5", "head_popularity_bias@5")
        }

        # RS-25 Grid Search over (w_prod, w_attr, w_rev) and RRF k
        grid_results: List[Dict[str, Any]] = []
        w_prod_grid = (0.5, 1.0, 1.5, 2.0)
        w_attr_grid = (0.5, 1.0, 1.5)
        w_rev_grid = (0.0, 0.25, 0.5, 1.0)
        k_grid = (20, 40, 60, 100)

        for w_p, w_a, w_r, rrf_k in itertools.product(w_prod_grid, w_attr_grid, w_rev_grid, k_grid):
            enabled_channels = ("product", "attribute") if w_r == 0.0 else CHANNELS
            cfg = FusionConfig(
                name=f"grid_k{rrf_k}_p{w_p}_a{w_a}_r{w_r}",
                method="rrf",
                channels=enabled_channels,
                weights={"product": w_p, "attribute": w_a, "review": w_r},
                rrf_k=rrf_k,
            )
            ev = evaluate_config_on_cache(
                cfg,
                cached_queries,
                popular_asins=popular_asins,
                review_cap_asins=review_cap_asins,
                head_popular_asins=head_popular_asins,
            )
            grid_results.append({
                "config": cfg.to_dict(),
                "overall_tuning": ev["overall_tuning"],
                "s0_s4_tuning": ev["s0_s4_tuning"],
                "by_stratum": {st: {"n": b["n"], "mean_strict_hit@5": b["mean_strict_hit@5"], "mean_strict_hit@20": b["mean_strict_hit@20"], "mean_mrr": b["mean_mrr"]} for st, b in ev["by_stratum"].items()},
                "_per_query": ev["per_query"],
            })

        # Rank grid configs by overall_tuning MRR, then strict_ndcg@10, then strict_hit@20, then lower review_cap_bias@5
        grid_results.sort(
            key=lambda entry: (
                entry["overall_tuning"]["mean_mrr"],
                entry["overall_tuning"]["mean_strict_ndcg@10"],
                entry["overall_tuning"]["mean_strict_hit@20"],
                -(entry["overall_tuning"].get("mean_review_cap_bias@5") or 0.0),
            ),
            reverse=True,
        )

        best_grid = grid_results[0]
        best_vs_rrf3 = {
            m: compare_two_runs(best_grid["_per_query"], rrf3_rows, m)
            for m in ("strict_hit@20", "strict_hit@5", "strict_ndcg@10", "mrr", "review_cap_bias@5", "head_popularity_bias@5")
        }

        for g in grid_results:
            g.pop("_per_query", None)
        for arm_data in arm_evals.values():
            arm_data.pop("per_query", None)

        # RS-02 & RS-25 Decision Logic (Technical_Specification_R2b.md §3.4)
        hr20_diff = rs02_comparisons["strict_hit@20"]["mean_diff_a_minus_b"]
        hr20_ci_low = rs02_comparisons["strict_hit@20"]["ci95_low"]
        if hr20_diff <= 0 and len(review_unique_rescues_at_20) == 0:
            rs02_verdict = (
                "REVIEW_CHANNEL_INERT_OR_REDUNDANT_FOR_RANKING: rrf3 (w_rev=1) yields non-positive "
                "delta HR@20 vs rrf2 (w_rev=0) with zero unique top-20 rescues on the tuning split; "
                "review nodes remain valuable for post-retrieval synthesis/grounding snippets."
            )
        elif hr20_ci_low > 0:
            rs02_verdict = "REVIEW_CHANNEL_POSITIVE_CONTRIBUTION: rrf3 significantly improves HR@20 over rrf2."
        else:
            rs02_verdict = (
                f"REVIEW_CHANNEL_MARGINAL_CONTRIBUTION: delta HR@20 = {hr20_diff:+.4f} "
                f"(95% CI [{hr20_ci_low:+.4f}, {rs02_comparisons['strict_hit@20']['ci95_high']:+.4f}]), "
                f"unique rescues={len(review_unique_rescues_at_20)}, demotions={len(review_demotions_at_20)}."
            )

        best_mrr_ci_excludes_zero = best_vs_rrf3["mrr"]["ci_excludes_zero"] and best_vs_rrf3["mrr"]["mean_diff_a_minus_b"] > 0
        best_ndcg_ci_excludes_zero = best_vs_rrf3["strict_ndcg@10"]["ci_excludes_zero"] and best_vs_rrf3["strict_ndcg@10"]["mean_diff_a_minus_b"] > 0
        promote_new_default = bool(best_mrr_ci_excludes_zero or best_ndcg_ci_excludes_zero)

        report = {
            "release": "R2b",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "benchmark": str(benchmark_path.relative_to(PROJECT_ROOT)),
            "split_evaluated": "tuning",
            "test_split_touched": False,
            "query_counts": {
                "total_tuning": len(tuning_items),
                "retrieval_tuning": len(retrieval_tuning_items),
                "by_stratum": {
                    st: sum(1 for q in cached_queries if q["stratum"] == st)
                    for st in ("S0", "S1", "S2", "S3", "S4", "legacy")
                },
            },
            "catalog_bias_sets": {
                "popular_asins_ge1_review": len(popular_asins),
                "review_cap_asins_eq20_reviews": len(review_cap_asins),
                "head_popular_asins_p90": len(head_popular_asins),
                "head_popular_p90_threshold": head_threshold,
            },
            "pre_registered_arms": arm_evals,
            "rs02_review_channel_attribution": {
                "verdict": rs02_verdict,
                "review_channel_target_hits_top50": len(review_channel_target_hits),
                "review_channel_target_hit_qids": review_channel_target_hits,
                "unique_rescues_at_20_rrf3_over_rrf2": review_unique_rescues_at_20,
                "demotions_at_20_rrf3_vs_rrf2": review_demotions_at_20,
                "comparisons_rrf3_minus_rrf2": rs02_comparisons,
            },
            "rs25_weighted_rrf_tuning": {
                "wrrf3_minus_rrf3": rs25_wrrf3_vs_rrf3,
                "grid_size": len(grid_results),
                "top_10_grid_configs": grid_results[:10],
                "best_grid_config": best_grid["config"],
                "best_grid_minus_rrf3": best_vs_rrf3,
                "promote_new_default": promote_new_default,
                "recommended_default_config": best_grid["config"] if promote_new_default else FUSION_ARMS["rrf3"].to_dict(),
                "decision_rationale": (
                    "Best grid config achieved statistically significant gain over rrf3 on tuning split."
                    if promote_new_default
                    else "Retain unweighted rrf3 (k=60, weights=(1,1,1)) as default by parsimony: no weighted RRF configuration achieved a 95% bootstrap CI excluding zero over rrf3 on the tuning split."
                ),
            },
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info("Saved R2b tuning report to %s", output_path)
        logger.info("RS-02 verdict: %s", rs02_verdict)
        logger.info("RS-25 decision: %s", report["rs25_weighted_rrf_tuning"]["decision_rationale"])
        return report
    finally:
        connector.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Release R2b RS-02/RS-25 tuning on benchmark_v2 tuning split.")
    parser.add_argument(
        "--benchmark",
        default="evaluations/benchmarks/benchmark_v2.json",
        help="Path to benchmark_v2.json",
    )
    parser.add_argument(
        "--output",
        default="evaluations/benchmarks/r2b_tuning_report.json",
        help="Output path for r2b_tuning_report.json",
    )
    args = parser.parse_args()
    run_tuning(PROJECT_ROOT / args.benchmark, PROJECT_ROOT / args.output)


if __name__ == "__main__":
    main()
