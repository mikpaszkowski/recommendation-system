# Evaluation Run Archive

This directory is tracked in git. It holds the evaluation runs that the thesis may refer to (Vision decision 2026-10-18-015, R2-D7; Technical Specification R2a §4.6).

## Policy

- **The thesis cites only archived runs.** A run under `evaluations/` (git-ignored) is local working data.
- **Only `citable: true` runs are evidence.** A run is citable when it ran in `--mode live` on the full benchmark (no `--sample-size`), with no uncommitted or untracked changes under `src/` or `scripts/`, and with a tracked, unmodified benchmark file. The manifest records the reasons in `citable_reasons`.
- **`citable: false` runs are context, not evidence.** The pre-R2 runs archived with `--legacy` carry a note explaining why. Their `per_query.jsonl` is reconstructed (`legacy_reconstructed: true`), and fields those runs did not record are `null`.
- **Traces are referenced by hash.** `execution_trace.log` is not copied. `ARCHIVE.json` records its SHA-256, byte size and line count, so a locally kept trace can be matched to the archive.

## Layout

```
evaluations_archive/
  index.json                 # one entry per archived run: run_id, citable, legacy, timestamp, git_commit, benchmark_sha256, note
  <run_id>/
    manifest.json            # copy (legacy runs gain citable: false and an "archive" block)
    summary.json             # copy
    retrieval_metrics.csv    # copy
    per_query.jsonl          # copy, or reconstructed for legacy runs
    ARCHIVE.json             # SHA-256 of each archived file, trace fingerprint, archived_at, archived_from_commit
```

## Commands

```bash
# Archive a citable live run
python scripts/archive_eval_run.py eval_YYYY-MM-DD_HHMM

# Archive a pre-R2 run as non-citable context
python scripts/archive_eval_run.py eval_YYYY-MM-DD_HHMM --legacy --note "<why it is not citable>"

# Check the R2a exit gate on three runs
python scripts/check_eval_gate.py --runs <R_a> <R_b> <R_c> --max-spurious-clarify 0
```
