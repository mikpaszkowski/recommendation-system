"""
tests/test_r2a_audit_fixes.py

Regression tests for the fixes applied in the R2a QA audit (production_artifacts/Audit_Report.md):
- M-2: a refused `--force` re-archive must not delete the existing archive folder;
- M-3: the review-coverage base rate is also reported over titled products only
  (untitled "ghost" ParentProduct nodes excluded), with parameterised Cypher.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_audit_under_test", REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


archive = _load("archive_eval_run")
evaluate_retrieval = _load("evaluate_retrieval")


def _write_run(base: Path, run_id: str, with_per_query: bool = True) -> Path:
    run_dir = base / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id, "timestamp": "2026-10-18T12:00:00", "git_commit": "c0ffee",
        "configuration": {"mode": "live", "query_count": 1},
        "citable": True, "citable_reasons": [], "citable_warnings": [],
        "provenance": {"git_commit": "c0ffee", "benchmark": {"sha256": "b" * 64}},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")
    (run_dir / "retrieval_metrics.csv").write_text("query_id,strategy\nq1,hybrid\n", encoding="utf-8")
    if with_per_query:
        (run_dir / "per_query.jsonl").write_text(json.dumps({"query_id": "q1", "action": "SEARCH"}) + "\n", encoding="utf-8")
    return run_dir


def _tree_hashes(folder: Path) -> Dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


class TestForceDoesNotDeleteOnRefusal:
    """M-2: refusals happen before the --force removal."""

    def test_refused_force_rearchive_keeps_existing_archive(self, tmp_path):
        evals, arch = tmp_path / "evaluations", tmp_path / "evaluations_archive"
        run_dir = _write_run(evals, "eval_A")
        assert archive.archive_run("eval_A", evals, arch) == 0
        before = _tree_hashes(arch / "eval_A")

        # The source run loses its per_query.jsonl; a non-legacy --force re-archive must be refused
        (run_dir / "per_query.jsonl").unlink()
        assert archive.archive_run("eval_A", evals, arch, force=True) == 1
        assert (arch / "eval_A").is_dir()
        assert _tree_hashes(arch / "eval_A") == before

    def test_force_still_overwrites_a_valid_run(self, tmp_path):
        evals, arch = tmp_path / "evaluations", tmp_path / "evaluations_archive"
        run_dir = _write_run(evals, "eval_B")
        assert archive.archive_run("eval_B", evals, arch) == 0
        (run_dir / "summary.json").write_text('{"changed": true}', encoding="utf-8")
        assert archive.archive_run("eval_B", evals, arch, force=True) == 0
        assert json.loads((arch / "eval_B" / "summary.json").read_text(encoding="utf-8")) == {"changed": True}


class _Result:
    def __init__(self, value: Optional[int]):
        self._value = value

    def single(self) -> Dict[str, Any]:
        return {"n": self._value}


class _FakeSession:
    """Answers the three base-rate counts; records every (cypher, params) call."""

    def __init__(self, total: int, titled: int, titled_popular: int, fail_titled: bool = False):
        self.total, self.titled, self.titled_popular, self.fail_titled = total, titled, titled_popular, fail_titled
        self.calls: List[Tuple[str, Optional[Dict[str, Any]]]] = []

    def run(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> _Result:
        self.calls.append((cypher, params))
        if "UNWIND $asins" in cypher:
            return _Result(self.titled_popular)
        if "p.title IS NOT NULL" in cypher:
            if self.fail_titled:
                raise RuntimeError("count failed")
            return _Result(self.titled)
        return _Result(self.total)


class TestTitledBaseRate:
    """M-3: the titled-only base rate is reported alongside the all-node one."""

    def test_rates_match_live_graph_counts(self):
        popular = {f"A{i}" for i in range(5715)}
        session = _FakeSession(total=265307, titled=161026, titled_popular=841)
        rates = evaluate_retrieval.compute_review_coverage_base_rates(session, popular)
        assert rates["catalog_products"] == 265307
        assert abs(rates["catalog_popular_share"] - 5715 / 265307) < 1e-12
        assert rates["catalog_titled_products"] == 161026
        assert rates["review_embedded_products_titled"] == 841
        assert abs(rates["catalog_popular_share_titled"] - 841 / 161026) < 1e-12
        assert round(rates["catalog_popular_share"], 4) == 0.0215
        assert round(rates["catalog_popular_share_titled"], 4) == 0.0052

    def test_asins_are_passed_as_a_parameter(self):
        session = _FakeSession(total=10, titled=6, titled_popular=1)
        evaluate_retrieval.compute_review_coverage_base_rates(session, {"B2", "B1"})
        unwind = [(c, p) for c, p in session.calls if "UNWIND" in c]
        assert len(unwind) == 1
        cypher, params = unwind[0]
        assert params == {"asins": ["B1", "B2"]}
        assert "B1" not in cypher and "B2" not in cypher

    def test_titled_count_failure_keeps_all_node_rate(self):
        session = _FakeSession(total=100, titled=60, titled_popular=1, fail_titled=True)
        rates = evaluate_retrieval.compute_review_coverage_base_rates(session, {"A1", "A2"})
        assert rates["catalog_popular_share"] == 0.02
        assert rates["catalog_titled_products"] is None
        assert rates["catalog_popular_share_titled"] is None

    def test_empty_catalogue_gives_none(self):
        session = _FakeSession(total=0, titled=0, titled_popular=0)
        rates = evaluate_retrieval.compute_review_coverage_base_rates(session, set())
        assert rates["catalog_popular_share"] is None
        assert rates["catalog_popular_share_titled"] is None
