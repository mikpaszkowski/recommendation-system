#!/usr/bin/env python3
"""
CLI Evaluation Script for Tier 2: Generative & Conversational LLM-as-a-Judge Engine.

Evaluates conversational recommendations across four decomposed quality pillars:
1. Groundedness (KG adherence and Hard Dilution Cap Rule)
2. Explainability (Graph reasoning path provenance and fidelity)
3. Coherence (Multi-turn dialogue context retention)
4. Recoverability (Negative feedback adaptation and negative constraint penalty)

Supports dual modes:
- Offline Mock Mode (--mode offline / --offline): Deterministic heuristic execution
- Live Mode (--mode live): Live LLM-as-a-Judge invocations via OpenAI models

Outputs versioned run artifacts (manifest.json, summary.json, generative_metrics.json,
generative_metrics.csv, and publication-grade plots in plots/).
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.judge import evaluate_generative_batch
from src.evaluation.tracker import create_evaluation_run_dir, save_run_artifacts
from src.evaluation.visualizer import plot_generative_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate_generative")


def get_git_commit() -> str:
    """Retrieves current git commit hash if available."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return "HEAD_EVAL"


def parse_metrics_list(raw_input: Optional[List[str]]) -> List[str]:
    """Parses metrics list from comma or space-separated arguments."""
    if not raw_input:
        return ["groundedness", "explainability", "coherence", "recoverability"]
    joined = " ".join(raw_input)
    metrics = [x.strip().lower() for x in joined.replace(",", " ").split() if x.strip()]
    return metrics if metrics else ["groundedness", "explainability", "coherence", "recoverability"]


def run_generative_evaluation(
    benchmark_path: Path,
    judge_model: str = "gpt-4o-mini",
    metrics_list: Optional[List[str]] = None,
    sample_size: Optional[int] = None,
    mode: str = "live",
    output_dir: Optional[str] = None,
) -> int:
    """Executes generative evaluation and persists artifacts."""
    logger.info(f"Loading generative benchmark from: {benchmark_path}")
    if not benchmark_path.exists():
        logger.error(f"Benchmark file not found: {benchmark_path}")
        return 1

    with open(benchmark_path, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    if not isinstance(test_cases, list):
        logger.error("Benchmark JSON must be a list of scenario objects.")
        return 1

    if sample_size is not None and sample_size > 0:
        test_cases = test_cases[:sample_size]

    logger.info(f"Loaded {len(test_cases)} generative scenarios. Running mode: {mode} (judge: {judge_model})")
    offline = mode in ("offline", "mock")

    # Run batch LLM-as-a-Judge evaluation
    batch_results = evaluate_generative_batch(test_cases, judge_model=judge_model, offline=offline)
    aggregates = batch_results["aggregates"]
    per_sample_results = batch_results["per_sample_results"]

    logger.info("Generative evaluation complete.")
    logger.info(f"Groundedness:   {aggregates.get('groundedness_mean', 0.0):.2f} / 5.0")
    logger.info(f"Explainability: {aggregates.get('explainability_mean', 0.0):.2f} / 5.0")
    logger.info(f"Coherence:      {aggregates.get('coherence_mean', 0.0):.2f} / 5.0")
    logger.info(f"Recoverability: {aggregates.get('recoverability_mean', 0.0):.2f} / 5.0")
    logger.info(f"Composite Score:{aggregates.get('composite_score', 0.0):.2f} / 5.0")

    # Set up output directory
    if output_dir:
        run_dir = Path(output_dir)
        run_id = run_dir.name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "plots").mkdir(parents=True, exist_ok=True)
    else:
        run_dir, run_id = create_evaluation_run_dir(base_dir="evaluations", prefix="eval")

    # Render publication-grade LLM-as-a-Judge dimension plots
    chart_scores = {
        "Groundedness": aggregates.get("groundedness_mean", 0.0),
        "Explainability": aggregates.get("explainability_mean", 0.0),
        "Coherence": aggregates.get("coherence_mean", 0.0),
        "Recoverability": aggregates.get("recoverability_mean", 0.0),
    }

    plot_png = run_dir / "plots" / "llm_judge_radar.png"
    plot_jpg = run_dir / "plots" / "llm_judge_radar.jpg"
    plot_generative_metrics(chart_scores, plot_png, format="png", dpi=300)
    plot_generative_metrics(chart_scores, plot_jpg, format="jpg", dpi=300)

    # Persist versioned run artifacts
    manifest: Dict[str, Any] = {
        "run_id": run_id,
        "timestamp": datetime.datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "evaluation_types": ["generative"],
        "configuration": {
            "mode": mode,
            "benchmark": str(benchmark_path),
            "judge_model": judge_model,
            "metrics": metrics_list,
            "sample_size": sample_size,
            "evaluated_count": len(test_cases),
        },
        "artifacts_generated": [
            "manifest.json",
            "summary.json",
            "generative_metrics.json",
            "generative_metrics.csv",
            "plots/llm_judge_radar.png",
            "plots/llm_judge_radar.jpg",
        ],
    }

    save_run_artifacts(run_dir, manifest, batch_results)
    logger.info(f"Artifacts successfully persisted to: {run_dir}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CRS Generative Quality using LLM-as-a-Judge.")
    parser.add_argument("--mode", choices=["live", "offline", "mock"], default="live", help="Execution mode (default: live)")
    parser.add_argument("--offline", action="store_true", help="Shortcut for --mode offline")
    parser.add_argument(
        "--benchmark",
        "--dataset",
        dest="benchmark",
        default="evaluations/benchmarks/generative_benchmark.json",
        help="Path to generative benchmark JSON",
    )
    parser.add_argument("--judge-model", default="gpt-4o-mini", help="Judge model (default: gpt-4o-mini)")
    parser.add_argument(
        "--metrics",
        nargs="*",
        default=None,
        help="Evaluation dimensions (e.g. groundedness,explainability,coherence,recoverability)",
    )
    parser.add_argument("--sample-size", type=int, default=None, help="Limit number of evaluated samples")
    parser.add_argument("--output-dir", default=None, help="Directory to save evaluation artifacts")

    args = parser.parse_args()
    mode = "offline" if args.offline else args.mode
    metrics_list = parse_metrics_list(args.metrics)
    benchmark_file = Path(args.benchmark)

    exit_code = run_generative_evaluation(
        benchmark_path=benchmark_file,
        judge_model=args.judge_model,
        metrics_list=metrics_list,
        sample_size=args.sample_size,
        mode=mode,
        output_dir=args.output_dir,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
