"""
tests/test_archive_eval_run.py

Run archive, per-query JSONL and gate checker (Technical Specification AC-025, AC-026, AC-029).
All run directories are fixtures under tmp_path.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.evaluation.tracker import write_per_query_jsonl

REPO_ROOT = Path(__file__).resolve().parent.parent
ARMS = ["hybrid@rrf3", "hybrid@rrf2", "hybrid@wrrf3", "hybrid@cc3", "hybrid@sum_legacy"]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


archive = _load("archive_eval_run")
gate = _load("check_eval_gate")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(qid: str, action: str = "SEARCH", hybrid_top=None, rrf3_top=None) -> Dict[str, Any]:
    top = hybrid_top if hybrid_top is not None else ["T", "X"]
    strategies = {"hybrid": {"top20": top, "target_rank": (top.index("T") + 1) if "T" in top else None, "cs_gold": [], "cs_req": []}}
    for arm in ARMS:
        arm_top = rrf3_top if (arm == "hybrid@rrf3" and rrf3_top is not None) else top
        strategies[arm] = {"top20": arm_top, "target_rank": None, "cs_gold": [], "cs_req": []}
    return {
        "query_id": qid, "action": action, "clarify_reason": None if action == "SEARCH" else "recovery_failed",
        "type_explicit": True, "gold_action": "SEARCH", "gold_product_type": "x",
        "parser_category": "x", "pipeline_category": "x", "category_source": "parser", "recovery_outcome": None,
        "applied_category": {"normalized": "X", "raw": "x"}, "target_admitted": True, "category_dropped_by_macs": False,
        "relaxed_constraints": [], "target_asin": "T", "target_review_embedded": False,
        "target_channel_ranks": {"product": 1, "attribute": None, "review": None},
        "gold_constraint_labels": ["price<=60"], "strategies": strategies, "latency_ms": 10.0,
        "legacy_reconstructed": False,
    }


def _make_run(base: Path, run_id: str, records: List[Dict[str, Any]], citable: bool = True,
              commit: str = "c0ffee", spurious: int = 0) -> Path:
    run_dir = base / run_id
    run_dir.mkdir(parents=True)
    n = len(records)
    manifest = {
        "run_id": run_id, "timestamp": "2026-10-18T12:00:00", "git_commit": commit,
        "configuration": {"mode": "live", "query_count": n},
        "citable": citable, "citable_reasons": [] if citable else ["git_dirty: src/x.py"], "citable_warnings": [],
        "provenance": {"git_commit": commit, "benchmark": {"sha256": "b" * 64}},
    }
    summary = {
        "total_queries": n,
        "dialogue": {
            "spurious_clarify": {"value": spurious / n, "numerator": spurious, "n": n, "query_ids": [], "by_reason": {}},
            "type_explicit_non_search": {"numerator": 0, "n": n, "query_ids": []},
            "cer_parser": {"value": 1.0, "numerator": n, "n": n},
            "cer_pipeline": {"value": 1.0, "numerator": n, "n": n},
            "target_admitting_category": {"value": 1.0, "numerator": n, "n": n, "category_dropped_by_macs": 0},
            "recovery_calls": 0,
        },
        "by_strategy": {s: {"n_all": n} for s in ["hybrid"] + ARMS},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run_dir / "retrieval_metrics.csv").write_text("query_id,strategy\nq1,hybrid\n", encoding="utf-8")
    write_per_query_jsonl(run_dir, records)
    (run_dir / "execution_trace.log").write_text("line one\nline two\nline three\n", encoding="utf-8")
    return run_dir


def _snapshot(run_dir: Path) -> Dict[str, str]:
    return {p.name: _sha(p) for p in sorted(run_dir.iterdir()) if p.is_file()}


class TestPerQueryJsonl:
    """AC-025."""

    def test_one_valid_line_per_query(self, tmp_path):
        records = [_record("q1"), _record("q2", action="CLARIFY")]
        path = write_per_query_jsonl(tmp_path, records)
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        assert [json.loads(line) for line in lines] == records
        assert lines == [json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in records]


class TestArchive:
    """AC-026."""

    def test_archives_citable_run(self, tmp_path):
        evals, arch = tmp_path / "evaluations", tmp_path / "evaluations_archive"
        run_dir = _make_run(evals, "eval_A", [_record("q1")])
        before = _snapshot(run_dir)
        assert archive.archive_run("eval_A", evals, arch) == 0
        target = arch / "eval_A"
        assert sorted(p.name for p in target.iterdir()) == sorted(archive.COPIED_FILES + ("ARCHIVE.json",))
        meta = json.loads((target / "ARCHIVE.json").read_text(encoding="utf-8"))
        assert meta["files"] == {name: _sha(target / name) for name in archive.COPIED_FILES}
        assert meta["files"]["per_query.jsonl"] == before["per_query.jsonl"]
        assert meta["execution_trace"] == {"sha256": before["execution_trace.log"], "bytes": 29, "lines": 3}
        assert meta["legacy"] is False and meta["run_id"] == "eval_A"
        assert not (target / "execution_trace.log").exists()
        index = json.loads((arch / "index.json").read_text(encoding="utf-8"))
        assert index == [{"run_id": "eval_A", "citable": True, "legacy": False, "timestamp": "2026-10-18T12:00:00",
                          "git_commit": "c0ffee", "benchmark_sha256": "b" * 64, "note": None}]
        assert _snapshot(run_dir) == before

    def test_refusals(self, tmp_path):
        evals, arch = tmp_path / "evaluations", tmp_path / "evaluations_archive"
        _make_run(evals, "eval_dirty", [_record("q1")], citable=False)
        assert archive.archive_run("eval_dirty", evals, arch) == 1
        assert archive.archive_run("eval_dirty", evals, arch, legacy=True) == 1
        assert archive.archive_run("eval_dirty", evals, arch, legacy=True, note="   ") == 1
        assert archive.archive_run("eval_missing", evals, arch) == 1
        _make_run(evals, "eval_ok", [_record("q1")])
        assert archive.archive_run("eval_ok", evals, arch) == 0
        assert archive.archive_run("eval_ok", evals, arch) == 1
        assert archive.archive_run("eval_ok", evals, arch, force=True) == 0
        assert archive.main(["eval_ok", "--evaluations-dir", str(evals), "--archive-dir", str(arch)]) == 1

    def test_offline_run_refused(self, tmp_path):
        evals, arch = tmp_path / "evaluations", tmp_path / "evaluations_archive"
        run_dir = _make_run(evals, "eval_off", [_record("q1")])
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["configuration"]["mode"] = "offline"
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert archive.archive_run("eval_off", evals, arch) == 1

    def test_legacy_reconstruction(self, tmp_path):
        evals, arch = tmp_path / "evaluations", tmp_path / "evaluations_archive"
        run_dir = evals / "eval_old"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps(
            {"run_id": "eval_old", "timestamp": "2026-10-09T13:44:00", "git_commit": "2fdf251",
             "configuration": {"mode": "live", "benchmark": "does_not_exist.json"}}), encoding="utf-8")
        (run_dir / "summary.json").write_text("{}", encoding="utf-8")
        (run_dir / "retrieval_metrics.csv").write_text("a\n1\n", encoding="utf-8")
        rows = [
            {"query_id": "q1", "strategy": "hybrid", "candidate_asins": ["X", "T1", "X"], "primary_target": "T1", "latency_ms": 5.0},
            {"query_id": "q1", "strategy": "vector_only", "candidate_asins": ["T1"], "primary_target": "T1", "latency_ms": 2.0},
            {"query_id": "q2", "strategy": "hybrid", "candidate_asins": [], "primary_target": "T2", "latency_ms": 1.0},
        ]
        (run_dir / "retrieval_metrics.json").write_text(json.dumps({"per_query_results": rows}), encoding="utf-8")
        (run_dir / "execution_trace.log").write_text(
            "noise\n<<< [END QUERY 1/2] ID: q1 | Status: SUCCESS\n   - Status: CLARIFIED (Handled cleanly)\n"
            "<<< [END QUERY 2/2] ID: q2 | Status: CLARIFIED\n", encoding="utf-8")
        before = _snapshot(run_dir)

        assert archive.archive_run("eval_old", evals, arch, legacy=True, note="Pre-R2 run") == 0
        target = arch / "eval_old"
        records = [json.loads(line) for line in (target / "per_query.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [(r["query_id"], r["action"]) for r in records] == [("q1", "SEARCH"), ("q2", "CLARIFY")]
        assert all(r["legacy_reconstructed"] is True and r["clarify_reason"] is None for r in records)
        assert records[0]["strategies"]["hybrid"] == {"top20": ["X", "T1"], "target_rank": 2, "cs_gold": None, "cs_req": None}
        assert records[0]["strategies"]["vector_only"]["target_rank"] == 1 and records[0]["latency_ms"] == 5.0
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["citable"] is False
        assert manifest["archive"]["legacy"] is True and manifest["archive"]["note"] == "Pre-R2 run"
        index = json.loads((arch / "index.json").read_text(encoding="utf-8"))
        assert index[0]["legacy"] is True and index[0]["citable"] is False and index[0]["git_commit"] == "2fdf251"
        assert json.loads((target / "ARCHIVE.json").read_text(encoding="utf-8"))["execution_trace"]["lines"] == 4
        assert _snapshot(run_dir) == before

    def test_index_upsert_sorted(self, tmp_path):
        archive.update_index(tmp_path, {"run_id": "b", "note": 1})
        archive.update_index(tmp_path, {"run_id": "a", "note": 2})
        archive.update_index(tmp_path, {"run_id": "b", "note": 3})
        assert json.loads((tmp_path / "index.json").read_text(encoding="utf-8")) == [
            {"run_id": "a", "note": 2}, {"run_id": "b", "note": 3}]


class TestGateChecker:
    """AC-029."""

    def _three(self, base: Path, **overrides: Any) -> List[str]:
        ids = []
        for i in range(3):
            records = [_record("q1"), _record("q2")]
            kwargs: Dict[str, Any] = {}
            if overrides.get("spurious_run") == i:
                records[1] = _record("q2", action="CLARIFY")
                kwargs["spurious"] = 1
            if overrides.get("noncitable_run") == i:
                kwargs["citable"] = False
            if overrides.get("commit_run") == i:
                kwargs["commit"] = "deadbeef"
            if overrides.get("mismatch_run") == i:
                records[0] = _record("q1", hybrid_top=["T", "X"], rrf3_top=["X", "T"])
            _make_run(base, f"eval_{i}", records, **kwargs)
            ids.append(f"eval_{i}")
        return ids

    def _main(self, base: Path, ids: List[str]) -> int:
        return gate.main(["--runs", *ids, "--evaluations-dir", str(base), "--archive-dir", str(base / "none")])

    def test_pass(self, tmp_path, caplog):
        ids = self._three(tmp_path)
        passed, causes, report = gate.check_runs([gate.load_run(tmp_path / i) for i in ids])
        assert passed and causes == []
        assert report["intersection"] == ["q1", "q2"]
        assert report["intersection_metrics"]["eval_0"] == {"n": 2, "hr@5": 1.0, "hr@20": 1.0, "mrr": 1.0}
        assert self._main(tmp_path, ids) == 0
        assert "RESULT: PASS" in gate.format_report(report)

    @pytest.mark.parametrize("override,needle", [
        ({"spurious_run": 1}, "G-4 eval_1: spurious CLARIFY 1/2"),
        ({"noncitable_run": 2}, "G-3 eval_2: not citable"),
        ({"commit_run": 0}, "G-3: runs come from different commits"),
        ({"mismatch_run": 1}, "G-6 eval_1: hybrid != hybrid@rrf3 top20 for ['q1']"),
    ])
    def test_fail_causes(self, tmp_path, override, needle):
        ids = self._three(tmp_path, **override)
        passed, causes, _ = gate.check_runs([gate.load_run(tmp_path / i) for i in ids])
        assert not passed
        assert any(needle in c for c in causes), causes
        assert self._main(tmp_path, ids) == 1

    def test_missing_arm_and_too_few_runs(self, tmp_path):
        ids = self._three(tmp_path)
        summary_path = tmp_path / ids[0] / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        del summary["by_strategy"]["hybrid@cc3"]
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        _, causes, _ = gate.check_runs([gate.load_run(tmp_path / i) for i in ids])
        assert any("arms missing from by_strategy: ['hybrid@cc3']" in c for c in causes)
        _, causes2, _ = gate.check_runs([gate.load_run(tmp_path / ids[1])])
        assert any("the gate needs 3" in c for c in causes2)
        assert self._main(tmp_path, ["eval_404", ids[1], ids[2]]) == 1
