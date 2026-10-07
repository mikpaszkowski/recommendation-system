"""
Versioned Execution Run Tracker and Artifact Persistence Engine.

Responsible for creating timestamped directories under evaluations/ and persisting:
- manifest.json: run metadata, git commit hash, hyperparameters, duration
- retrieval_metrics.json / generative_metrics.json: detailed raw scoring outputs
- retrieval_metrics.csv / generative_metrics.csv: tabular flattened outputs
- summary.json: high-level aggregate scorecards
"""
from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import json
import pandas as pd


def create_evaluation_run_dir(
    base_dir: Union[str, Path] = "evaluations",
    prefix: str = "eval",
) -> Tuple[Path, str]:
    """
    Creates an immutable timestamped directory for the evaluation run.

    Format:
        {base_dir}/{prefix}_YYYY-MM-DD_HHMM/ (or _HHMMSS or _HHMMSS_N if collision occurs)

    Ensures that a 'plots/' subdirectory is pre-created within the run directory.

    Returns:
        Tuple[Path, str]: (run_directory_path, run_id_string)
    """
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H%M")
    candidate_name = f"{prefix}_{timestamp_str}"
    candidate_dir = base_path / candidate_name

    # Try standard minute-level timestamp first
    try:
        candidate_dir.mkdir(parents=True, exist_ok=False)
        (candidate_dir / "plots").mkdir(parents=True, exist_ok=True)
        return candidate_dir, candidate_name
    except FileExistsError:
        pass

    # If minute-level exists, fall back to second-level with collision loop
    sec_base_name = f"{prefix}_{now.strftime('%Y-%m-%d_%H%M%S')}"
    candidate_name = sec_base_name
    candidate_dir = base_path / candidate_name
    counter = 1
    while True:
        try:
            candidate_dir.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            candidate_name = f"{sec_base_name}_{counter}"
            candidate_dir = base_path / candidate_name
            counter += 1

    (candidate_dir / "plots").mkdir(parents=True, exist_ok=True)
    return candidate_dir, candidate_name


def save_run_artifacts(
    run_dir: Path,
    manifest: Dict[str, Any],
    raw_metrics: Dict[str, Any],
    summary_df: Optional[pd.DataFrame] = None,
    figures: Optional[List[str]] = None,
) -> Dict[str, str]:
    """
    Persists evaluation artifacts to the designated run directory.

    Saves:
        1. manifest.json
        2. retrieval_metrics.json or generative_metrics.json
        3. retrieval_metrics.csv or generative_metrics.csv
        4. summary.json

    Returns:
        Dict mapping artifact keys to their absolute string paths.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: Dict[str, str] = {}

    # 1. Manifest
    manifest_path = run_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    saved_paths["manifest"] = str(manifest_path)

    # 2. Raw Metrics JSON
    aggregates = raw_metrics.get("aggregates", {})
    is_retrieval = "per_query_results" in raw_metrics or any("ndcg" in str(k) or "hr" in str(k) for k in aggregates)
    is_generative = "per_sample_results" in raw_metrics or any("groundedness" in str(k) for k in aggregates)

    if is_retrieval:
        metrics_path = run_dir / "retrieval_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(raw_metrics, f, indent=2)
        saved_paths["raw_metrics"] = str(metrics_path)
    elif is_generative:
        metrics_path = run_dir / "generative_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(raw_metrics, f, indent=2)
        saved_paths["raw_metrics"] = str(metrics_path)
    else:
        metrics_path = run_dir / "metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(raw_metrics, f, indent=2)
        saved_paths["raw_metrics"] = str(metrics_path)

    # 3. CSV Summary
    csv_filename = "retrieval_metrics.csv" if is_retrieval else "generative_metrics.csv"
    csv_path = run_dir / csv_filename
    if summary_df is not None:
        summary_df.to_csv(csv_path, index=False)
    else:
        items = raw_metrics.get("per_query_results") or raw_metrics.get("per_sample_results") or []
        if items:
            if is_retrieval:
                df = pd.DataFrame(items)
            else:
                # Flatten nested scores for generative scenarios
                flat_items = []
                for item in items:
                    flat = dict(item)
                    if "scores" in flat and isinstance(flat["scores"], dict):
                        for sk, sv in flat["scores"].items():
                            flat[f"{sk}_score"] = sv
                    flat_items.append(flat)
                df = pd.DataFrame(flat_items)
            df.to_csv(csv_path, index=False)
        else:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["status", "metric_count"])
                writer.writerow(["complete", len(aggregates)])
    saved_paths["summary_csv"] = str(csv_path)

    # 4. Summary JSON
    summary_path = run_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(aggregates, f, indent=2)
    saved_paths["summary_json"] = str(summary_path)

    return saved_paths
