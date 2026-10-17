# Documentation Audit Report

**Date**: 2026-10-17
**Auditor**: Documentation Auditor Agent (@doc-cleaner)
**Scope**: Documentation affected by release R1 (rank-based multi-channel fusion, AFP-002 via RRF) on `feature/afp-002-vector-aggregation`
**Previous report**: The 2026-10-09 full audit previously at this path is preserved in git history (`git show 2fdf251:production_artifacts/Documentation_Audit_Report.md`).

## Executive Summary

The docs that describe the retrieval score were checked against the R1 code. Status lines for AFP-002, the roadmap and the plan were still saying "not implemented / in progress", and those are corrected. One roadmap row contradicted the delivered metrics, and the architecture diagram had one wrong resolver label; both are fixed. Historical documents that describe the old `sum(score)` as the problem (AFP-002 analysis, failure analysis, brainstorm, dated thesis contributions) are accurate as records and were left unchanged. No conflicts remain open. One documentation gap is flagged: there is no thesis contribution document for R1 yet.

## Documentation Inventory

| File | Status | Category | Notes |
|------|--------|----------|-------|
| `production_artifacts/action_items/Proposed_Fix_Vector_Aggregation.md` | ✅ (fixed) | Status line | Now marked implemented 2026-10-17 via RRF |
| `production_artifacts/action_items/README.md` | ✅ (fixed) | Index | AFP-002 implemented; roadmap R1 done, RS range extended to RS-24 |
| `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` | ✅ (fixed) | Roadmap | Status header; RS-01/02/05/20 statuses; RS-20 release split corrected |
| `production_artifacts/Implementation_Plan.md` | ✅ (fixed) | Plan | A1 multi-index note (UNION now only in `sum_legacy`); gap table; RS range |
| `diagrams/crs_detailed_architecture.html` + `_2026-10-17.jpg` | ✅ (fixed) | Diagram | R1 shown as implemented; ablation arms named; resolver label corrected |
| `README.md` | ✅ (fixed) | Setup | `--fusion-arms` eval command added |
| `.env.example` | ✅ | Config | `RETRIEVAL_FUSION_ARM` documented (Phase 3) |
| `docs/changelog/changelog.md` | ✅ | Changelog | 2026-10-17 entry appended (Phase 5) |
| `production_artifacts/Vision_Report.md` | ✅ | Vision | Decision 2026-10-17-013 present; not modified by this audit |
| `production_artifacts/Technical_Specification.md`, `Research_Report.md`, `Audit_Report.md` | ✅ | Pipeline | Current for R1 |
| `production_artifacts/Evaluation_Failure_Analysis.md` | ✅ | Historical | Describes the `sum(score)` defect at the time; accurate as a record |
| `production_artifacts/action_items/Live_Graph_Audit_2026-10-10.md` | ✅ | Dated audit | AI-01 progress is tracked in the plan, not in the dated audit |
| `_bmad-output/brainstorming/brainstorm-retrieval-score-relevance-2026-10-10/*` | ✅ | Session record | Describes the problem and the decision; not a spec |
| `thesis/3-doc-robust-retrieval.md`, `thesis/4-doc-hybrid-scoring.md`, `thesis/7-doc-evaluation-framework.md` | ✅ | Dated contributions | Generic "multi-index" wording remains true; no `sum(score)` presented as current |
| `src/README.md`, `src/knowledge_graph/README.md`, `thesis/README.md` | ✅ | Overview | No retrieval-score detail |

## Findings by Severity

### ⚠️ Conflicting Documentation
- **Roadmap RS-20 row vs R1 delivery**: the row said R1 delivers "the first two" metrics (type-precision and constraint-satisfaction), but the R1 scope row, the spec and the code deliver popularity-bias@K and type-precision@K, with constraint-satisfaction@K in R2. **Resolved** in favour of the code.

### ⏰ Outdated Documentation
- **AFP-002 status line**: "Approved … revised" with no implementation note. **Fixed**: implemented 2026-10-17, with the C920 diagnostic note.
- **Action-items index**: "Approved, not implemented" for AFP-002; roadmap "R1 in progress". **Fixed**.
- **Roadmap header**: "R1 is ready for the `/implement` pipeline". **Fixed**: R1 implemented, links to audit and eval.
- **Implementation Plan A1 "Multi-Index Semantic Search"**: described the `CALL { … } UNION` query as the retrieval path. **Fixed** with a dated note; the original line is preserved.
- **Architecture diagram**: R1 boxes drawn as "this branch" (planned). **Fixed**: shown as "new in R1", ablation arms named.

### 📋 Duplicated Content
- R1 evaluation results appear in the Audit Report, the changelog and the plan status line. The Audit Report is canonical; the others are summaries that link to `evaluations/eval_2026-10-17_1937`.

### 🔗 Stale References
- **Diagram, Entity Resolver box**: "exact → full-text → vector". `ResolverService._execute_waterfall` uses exact → substring / word-boundary regex → vector, and the live graph has no full-text indexes. **Fixed**. (Vision decision 2026-09-28-006 still says "Lucene full-text second"; decision 2026-10-07-009 records the regex tier. The Vision Report is append-only and owned by @pm-research, so this is noted, not edited.)
- **RS range** "RS-01 … RS-22" in the index, the plan header and the gap table after RS-23 / RS-24 were added. **Fixed** to RS-24.

### 🕳️ Missing Documentation
- **Thesis contribution for R1**: no `thesis/<N>-doc-*.md` covers rank-based fusion, MaxP aggregation, the popularity-bias finding or the same-request arm replay. Suggest running @thesis-evaluator. Not created without approval.
- **Evaluation artifacts are not versioned**: `evaluations/` is git-ignored, so `eval_2026-10-17_1937` (cited by the audit, changelog and plan) exists only locally. Flag for a decision on how thesis-evidence runs are archived.

### ✅ Valid Documentation
- Vision Report, Research Report, Technical Specification (with §11 amendments), Audit Report, changelog entry, `.env.example`, historical AFP and failure-analysis documents, dated thesis contributions.

## Fixes Applied

| File | Change | Reason |
|------|--------|--------|
| `production_artifacts/action_items/Proposed_Fix_Vector_Aggregation.md` | Status: implemented 2026-10-17 | Outdated status |
| `production_artifacts/action_items/README.md` | AFP-002 implemented; R1 done; RS-01 … RS-24 | Outdated status, stale range |
| `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` | Header status; RS-01/02/05/20 statuses; RS-20 release split | Outdated status, internal conflict |
| `production_artifacts/Implementation_Plan.md` | A1 multi-index note; gap table; RS range in A1.1 header | Outdated description, stale range |
| `diagrams/crs_detailed_architecture.html`, `diagrams/crs_detailed_architecture_2026-10-17.jpg` | R1 styling and legend; ablation arms; resolver label; re-rendered | Outdated status, wrong label |
| `README.md` | `--fusion-arms` command | Undocumented CLI option |

## Flagged for User Approval

1. Create a thesis contribution document for R1 (@thesis-evaluator).
2. Decide how evaluation runs used as thesis evidence are archived (they are git-ignored today).
