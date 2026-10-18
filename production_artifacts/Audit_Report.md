# Audit Report: R2a — Evaluation Metrics, Spurious-CLARIFY Fix (RS-23) and Citable Run Archive

**Date**: 2026-10-18
**Spec Audited**: `production_artifacts/Technical_Specification.md` (R2a, approved 2026-10-18 at Gate #2; Appendix A approved; open questions 1–8 resolved as recommended; numeric constraints "option 1": verdicts on `Attribute.numeric_value` only, every `graph_attribute_names` empty, coverage reported as 0%)
**Context**: `production_artifacts/Research_Report.md` (R2), Vision decisions 2026-10-18-014 … 017
**Status**: PASS WITH FIXES. One High finding (H-1) is open and needs a user decision before the gate commit. The live exit gate (§7) has not run yet.
**Branch**: `feature/afp-002-vector-aggregation` (uncommitted working tree on top of `9cbf426`)
**Previous report**: The R1 audit (rank-based multi-channel fusion) previously at this path is preserved in git history (`git show 9cbf426:production_artifacts/Audit_Report.md`).

## Executive Summary

R2a is implemented as specified:
- prompt option A, with verbatim rule texts;
- category recovery (option C), which reuses the search parameters, so there is at most one `_generate_search_params` call per turn;
- attribution in `eval_trace`;
- gold annotations that match Appendix A exactly;
- three-valued CS@K, the denominators and the dialogue metrics;
- seeded statistics, which match SciPy and statsmodels exactly;
- provenance, the `citable` flag, `--require-clean`, the archive and the gate checker.

The engineer's eight deviations are all acceptable. Each needs a short spec amendment (listed below). All 617 tests the engineer reported pass. The three live tests pass. No existing test was modified.

The audit fixed two medium issues:
- **M-1**: the review-coverage base rate is dominated by ghost nodes. The manifest now also reports a titled-only base rate.
- **M-2**: `archive_eval_run.py --force` deleted an existing archive before refusing a run.

One **High** finding is open (H-1). In 2 of 3 QA passes of the ambiguous smoke check, recovery turned a vague request into a SEARCH. The request was "I need a gift for my dad who likes gadgets, around $50.", and the recovered category was `'gadget'`. This is the over-search risk in spec §10, and it violates Vision §2 ("does not guess"). The code follows the spec. The failure is the LLM not following the FR-007 null rule. Fixing it means changing approved prompt text or adding a guard, which is a design decision. It is escalated, not patched.

Confidence:
- High that the code is correct and the metrics are computed correctly.
- Moderate that the legacy-21 gate will pass. Two dev runs showed 0/21 spurious CLARIFY, with the prompt fix alone producing every category.
- Low that recovery is safe on vague requests until H-1 is decided.

## Spec Compliance

| ID | Requirement / Acceptance Criterion | Status | Notes |
|----|-----------------------------------|--------|-------|
| FR-001 | Product-type rule | ✅ | `PRODUCT_TYPE_RULE` equals spec §4.1.1 verbatim (string-compared) |
| FR-002 | Long-modifier example, contamination rule | ✅ | `<example_7>` matches §4.1.3. No legacy-21 type and no "plural", "singular" or "lemma" in any new text (checked, including the new `SEARCH_GENERATION_PROMPT` rules) |
| FR-003 | Example 1 taxonomy fix | ✅ | `operating_system` is a soft preference with polarity −1.0. The only other prompt change is one blank line |
| FR-004 | Consistency rule | ✅ | Verbatim §4.1.2 |
| FR-005 | Schema-injection hint | ✅ | `PRODUCT_TYPE_SCHEMA_HINT` |
| FR-006 | Recovery before clarifying | ✅ | `_decide_next_step`. `has_category` is stricter than the spec text (deviation 1) |
| FR-007 | Null category; `param_source` | ✅ code / ⚠️ behaviour | Prompt rule verbatim. Error strings, non-JSON, non-object JSON and exceptions all fail closed (`param_source: "fallback"` → `recovery_error`). The LLM did not follow the null rule on one smoke utterance (H-1) |
| FR-008 | One search-params call per turn | ✅ | `state["search_params"]` is reused, and `_search_history_text` is shared. A second call is impossible: the only path where recovery leaves `search_params` unset ends in CLARIFY |
| FR-009 | Attribution in `eval_trace` | ✅ | The SEARCH branch has a single result path; CLARIFY results carry `eval_trace` |
| FR-010 | Recovery switch | ✅ | Argument, then `ORCH_CATEGORY_RECOVERY`; documented in `.env.example` |
| FR-011 | "1500 → 150" fix | ✅ | First line of the prompt unchanged |
| FR-012 | Gold schema, exit 1 on errors | ✅ | `validate_gold_annotations`; checked before provenance |
| FR-013 | Legacy-21 annotations | ✅ | All 21 rows match Appendix A (12 price, 7 brand, 19 numeric). Every evidence quote and brand occurs in the utterance. Existing fields and key order are unchanged against HEAD. All `graph_attribute_names` are `[]` (option 1) |
| FR-014 | CER parser-only / pipeline | ✅ | Excluded categories are not counted (deviation 1) |
| FR-015 | Target-admitting category rate | ✅ | `match_category(..., raw_category=...)`; MACS drops counted |
| FR-016 | `normalized_filters` | ✅ | Shallow copy taken before MACS mutates `filters` |
| FR-017 | Spurious-CLARIFY rate | ✅ | `type_explicit_non_search` excludes CLARIFY (deviation 5) |
| FR-018 | Clarification recall / precision | ✅ | `n/a (n=0)` on legacy-21. Precision denominator: see L-3 |
| FR-019 | Denominators, all-queries rule, `search_intersection`, `aggregate_rows` | ✅ | `clarify_gold` also sets `strict_hit` (deviation 3, L-1) |
| FR-020 | Review-coverage label | ✅ | Key unchanged; `RevCovBias` in logs |
| FR-021 | `target_review_embedded` tag and slices | ✅ | |
| FR-022 | Three-valued verdicts | ✅ | Every truth-table cell re-checked. Price null/≤ 0 → unknown. Unknown is never counted as violated |
| FR-023 | CS aggregates | ✅ | `None` for 0 items or 0 constraints, excluded via `n_*` |
| FR-024 | Gold and request flavours | ✅ | Key names: deviation 4 |
| FR-025 | Batched fact fetch | ✅ | One query; values only in `$asins` and `$attribute_names` |
| FR-026 | Gold-vs-target pre-flight | ✅ | 17 targets, 38 constraints: 0 violated, 19 unknown (all numeric) |
| FR-027 | Statistics helper | ✅ | Checked against SciPy `binomtest`, statsmodels Wilson and Holm, and brute-force sign-flip enumeration. All AC-021 vectors are exact. Seeded and deterministic. No SciPy import in `src/` or `scripts/` |
| FR-028 | Pre-registered comparisons | ✅ | SEARCH-only, paired by `query_id` |
| FR-029 | Manifest provenance | ✅ | Live: `gpt-4o-2024-08-06`, Neo4j 5.14.0 community, snapshot counts. Adds `git_scope` (deviation 8) |
| FR-030 | `citable`, `--require-clean` | ✅ | Exit 2 before the grounding gate and before the orchestrator is built. The check also covers the benchmark (deviation 8). On the real tree it lists the 15 dirty paths and the benchmark |
| FR-031 | Resolved model ID | ✅ | |
| FR-032 | `per_query.jsonl` | ✅ | All §5.1.7 keys, plus `recovery_attempted` |
| FR-033 | Archive script | ✅ (fixed) | M-2 |
| FR-034 | `.gitignore` | ✅ | Plain `git check-ignore`: `evaluations_archive/**/retrieval_metrics.csv` → no match (exit 1); `scripts/graph_ingestion/.ingest_checkpoint.json` → match; `evaluations/…` → match |
| FR-035 | Retroactive archive | ✅ | Three runs: `citable: false`, `archive.legacy: true`, the §4.6.3 notes verbatim, `legacy_reconstructed: true`. CLARIFY counts are 0 / 4 / 5 |
| FR-036 | Gate checker | ✅ | Requires at least 3 runs (deviation 8) |
| FR-037 | Ambiguous smoke check | ✅ | QA ran it 3 times (see Evaluation Results) |
| NFR-001 | LLM-call budget | ✅ | Unit test: a recovered turn makes 3 LLM calls, the same as a normal SEARCH turn |
| NFR-002 | Determinism | ✅ | Exact enumeration up to n_nonzero 16. Monte Carlo agrees with exact enumeration at n = 20 (0.14926 vs 0.14924) |
| NFR-003 | No new dependencies | ✅ | `requirements.txt` unchanged |
| NFR-004 | Parameterised Cypher, Neo4j 5.14 | ✅ | New queries (facts, provenance counts, the QA titled counts) are parameterised or constant. The interpolated category title condition is pre-existing (AI-11, L-7) |
| NFR-005 | Backward compatibility | ✅ | The 453 pre-existing tests pass unmodified. `hybrid == hybrid@rrf3` on 21/21 queries |
| NFR-006 | Domain-agnostic | ✅ | No category lists or inflection rules in new code or prompts. `NULL_CATEGORY_VALUES` is a null-marker set, not vocabulary |
| NFR-007 | Live-only evidence | ✅ | Offline runs are `citable: false` (`mode_not_live`) |
| NFR-008 | Every aggregate has its `n` | ✅ | Logs, `summary.json` and gate output |
| NFR-009 | Archive ≤ 1 MB per run | ✅ | 96–216 KB per legacy run; the live dev run's `per_query.jsonl` is 92 KB |
| NFR-010 | No secrets | ✅ | Archive scanned: no API keys, URIs, passwords or email address. No `/Users/` paths |
| AC-001 … AC-003 | Prompt | ✅ | `tests/test_preference_prompt_r2.py`, `tests/test_prompt_constraint_inversion.py` |
| AC-004 … AC-010 | Recovery, reuse, reasons, switch, immunisation, prompt | ✅ | `tests/test_category_recovery.py`. Search-param calls are counted per test. `graph.search` is never called on `recovery_failed` or `recovery_error` |
| AC-011 | Gold annotations | ✅ | Also re-checked by QA against Appendix A and the utterances |
| AC-012 … AC-020 | Metrics, CS, facts | ✅ | Unit tests plus QA re-derivation of the dev-run aggregates |
| AC-021, AC-022 | Statistics | ✅ | Independently verified (FR-027) |
| AC-023, AC-024 | Provenance, model ID | ✅ | Also exercised on the real repository |
| AC-025, AC-026 | JSONL, archive | ✅ | New regression test for M-2 |
| AC-027 | `.gitignore` | ✅ | See FR-034 |
| AC-028 | Retroactive archives | ✅ | |
| AC-029 | Gate checker | ✅ | |
| AC-030 | Full suite and live tests | ✅ | 623 passed, 3 skipped; live 3 passed |
| AC-031, AC-032 | Live exit gate, R1 replay in gate runs | ⏳ | Not run: needs a clean commit (see Gate Procedure) |
| AC-033 | Smoke counts in the report | ✅ | See Evaluation Results |

### Engineer deviations (judged)

| # | Deviation | Verdict | Why |
|---|-----------|---------|-----|
| 1 | `has_category` is stricter: null-like values and `exclude` operators are ignored, and the value also feeds brand immunisation | Accept; amend | It is one computation for the guardrail, the immunisation and `parser_category`. Immunisation now fires on a usable, non-excluded category only. Before, `{"attribute": "category", "value": null}` or an excluded category plus a brand overrode a router CLARIFY. The new behaviour follows "does not guess" more closely. The AFP-004 test (`test_orchestrator_routes_affirmative_brand_to_search`) and AC-009 pass unmodified. Side effect: the key set widened to all `CATEGORY_FILTER_KEYS` (L-4) |
| 2 | Source precedence: parser → active filters → session context | Accept; amend | Matches §5.1.1 ("source = parser when the parser had a category"). `parser_category` is the accumulated session hard constraint, as §5.1.1 defines it |
| 3 | CLARIFY-gold scoring also sets `strict_hit` | Accept; amend | `hit@k` is `strict_hit@k` in this code, and aggregates read `strict_hit`, so this is required. `soft_hit`, `graded_ndcg` and `recall` are not overridden (L-1) |
| 4 | CS key names | Accept; amend | Gold: `cs_sat`, `cs_viol`, `cs_unk`, `cs_known`, `violation_free`, `cs_coverage`. Request: the same names with prefix `cs_req_`, including `cs_req_violation_free` |
| 5 | `type_explicit_non_search` excludes CLARIFY | Accept; amend | It avoids double-counting with spurious CLARIFY. G-5 still checks every JSONL line is SEARCH |
| 6 | `category_source = "search_request"` | Accept; amend | Needed for SEARCH turns where the guardrail did not fire and only the SEARCH-branch call produced the category. Add it to the §5.1.1 / §5.1.7 enum |
| 7 | Runtime provenance is collected after the query loop | Accept; amend | Resolved model IDs are known only after LLM calls. The graph snapshot is read-only, so the timing does not matter |
| 8 | Extras: `--require-clean` also refuses a dirty or untracked benchmark; the gate checker needs ≥ 3 runs; `git_scope`; `gold_target_check.constraints` / `.unknown`; helper functions | Accept; amend | Consistent with the `citable` rule (FR-030) and G-3; additive keys only |

## Findings

### 🔴 Critical Issues
None.

### 🟠 High Issues
- **H-1 — Recovery over-searches a vague request** (`AgentOrchestrator._recover_category`, `SEARCH_GENERATION_PROMPT`; Vision §2, spec FR-007 and §10). Utterance: "I need a gift for my dad who likes gadgets, around $50." The router chose SEARCH in every pass. With recovery off, the guardrail clarifies (`parser_missing_category`). With recovery on, `_generate_search_params` returned `category = "gadget"` in **2 of 3 QA passes**. The turn then ran a SEARCH for "gadget" at ≤ $50 instead of asking. (The engineer's single pass returned null.) The other four utterances were router CLARIFYs in every pass, so recovery never ran on them.

  The code does what the spec says: the null rule is verbatim and every failure fails closed. The weakness is that the only guard against guessing is the same LLM call. The legacy-21 gate cannot detect this, because every legacy item is type-explicit.

  **Not fixed by QA.** Every fix changes approved behaviour: new prompt text, or a second check such as an explicit "decided / undecided" field or agreement with the parser. Any wording written now would also be tuned on the diagnostic smoke set, so the smoke set would stop being an independent check. **Escalated to @pm-specs / the user.** Options:
  - (a) accept the spec's R2b deferral (the ambiguous-stratum clarification-recall gate) and document the observed rate;
  - (b) amend FR-007 before the gate commit with a domain-agnostic rule and re-test on fresh ambiguous utterances, not on these five;
  - (c) gate recovery on an explicit `product_type_decided` boolean from the same call (one call; the recovered category is used only when it is `true`).

  Recommended: (c) or (b) before R2b, and in any case add the smoke check to the gate procedure as a reported diagnostic.

### 🟡 Medium Issues
- **M-1 — The review-coverage base rate is dominated by ghost nodes** (`scripts/evaluate_retrieval.py`). Verified on the live graph:
  - 104,281 of 265,307 `ParentProduct` nodes (39.3%) are ghosts with no title, no price and no category, only an embedding;
  - 4,874 of the 5,715 review-embedded products (85.3%) are ghosts;
  - the manifest's `catalog_popular_share` (5,715 / 265,307 = 2.15%) therefore mostly measures ghosts. Over titled products the rate is 841 / 161,026 = **0.52%**.

  **Fixed**: `compute_review_coverage_base_rates` adds `catalog_titled_products`, `review_embedded_products_titled` and `catalog_popular_share_titled` to `manifest.configuration`, next to the unchanged `catalog_popular_share`. It uses parameterised Cypher, and the log line prints both rates. The `compute_popularity_bias_at_k` docstring notes the titled rate. Retrieval is unchanged, and ghosts are not excluded from search (brainstorm K-3, not approved). Tests: `tests/test_r2a_audit_fixes.py::TestTitledBaseRate`. Verified live in `eval_2026-10-18_1705` (0.00522).

  Interpretation: in the hybrid arms almost all review-embedded top-K slots are titled products (`eval_2026-10-18_1449`, @20: `rrf3` 71 of 76, `sum_legacy` 77 of 93). Measured against 0.52%, review-coverage bias is about 4× stronger than the R1 report's comparison against 2.15% suggested (`rrf3` RevCovBias@5 0.21 ≈ 40× the titled base rate).
- **M-2 — `archive_eval_run.py --force` deleted the existing archive before refusing** (`archive_run`). With `--force`, the target folder was removed before the "no `per_query.jsonl`" refusal, so a refused re-archive destroyed a tracked archive. **Fixed**: all refusals now come before the removal. Regression test: `TestForceDoesNotDeleteOnRefusal`, which fails on the old ordering (checked). Residual (Low): a `--legacy --force` re-archive whose reconstruction raises, for example because `retrieval_metrics.json` is missing, still fails after the removal. A copy-to-temp-then-rename would close it.
- **M-3 — Ghost products in result lists** (not R2a code; reported as asked). Ghosts have `price = NULL`, so they pass the `(node.price IS NULL OR node.price <= $price_max)` filter. They have no category and no title, so only a query without a category filter admits them, including after MACS drops the category. In `eval_2026-10-18_1449`:
  - `camera_02` (MACS dropped the category) has 5 ghosts in the `hybrid` / `rrf3` top 20, 8 in `cc3` and 16 in `sum_legacy`;
  - `vector_only` (no filters) has ghosts in 102 of 420 slots, on every query.

  Ghosts are unrecommendable: they have no title and no price, and CS gives their price verdicts as unknown. Excluding them is the separate decision K-3; no change was made.

### 🔵 Low Issues / Suggestions
- **L-1**: On `scored_as: "clarify_gold"` rows only `hit` / `strict_hit`, `strict_ndcg` and `mrr` are overridden. `soft_hit`, `graded_ndcg` and `recall` stay retrieval-scored (0 on a CLARIFY). This does not matter on legacy-21 (all gold SEARCH). Decide before R2b's ambiguous stratum.
- **L-2**: `collect_benchmark_provenance` resolves a relative benchmark path against the repo root, but the loader opens it relative to the working directory. Runs from another directory could hash a different file. The gate procedure runs from the repo root.
- **L-3**: `clarification_precision` counts CLARIFY actions on gold-annotated queries only; the spec says "all CLARIFY actions". The result is identical when every item is annotated.
- **L-4**: `_category_from_filters` accepts `type`, `product_type` and `categories` from `active_filters`, which include profile preferences. A profile key `type` holding a modifier would count as a category: it would skip recovery and could immunise a router CLARIFY. No current profile has such a key.
- **L-5**: Lint. There is a new unused import (`List` in `src/evaluation/dialogue_metrics.py`) and one new placeholder-less f-string in `orchestrator.py`. Net pyflakes counts are unchanged for every modified file.
- **L-6**: `p50_latency_ms` for `hybrid`, `vector_only` and `cypher_only` is the whole-turn latency (≈ 13 s); the arms show ≈ 0.6 s search-only latency. This is pre-existing, but it now appears on the same log line as the arms.
- **L-7**: AI-11 (pre-existing). The multi-token category title condition escapes `'` but not `\`, so a value ending in a backslash can break out of the string literal. The eval's new `match_category(..., raw_category=…)` passes the same request value that `search` already interpolates, so there is no new exposure.
- **L-8**: `default_git_runner` decodes with `text=True`. A non-UTF-8 diff would raise `UnicodeDecodeError`, which is not caught, and abort the run. `_porcelain_paths` strips quotes but does not unescape C-quoted paths.
- **L-9**: Offline runs compute a `dialogue` block (e.g. CER 0/5), which looks like a measurement. Consider `null` in offline mode. These runs are already `citable: false`.

## Live-Graph Facts (verified 2026-10-18, read-only)

| Fact | Count |
|---|---:|
| `ParentProduct` nodes | 265,307 |
| Ghosts (no title, no price, no category; embedding only) | 104,281 (39.3%) |
| Titled products | 161,026 |
| Review-embedded products | 5,715 (2.15% of all nodes) |
| … of which ghosts | 4,874 (85.3%) |
| … of which titled | 841 (0.52% of titled products) |
| `Attribute` nodes with `numeric_value` | 0 |
| Titled products with `price IS NULL` | 48,037 |
| `Brand` nodes with an empty name | 0 (so the Cypher `CONTAINS ''` edge case cannot occur) |

**`graph_attribute_names` mapping (§5.1.4, option 1)**: empty for all 19 numeric gold constraints, because no `Attribute` node carries `numeric_value`. Every numeric verdict is `unknown` and numeric CS coverage is 0%. This is evidence for RS-11.

**Gold-vs-target pre-flight (FR-026)**: 17 targets, 38 constraints: 0 violated, 19 unknown (the numeric ones). All 12 price and 7 brand constraints are satisfied by their targets. `phone_03`'s "Apple" is satisfied through the title rule. No annotation conflict.

## Evaluation Results (dev runs; non-citable: dirty tree)

Two live runs on legacy-21 at `9cbf426` with a dirty tree: the engineer's `eval_2026-10-18_1449` and QA's `eval_2026-10-18_1705` (after the M-1 / M-2 fixes). Both are `citable: false` with `git_dirty` and `benchmark_modified`, which is the correct policy outcome. **They are context, not evidence.**

### Dialogue (RS-23)

| Metric | `_1449` | `_1705` |
|---|---:|---:|
| Spurious CLARIFY | 0/21 | 0/21 |
| Type-explicit non-SEARCH | 0/21 | 0/21 |
| CER parser-only | 21/21 | 21/21 |
| CER pipeline | 21/21 | 21/21 |
| Recovery calls | 0 | 0 |
| `category_source_counts` | parser 21 | parser 21 |
| Target-admitting category | 20/21 (MACS dropped 1) | 20/21 (MACS dropped 1) |
| `hybrid == hybrid@rrf3` (SEARCH queries) | 21/21 | 21/21 |

- Option A alone produced every category in both runs, so recovery never ran on legacy-21. The recovery path is covered by unit tests and the smoke check only.
- The target-admitting miss is `camera_02` in both runs. The applied category "smart home security bundle" does not admit the target, and MACS then dropped the category.

### Ambiguous smoke check (FR-037, diagnostic)

| Pass | Recovery on | Recovery off | Utterance 1 ("gift … gadgets, around $50") with recovery on |
|---|---:|---:|---|
| Engineer | CLARIFY 5/5 | 5/5 | `recovery_failed` (null) |
| QA 1 | CLARIFY 4/5 | 5/5 | **SEARCH, category `'gadget'`** |
| QA 2 | CLARIFY 5/5 | 5/5 | `recovery_failed` (null) |
| QA 3 | CLARIFY 4/5 | 5/5 | **SEARCH, category `'gadget'`** |

Utterances 2–5 were router CLARIFYs in every pass. Utterance 1 with recovery off was always `parser_missing_category`. See H-1.

### Retrieval per arm (all 21 queries are SEARCH, so all-queries = SEARCH-only, n = 21)

| Arm | HR@5 `_1449` / `_1705` | HR@20 | NDCG@10 | MRR | RevCovBias@5 | TypeP@5 |
|---|---:|---:|---:|---:|---:|---:|
| `sum_legacy` | 0.286 / 0.286 | 0.476 / 0.476 | 0.220 / 0.217 | 0.193 / 0.190 | 0.476 / 0.476 | 0.848 / 0.838 |
| `rrf3` (= `hybrid`) | 0.333 / 0.286 | 0.429 / 0.429 | 0.275 / 0.271 | 0.247 / 0.242 | 0.210 / 0.219 | 0.838 / 0.838 |
| `rrf2` | 0.333 / 0.286 | 0.476 / 0.476 | 0.290 / 0.287 | 0.251 / 0.247 | 0.057 / 0.057 | 0.848 / 0.848 |
| `wrrf3` | 0.429 / 0.476 | 0.524 / 0.571 | 0.354 / 0.381 | 0.318 / 0.338 | 0.038 / 0.038 | 0.876 / 0.876 |
| `cc3` | 0.429 / 0.381 | 0.524 / 0.524 | 0.371 / 0.340 | 0.341 / 0.301 | 0.152 / 0.152 | 0.848 / 0.838 |

Base rates for RevCovBias: 2.15% over all nodes, **0.52% over titled products** (M-1).

### Constraint satisfaction

CS@20 per kind (`hybrid`; `_1449` / `_1705`):

| Kind | Coverage | `cs_known` | Notes |
|---|---:|---:|---|
| Price | 0.532 / 0.543 | 1.0 | Unknowns are null prices: ghosts and the 48,037 titled products with no price |
| Brand | 1.0 / 1.0 | 1.0 | |
| Numeric | 0.0 / 0.0 | — | Option 1 |

`mean_cs_known@20 = 1.0` (n = 15) and `mean_cs_viol@20 = 0.0` (n = 17) for every hybrid arm. Every known verdict is satisfied: the hard filters enforce price and brand, and MACS widened no budget in these runs.

### Primary comparisons (R2-D3; not significant, n = 21 cannot separate the arms)

| Comparison | Run | RR diff (95% CI) | p (RR) | NDCG@10 diff | p (NDCG@10) | HR@5 discordant | HR@20 discordant |
|---|---|---|---:|---:|---:|---|---|
| `rrf3` vs `sum_legacy` | `_1449` | +0.054 [−0.097, +0.197] | 0.488 | +0.055 | 0.492 | 2–1 | 1–2 |
| `rrf3` vs `sum_legacy` | `_1705` | +0.051 [−0.100, +0.195] | 0.516 | +0.053 | 0.500 | 1–1 | 1–2 |
| `rrf2` vs `rrf3` | `_1449` | +0.005 [0.000, +0.012] | 0.250 | +0.015 | 0.500 | 0–0 | 1–0 |
| `rrf2` vs `rrf3` | `_1705` | +0.006 [+0.001, +0.013] | 0.125 | +0.016 | 0.250 | 0–0 | 1–0 |

- All McNemar p-values are 1.0.
- Secondary family (Holm), `_1449`: no rejection; the smallest p_holm is 0.0625 (`wrrf3` vs `sum_legacy`).
- Secondary family (Holm), `_1705`: `wrrf3` vs `sum_legacy` reaches p_holm = 0.031.
- The weighted arm (`wrrf3`) leads in both runs. It is the only consistent signal, and it is not citable; R2b tests it on held-out data.

## Test Results

- `python -m pytest tests/ -v --tb=short`: **623 passed, 3 skipped**. That is 617 before the audit plus 6 new tests in `tests/test_r2a_audit_fixes.py`; the 3 skipped are live tests. No existing test file is modified (`git diff --stat HEAD -- tests/` is empty).
- `RUN_LIVE_TESTS=1 pytest tests/integration/test_category_recovery_live.py tests/integration/test_fusion_live_regression.py`: **3 passed** (smoke check; `ret_021` C920 diagnostic; `ret_001` no hub runaway).
- `pyflakes`: no net new warnings in modified files; one unused import in a new file (L-5).

## Recommended Spec Amendments (for @pm-specs)

1. **FR-006 / §4.2.2** (deviation 1): define `has_category` as the first usable value (string, or first list item; not in `NULL_CATEGORY_VALUES`; operator not `exclude`) from the session hard constraints, then `active_filters` under `CATEGORY_FILTER_KEYS`, then `current_context.category`. State that the guardrail, the brand immunisation and `parser_category` share it.
2. **§5.1.1** (deviation 2): source precedence parser → active_filters → session_context.
3. **FR-019 (c)** (deviation 3, L-1): list `strict_hit@k` as overridden. Decide `soft_hit`, `graded_ndcg` and `recall` on `clarify_gold` rows before R2b.
4. **FR-023 / FR-024** (deviation 4): list the exact key names (see the deviation table).
5. **FR-017** (deviation 5): `type_explicit_non_search` = actions that are neither SEARCH nor CLARIFY.
6. **§5.1.1 / §5.1.7** (deviation 6): add `"search_request"` to the `category_source` values.
7. **§5.2.3 step 3** (deviation 7): runtime provenance (LLM IDs, Neo4j, graph snapshot) is collected after the query loop.
8. **FR-026, FR-029, FR-030, FR-036** (deviation 8): `gold_target_check` also has `constraints` and `unknown`; provenance records `git_scope`; `--require-clean` also refuses a dirty or untracked benchmark; the gate checker fails with fewer than 3 runs.
9. **FR-018** (L-3): the precision denominator is CLARIFY actions on gold-annotated queries.
10. **FR-013 / R1 FR-013** (M-1): the manifest adds `catalog_titled_products`, `review_embedded_products_titled` and `catalog_popular_share_titled`. Thesis text should compare review-coverage bias against the titled base rate (0.52%), or state both rates.
11. **§7 / FR-037** (H-1): after each gate run, run the ambiguous smoke check and report "CLARIFY k/5 with recovery on / off" next to the gate table. Record the H-1 decision (options a–c) in the spec before the gate commit.

## Verdict

**PASS WITH FIXES.** The implementation complies with the R2a specification. M-1 and M-2 are fixed in source with regression tests. M-3 and L-1 … L-9 are reported. All eight engineer deviations are accepted, pending the amendments above.

**Open before the gate commit: H-1.** It is a design-level risk the spec anticipated: recovery guessed a product type on a vague request in 2 of 3 live passes. The user should choose option (a), (b) or (c). If (b) or (c), the change goes back through @engineer and this audit is repeated for the affected FRs.

The R2a exit gate (G-3 … G-8, AC-031, AC-032) is **not yet evaluated**, because it needs a clean commit. Follow the procedure below.

## Gate Procedure (to run after the user authorises the commit)

Run everything from the repository root with the R1 interpreter. Every run made at the final commit must be reported; selecting 3 of N runs is not allowed.

```bash
cd /Users/mikolajpaszkowski/recommendation-system
PY=/opt/homebrew/anaconda3/bin/python

# 0. Resolve H-1 first (option a, b or c). If b or c, re-implement, re-test and re-audit before step 1.

# 1. Commit all implementation work (src/, scripts/, tests/, live_eval_dataset.json, .gitignore, .env.example,
#    evaluations_archive/ with the three legacy archives, and the production_artifacts/ updates). Then confirm a clean scope:
git status --porcelain --untracked-files=all -- src scripts live_eval_dataset.json   # must print nothing
git rev-parse HEAD                                                                   # note the gate commit

# 2. G-1 and G-2
$PY -m pytest tests/ -v --tb=short
RUN_LIVE_TESTS=1 $PY -m pytest tests/integration/test_fusion_live_regression.py -v

# 3. Three sequential citable runs (exit code 2 means the tree is not clean: stop and fix, do not drop --require-clean)
$PY scripts/evaluate_retrieval.py --mode live --require-clean --fusion-arms rrf3 rrf2 wrrf3 cc3 sum_legacy   # R_a
$PY scripts/evaluate_retrieval.py --mode live --require-clean --fusion-arms rrf3 rrf2 wrrf3 cc3 sum_legacy   # R_b
$PY scripts/evaluate_retrieval.py --mode live --require-clean --fusion-arms rrf3 rrf2 wrrf3 cc3 sum_legacy   # R_c

# 3b. Diagnostic (amendment 11, not gating): ambiguous smoke check, once per gate run
RUN_LIVE_TESTS=1 $PY -m pytest tests/integration/test_category_recovery_live.py -s

# 4. G-3 … G-6
$PY scripts/check_eval_gate.py --runs <R_a> <R_b> <R_c> --max-spurious-clarify 0     # exit 0 = PASS

# 5. G-7: archive the three runs (no --legacy), then commit evaluations_archive/
$PY scripts/archive_eval_run.py <R_a>
$PY scripts/archive_eval_run.py <R_b>
$PY scripts/archive_eval_run.py <R_c>
git add evaluations_archive/ && git commit -m "eval: archive R2a gate runs"

# 6. G-8 is already satisfied: evaluations_archive/eval_2026-10-09_1336, _1846, _1937 (citable: false, legacy notes)
```

Then @qa appends the following to this report:
- the gate table;
- the parser-only CER per run;
- `category_source_counts`;
- the gold-vs-target pre-flight;
- CS@K coverage per kind;
- the primary comparisons (n = 21 cannot separate the arms, R2-D3);
- the smoke counts.

If any run shows a spurious CLARIFY, the gate fails (§7.3). Record the query, `clarify_reason` and `category_resolution` from `per_query.jsonl`. After a fix, repeat all three runs at the new commit.
