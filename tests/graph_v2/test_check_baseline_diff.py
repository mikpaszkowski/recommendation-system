"""
tests/graph_v2/test_check_baseline_diff.py

Baseline-commit allow-list check (§6.6, OQ-2, D-12). Git is reached only through a fake runner.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cli():
    spec = importlib.util.spec_from_file_location("check_baseline_diff_under_test", REPO_ROOT / "scripts" / "graph_ingestion" / "check_baseline_diff.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runner(out: str, code: int = 0):
    calls = []

    def run(args):
        calls.append(list(args))
        return code, out
    return run, calls


def test_allow_listed_paths_pass() -> None:
    """Only allow-listed graph v2 paths changed -> exit 0; the diff is scoped to src, scripts and the benchmark."""
    module = _cli()
    run, calls = _runner("src/evaluation/provenance.py\nsrc/knowledge_graph/graph_v2/transform.py\nscripts/graph_ingestion/post_import_v2.py\n")
    assert module.main(["--base", "88cdbdf"], runner=run) == 0
    assert calls[0] == ["diff", "--name-only", "88cdbdf", "HEAD", "--", "src", "scripts", "live_eval_dataset.json"]


def test_path_outside_allow_list_fails() -> None:
    """A retrieval-code or benchmark change -> exit 1."""
    module = _cli()
    run, _ = _runner("src/tools/graph_search_tool.py\nsrc/evaluation/provenance.py\n")
    assert module.main(["--base", "88cdbdf"], runner=run) == 1
    run, _ = _runner("live_eval_dataset.json\n")
    assert module.main(["--base", "88cdbdf", "--head", "abc"], runner=run) == 1
    assert module.is_allowed("scripts/evaluate_retrieval.py") and not module.is_allowed("scripts/check_eval_gate.py")


def test_git_failure_exits_2() -> None:
    """git failure -> exit 2."""
    run, _ = _runner("", code=128)
    assert _cli().main(["--base", "nope"], runner=run) == 2


def test_docs_and_compose_are_allowed() -> None:
    """A-7: documentation (.md, including deleted docs) and docker-compose.yml never block the baseline; code still does."""
    module = _cli()
    run, _ = _runner("src/README.md\nsrc/knowledge_graph/DOCKER.md\nsrc/knowledge_graph/QUICKSTART.md\n"
                     "src/knowledge_graph/docker-compose.yml\nsrc/evaluation/provenance.py\n")
    assert module.main(["--base", "88cdbdf"], runner=run) == 0
    assert not module.is_allowed("src/tools/graph_search_tool.py")
    assert not module.is_allowed("src/knowledge_graph/docker-compose.override.yml")

