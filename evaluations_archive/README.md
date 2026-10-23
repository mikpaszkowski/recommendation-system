# Evaluation Run Archive

This directory is tracked in git. It holds the evaluation runs that the thesis may refer to (Vision decision 2026-10-18-015, R2-D7; Technical Specification R2a §4.6).

## Policy

- **The thesis cites only archived runs.** A run under `evaluations/` (git-ignored) is local working data.
- **Only `citable: true` runs are evidence.** A run is citable when it ran in `--mode live` on the full benchmark (no `--sample-size`), with no uncommitted or untracked changes under `src/` or `scripts/`, and with a tracked, unmodified benchmark file. The manifest records the reasons in `citable_reasons`.
- **`citable: false` runs are context, not evidence.** The pre-R2 runs archived with `--legacy` carry a note explaining why. Their `per_query.jsonl` is reconstructed (`legacy_reconstructed: true`), and fields those runs did not record are `null`.
- **Traces are referenced by hash.** `execution_trace.log` is not copied. `ARCHIVE.json` records its SHA-256, byte size and line count, so a locally kept trace can be matched to the archive.

## Archived runs

| Run | Citable | Notes |
|---|---|---|
| `eval_2026-10-09_1336` | no (legacy) | Pre-R1 hybrid-only baseline. `git_commit` records HEAD only |
| `eval_2026-10-17_1846`, `eval_2026-10-17_1937` | no (legacy) | R1 arm comparison and R1 audit run. Ran uncommitted; the recorded commit does not identify the evaluated code |
| `eval_2026-10-18_2340`, `_2349`, `_2358` | yes | R2a exit-gate runs at `88cdbdf`, legacy-21 benchmark, 0/21 spurious CLARIFY in each (Graph v1 evidence) |
| `eval_2026-10-20_1114`, `_1128`, `_1142` | yes | Graph v2 baseline runs at `4248d03`, legacy-21 benchmark, 0 ghost products, GraphVersion v2 (Graph v2 evidence) |
| `eval_2026-10-22_2254` | yes | Release R3.2 live evaluation at `4fb77f7`, 13 fusion arms, 100% Target Admission, peak wrrf4 HR@20 = 0.571, MRR = 0.364 |

`index.json` is the authoritative list; the table is a summary.

## Reading a manifest

- `provenance.git_dirty`, `git_dirty_paths` and `untracked_files` cover `src/` and `scripts/` only (`provenance.git_scope`). The citable decision uses these fields.
- `provenance.git_describe` comes from `git describe --always --dirty` and covers the **whole repository**. It can end in `-dirty` (for example `88cdbdf-dirty` in the three R2a runs) because of an unrelated tracked file outside `src/` and `scripts/`, while `git_dirty` is `false` and `citable` is `true`. Trust `git_dirty` and `citable`, not the suffix.

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

# Check the R2a exit gate on three runs (looks in evaluations/ first, then evaluations_archive/)
python scripts/check_eval_gate.py --runs <R_a> <R_b> <R_c> --max-spurious-clarify 0
```

`archive_eval_run.py` takes a run ID, not a path. `--force` overwrites an existing archive folder, and a refused run never deletes one. The archive script never modifies the source run.
