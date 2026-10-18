#!/usr/bin/env python3
"""
Archive an evaluation run into the git-tracked evaluations_archive/ (R2a, FR-033 … FR-035;
Technical Specification §4.6).

Copies manifest.json, summary.json, retrieval_metrics.csv and per_query.jsonl into
evaluations_archive/<run_id>/, writes ARCHIVE.json (SHA-256 of every copied file plus the
SHA-256, byte size and line count of execution_trace.log, which is never copied) and updates
evaluations_archive/index.json. Only citable live runs are accepted unless --legacy --note is
given; legacy runs without per_query.jsonl get one reconstructed from retrieval_metrics.json and
the trace's END QUERY status lines (legacy_reconstructed: true). The source run is never modified.

Usage:
    python scripts/archive_eval_run.py <run_id> [--evaluations-dir evaluations]
        [--archive-dir evaluations_archive] [--legacy --note "<text>"] [--force]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.provenance import default_git_runner, file_sha256  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("archive_eval_run")

COPIED_FILES: Tuple[str, ...] = ("manifest.json", "summary.json", "retrieval_metrics.csv", "per_query.jsonl")
STATUS_TO_ACTION: Dict[str, str] = {"SUCCESS": "SEARCH", "CLARIFIED": "CLARIFY", "ERROR": "ERROR"}
END_QUERY_RE = re.compile(r"<<< \[END QUERY (\d+)/(\d+)\] ID: (\S+) \| Status: (\w+)")
TOP_K = 20
_CHUNK = 1024 * 1024


def parse_trace_statuses(trace_path: Path) -> Dict[str, str]:
    """Maps query_id -> action from the `<<< [END QUERY i/n] ID: … | Status: …` lines (streamed)."""
    statuses: Dict[str, str] = {}
    if not trace_path.exists():
        return statuses
    with open(trace_path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = END_QUERY_RE.search(line)
            if match:
                statuses[match.group(3)] = STATUS_TO_ACTION.get(match.group(4), match.group(4))
    return statuses


def trace_fingerprint(trace_path: Path) -> Optional[Dict[str, Any]]:
    """{sha256, bytes, lines} of execution_trace.log computed by streaming; None if absent."""
    if not trace_path.exists():
        return None
    digest = hashlib.sha256()
    size = 0
    newlines = 0
    last_byte = b""
    with open(trace_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
            newlines += chunk.count(b"\n")
            last_byte = chunk[-1:]
    lines = newlines + (1 if size and last_byte != b"\n" else 0)
    return {"sha256": digest.hexdigest(), "bytes": size, "lines": lines}


def _empty_record(query_id: str) -> Dict[str, Any]:
    """A per_query.jsonl record with every §5.1.7 key; fields pre-R2 runs did not record stay None."""
    return {
        "query_id": query_id, "action": None, "clarify_reason": None,
        "type_explicit": None, "gold_action": None, "gold_product_type": None,
        "parser_category": None, "pipeline_category": None, "category_source": None,
        "recovery_outcome": None, "applied_category": None, "target_admitted": None,
        "category_dropped_by_macs": None, "relaxed_constraints": None,
        "target_asin": None, "target_review_embedded": None, "target_channel_ranks": None,
        "gold_constraint_labels": None, "strategies": {}, "latency_ms": None,
        "legacy_reconstructed": True,
    }


def reconstruct_per_query(run_dir: Path, benchmark: Optional[Sequence[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Rebuilds per_query.jsonl records for a pre-R2 run from retrieval_metrics.json
    (per-strategy top-20 and target rank) and the trace status lines. Fields that pre-R2 runs
    did not record are None; every record has legacy_reconstructed = True.
    `benchmark` (optional) only supplies the target ASIN when a row lacks primary_target.
    """
    metrics_path = run_dir / "retrieval_metrics.json"
    with open(metrics_path, "r", encoding="utf-8") as handle:
        rows = json.load(handle).get("per_query_results") or []
    statuses = parse_trace_statuses(run_dir / "execution_trace.log")
    targets = {str(i.get("query_id") or i.get("id")): i.get("target_asin") for i in (benchmark or [])}

    records: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        qid = str(row.get("query_id") or "")
        if not qid:
            continue
        record = records.setdefault(qid, _empty_record(qid))
        target = row.get("primary_target") or targets.get(qid)
        record["target_asin"] = record["target_asin"] or target
        top = list(dict.fromkeys(a for a in (row.get("candidate_asins") or []) if a))[:TOP_K]
        strategy = str(row.get("strategy") or "hybrid")
        record["strategies"][strategy] = {
            "top20": top,
            "target_rank": (top.index(target) + 1) if target in top else None,
            "cs_gold": None,
            "cs_req": None,
        }
        if strategy == "hybrid" and isinstance(row.get("latency_ms"), (int, float)):
            record["latency_ms"] = row["latency_ms"]
    for qid, record in records.items():
        record["action"] = statuses.get(qid)
    return list(records.values())


def update_index(archive_dir: Path, entry: Dict[str, Any]) -> None:
    """Upserts {run_id, citable, legacy, timestamp, git_commit, benchmark_sha256, note} into index.json, sorted by run_id."""
    index_path = archive_dir / "index.json"
    entries: List[Dict[str, Any]] = []
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        entries = loaded if isinstance(loaded, list) else []
    entries = [e for e in entries if e.get("run_id") != entry["run_id"]] + [entry]
    entries.sort(key=lambda e: str(e.get("run_id")))
    with open(index_path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def _load_benchmark(manifest: Dict[str, Any], repo_root: Path) -> Optional[List[Dict[str, Any]]]:
    """The run's benchmark (for target ASINs during reconstruction), if it can still be read."""
    raw = (manifest.get("configuration") or {}).get("benchmark")
    if not raw:
        return None
    path = Path(raw) if Path(raw).is_absolute() else repo_root / raw
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else None
    except (OSError, ValueError) as e:
        logger.warning(f"Benchmark {path} unavailable for reconstruction: {e}")
        return None


def archive_run(
    run_id: str,
    evaluations_dir: Path,
    archive_dir: Path,
    legacy: bool = False,
    note: Optional[str] = None,
    force: bool = False,
    repo_root: Optional[Path] = None,
) -> int:
    """Archives one run; returns the process exit code (0 success, 1 refused or failed)."""
    repo_root = repo_root or REPO_ROOT
    run_dir = Path(evaluations_dir) / run_id
    manifest_path = run_dir / "manifest.json"
    if legacy and not (note and note.strip()):
        logger.error("--legacy requires --note explaining why the run is archived as non-citable context.")
        return 1
    if not run_dir.is_dir() or not manifest_path.exists():
        logger.error(f"Run directory or manifest.json missing: {run_dir}")
        return 1
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    mode = (manifest.get("configuration") or {}).get("mode")
    if not legacy and (manifest.get("citable") is not True or mode != "live"):
        logger.error(
            f"Run {run_id} is not a citable live run (citable={manifest.get('citable')!r}, mode={mode!r}). "
            f"citable_reasons: {manifest.get('citable_reasons')}"
        )
        return 1

    target_dir = Path(archive_dir) / run_id
    if target_dir.exists() and not force:
        logger.error(f"Archive folder {target_dir} exists; pass --force to overwrite.")
        return 1
    # Every refusal comes before the --force removal, so a refused run never deletes an existing archive
    if not legacy and not (run_dir / "per_query.jsonl").exists():
        logger.error(f"Run {run_id} has no per_query.jsonl; only --legacy runs may be reconstructed.")
        return 1
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    archived_at = datetime.datetime.now().isoformat(timespec="seconds")

    archived_manifest = dict(manifest)
    if legacy:
        archived_manifest["citable"] = False
        archived_manifest["archive"] = {"legacy": True, "note": note, "archived_at": archived_at}
    _write_json(target_dir / "manifest.json", archived_manifest)

    for name in ("summary.json", "retrieval_metrics.csv"):
        source = run_dir / name
        if source.exists():
            shutil.copyfile(source, target_dir / name)
        else:
            logger.warning(f"{name} missing in {run_dir}; not archived.")

    per_query_source = run_dir / "per_query.jsonl"
    if per_query_source.exists():
        shutil.copyfile(per_query_source, target_dir / "per_query.jsonl")
    else:
        records = reconstruct_per_query(run_dir, _load_benchmark(manifest, repo_root))
        with open(target_dir / "per_query.jsonl", "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
        logger.info(f"Reconstructed per_query.jsonl for {len(records)} queries (legacy_reconstructed: true).")

    code, out = default_git_runner(repo_root)(["rev-parse", "HEAD"])
    files = {name: file_sha256(target_dir / name) for name in COPIED_FILES if (target_dir / name).exists()}
    _write_json(target_dir / "ARCHIVE.json", {
        "run_id": run_id,
        "archived_at": archived_at,
        "archived_from_commit": out.strip() if code == 0 and out.strip() else None,
        "legacy": bool(legacy),
        "note": note,
        "files": files,
        "execution_trace": trace_fingerprint(run_dir / "execution_trace.log"),
    })

    provenance = manifest.get("provenance") or {}
    update_index(Path(archive_dir), {
        "run_id": run_id,
        "citable": bool(archived_manifest.get("citable") is True),
        "legacy": bool(legacy),
        "timestamp": manifest.get("timestamp"),
        "git_commit": provenance.get("git_commit") or manifest.get("git_commit"),
        "benchmark_sha256": (provenance.get("benchmark") or {}).get("sha256"),
        "note": note,
    })
    logger.info(f"Archived {run_id} -> {target_dir} ({len(files)} files)")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point (§4.6.1)."""
    parser = argparse.ArgumentParser(description="Archive an evaluation run into the git-tracked evaluations_archive/.")
    parser.add_argument("run_id", help="Run directory name, e.g. eval_2026-10-18_1530")
    parser.add_argument("--evaluations-dir", default=str(REPO_ROOT / "evaluations"))
    parser.add_argument("--archive-dir", default=str(REPO_ROOT / "evaluations_archive"))
    parser.add_argument("--legacy", action="store_true", help="Archive a non-citable pre-R2 run as context (requires --note)")
    parser.add_argument("--note", default=None, help="Why a legacy run is archived and how it may (not) be cited")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing archive folder")
    args = parser.parse_args(argv)
    return archive_run(
        args.run_id, Path(args.evaluations_dir), Path(args.archive_dir),
        legacy=args.legacy, note=args.note, force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
