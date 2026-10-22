"""
tests/test_eval_stats.py

Seeded paired statistics and pre-registered comparisons (Technical Specification AC-021, AC-022).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.evaluation import stats
from src.evaluation.stats import (
    build_comparisons,
    format_comparison,
    holm_correction,
    mcnemar_exact,
    paired_bootstrap_ci,
    paired_randomization_test,
    wilson_ci,
)


class TestVectors:
    """AC-021."""

    @pytest.mark.parametrize("a_only,b_only,expected", [(5, 0, 0.0625), (6, 0, 0.03125), (9, 1, 0.02148), (0, 0, 1.0)])
    def test_mcnemar(self, a_only, b_only, expected):
        a = [1] * a_only + [0] * b_only + [1, 0]
        b = [0] * a_only + [1] * b_only + [1, 0]
        res = mcnemar_exact(a, b)
        assert (res.a_only, res.b_only, res.n) == (a_only, b_only, a_only + b_only)
        assert res.p_value == pytest.approx(expected, abs=1e-4)

    def test_mcnemar_unequal_lengths(self):
        with pytest.raises(ValueError):
            mcnemar_exact([1], [1, 0])

    def test_wilson(self):
        low, high = wilson_ci(6, 21)
        assert low == pytest.approx(0.138, abs=0.005) and high == pytest.approx(0.500, abs=0.005)
        assert wilson_ci(0, 0) == (None, None)
        assert wilson_ci(0, 10)[0] == pytest.approx(0.0)
        assert wilson_ci(10, 10)[1] == pytest.approx(1.0)

    def test_randomization_exact(self):
        res = paired_randomization_test([1.0] * 6 + [0.0] * 15, [0.0] * 21)
        assert res.p_value == pytest.approx(0.03125)
        assert res.method == "exact" and res.n == 21 and res.n_nonzero == 6
        assert res.mean_diff == pytest.approx(6 / 21)

    def test_randomization_all_zero_and_errors(self):
        assert paired_randomization_test([0.5, 0.2], [0.5, 0.2]).p_value == 1.0
        with pytest.raises(ValueError):
            paired_randomization_test([1.0], [1.0, 2.0])

    def test_randomization_monte_carlo_is_seeded(self):
        a = [float(i % 3) for i in range(40)]
        b = [0.0] * 40
        r1 = paired_randomization_test(a, b, n_resamples=2000, seed=7)
        r2 = paired_randomization_test(a, b, n_resamples=2000, seed=7)
        assert r1 == r2 and r1.method == "monte_carlo"
        assert r1.p_value == pytest.approx(1 / 2001)

    def test_bootstrap(self):
        a = [1.0, 0.0, 0.5, 1.0, 0.25]
        b = [0.0, 0.0, 0.5, 0.5, 0.0]
        c1 = paired_bootstrap_ci(a, b, n_resamples=3000, seed=11)
        c2 = paired_bootstrap_ci(a, b, n_resamples=3000, seed=11)
        assert c1 == c2
        assert c1.low <= c1.mean_diff <= c1.high
        assert c1.mean_diff == pytest.approx(0.35)
        with pytest.raises(ValueError):
            paired_bootstrap_ci([], [])

    def test_holm(self):
        out = holm_correction({"x": 0.01, "y": 0.04, "z": 0.03})
        assert out["x"]["p_holm"] == pytest.approx(0.03)
        assert out["y"]["p_holm"] == pytest.approx(0.06)
        assert out["z"]["p_holm"] == pytest.approx(0.06)
        assert [name for name, v in out.items() if v["reject"]] == ["x"]

    def test_no_scipy_import(self):
        tree = ast.parse(Path(stats.__file__).read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert "scipy" not in imported


def _rows(strategy: str, mrrs: List[float], actions: List[str] = None) -> List[Dict[str, Any]]:
    rows = []
    for i, rr in enumerate(mrrs):
        hit = 1 if rr >= 0.2 else 0
        rows.append({"query_id": f"q{i}", "strategy": strategy, "mrr": rr, "strict_ndcg@10": rr,
                     "strict_hit@5": hit, "strict_hit@20": 1 if rr > 0 else 0,
                     "action": (actions[i] if actions else "SEARCH")})
    return rows


ARMS = ["hybrid", "hybrid@rrf3", "hybrid@rrf2", "hybrid@wrrf3", "hybrid@cc3", "hybrid@sum_legacy"]


def _results() -> List[Dict[str, Any]]:
    actions = ["SEARCH"] * 7 + ["CLARIFY"]
    out: List[Dict[str, Any]] = []
    out += _rows("hybrid", [1, 0.5, 0, 0.25, 1, 0, 0.1, 0], actions)
    out += _rows("hybrid@rrf3", [1, 0.5, 0, 0.25, 1, 0, 0.1, 0], actions)
    out += _rows("hybrid@rrf2", [1, 0.5, 0, 0.2, 1, 0, 0, 0], actions)
    out += _rows("hybrid@wrrf3", [0.5, 0.5, 0, 0.25, 1, 0.1, 0.1, 0], actions)
    out += _rows("hybrid@cc3", [1, 0.33, 0, 0.25, 0.5, 0, 0.1, 0], actions)
    out += _rows("hybrid@sum_legacy", [0.5, 0, 0, 0, 1, 0, 0.05, 0], actions)
    return out


class TestComparisons:
    """AC-022."""

    def test_primary_entries(self):
        comp = build_comparisons(_results(), ARMS, (1, 5, 10, 20), n_resamples=500)
        assert comp["protocol"] == "R2-D3" and comp["population"] == "search_only"
        first, second = comp["primary"]
        assert (first["a"], first["b"]) == ("hybrid@rrf3", "hybrid@sum_legacy")
        assert (second["a"], second["b"]) == ("hybrid@rrf2", "hybrid@rrf3")
        assert first["n"] == 7  # the CLARIFY row is excluded
        for key in ("rr", "ndcg@10"):
            assert set(first[key]) == {"mean_a", "mean_b", "mean_diff", "ci95", "p_randomization", "method", "n_nonzero"}
        for key in ("hr@5", "hr@20"):
            assert set(first[key]) == {"a", "b", "a_only", "b_only", "p_mcnemar_exact"}
            assert set(first[key]["a"]) == {"hits", "n", "wilson95"}
        assert first["rr"]["mean_diff"] == pytest.approx((0.5 + 0.5 + 0.25 + 0.05) / 7)
        assert "vs" in format_comparison(first)

    def test_falls_back_to_hybrid_and_reports_missing_arm(self):
        comp = build_comparisons(_results(), ["hybrid", "hybrid@sum_legacy"], (5, 10, 20), n_resamples=200)
        assert comp["primary"][0]["a"] == "hybrid" and comp["primary"][0]["status"] == "ok"
        assert comp["primary"][1]["status"] == "arm_missing"
        assert set(comp["primary"][1]["missing"]) == {"hybrid@rrf2", "hybrid@rrf3"}
        assert format_comparison(comp["primary"][1]).endswith("arm_missing")

    def test_secondary_holm(self):
        comp = build_comparisons(_results(), ARMS, (5, 10, 20), n_resamples=200)
        tests = comp["secondary"]["tests"]
        pairs = {(t["a"], t["b"]) for t in tests}
        # 5 replayed arms -> 10 pairs, minus the 2 primary pairs
        assert len(pairs) == 8
        assert ("hybrid@rrf3", "hybrid@sum_legacy") not in pairs and ("hybrid@rrf3", "hybrid@rrf2") not in pairs
        assert all(t["p_holm"] >= t["p"] for t in tests)
        assert comp["secondary"]["correction"] == "holm"

    def test_deterministic(self):
        assert build_comparisons(_results(), ARMS, (5, 10, 20), n_resamples=300, seed=5) == \
            build_comparisons(_results(), ARMS, (5, 10, 20), n_resamples=300, seed=5)
