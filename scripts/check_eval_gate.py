#!/usr/bin/env python3
"""
R2a exit-gate checker (FR-036; Technical Specification §7).

Reads three (or more) run directories from evaluations/ or evaluations_archive/ and checks:
- G-3: every manifest has citable == true, and all runs share provenance.git_commit and
  provenance.benchmark.sha256;
- G-4: summary.dialogue.spurious_clarify.numerator <= --max-spurious-clarify and n == query count;
- G-5: type_explicit_non_search.numerator == 0, and every per_query.jsonl line is SEARCH with
  clarify_reason null;
- G-6: strategies.hybrid.top20 == strategies["hybrid@rrf3"].top20 on every SEARCH query, and
  all five arms are present in summary.by_strategy.
Prints a per-run table (spurious CLARIFY, CER parser / pipeline, recovery calls, target-admitting
rate, citable, commit) and the cross-run SEARCH intersection with per-run hybrid HR@5 / HR@20 / MRR
on it. Exit code 0 = PASS, 1 = FAIL (each cause named).

Usage:
    python scripts/check_eval_gate.py --runs <id> <id> <id> [--evaluations-dir evaluations]
        [--max-spurious-clarify 0]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.dialogue_metrics import format_share, search_intersection  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("check_eval_gate")

REQUIRED_ARMS: Tuple[str, ...] = ("hybrid@rrf3", "hybrid@rrf2", "hybrid@wrrf3", "hybrid@cc3", "hybrid@sum_legacy")
MIN_RUNS = 3


def resolve_run_dir(run_id: str, evaluations_dir: Path, archive_dir: Path) -> Optional[Path]:
    """Finds a run by ID in evaluations_dir first, then archive_dir; a path to a directory is accepted as-is."""
    direct = Path(run_id)
    if direct.is_dir():
        return direct
    for base in (evaluations_dir, archive_dir):
        candidate = Path(base) / run_id
        if candidate.is_dir():
            return candidate
    return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def load_run(run_dir: Path) -> Dict[str, Any]:
    """Loads manifest.json, summary.json and per_query.jsonl of one run (missing files -> None / [])."""
    per_query: List[Dict[str, Any]] = []
    path = run_dir / "per_query.jsonl"
    if path.exists():
        with open(path, "r", encoding="utf-8") as handle:
            per_query = [json.loads(line) for line in handle if line.strip()]
    return {
        "run_id": run_dir.name,
        "dir": str(run_dir),
        "manifest": _load_json(run_dir / "manifest.json"),
        "summary": _load_json(run_dir / "summary.json"),
        "per_query": per_query,
    }


def _hybrid_metrics(per_query: Sequence[Dict[str, Any]], query_ids: Sequence[str]) -> Dict[str, Optional[float]]:
    """HR@5, HR@20 and MRR of the default `hybrid` strategy on a query subset (from target ranks)."""
    by_id = {str(r.get("query_id")): r for r in per_query}
    ranks = [((by_id.get(q) or {}).get("strategies") or {}).get("hybrid", {}).get("target_rank") for q in query_ids]
    n = len(ranks)
    if not n:
        return {"n": 0, "hr@5": None, "hr@20": None, "mrr": None}
    return {
        "n": n,
        "hr@5": sum(1 for r in ranks if r is not None and r <= 5) / n,
        "hr@20": sum(1 for r in ranks if r is not None and r <= 20) / n,
        "mrr": sum(1.0 / r for r in ranks if r) / n,
    }


def check_runs(runs: Sequence[Dict[str, Any]], max_spurious_clarify: int = 0) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Applies G-3 … G-6; returns (passed, failure causes, report data for printing)."""
    causes: List[str] = []
    if len(runs) < MIN_RUNS:
        causes.append(f"G-3: {len(runs)} run(s) given, the gate needs {MIN_RUNS}")

    rows: List[Dict[str, Any]] = []
    commits, benchmarks = set(), set()
    for run in runs:
        rid = run["run_id"]
        manifest, summary = run.get("manifest"), run.get("summary")
        if not isinstance(manifest, dict) or not isinstance(summary, dict):
            causes.append(f"{rid}: manifest.json or summary.json missing or unreadable")
            continue
        provenance = manifest.get("provenance") or {}
        commit = provenance.get("git_commit")
        bench_sha = (provenance.get("benchmark") or {}).get("sha256")
        commits.add(commit)
        benchmarks.add(bench_sha)
        if manifest.get("citable") is not True:
            causes.append(f"G-3 {rid}: not citable ({manifest.get('citable_reasons')})")

        dialogue = summary.get("dialogue") or {}
        spurious = dialogue.get("spurious_clarify") or {}
        query_count = (manifest.get("configuration") or {}).get("query_count", summary.get("total_queries"))
        if spurious.get("numerator") is None or spurious["numerator"] > max_spurious_clarify:
            causes.append(f"G-4 {rid}: spurious CLARIFY {spurious.get('numerator')}/{spurious.get('n')} "
                          f"(max {max_spurious_clarify}; queries {spurious.get('query_ids')}, reasons {spurious.get('by_reason')})")
        if spurious.get("n") != query_count:
            causes.append(f"G-4 {rid}: spurious-CLARIFY n={spurious.get('n')} != query count {query_count}")

        non_search = dialogue.get("type_explicit_non_search") or {}
        if non_search.get("numerator") != 0:
            causes.append(f"G-5 {rid}: type-explicit non-SEARCH {non_search.get('numerator')} ({non_search.get('query_ids')})")
        per_query = run.get("per_query") or []
        if not per_query:
            causes.append(f"G-5 {rid}: per_query.jsonl missing or empty")
        bad_lines = [r.get("query_id") for r in per_query if r.get("action") != "SEARCH" or r.get("clarify_reason") is not None]
        if bad_lines:
            causes.append(f"G-5 {rid}: non-SEARCH or clarify_reason set in per_query.jsonl for {bad_lines}")

        mismatched = [
            r.get("query_id") for r in per_query if r.get("action") == "SEARCH"
            and ((r.get("strategies") or {}).get("hybrid") or {}).get("top20")
            != ((r.get("strategies") or {}).get("hybrid@rrf3") or {}).get("top20")
        ]
        if mismatched:
            causes.append(f"G-6 {rid}: hybrid != hybrid@rrf3 top20 for {mismatched}")
        missing_arms = [arm for arm in REQUIRED_ARMS if arm not in (summary.get("by_strategy") or {})]
        if missing_arms:
            causes.append(f"G-6 {rid}: arms missing from by_strategy: {missing_arms}")

        rows.append({
            "run_id": rid,
            "spurious_clarify": spurious,
            "cer_parser": dialogue.get("cer_parser"),
            "cer_pipeline": dialogue.get("cer_pipeline"),
            "recovery_calls": dialogue.get("recovery_calls"),
            "target_admitting": dialogue.get("target_admitting_category"),
            "citable": manifest.get("citable"),
            "commit": commit,
        })

    if len(commits) > 1:
        causes.append(f"G-3: runs come from different commits {sorted(str(c) for c in commits)}")
    if len(benchmarks) > 1:
        causes.append(f"G-3: runs use different benchmark hashes {sorted(str(b) for b in benchmarks)}")

    intersection = sorted(search_intersection({run["run_id"]: run.get("per_query") or [] for run in runs})) if runs else []
    report = {
        "rows": rows,
        "intersection": intersection,
        "intersection_metrics": {run["run_id"]: _hybrid_metrics(run.get("per_query") or [], intersection) for run in runs},
        "causes": causes,
    }
    return not causes, causes, report


def format_report(report: Dict[str, Any]) -> str:
    """Per-run table plus the cross-run SEARCH intersection block, every share with its n."""
    lines = ["Run | spurious CLARIFY | CER parser | CER pipeline | recovery calls | target-admitting | citable | commit"]
    for row in report.get("rows", []):
        spurious = row.get("spurious_clarify") or {}
        lines.append(" | ".join([
            str(row["run_id"]),
            f"{spurious.get('numerator')}/{spurious.get('n')}",
            format_share(row.get("cer_parser")),
            format_share(row.get("cer_pipeline")),
            str(row.get("recovery_calls")),
            format_share(row.get("target_admitting")),
            str(row.get("citable")),
            str(row.get("commit"))[:12],
        ]))
    intersection = report.get("intersection") or []
    lines.append(f"Cross-run SEARCH intersection: {len(intersection)} queries")

    def _f(value: Optional[float]) -> str:
        return f"{value:.3f}" if isinstance(value, (int, float)) else "n/a"

    for run_id, m in (report.get("intersection_metrics") or {}).items():
        lines.append(f"  {run_id} hybrid (n={m['n']}): HR@5 {_f(m['hr@5'])} | HR@20 {_f(m['hr@20'])} | MRR {_f(m['mrr'])}")
    causes = report.get("causes") or []
    lines.append("RESULT: PASS" if not causes else "RESULT: FAIL")
    lines.extend(f"  - {c}" for c in causes)
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; returns 0 on PASS, 1 on FAIL."""
    parser = argparse.ArgumentParser(description="Check the R2a exit gate on evaluation runs.")
    parser.add_argument("--runs", nargs="+", required=True, help="Run IDs (or run directories)")
    parser.add_argument("--evaluations-dir", default=str(REPO_ROOT / "evaluations"))
    parser.add_argument("--archive-dir", default=str(REPO_ROOT / "evaluations_archive"))
    parser.add_argument("--max-spurious-clarify", type=int, default=0)
    args = parser.parse_args(argv)

    runs: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    for run_id in args.runs:
        run_dir = resolve_run_dir(run_id, Path(args.evaluations_dir), Path(args.archive_dir))
        if run_dir is None:
            unresolved.append(run_id)
        else:
            runs.append(load_run(run_dir))
    passed, causes, report = check_runs(runs, args.max_spurious_clarify)
    if unresolved:
        causes.insert(0, f"runs not found: {unresolved}")
        report["causes"] = causes
        passed = False
    logger.info(format_report(report))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
