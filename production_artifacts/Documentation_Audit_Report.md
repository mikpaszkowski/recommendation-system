# Documentation Audit Report

**Date**: 2026-10-19
**Auditor**: Documentation Auditor Agent (@doc-cleaner)
**Scope**: Documentation affected by release R2a (RS-23 spurious-CLARIFY fix with the `product_type_decided` gate, constraint-satisfaction@K, paired statistics, citable-run provenance, `evaluations_archive/`, exit gate) on `feature/afp-002-vector-aggregation`, commits `5446dcf..HEAD` since R1's `9cbf426`
**Previous report**: The R1 audit (2026-10-17) previously at this path is preserved in git history (`git show 9cbf426:production_artifacts/Documentation_Audit_Report.md`). The 2026-10-09 full audit is at `git show 2fdf251:production_artifacts/Documentation_Audit_Report.md`.

## Executive Summary

The docs that track R2 were checked against the R2a code (`src/agents/orchestrator.py`, `src/evaluation/{provenance,stats,constraint_satisfaction,dialogue_metrics,metrics}.py`, `scripts/{evaluate_retrieval,archive_eval_run,check_eval_gate}.py`) and the archived gate runs. The Implementation Plan and the roadmap still listed RS-23, RS-20 (rest) and the R2 gate as open; they now show R2a done and R2b (RS-21, RS-02 evidence) open. The README did not mention `--require-clean`, the gate checker, the archive script or `evaluations_archive/`; it does now. `.env.example` and `evaluations_archive/README.md` were already accurate and were extended or confirmed. The architecture diagram's guardrail text ("category missing → CLARIFY") no longer matched the code; the HTML is fixed, but the rendered JPG is stale and needs a re-render. Last time's flag "evaluation artifacts are not versioned" is **resolved** by `evaluations_archive/`; the flag "no thesis contribution for R1" is **resolved** by `thesis/10-doc-fusion-ablation.md`. Open: the Audit Report's top status lines are stale, and several documents from the separate graph-v2 workstream will need updating once that work is committed.

## Documentation Inventory

| File | Status | Category | Notes |
|------|--------|----------|-------|
| `production_artifacts/Implementation_Plan.md` | ✅ (fixed) | Plan | Header R2a line; A1.1 status; R2 block split into R2a (RS-23, RS-20 rest, statistics, provenance, archive: done) and R2b (RS-21, RS-02 evidence: open); A6 baseline and label-free-metrics items; AI-07 "1500 → 150" part done; gap-table row |
| `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` | ✅ (fixed) | Roadmap | Header status; RS-02, RS-20, RS-21, RS-23 rows; release table R2 split into R2a / R2b with gates; metric rename note; statistics and citable-run note |
| `production_artifacts/action_items/README.md` | ✅ (fixed) | Index | Roadmap row: R1 and R2a done, R2b next, Vision 014 … 017 |
| `README.md` | ✅ (fixed) | Setup | `--require-clean`, `--stats-seed` / `--stats-resamples`, `scripts/check_eval_gate.py`, `scripts/archive_eval_run.py`, `ORCH_CATEGORY_RECOVERY`; `evaluations/` and `evaluations_archive/` in the directory list |
| `.env.example` | ✅ | Config | `ORCH_CATEGORY_RECOVERY=1` matches `AgentOrchestrator._resolve_category_recovery` (default on; `0`, `false`, `no` disable) |
| `evaluations_archive/README.md` | ✅ (extended) | Policy | Policy, layout and commands match `archive_eval_run.py` and `check_eval_gate.py`. Added the archived-run table, a manifest-reading note (`git_describe` is repository-wide, QA observation L-14) and the run-ID / `--force` behaviour |
| `evaluations_archive/index.json`, run folders | ✅ | Archive | Six runs: three legacy (`citable: false`), three citable R2a runs at `88cdbdf` with one benchmark hash |
| `diagrams/crs_detailed_architecture.html` | ✅ (fixed) | Diagram | Guardrail card now describes category recovery; roadmap line and date updated. **JPG not re-rendered** (see Flagged) |
| `diagrams/crs_detailed_architecture_2026-10-17.jpg` | ⏰ | Diagram | Shows the old guardrail card text and the 2026-10-17 roadmap line |
| `diagrams/conversation_flow.md` | ✅ | Diagram | Older flow chart; does not show the guardrail or recovery, but states nothing wrong about them |
| `production_artifacts/Technical_Specification.md` | ✅ | Pipeline | R2a spec with amendments A-1 … A-13; consistent with the code. Not edited |
| `production_artifacts/Audit_Report.md` | ⚠️ | Pipeline | Gate section at the end is current; header lines 6-8 are stale (see Conflicting). Not edited |
| `production_artifacts/Research_Report.md` | ✅ | Pipeline | R2 research; the "1500 → 150" recommendation was implemented as FR-011. Not edited |
| `production_artifacts/Vision_Report.md` | ✅ | Vision | Decisions 2026-10-18-014 … 017 describe R2 and match the delivered R2a; not modified by this audit |
| `docs/changelog/changelog.md` | ✅ | Changelog | Not read for edits; @historian is appending in parallel |
| `thesis/10-doc-fusion-ablation.md`, `11-doc-evaluation-protocol.md`, `12-doc-clarification-gating.md`, `thesis/README.md` | ✅ | Thesis | Listed in `thesis/README.md`; not touched |
| `src/README.md`, `src/knowledge_graph/README.md` | ✅ | Overview | No R2a-specific detail |
| `production_artifacts/Evaluation_Failure_Analysis.md`, AFP documents, `Live_Graph_Audit_2026-10-10.md` | ✅ | Historical | Dated records; AI-07 progress is tracked in the plan |

## Findings by Severity

### ⚠️ Conflicting Documentation
- **Audit Report header vs its own gate section**: `production_artifacts/Audit_Report.md` lines 6-8 say "PASS WITH FIXES … H-1 is open … The live exit gate has not run yet" and "uncommitted working tree on top of `9cbf426`", while the end of the same file records H-1 fixed (`5446dcf`), the exit gate PASS at `88cdbdf`, and the three runs archived. The code and the gate section agree; the header is stale. **Flagged** (the Audit Report is @qa's file and was not edited).
- **Implementation Plan vs Audit Report on R2a**: the plan listed RS-23, RS-20 (rest) and RS-21 as open while the Audit Report recorded the gate as passed. **Resolved** in favour of the audit and the code: RS-23 and RS-20 done, RS-21 open as R2b.

### ⏰ Outdated Documentation
- **Plan R2 block**: RS-23 and RS-20 (rest) unchecked, no R2a / R2b split (Vision 2026-10-18-015 sets that order). **Fixed**, with the still-open leftovers named (ambiguous-stratum clarification recall in R2b, vocabulary fallback in RS-24, parser merge in AI-07).
- **Plan A6**: "Live baseline: `eval_2026-10-09_1336`" with no mention of citable runs; the label-free metrics item still listed `popularity-bias@K` and `constraint-satisfaction@K` as scheduled. **Fixed**: citable reference runs named, `review-coverage-bias@K` rename noted, RS-20 done, RS-21 open.
- **Plan AI-07**: still asked to "Fix the '1500 → 150' example". `SEARCH_GENERATION_PROMPT` now says `price_max` to 1500 (FR-011). **Fixed** with a dated note; the merge itself stays open.
- **Plan gap table, roadmap header, roadmap release table, RS-02 / RS-20 / RS-21 / RS-23 rows, action-items index**: "R2 next", "Decided", "removal decided in R2". **Fixed**.
- **README**: no mention of the citable-run workflow, the gate checker, the archive script or `--require-clean`. **Fixed**.
- **Architecture diagram**: "Guardrail: category missing → CLARIFY". The code (`AgentOrchestrator._decide_next_step`) keeps SEARCH when any category source exists, otherwise makes one recovery call and accepts its category only if `product_type_decided` is true; CLARIFY follows only when none is found (or recovery is disabled). **HTML fixed; JPG stale**.
- **Plan / roadmap metric name**: `popularity-bias@K` measures review-embedding coverage, and reports call it `review-coverage-bias@K` (code key `popularity_bias@k` unchanged). Noted in the plan and roadmap; R1-era text that uses the old name is kept as history.

### 📋 Duplicated Content
- R2a gate results appear in the Audit Report, the plan R2 block, the roadmap header and `evaluations_archive/README.md`. The Audit Report ("R2a exit gate") is canonical; the others are one-line summaries with the same run IDs and commit (`88cdbdf`).

### 🔗 Stale References
- No broken paths found in the scoped documents. The commands in `README.md` and `evaluations_archive/README.md` match the argparse definitions (`archive_eval_run.py` takes a run ID, not a path; `check_eval_gate.py` resolves runs from `evaluations/` then `evaluations_archive/`).
- `production_artifacts/Research_Report_Graph_Rebuild.md` (lines 23, 246) says `evaluations_archive/` holds only the three legacy R1 runs and that the K-2 gate is not met. That is no longer true: the three citable R2a runs are archived. The file belongs to the graph-v2 workstream and was not touched.

### 🕳️ Missing Documentation
- **Rendered diagram**: no current JPG for the updated guardrail card (see Flagged).
- **Project instructions**: `CLAUDE.md` lists neither `evaluations_archive/` in Project Structure nor `scripts/check_eval_gate.py` / `scripts/archive_eval_run.py` in the commands. Not edited (project instructions).
- **Graph-v2 workstream**: `src/knowledge_graph/graph_v2/`, `scripts/graph_ingestion/{build,import,post_import,preflight}_graph_v2.py`, `validate_graph.py`, `check_baseline_diff.py`, `export_v1_snapshot.py`, `Research_Report_Graph_Rebuild.md`, `Technical_Specification_Graph_Rebuild.md` and Vision decisions 2026-10-19-018 … 021 are uncommitted and from another session. When committed, these will need: a plan section (the plan has no graph-rebuild phase, and F-phase and A1.1 data facts will change), README directory and getting-started steps, `CLAUDE.md` project structure, and `.env.example` review (`scripts/graph_ingestion/preflight_v2.py` and `import_graph_v2.py` read `os.environ`). Also `production_artifacts/Technical_Specification.md` is the R2a spec, so the rebuild spec lives in a separate file. Noted only.

### ✅ Resolved from the previous audit
- **"Evaluation artifacts are not versioned"**: resolved. `evaluations_archive/` is git-tracked (`.gitignore` un-ignores its CSVs), holds `ARCHIVE.json` hashes and a trace fingerprint per run, and has `index.json` and a policy README. The runs cited by the plan (`eval_2026-10-09_1336`, `_1846`, `_1937`) are archived as non-citable context; the R2a gate runs are citable.
- **"No thesis contribution for R1"**: resolved by `thesis/10-doc-fusion-ablation.md` (listed in `thesis/README.md`). Not touched.

### ✅ Valid Documentation
- Technical Specification (R2a, with §13 amendments), Research Report (R2), Vision decisions 2026-10-18-014 … 017, `.env.example`, `evaluations_archive/` policy, historical AFP and failure-analysis documents, dated thesis contributions.

## Fixes Applied

| File | Change | Reason |
|------|--------|--------|
| `production_artifacts/Implementation_Plan.md` | Header R2a line; A1.1 status; R2 block split into R2a (done) and R2b (open); A6 baseline and metrics items; AI-07 note; gap-table row | Outdated status |
| `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` | Header; RS-02 / RS-20 / RS-21 / RS-23 rows; release table R2a / R2b; R1-7 and §6 metric rename; statistics note | Outdated status, renamed metric |
| `production_artifacts/action_items/README.md` | Roadmap row status | Outdated status |
| `README.md` | Citable-run, gate and archive commands; `--require-clean`; stats flags; `ORCH_CATEGORY_RECOVERY`; two directory entries | Undocumented CLI options and directory |
| `evaluations_archive/README.md` | Archived-run table; manifest-reading note (`git_describe` scope); run-ID, `--force` and gate-lookup notes | Missing reader guidance (QA L-14) |
| `diagrams/crs_detailed_architecture.html` | Guardrail card text; roadmap line; "flows as of" date | Outdated description |

## Flagged for User Approval

1. Re-render `diagrams/crs_detailed_architecture_2026-10-17.jpg` from the updated HTML (this audit had no rendering tool). Also decide on the untracked `diagrams/crs_detailed_architecture_1791405352600.jpg`: its origin is unknown, and it may be a render of an older or newer HTML. Delete or keep is your call; nothing was deleted.
2. Ask @qa to refresh the header of `production_artifacts/Audit_Report.md` (lines 6-8: status, "gate has not run yet", branch base) so it matches the R2a exit gate section.
3. Update `CLAUDE.md` (Project Structure and Build & Test Commands) with `evaluations_archive/`, `scripts/check_eval_gate.py` and `scripts/archive_eval_run.py`.
4. After the graph-v2 work is committed, run a follow-up audit: plan phase, README, `CLAUDE.md`, `.env.example`, and the stale "archive holds only R1 legacy runs" statement in `Research_Report_Graph_Rebuild.md` (K-2 gate is met now).
5. Vision Report (for @pm-research): nothing to change for R2a. The standing note from R1 remains: decision 2026-09-28-006 still says "Lucene full-text second" (superseded; recorded in 2026-10-18-017).
