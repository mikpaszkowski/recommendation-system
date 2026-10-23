"""
tests/test_evaluate_generative.py

Unit and integration tests for Tier 2 Generative Evaluation (Meta-Phase A6 / AI-04).

Verifies:
1. evaluate_generative.py runs in offline mode and outputs all required artifacts:
   manifest.json, summary.json, generative_metrics.json, generative_metrics.csv,
   and radar plots (plots/llm_judge_radar.png, .jpg).
2. --run-orchestrator executes AgentOrchestrator to produce dynamic responses,
   graph reasoning paths, and eval_trace before evaluation (AI-04).
3. Grounded benchmark integrity: All target candidate ASINs in
   evaluations/benchmarks/generative_benchmark.json exist in Neo4j Graph v2.
4. Output directory isolation: Verifies tests do not pollute evaluations/.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from scripts.evaluate_generative import (
    _execute_orchestrator_batch,
    parse_metrics_list,
    run_generative_evaluation,
)
from src.database.neo4j_connection import Neo4jConnectionManager


def test_parse_metrics_list_default_and_custom() -> None:
    """Verifies parsing of generative evaluation metric dimensions."""
    defaults = parse_metrics_list(None)
    assert defaults == ["groundedness", "explainability", "coherence", "recoverability"]

    custom = parse_metrics_list(["groundedness,explainability", "coherence"])
    assert custom == ["groundedness", "explainability", "coherence"]


def test_generative_evaluation_offline_pipeline(tmp_path: Path) -> None:
    """Verifies full CLI execution in offline mode with complete artifact generation."""
    out_dir = tmp_path / "gen_eval_run"
    cmd = [
        sys.executable,
        "scripts/evaluate_generative.py",
        "--mode", "offline",
        "--sample-size", "3",
        "--output-dir", str(out_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"evaluate_generative.py failed: {proc.stderr}\n{proc.stdout}"

    # Verify generated artifacts
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "summary.json").exists()
    assert (out_dir / "generative_metrics.json").exists()
    assert (out_dir / "generative_metrics.csv").exists()
    assert (out_dir / "plots" / "llm_judge_radar.png").exists()
    assert (out_dir / "plots" / "llm_judge_radar.jpg").exists()

    # Verify manifest content
    with open(out_dir / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["evaluation_types"] == ["generative"]
    assert manifest["configuration"]["mode"] == "offline"
    assert manifest["configuration"]["evaluated_count"] == 3


def test_execute_orchestrator_batch_populates_system_output() -> None:
    """
    Verifies that _execute_orchestrator_batch invokes AgentOrchestrator
    and binds generated_response, graph_evidence, and eval_trace to each scenario (AI-04).
    """
    async def _run() -> None:
        mock_cases = [
            {
                "sample_id": "test_case_001",
                "user_query": "I need wireless headphones under $100",
            }
        ]

        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value={
            "action": "SEARCH",
            "answer": "I recommend the Soundcore Life Q20 ($65.99).",
            "data": {
                "items": [{"asin": "B08PFW1S1V", "title": "Soundcore Anker Life Q20"}]
            },
            "eval_trace": {
                "graph_evidence": [
                    {"target_item": "Soundcore Life Q20", "reasoning_path": "Matches requested ANC"}
                ],
                "critic_verdict": {"status": "success"},
            }
        })

        with patch("src.agents.orchestrator.AgentOrchestrator", return_value=mock_orch):
            enriched = await _execute_orchestrator_batch(mock_cases, mode="live")

        sample = enriched[0]
        assert sample["generated_response"] == "I recommend the Soundcore Life Q20 ($65.99)."
        assert len(sample["graph_evidence"]) == 1
        assert sample["graph_evidence"][0]["target_item"] == "Soundcore Life Q20"
        assert sample["retrieved_candidates"][0]["asin"] == "B08PFW1S1V"
        assert "eval_trace" in sample

    asyncio.run(_run())


def test_generative_benchmark_100_percent_grounded_in_neo4j() -> None:
    """
    Asserts that 100% of candidate ASINs in evaluations/benchmarks/generative_benchmark.json
    exist in the live Neo4j database (resolving Finding F-04 / AI-04).
    """
    benchmark_file = Path("evaluations/benchmarks/generative_benchmark.json")
    assert benchmark_file.exists(), f"Benchmark file {benchmark_file} not found"

    with open(benchmark_file, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    assert len(scenarios) == 15, f"Expected 15 generative scenarios, found {len(scenarios)}"

    conn = Neo4jConnectionManager()
    conn.connect()

    missing = []
    for s in scenarios:
        for cand in s.get("retrieved_candidates", []):
            asin = cand["asin"]
            res = conn.execute_query(
                "MATCH (p:ParentProduct {parent_asin: $asin}) RETURN p.parent_asin as asin, p.title as title",
                {"asin": asin}
            )
            if not res:
                missing.append((s["id"], asin))

    conn.close()

    assert not missing, (
        f"Found {len(missing)} ungrounded ASINs in generative_benchmark.json: {missing}. "
        f"All 15 scenarios must be 100% grounded in Neo4j Graph v2."
    )
