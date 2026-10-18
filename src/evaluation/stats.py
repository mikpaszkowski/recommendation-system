"""
Seeded paired statistics for arm comparisons (R2a, FR-027; Technical Specification §4.5).

Pure Python + NumPy + the `statistics` stdlib only (no SciPy). Every function is deterministic
for a given seed. Protocol R2-D3: RR and NDCG@10 with a paired randomization test and a paired
bootstrap CI; HR@K with Wilson CIs and an exact McNemar test; Holm across secondary pairs.
"""
from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_SEED: int = 20261018
DEFAULT_RESAMPLES: int = 10000
EXACT_ENUMERATION_MAX: int = 16  # exact sign-flip enumeration up to 2**16 patterns


@dataclass(frozen=True)
class PairedTestResult:
    """Two-sided paired sign-flip randomization test on d = a - b."""

    n: int
    n_nonzero: int
    mean_a: float
    mean_b: float
    mean_diff: float
    p_value: float
    method: str  # "exact" | "monte_carlo"


@dataclass(frozen=True)
class BootstrapCI:
    """Percentile bootstrap interval of the paired mean difference."""

    mean_diff: float
    low: float
    high: float
    confidence: float
    n_resamples: int


@dataclass(frozen=True)
class McNemarResult:
    """Exact two-sided McNemar (binomial) test on discordant pairs."""

    n: int
    a_only: int
    b_only: int
    p_value: float


def _paired_arrays(a: Sequence[float], b: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
    """Float arrays for a paired test; ValueError when the lengths differ."""
    if len(a) != len(b):
        raise ValueError(f"Paired samples must have equal length, got {len(a)} and {len(b)}")
    return np.asarray(list(a), dtype=float), np.asarray(list(b), dtype=float)


def paired_randomization_test(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> PairedTestResult:
    """
    Two-sided sign-flip test. Exact enumeration when n_nonzero <= EXACT_ENUMERATION_MAX,
    otherwise seeded Monte Carlo with p = (count + 1) / (n_resamples + 1). All-zero
    differences give p = 1.0.

    Raises:
        ValueError: if `a` and `b` differ in length.
    """
    arr_a, arr_b = _paired_arrays(a, b)
    n = int(arr_a.size)
    if n == 0:
        return PairedTestResult(0, 0, 0.0, 0.0, 0.0, 1.0, "exact")
    diff = arr_a - arr_b
    nonzero = diff[diff != 0.0]
    m = int(nonzero.size)
    mean_a, mean_b, mean_diff = float(arr_a.mean()), float(arr_b.mean()), float(diff.mean())
    if m == 0:
        return PairedTestResult(n, 0, mean_a, mean_b, mean_diff, 1.0, "exact")

    threshold = abs(mean_diff) - 1e-12
    if m <= EXACT_ENUMERATION_MAX:
        patterns = np.arange(2 ** m, dtype=np.int64)[:, None]
        signs = ((patterns >> np.arange(m, dtype=np.int64)) & 1) * 2 - 1
        permuted = np.abs(signs @ nonzero) / n
        p_value = float(np.count_nonzero(permuted >= threshold)) / float(2 ** m)
        return PairedTestResult(n, m, mean_a, mean_b, mean_diff, p_value, "exact")

    rng = np.random.default_rng(seed)
    count = 0
    remaining = int(n_resamples)
    while remaining > 0:
        batch = min(remaining, 2000)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(batch, m))
        count += int(np.count_nonzero(np.abs(signs @ nonzero) / n >= threshold))
        remaining -= batch
    p_value = (count + 1) / (int(n_resamples) + 1)
    return PairedTestResult(n, m, mean_a, mean_b, mean_diff, float(p_value), "monte_carlo")


def paired_bootstrap_ci(
    a: Sequence[float],
    b: Sequence[float],
    confidence: float = 0.95,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> BootstrapCI:
    """
    Resamples query indices with replacement (seeded) and returns the percentile interval of
    the mean difference a - b.

    Raises:
        ValueError: if `a` and `b` differ in length or are empty.
    """
    arr_a, arr_b = _paired_arrays(a, b)
    n = int(arr_a.size)
    if n == 0:
        raise ValueError("Bootstrap needs at least one paired observation")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    diff = arr_a - arr_b
    rng = np.random.default_rng(seed)
    means: List[np.ndarray] = []
    remaining = int(n_resamples)
    while remaining > 0:
        batch = min(remaining, 2000)
        idx = rng.integers(0, n, size=(batch, n))
        means.append(diff[idx].mean(axis=1))
        remaining -= batch
    resampled = np.concatenate(means) if means else np.array([diff.mean()])
    alpha = (1.0 - confidence) / 2.0
    low, high = np.percentile(resampled, [100.0 * alpha, 100.0 * (1.0 - alpha)])
    return BootstrapCI(float(diff.mean()), float(low), float(high), float(confidence), int(n_resamples))


def mcnemar_exact(a_hits: Sequence[int], b_hits: Sequence[int]) -> McNemarResult:
    """
    Exact McNemar test: b = #(a hit, b miss), c = #(a miss, b hit), n = b + c,
    p = min(1, 2 * sum_{i <= min(b, c)} C(n, i) * 0.5^n); n = 0 gives p = 1.0.

    Raises:
        ValueError: if the sequences differ in length.
    """
    if len(a_hits) != len(b_hits):
        raise ValueError(f"Paired samples must have equal length, got {len(a_hits)} and {len(b_hits)}")
    a_only = sum(1 for x, y in zip(a_hits, b_hits) if bool(x) and not bool(y))
    b_only = sum(1 for x, y in zip(a_hits, b_hits) if bool(y) and not bool(x))
    n = a_only + b_only
    if n == 0:
        return McNemarResult(0, 0, 0, 1.0)
    tail = sum(math.comb(n, i) for i in range(min(a_only, b_only) + 1))
    return McNemarResult(n, a_only, b_only, float(min(1.0, 2.0 * tail / (2 ** n))))


def wilson_ci(successes: int, n: int, confidence: float = 0.95) -> Tuple[Optional[float], Optional[float]]:
    """Wilson score interval for a binomial proportion; (None, None) when n = 0."""
    if n <= 0:
        return None, None
    z = NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def holm_correction(p_values: Mapping[str, float], alpha: float = 0.05) -> Dict[str, Dict[str, Any]]:
    """
    Holm step-down adjustment. Returns {name: {"p": p, "p_holm": adjusted, "reject": bool}},
    with adjusted p_(i) = max_{j <= i} min(1, (m - j + 1) * p_(j)).
    """
    ordered = sorted(p_values.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(ordered)
    out: Dict[str, Dict[str, Any]] = {}
    running = 0.0
    for j, (name, p) in enumerate(ordered, start=1):
        running = max(running, min(1.0, (m - j + 1) * float(p)))
        out[name] = {"p": float(p), "p_holm": running, "reject": running <= alpha}
    return out


def _is_search_row(row: Mapping[str, Any]) -> bool:
    action = row.get("action")
    return action is None or action == "SEARCH"


def _continuous_block(a: List[float], b: List[float], seed: int, n_resamples: int) -> Dict[str, Any]:
    test = paired_randomization_test(a, b, n_resamples=n_resamples, seed=seed)
    ci = paired_bootstrap_ci(a, b, n_resamples=n_resamples, seed=seed)
    return {
        "mean_a": test.mean_a, "mean_b": test.mean_b, "mean_diff": test.mean_diff,
        "ci95": [ci.low, ci.high], "p_randomization": test.p_value, "method": test.method,
        "n_nonzero": test.n_nonzero,
    }


def _binary_block(a: List[int], b: List[int]) -> Dict[str, Any]:
    result = mcnemar_exact(a, b)
    def arm(hits: List[int]) -> Dict[str, Any]:
        low, high = wilson_ci(sum(hits), len(hits))
        return {"hits": int(sum(hits)), "n": len(hits), "wilson95": [low, high]}
    return {"a": arm(a), "b": arm(b), "a_only": result.a_only, "b_only": result.b_only, "p_mcnemar_exact": result.p_value}


def _compare_pair(rows_by_strategy: Mapping[str, Mapping[str, Mapping[str, Any]]], a: str, b: str,
                  k_values: Sequence[int], seed: int, n_resamples: int) -> Dict[str, Any]:
    """One primary comparison entry (§5.1.6) on the paired SEARCH-only population."""
    entry: Dict[str, Any] = {"a": a, "b": b}
    missing = [arm for arm in (a, b) if arm not in rows_by_strategy]
    if missing:
        entry.update({"status": "arm_missing", "missing": missing, "n": 0})
        return entry
    qids = sorted(set(rows_by_strategy[a]) & set(rows_by_strategy[b]))
    entry["n"] = len(qids)
    if not qids:
        entry["status"] = "no_search_queries"
        return entry
    ra = [rows_by_strategy[a][q] for q in qids]
    rb = [rows_by_strategy[b][q] for q in qids]
    entry["status"] = "ok"
    entry["rr"] = _continuous_block([float(r["mrr"]) for r in ra], [float(r["mrr"]) for r in rb], seed, n_resamples)
    if 10 in k_values:
        entry["ndcg@10"] = _continuous_block([float(r["strict_ndcg@10"]) for r in ra],
                                             [float(r["strict_ndcg@10"]) for r in rb], seed, n_resamples)
    for k in (5, 20):
        if k in k_values:
            entry[f"hr@{k}"] = _binary_block([int(r[f"strict_hit@{k}"]) for r in ra], [int(r[f"strict_hit@{k}"]) for r in rb])
    return entry


def build_comparisons(
    per_query_results: Sequence[Mapping[str, Any]],
    strategies: Sequence[str],
    k_values: Sequence[int],
    seed: int = DEFAULT_SEED,
    n_resamples: int = DEFAULT_RESAMPLES,
) -> Dict[str, Any]:
    """
    Pre-registered arm comparisons for summary.json["comparisons"] (FR-028, §5.1.6).

    Population: SEARCH-only rows (rows without `action` count as SEARCH), paired by query_id.
    Primary: (hybrid@rrf3, else hybrid) vs hybrid@sum_legacy, and hybrid@rrf2 vs hybrid@rrf3:
    RR and strict NDCG@10 (randomization p, bootstrap CI95), HR@5 / HR@20 (Wilson CI95 per
    arm, discordant counts, exact McNemar p). Unadjusted. A missing arm gives
    {"status": "arm_missing"}. Secondary: every other pair of replayed arms (hybrid@*),
    randomization test on RR, Holm-adjusted within the family.
    """
    present = set(strategies)
    rows_by_strategy: Dict[str, Dict[str, Mapping[str, Any]]] = {}
    for row in per_query_results:
        strategy = row.get("strategy")
        if strategy in present and _is_search_row(row):
            rows_by_strategy.setdefault(strategy, {})[str(row.get("query_id"))] = row
    for strategy in present:
        rows_by_strategy.setdefault(strategy, {})

    reference = "hybrid@rrf3" if "hybrid@rrf3" in present else "hybrid"
    primary_pairs = [(reference, "hybrid@sum_legacy"), ("hybrid@rrf2", "hybrid@rrf3")]
    primary = [_compare_pair(rows_by_strategy, a, b, k_values, seed, n_resamples) for a, b in primary_pairs]

    arms = [s for s in strategies if s.startswith("hybrid@")]
    primary_keys = {frozenset(pair) for pair in primary_pairs}
    secondary_raw: List[Dict[str, Any]] = []
    for a, b in itertools.combinations(arms, 2):
        if frozenset((a, b)) in primary_keys:
            continue
        qids = sorted(set(rows_by_strategy[a]) & set(rows_by_strategy[b]))
        if not qids:
            secondary_raw.append({"a": a, "b": b, "n": 0, "status": "no_search_queries"})
            continue
        test = paired_randomization_test([float(rows_by_strategy[a][q]["mrr"]) for q in qids],
                                         [float(rows_by_strategy[b][q]["mrr"]) for q in qids],
                                         n_resamples=n_resamples, seed=seed)
        secondary_raw.append({"a": a, "b": b, "n": len(qids), "mean_diff": test.mean_diff,
                              "p": test.p_value, "method": test.method, "status": "ok"})
    adjusted = holm_correction({f"{t['a']} vs {t['b']}": t["p"] for t in secondary_raw if t["status"] == "ok"})
    for test in secondary_raw:
        if test["status"] == "ok":
            holm = adjusted[f"{test['a']} vs {test['b']}"]
            test["p_holm"] = holm["p_holm"]
            test["reject"] = holm["reject"]

    return {
        "protocol": "R2-D3",
        "seed": int(seed),
        "n_resamples": int(n_resamples),
        "population": "search_only",
        "primary": primary,
        "secondary": {"metric": "rr", "correction": "holm", "tests": secondary_raw},
    }


def format_comparison(entry: Mapping[str, Any]) -> str:
    """One log line for a primary comparison, with n, CIs and discordant counts."""
    head = f"{entry.get('a')} vs {entry.get('b')} (n={entry.get('n', 0)})"
    if entry.get("status") != "ok":
        return f"{head}: {entry.get('status')}"
    parts = [head]
    for key in ("rr", "ndcg@10"):
        block = entry.get(key)
        if block:
            low, high = block["ci95"]
            parts.append(f"{key.upper()} diff {block['mean_diff']:+.4f} CI95 [{low:+.4f}, {high:+.4f}] p={block['p_randomization']:.4f} ({block['method']})")
    for key in ("hr@5", "hr@20"):
        block = entry.get(key)
        if block:
            parts.append(f"{key.upper()} {block['a']['hits']}/{block['a']['n']} vs {block['b']['hits']}/{block['b']['n']} "
                         f"discordant {block['a_only']}-{block['b_only']} p={block['p_mcnemar_exact']:.4f}")
    return " | ".join(parts)
