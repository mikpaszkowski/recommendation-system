# Audit Report: R1 — Rank-Based Multi-Channel Fusion (AFP-002 via RRF)

**Date**: 2026-10-17
**Spec Audited**: `production_artifacts/Technical_Specification.md` (R1, approved 2026-10-17, amendments §11)
**Status**: PASS WITH FIXES
**Branch**: `feature/afp-002-vector-aggregation`
**Previous report**: The Phase A4 KECR audit previously at this path is preserved in git history (`git show f2d4939:production_artifacts/Audit_Report.md`).

## Executive Summary

The R1 fusion path is implemented as specified. Each channel returns each product once by its best match, ranked after filters, and the lists are fused by RRF (default) with four ablation arms, all from the same lists. The audit found and fixed two medium issues: `.env` load order for `RETRIEVAL_FUSION_ARM`, and arm-order latency bias in the eval. It also restated one acceptance criterion as a diagnostic, because fusion cannot satisfy it (C920; spec §11). The unit suite passes (453 passed, 2 live tests skipped by design), and both live tests pass against Neo4j 5.14.

On the live benchmark, fusion lowers popularity bias clearly but does not change hit rate measurably on 21 queries. Confidence in correctness is high; confidence in any ranking-quality claim beyond popularity bias is low until the R2 benchmark.

## Spec Compliance

| ID | Requirement / Acceptance Criterion | Status | Notes |
|----|-----------------------------------|--------|-------|
| FR-001 | Per-channel MaxP lists, filters before ranking | ✅ | `GraphSearchTool._build_channel_query`: `max(score)` per `node`, `WHERE` inside the channel query |
| FR-002 | Deterministic truncation at `channel_depth` | ✅ | `ORDER BY similarity DESC, asin ASC LIMIT $depth` |
| FR-003 | Competition ranking | ✅ | `score_fusion.competition_ranks` |
| FR-004 | RRF default (`k = 60`, equal weights) | ✅ | `score_fusion.fuse`, `FUSION_ARMS["rrf3"]` |
| FR-005 | Arms `rrf3`, `rrf2`, `wrrf3`, `cc3`, `sum_legacy` | ✅ | `FUSION_ARMS`; `sum_legacy` = `_execute_legacy_sum_search` (verbatim pre-R1 Cypher) |
| FR-006 | Fused tie-break | ✅ | score, channels matched, best similarity, asin |
| FR-007 | Hybrid + vector-only paths; filter-only unchanged | ✅ | `_execute_hybrid_search`, `_execute_vector_search` → `_execute_fused_search` |
| FR-008 | Soft bonus `β × max_fused` | ✅ | Filter-only and `sum_legacy` keep 0.2 (spec §11.2) |
| FR-009 | Fusion evidence on every item | ✅ | `fused_score`, `soft_bonus`, `fusion.channels[*]`; original keys kept |
| FR-010 | `search_request` in `eval_trace`; fusion in metadata | ✅ | `AgentOrchestrator._execute_step`; `metadata["fusion"]` |
| FR-011 | Arm replay `hybrid@<arm>` (live only) | ✅ | `scripts/evaluate_retrieval.py --fusion-arms`; unknown arm or non-live mode → exit 1 |
| FR-012 | Per-strategy aggregates | ✅ | `aggregates_by_strategy`; `summary.json["by_strategy"]` |
| FR-013 | `popularity-bias@K` | ✅ | 5,715 review-embedded products; catalogue share 2.15% in manifest |
| FR-014 | `type-precision@K` | ✅ | `GraphSearchTool.match_category` with the benchmark's category |
| FR-015 | Regression checks | ✅ | As amended: Senso gated, C920 rank recorded |
| FR-016 | `RETRIEVAL_FUSION_ARM` | ✅ (fixed) | Was read before `.env` load; see M-1 |
| NFR-001 | p50 search ≤ 1.5 × `sum_legacy` | ✅ | 757 ms vs 727 ms (1.04×) in `eval_2026-10-17_1937`, after M-2 |
| NFR-002 | Determinism | ✅ | `hybrid@rrf3` reproduces `hybrid` exactly in both live runs |
| NFR-003 | Fusion testable without Neo4j | ✅ | `score_fusion.py` has no I/O |
| NFR-004 | Parameterised new Cypher | ✅ | AC-010 test; pre-existing interpolation in `_build_filters` remains (AI-11) |
| NFR-005 | Router, Critic, KECR, MACS unchanged | ✅ | MACS test via fused path (AC-011) |
| NFR-006 | Neo4j 5.14 | ✅ | `db.index.vector.queryNodes`; live queries succeed |
| AC-001 | Fan-out gives no extra credit | ✅ | `test_fan_out_gives_no_extra_credit` |
| AC-002 | RRF formula; brainstorm example orders | ✅ | `test_rrf_score_matches_formula`, `test_brainstorm_example_orders` |
| AC-003 | Competition ranks; order independence | ✅ | `test_competition_ranks_share_ties`, `test_fusion_is_order_independent` |
| AC-004 | `rrf2`, `wrrf3`, `cc3` behaviour | ✅ | three tests |
| AC-005 | `max_fused_score` per arm, bound holds | ✅ | `test_max_fused_score_per_arm` |
| AC-006 | Env selection and fallback | ✅ | three tests + `test_fusion_arm_read_after_connector_loads_env` |
| AC-007 … AC-011 | Fused order and evidence, bonus scale, legacy query, parameters, MACS | ✅ | `tests/test_graph_search_tool.py` (mocked session) |
| AC-012 | `search_request` in `eval_trace` | ✅ | `test_eval_trace_records_search_request` |
| AC-013 | New metrics, per-strategy aggregates | ✅ | `tests/test_retrieval_metrics_r1.py` |
| AC-014 | Live regression (amended) | ✅ | Both live tests pass; C920 not in the top 20 (diagnostic) |
| AC-015 | Live eval, all arms, vs baseline | ✅ | See Evaluation Results |
| AC-016 | Full suite passes | ✅ | 453 passed, 2 skipped |

## Findings

### 🔴 Critical Issues
None.

### 🟠 High Issues
- **H-1 — AC-002.4 unachievable by fusion** (`tests/integration/test_fusion_live_regression.py`). The C920 is excluded by the category filter before fusion ("Webcams" vs title "Webcam", category "Computers"), and when eligible it ranks 114 of 742 by title similarity (0.547). **Resolution**: spec amended (§11.1); the check became a recorded diagnostic. Root cause scheduled as RS-24 (R3). A rule-based plural fix was implemented, rejected by the user as not domain-agnostic, and reverted.

### 🟡 Medium Issues
- **M-1 — `RETRIEVAL_FUSION_ARM` ignored when set only in `.env`** (`src/tools/graph_search_tool.py`, `GraphSearchTool.__init__`). The arm was read before `Neo4jConnector()`, which is what calls `load_dotenv`. **Fixed**: the arm is now read after the connector; test added.
- **M-2 — Arm-order latency bias** (`scripts/evaluate_retrieval.py`). Arms replayed in a fixed order, and `rrf3` (always first) measured 1107 ms against 723–751 ms for identical queries in other arms. **Fixed**: the replay order rotates per query; `rrf3` now measures 757 ms.
- **M-3 — Spurious CLARIFY** (not R1 code): 4–5 of 21 queries lose their category in `LLMPreferenceParser` extraction and end as CLARIFY, so every arm scores a miss on them. Varies between runs (4 in `_1846`, 5 in `_1937`). **Flagged**: RS-23 (R2).

### 🔵 Low Issues / Suggestions
- **L-1**: No offline unit test covers the `--fusion-arms` replay loop itself; it is exercised by the two live runs. Suggest a mocked-orchestrator test when the grounding gate can be bypassed in tests.
- **L-2**: `retrieval_metrics.json` carries the per-strategy block twice (`aggregates_by_strategy` and `aggregates.by_strategy`), because `summary.json` is written from `aggregates`.
- **L-3**: Six pre-existing f-strings without placeholders in `graph_search_tool.py` (pyflakes); untouched lines.
- **L-4**: Attribute-channel ties are cut at `channel_depth` by `parent_asin` (known limitation, RS-03).

## Evaluation Results (live, `eval_2026-10-17_1937`, 21 queries)

All arms replay the same LLM-extracted request per query.

| Arm | HR@1 | HR@5 | HR@20 | NDCG@5 | MRR | PopBias@5 | PopBias@20 | TypeP@5 | p50 search |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `sum_legacy` | 0.238 | 0.286 | 0.286 | 0.259 | 0.250 | 0.337 | 0.184 | 0.837 | 727 ms |
| `rrf3` (default) | 0.238 | 0.286 | 0.286 | 0.262 | 0.254 | 0.212 | 0.146 | 0.863 | 757 ms |
| `rrf2` | 0.238 | 0.286 | 0.333 | 0.262 | 0.256 | 0.062 | 0.043 | 0.887 | 642 ms |
| `wrrf3` | 0.238 | 0.286 | 0.333 | 0.268 | 0.265 | 0.050 | 0.021 | 0.925 | 716 ms |
| `cc3` | 0.238 | 0.286 | 0.333 | 0.268 | 0.264 | 0.088 | 0.099 | 0.887 | 707 ms |

- Catalogue base rate of review-embedded products: 2.15%. All fused arms lower popularity bias versus `sum_legacy`; damping the review channel (`rrf2`, `wrrf3`) removes most of it.
- Arms differ on 2 of 21 queries (`phone_02`: target rank 4 → 2–3; `mouse_03`: enters the top 20 in `rrf2`/`wrrf3`/`cc3`). HR@20 0.286 vs 0.333 is one query. No arm is a winner on this benchmark.
- The earlier run (`eval_2026-10-17_1846`) shows the same pattern.
- **Baseline attribution**: hybrid HR@1 rose from 0.048 (`eval_2026-10-09_1336`, hybrid-only) to 0.238, but `sum_legacy` scores 0.238 in the same run. The gain comes from extraction differences and commit `f7bbf81`, not from fusion.

## Test Results

- `python -m pytest tests/ -q`: **453 passed, 2 skipped** (live tests; skipped without `RUN_LIVE_TESTS=1`).
- `RUN_LIVE_TESTS=1 pytest tests/integration/test_fusion_live_regression.py`: **2 passed**.
- `pyflakes` on new/modified files: no new warnings.

## Verdict

**PASS WITH FIXES.** M-1 and M-2 fixed in source; H-1 resolved by spec amendment; M-3 flagged to RS-23.
