"""
tests/test_provenance.py

Run provenance, the citable policy and model-ID recording (Technical Specification AC-023, AC-024,
AC-025). Git is reached only through an injected runner, so no real repository state is asserted.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.evaluation.provenance import (
    collect_benchmark_provenance,
    collect_git_provenance,
    collect_runtime_provenance,
    evaluate_citable,
    file_sha256,
    offending_paths,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = REPO_ROOT / "live_eval_dataset.json"
PER_QUERY_KEYS = {
    "query_id", "action", "clarify_reason", "type_explicit", "gold_action", "gold_product_type",
    "parser_category", "pipeline_category", "category_source", "recovery_outcome", "applied_category",
    "target_admitted", "category_dropped_by_macs", "relaxed_constraints", "target_asin",
    "target_review_embedded", "target_channel_ranks", "gold_constraint_labels", "strategies",
    "latency_ms", "legacy_reconstructed",
}


def make_runner(status: str = "", diff: str = "", bench_status: str = "", tracked: bool = True,
                commit: str = "abc123") -> Tuple[callable, List[Sequence[str]]]:
    """Fake git: answers by sub-command; records every call."""
    calls: List[Sequence[str]] = []

    def run(args: Sequence[str]) -> Tuple[int, str]:
        calls.append(list(args))
        cmd = args[0]
        if cmd == "rev-parse":
            return 0, commit + "\n"
        if cmd == "describe":
            return 0, f"{commit[:7]}-dirty\n" if status else f"{commit[:7]}\n"
        if cmd == "status" and "--untracked-files=all" in args:
            return 0, status
        if cmd == "status":
            return 0, bench_status
        if cmd == "diff":
            return 0, diff
        if cmd == "ls-files":
            return (0 if tracked else 1), ""
        return 1, ""

    return run, calls


class TestGitProvenance:
    def test_clean_tree(self):
        runner, calls = make_runner()
        git = collect_git_provenance(REPO_ROOT, runner=runner)
        assert git["git_commit"] == "abc123" and git["git_dirty"] is False
        assert git["git_dirty_paths"] == [] and git["untracked_files"] == []
        assert git["git_diff_sha256"] is None
        status_call = next(c for c in calls if c[0] == "status")
        assert status_call[-3:] == ["--", "src", "scripts"]

    def test_dirty_tree(self):
        runner, _ = make_runner(status=" M src/agents/orchestrator.py\n?? scripts/new_tool.py\n", diff="diff --git a b\n+x\n")
        git = collect_git_provenance(REPO_ROOT, runner=runner)
        assert git["git_dirty"] is True
        assert git["git_dirty_paths"] == ["src/agents/orchestrator.py", "scripts/new_tool.py"]
        assert git["untracked_files"] == ["scripts/new_tool.py"]
        assert len(git["git_diff_sha256"]) == 64

    def test_git_failure_is_unknown(self):
        git = collect_git_provenance(REPO_ROOT, runner=lambda args: (-1, ""))
        assert git["git_commit"] is None and git["git_dirty"] is None
        citable, reasons, _ = evaluate_citable("live", None, git, {"sha256": "x", "git_tracked": True, "git_dirty": False})
        assert citable is False and "git_status_unavailable" in reasons and "git_commit_unknown" in reasons


class TestCitable:
    """AC-023."""

    def _bench(self, runner) -> Dict:
        return collect_benchmark_provenance(REPO_ROOT, Path("live_eval_dataset.json"), 21, runner=runner)

    def test_clean_live_run_is_citable(self):
        runner, _ = make_runner()
        git, bench = collect_git_provenance(REPO_ROOT, runner=runner), self._bench(runner)
        assert bench["sha256"] == file_sha256(BENCHMARK) and bench["query_count"] == 21
        assert bench["split"] is None and bench["salt"] is None
        citable, reasons, warnings = evaluate_citable("live", None, git, bench, {"resolved_model_ids": ["gpt-4o-2024-08-06"]})
        assert (citable, reasons, warnings) == (True, [], [])
        assert offending_paths(git, bench) == []

    def test_dirty_source_is_not_citable(self):
        runner, _ = make_runner(status="?? src/evaluation/new.py\n")
        git = collect_git_provenance(REPO_ROOT, runner=runner)
        citable, reasons, _ = evaluate_citable("live", None, git, self._bench(runner))
        assert citable is False
        assert reasons == ["git_dirty: src/evaluation/new.py"]

    def test_dirty_or_untracked_benchmark_is_not_citable(self):
        runner, _ = make_runner(bench_status=" M live_eval_dataset.json\n")
        bench = self._bench(runner)
        assert bench["git_dirty"] is True
        citable, reasons, _ = evaluate_citable("live", None, collect_git_provenance(REPO_ROOT, runner=runner), bench)
        assert citable is False and reasons == ["benchmark_modified: live_eval_dataset.json"]
        runner2, _ = make_runner(tracked=False)
        _, reasons2, _ = evaluate_citable("live", None, collect_git_provenance(REPO_ROOT, runner=runner2), self._bench(runner2))
        assert reasons2 == ["benchmark_untracked: live_eval_dataset.json"]

    def test_sample_size_and_offline(self):
        runner, _ = make_runner()
        git, bench = collect_git_provenance(REPO_ROOT, runner=runner), self._bench(runner)
        assert evaluate_citable("live", 5, git, bench)[1] == ["sample_size_set: 5"]
        assert evaluate_citable("offline", None, git, bench)[1] == ["mode_not_live: offline"]

    def test_model_id_warnings(self):
        runner, _ = make_runner()
        git, bench = collect_git_provenance(REPO_ROOT, runner=runner), self._bench(runner)
        assert evaluate_citable("live", None, git, bench, {"resolved_model_ids": []}) == (True, [], ["model_id_unresolved"])
        assert evaluate_citable("live", None, git, bench, {"resolved_model_ids": ["a", "b"]})[2] == ["multiple_model_ids"]


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("evaluate_retrieval_under_test", REPO_ROOT / "scripts" / "evaluate_retrieval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEvaluationScript:
    def test_require_clean_exits_before_orchestrator(self, monkeypatch, tmp_path):
        import src.agents.orchestrator as orchestrator_module
        import src.evaluation.dialogue_metrics  # noqa: F401  (bind the real class before patching)
        import src.knowledge_graph.graphdb.neo4j_connector as connector_module

        def _forbidden(*args, **kwargs):
            raise AssertionError("must not be constructed with --require-clean on a dirty tree")

        monkeypatch.setattr(orchestrator_module, "AgentOrchestrator", _forbidden)
        monkeypatch.setattr(connector_module, "Neo4jConnector", _forbidden)
        module = _load_eval_module()
        runner, _ = make_runner(status=" M src/tools/graph_search_tool.py\n")
        code = module.run_retrieval_evaluation(
            benchmark_path=BENCHMARK, k_values=[5], strategies=["hybrid"], mode="live",
            output_dir=str(tmp_path / "run"), require_clean=True, git_runner=runner,
        )
        assert code == 2
        assert not (tmp_path / "run").exists()

    def test_offline_manifest_has_provenance_and_no_secrets(self, monkeypatch, tmp_path):
        """AC-023 (no environment values) and AC-025 (per_query.jsonl keys) on an offline run."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-UNIT-TEST-SECRET-31337")
        monkeypatch.setenv("NEO4J_PASSWORD", "neo4j-UNIT-TEST-SECRET-31337")
        module = _load_eval_module()
        runner, _ = make_runner()
        run_dir = tmp_path / "offline_run"
        code = module.run_retrieval_evaluation(
            benchmark_path=BENCHMARK, k_values=[1, 5, 10, 20], strategies=["hybrid"], mode="offline",
            output_dir=str(run_dir), git_runner=runner, stats_resamples=100,
        )
        assert code == 0
        manifest_text = (run_dir / "manifest.json").read_text(encoding="utf-8")
        assert "UNIT-TEST-SECRET" not in manifest_text
        manifest = json.loads(manifest_text)
        assert manifest["citable"] is False and "mode_not_live: offline" in manifest["citable_reasons"]
        assert manifest["git_commit"]
        assert manifest["provenance"]["git_commit"] == "abc123"
        assert manifest["provenance"]["benchmark"]["sha256"] == file_sha256(BENCHMARK)
        assert set(manifest["provenance"]) >= {"git_describe", "git_dirty", "git_dirty_paths", "git_diff_sha256",
                                               "untracked_files", "llm", "neo4j", "graph_snapshot", "python"}
        assert "per_query.jsonl" in manifest["artifacts_generated"]

        lines = (run_dir / "per_query.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 21
        records = [json.loads(line) for line in lines]
        assert all(PER_QUERY_KEYS <= set(r) for r in records)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["dialogue"]["spurious_clarify"]["n"] == 21
        assert summary["metric_labels"]["popularity_bias"].startswith("review-coverage-bias@K")
        assert summary["comparisons"]["primary"][1]["status"] == "arm_missing"


class TestModelIdRecording:
    """AC-024."""

    def _handler(self):
        from src.llm.simple_llm_handler import SimpleLLMHandler
        return SimpleLLMHandler(api_key="sk-test-not-used")

    def test_record_response_model(self):
        handler = self._handler()
        assert handler.model_name == "gpt-4o" and handler.resolved_model_ids == set()
        handler.record_response_model(AIMessage(content="x", response_metadata={"model_name": "gpt-4o-2024-08-06"}))
        handler.record_response_model(AIMessage(content="y"))
        handler.record_response_model(object())
        assert handler.resolved_model_ids == {"gpt-4o-2024-08-06"}

    def test_aquery_records_model(self):
        handler = self._handler()
        fake_llm = MagicMock()

        async def _ainvoke(messages):
            return AIMessage(content="hello", response_metadata={"model_name": "gpt-4o-2024-11-20"})

        fake_llm.ainvoke = _ainvoke
        handler.llm = fake_llm
        assert asyncio.run(handler.aquery([])) == "hello"
        assert handler.resolved_model_ids == {"gpt-4o-2024-11-20"}

    def test_parser_tolerates_handlers_without_hook(self):
        from src.llm_interface.preference_parser import LLMPreferenceParser

        class _NoHook:
            def __init__(self):
                self.llm = MagicMock()

        parser = LLMPreferenceParser(llm_handler=_NoHook())
        result = parser.extract_preferences("I want a kettle")
        assert "current_session_context" in result

    def test_parser_calls_hook_with_tool_call_result(self):
        from src.llm_interface.preference_parser import LLMPreferenceParser

        class _Hook:
            def __init__(self):
                self.llm = MagicMock()
                self.seen = []

            def record_response_model(self, response):
                self.seen.append(response)

        handler = _Hook()
        parser = LLMPreferenceParser(llm_handler=handler)
        parser.extract_preferences("I want a kettle")
        assert len(handler.seen) == 1


class _Record(dict):
    def single(self):
        return self


class _Session:
    def run(self, cypher, params=None):
        if "dbms.components" in cypher:
            return _Record(name="Neo4j Kernel", version="5.14.0", edition="community")
        if "ParentProduct" in cypher:
            return _Record(n=10)
        if "Category" in cypher:
            raise RuntimeError("count failed")
        return _Record(n=3)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_runtime_provenance():
    orchestrator = MagicMock()
    orchestrator.llm_handler.model_name = "gpt-4o"
    orchestrator.llm_handler.resolved_model_ids = {"gpt-4o-2024-08-06"}
    orchestrator.graph_tool.db.session.return_value = _Session()
    orchestrator.category_recovery = True
    runtime = collect_runtime_provenance(orchestrator, 5715)
    assert runtime["llm"] == {"alias": "gpt-4o", "resolved_model_ids": ["gpt-4o-2024-08-06"]}
    assert runtime["neo4j"] == {"name": "Neo4j Kernel", "version": "5.14.0", "edition": "community"}
    assert runtime["graph_snapshot"] == {"products": 10, "categories": None, "reviews": 3, "review_embedded_products": 5715}
    assert runtime["category_recovery"] is True
    assert set(runtime["python"]) == {"version", "executable"}
    empty = collect_runtime_provenance(None, None)
    assert empty["llm"] == {"alias": None, "resolved_model_ids": []} and empty["neo4j"]["version"] is None
