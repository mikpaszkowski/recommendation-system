# Audit Report: Graph v2 Rebuild (code phase, Phases 1–3)

**Date**: 2026-10-19
**Spec Audited**: `production_artifacts/Technical_Specification_Graph_Rebuild.md` (Gate #2 approved 2026-10-19), with Gate #3 decisions D-1 … D-12
**Context**: `production_artifacts/Research_Report_Graph_Rebuild.md`, Vision 2026-10-19-018 … 021
**Scope**: The uncommitted graph v2 implementation on `feature/afp-002-vector-aggregation`: `src/knowledge_graph/graph_v2/`, `src/knowledge_graph/graphdb/embedding_templates.py`, 7 new scripts in `scripts/graph_ingestion/`, `tests/graph_v2/`, `tests/fixtures/graph_v2/`, `tests/test_legacy_ingest_guards.py`, `tests/test_graph_cypher_prompt.py`, and the modified files listed in the spec §7.
**Not done in this audit, by rule**: no Docker command, no Neo4j connection, no reading of `datasets/raw/*.jsonl` (file sizes only, via `ls`), no commit.
**Status**: **PASS WITH FIXES**

## Executive Summary

The implementation covers every functional requirement FR-001 … FR-039 and every unit-testable acceptance criterion AC-001 … AC-039 and AC-046. Ghost safety holds end to end. Products come only from metadata. Reviews of missing products are dropped (`product_missing`). The transform checks every relationship endpoint before writing the lineage. The import runs with `--bad-tolerance=0 --skip-bad-relationships=false --skip-duplicate-nodes=false`. H-04 checks the ghost signature.

The audit found two High safety issues, both fixed:
- **Import guard**: the v1-name guard of the import wrapper failed open when `NEO4J_DATA_VOLUME_V1` was not in the process environment. The script did not load `.env`, which is where `.env.example` puts that variable.
- **Wrong-graph guard (FR-021)**: as specified, the post-import guard cannot tell v1 from v2. If every catalogue ASIN is found in the raw metadata, which is the expected outcome because the ghosts are "filled from raw metadata", v2 has the same product count as v1.

Five Medium issues were found; three were fixed. The other two need a decision or a fix in a later task. No Critical issues were found.

Tests: 155/155 targeted tests and 767 tests in the full suite pass (5 skipped). Neo4j and Docker were not used, and the four live-bolt files were excluded.

## Spec Compliance

### Functional requirements

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-001 | Pre-flight P-01 … P-10 | ✅ | `scripts/graph_ingestion/preflight_v2.py`. It shares the dry-run code path (`run_dry_transform`). Audit addition: P-10 now records `dry_run_peak_rss_bytes` (M-2). |
| FR-002 | Approved build parameters | ✅ | `models.BuildParams` with `product_content_rule` (D-8). The file is written by hand after CP-1 (runbook). |
| FR-003 | Catalogue and v1 snapshot export, `--verify-only` | ✅ | `export_v1_snapshot.py`; gzip `mtime=0`, no file name (`lineage.write_catalogue`). |
| FR-004 | v1 offline dump | ✅ | `import_graph_v2.py dump`: `--execute --confirm-volume`, volume must exist (D-10), refused while in use, `DUMP.json` with SHA-256 and size. |
| FR-004a | Dump restore test | ✅ | The scratch volume must not exist, must not equal V1 or the current volume, and is removed in `finally`. |
| FR-005 | Verified inputs, exit 2 before output | ✅ | `lineage.verify_raw_inputs`, `hash_splits` and `read_catalogue` run before `out_dir.mkdir` (AC-018 test). |
| FR-006 | Products only from metadata | ✅ | `transform.run_meta_pass`: first line wins; conflicting duplicates are listed. |
| FR-007 | Brand rule | ✅ | `product_mapping.resolve_brand`, exact name; case groups in the lineage. |
| FR-008 | Category = `main_category` | ✅ | |
| FR-009 | Attributes for 4 exact keys | ✅ | See L-1 for a NUL-only edge case. |
| FR-010 | Taxon tree | ✅ | `taxonomy.TaxonomyBuilder`; collision raises, exit 2. |
| FR-011 | Review selection, drop order, cap, duplicates | ✅ | `review_selection.TopKSelector`, equivalent to the reference on 50 seeded cases. D-4, D-6 and D-7 are honoured. |
| FR-012 | Review properties, `in_train_split`, `cap_rank`, `embed_rank` | ✅ | |
| FR-013 | Users only from kept reviews | ✅ | |
| FR-014 | CSV format | ✅ | `csv_io`. Reviews are written in byte-offset order (D-2) and the order is asserted. Product-side files are sorted. |
| FR-015 | Lineage and invariants | ✅ | `lineage.assert_invariants` (source balance and dangling endpoints). |
| FR-016 | Pilot sample mode | ✅ | The sample acts as the catalogue (D-5). |
| FR-017 | Dry run | ✅ | Count-only writers; no CSV and no lineage. |
| FR-018 | `--require-clean` | ✅ | Fails closed when the git status is unknown. |
| FR-019 | Import wrapper and guards | ✅ (fixed) | H-1: the V1-name guard is now fail-closed under `--execute`, and `.env` is loaded. |
| FR-020 | External volume, memory via env | ✅ | `docker-compose.yml`; env-to-setting mapping checked (`db.transaction.timeout`, `db.tx_log.rotation.retention_policy`). |
| FR-021 | Wrong-graph guard and seal | ✅ (fixed) | H-2: a Taxon-count check is added. |
| FR-022 | 8 constraints | ✅ | |
| FR-023 | Embeddings (keyset, skip-empty, Review scope) | ✅ | |
| FR-024 | Vector indexes in procedure form, `awaitIndexes` | ✅ (fixed) | `allow_ddl_fallback = version >= 5.15` (D-3), so no DDL reaches 5.14. M-1: results are now consumed. |
| FR-025 | Full-text index, smoke test, `features_text` fallback | ✅ | Valid 5.x syntax. See L-5. |
| FR-026 | Validation gate | ✅ (delta) | The gates are implemented and fail the report. The gaps found in the first audit are closed by the delta (A-3 pilot thresholds, A-5 `seaborn`, A-6 collector tests). |
| FR-027 | Stamp | ✅ | Also requires `--confirm-validation-sha256` (D-9), unchanged embedding report and build params, and a clean lineage commit. |
| FR-028 | `graph_snapshot` keys | ✅ | `provenance._graph_version` returns `None` for 0 or more than 1 node. |
| FR-029 | Citable rule | ✅ | Live runs on v1 are no longer citable (intended, R8). Offline mode is unchanged. |
| FR-030 | Archive index `graph_version` | ✅ | |
| FR-031 | `batch_ingest.py` guarded MATCH | ✅ | No `MERGE (p:ParentProduct` in `REVIEW_QUERY`. The metadata step still merges products from metadata, as intended. |
| FR-032 | `BackfillService` skip-empty, ordered attributes | ✅ | |
| FR-033 | Ordered, titled category samples | ✅ | |
| FR-034 | 5.14-form `.cypher`, `create_indexes.py` note | ✅ | |
| FR-035 | `AmazonDataProcessor` fixes | ✅ | Both readers fixed (D-12). The stray `1` is removed: HEAD line 1292 fails `ast.parse`, and the working tree now parses. |
| FR-036 | Prompt cleanup (G-12) | ✅ | |
| FR-037 | README | ✅ (amended) | M-3: the pilot row now gives explicit paths. |
| FR-038 | H-15 grounding gate | ✅ (delta) | Implemented. `seaborn` is now in `.venv` and `requirements.txt` (A-5); M-4 is closed. |
| FR-039 | v2 baseline re-run | n/a | Runbook step R-12. `check_baseline_diff.py` is implemented and tested. |

### Non-functional requirements

| ID | Status | Notes |
|----|--------|-------|
| NFR-001 Determinism | ✅ | AC-016 test (byte-identical CSVs and lineage). |
| NFR-002 ≤ 3 GB RSS | ⚠️ | Measured per-entry costs: selector ≈ 539 B, selection plus pairs ≈ 238 B, exclusion pair ≈ 234 B. Before the fix the estimated peak was about 4.5–5.5 GB because all product records stayed alive through the review passes. After M-2 the estimate is about 3.3 GB. It is now measured by P-10. |
| NFR-003 ≤ 2 h | n/a | Measured at P-10. |
| NFR-004 Zero writes to v1 | ✅ (fixed) | Now enforced by H-1 and H-2. |
| NFR-005 Unit-testability | ✅ | No test references `datasets/raw` or bolt (grep). |
| NFR-006 Disk ≥ 40 GB | ✅ | Import guard. |
| NFR-007 Runtime memory | ✅ | Compose defaults. |
| NFR-008 Conventions | ✅ | Type hints, docstrings, logging, parameterised Cypher. Labels and keys are interpolated only from constants or `db.labels()`. |
| NFR-009 Reader compatibility | ✅ | No reader file changed. |

### Acceptance criteria

| ID | Status | Verification |
|----|--------|--------------|
| AC-001 | ✅ | `test_transform.py::test_meta_not_in_catalogue_counted` |
| AC-002 | ✅ | `test_catalogue_asin_without_meta` |
| AC-003 | ✅ | `test_split_exclusion_per_user_and_parent` |
| AC-004 | ✅ | `test_review_selection.py::test_cap_and_tie_order_on_25_reviews` |
| AC-005 | ✅ | `test_selector_matches_reference_on_seeded_fixtures` (50 seeds) |
| AC-006 | ✅ | `test_make_review_id_formula`, duplicate tests |
| AC-007 | ✅ | `test_embed_ranks_*` |
| AC-008 | ✅ | `test_product_mapping.py` (price, description, features, details cases) |
| AC-009 | ✅ | Brand tests and `test_brand_nodes_and_case_group_in_lineage` |
| AC-010 | ✅ | `test_category_is_main_category`, `test_blank_main_category_has_no_edge` |
| AC-011 | ✅ | `test_attributes_exact_keys_only`, `test_attribute_non_string_counted`, `test_attributes_deduplicated_across_products` |
| AC-012 | ✅ | `test_taxonomy.py` (a)–(g) |
| AC-013 | ✅ | `test_user_without_kept_reviews_has_no_row` |
| AC-014 | ✅ | `test_csv_io.py` round trip and counters |
| AC-015 | ✅ | `test_headers_match_spec` |
| AC-016 | ✅ | `test_two_runs_byte_identical` |
| AC-017 | ✅ | `test_lineage.py` |
| AC-018 | ✅ | `test_sha256_mismatch_exits_before_output`, `test_missing_split_exits_before_output` |
| AC-019 | ✅ | `test_sample_mod_selection` |
| AC-020 | ✅ | `test_dry_run_writes_nothing_same_counts` |
| AC-021 | ✅ | `test_import_command.py`, plus the new fail-closed test |
| AC-022 | ✅ | `test_embedding_templates.py` |
| AC-023 | ✅ | `test_post_import.py` embed tests |
| AC-024 | ✅ | `test_constraints_statements` |
| AC-025 | ✅ | `test_vector_indexes_procedure_only_on_514` |
| AC-026 | ✅ | `test_fulltext_fallback` |
| AC-027 | ✅ | `test_guard_*`, plus the new `test_guard_v1_lookalike_graph` |
| AC-028 | ✅ | `test_validation.py::test_each_gate_passes_and_fails`. This covers the gate functions only (M-5). |
| AC-029 | ✅ | `test_report_validates_and_fails_on_gate`, `test_report_only_never_changes_passed` |
| AC-030 | ✅ | `test_stamp_*` |
| AC-031 | ✅ | `test_provenance.py` (runtime snapshot, single GraphVersion) |
| AC-032 | ✅ | `test_graph_version_reasons` |
| AC-033 | ✅ | `test_provenance.py` manifest test (`graph_snapshot` keys) |
| AC-034 | ✅ | `test_legacy_ingest_guards.py` |
| AC-035 | ✅ | `test_backfill_service_skips_blank_texts`, `test_backfill_product_fetch_orders_attributes` |
| AC-036 | ✅ | `test_category_backfill_query_ordered_titled` |
| AC-037 | ✅ | `test_amazon_processor_*` |
| AC-038 | ✅ | `test_create_vector_indexes_cypher_procedure_form` |
| AC-039 | ✅ | `test_graph_cypher_prompt.py` |
| AC-040 | Runbook | Manual (R-1): `docker compose config` with and without `NEO4J_DATA_VOLUME`. Not run (no Docker). The compose file was read and is consistent with the spec. |
| AC-041 | Runbook | Manual (after CP-1). |
| AC-042 | Runbook | Manual (R-5). |
| AC-043 | Runbook | Integration (R-7). The pilot thresholds are now handled by amendment A-3 (AC-047); M-3 is closed. |
| AC-044 | Runbook | Integration (R-9, R-10). |
| AC-045 | Runbook | Integration (§6.6). |
| AC-047 | ✅ (delta) | `tests/graph_v2/test_validation.py`: `test_pilot_build_params_substitutes_three_counts`, `test_pilot_counts_pass_against_pilot_graph`, `test_pilot_counts_fail_against_full_build_graph`, `test_pilot_untitled_bound_stays_from_build_params`, `test_pilot_report_hashes_file_read_and_mode_errors` (see Delta audit) |
| AC-048 | ✅ (delta) | `tests/graph_v2/test_validate_graph_collectors.py`: every collector, R-01 … R-08, the `run_validation` wiring test and the per-collector exception test (11 cases) (see Delta audit) |
| AC-046 | ✅ | The targeted command passes with Docker and Neo4j unused. No test touches `datasets/raw/` (the directory was not renamed, by rule). The full suite has no new failures. |

### Gate #3 decisions

D-1 `graph_queries.py` kept ✅. D-2 byte-offset review order, asserted by `CsvOrderError` ✅. D-3 `setup_indexes(allow_ddl_fallback)` returning outcomes ✅. D-4 `ReviewCandidate.user_id` ✅. D-5 sample acts as the catalogue ✅. D-6 duplicates beyond the cap counted as `beyond_cap` (documented, and the kept list equals the reference) ✅. D-7 meta pass before reviews ✅. D-8 `product_content_rule` and `--build-params` ✅. D-9 `--confirm-validation-sha256` ✅. D-10 import and dump refuse missing volumes ✅. D-12 `process_reviews_for_products` field names and the `check_baseline_diff.py` test ✅.

## Findings

### 🔴 Critical Issues

None.

### 🟠 High Issues

**H-1. The import v1-name guard failed open** (`scripts/graph_ingestion/import_graph_v2.py:148`, `:367`). FIXED.
- **Problem**: `guard_import` only logged a warning when `NEO4J_DATA_VOLUME_V1` was unset, and `main` read `os.environ` without loading `.env`. `.env.example` documents the variable in `.env`, and nothing in this script loaded it. In the likely setup (value in `.env`, not exported in the shell), the guard was therefore inactive. With v1 stopped (R-4), `import --volume <v1> --execute --confirm-volume <v1>` would then run `--overwrite-destination=true` on the v1 volume. That breaks NFR-004 and FR-019 / AC-021 ("refuses a volume equal to `NEO4J_DATA_VOLUME_V1`").
- **Fix**:
  - `main` loads `REPO_ROOT/.env` with `override=False` when no env is injected.
  - `guard_import` raises `GuardRefused` (exit 2) under `--execute` when the variable is unset; log-only mode still only warns.
  - `python-dotenv` is already in `requirements.txt`.
  - New test: `tests/graph_v2/test_import_command.py::test_refuses_execute_without_v1_volume_name`.

**H-2. The FR-021 wrong-graph guard could not tell v1 from v2** (`scripts/graph_ingestion/post_import_v2.py:195-210`). FIXED (stricter than the spec's literal rule).
- **Problem**: the guard checked only `count(:ParentProduct) == lineage.counts.meta.products_written` and that no `GraphVersion` exists. The catalogue is the 265,307 v1 ASINs, and the ghosts are "filled from raw metadata" (research report). If P-01 finds `catalogue_missing_in_meta = 0`, `products_written` equals the v1 product count. v1 has no `GraphVersion`, so every post-import sub-command would pass the guard on a mis-pointed v1. Those sub-commands write constraints, a full-text index and `features_text`. NFR-004 relies on this guard.
- **Fix**: the guard also requires `count(:Taxon) == lineage.counts.nodes["Taxon"]`. This is a v2-only signature: v1 has no `Taxon` label, and no post-import step changes Taxon counts.
  - Test fakes updated.
  - New parametrised test over all 6 sub-commands: `tests/graph_v2/test_post_import.py::test_guard_v1_lookalike_graph`.
- **User confirmation requested**: this adds a condition to FR-021 (see "Decisions").

### 🟡 Medium Issues

**M-1. Unconsumed procedure and DDL results in `setup_indexes`** (`src/knowledge_graph/graphdb/setup_indexes.py:64-69, 81`). FIXED.
- **Problem**: the neo4j Python driver reports execution errors lazily. A failing `db.index.vector.createNodeIndex` was recorded as `"created"`, and its error surfaced on the next statement, so it was attributed to the next index. For the last index it was raised at session close, outside the per-index `try`. On ≥ 5.15 a procedure failure also never reached the DDL fallback.
- **Fix**: `.consume()` on both calls, so each error is raised inside its own index's `try`.

**M-2. NFR-002 memory risk** (`src/knowledge_graph/graph_v2/transform.py:449-460`; `scripts/graph_ingestion/preflight_v2.py:110-118, 335`). FIXED in part.
- **Problem**: all 265k `ProductRecord`s (description, features, `details_json`, `details_text`) and the valid ∪ test pair set (≈ 2.83M pairs, ≈ 0.66 GB) stayed alive through both review passes. Measured selector cost is ≈ 539 B per candidate, so ≈ 1.8 GB at 3.4M candidates. Estimated peak: 4.5–5.5 GB, against a 3 GB target.
- **Fix**:
  - The product records are released (`meta.records.clear()`) once the product-side CSVs are written, after computing the product-ID set and brand case groups.
  - `excluded` is deleted after pass 1.
  - Pre-flight P-10 now records `dry_run_peak_rss_bytes`, taken right after the full dry run and before the embedding model loads, so NFR-002 is measured.
- **Remaining**: the estimated peak is about 3.3 GB at the end of pass 1 (selector plus selection plus exclusion set). The host has 16 GB, so this is not a crash risk. The user should judge the measured value at CP-1.

**M-3. Pilot runbook gap: pilot build params and paths** (`scripts/graph_ingestion/README.md`, R-7 row). CLOSED by the delta: the user chose option (a), amendment A-3 (see Delta audit).
- **Problem**: R-7 said only `post_import_v2.py all` and `validate_graph.py --pilot`. The defaults of both scripts point at the full build (`graph_versions/v2/lineage.json`, `build_params.json`, `embedding_report.json`), so a pilot run would hit the guard or overwrite the full embedding report. Also, H-01, H-08 and H-10 compare against `accepted_catalogue_missing`, `expected_review_count` and `expected_embed_reviews`. With the full build's `build_params.json`, `validate_graph.py --pilot` always fails H-08, so AC-043 cannot pass. The spec (§6.4, FR-026) does not define pilot build params.
- **Fix**: the README R-7 row now gives explicit pilot paths and states that a pilot `graph_versions/v2/pilot/build_params.json` with the pilot-lineage values is needed.

**M-4. H-15 depends on `seaborn`** (`scripts/graph_ingestion/validate_graph.py:354`). CLOSED by the delta: `seaborn` is installed in `.venv` and declared in `requirements.txt` (A-5).
- **Problem**: `collect_h15` loads `scripts/evaluate_retrieval.py`, which imports `src/evaluation/visualizer.py` and through it `seaborn`. The project `.venv` lacks `seaborn` (AI-13), so H-15 fails there with an import error, which counts as a gate failure. The spec requires `validate_benchmark_graph_grounding()` from `evaluate_retrieval.py` unchanged.
- **Action**: README note added. Either run validation with the Anaconda interpreter, or do AI-13 before R-7.

**M-5. The validation collectors have no tests** (`scripts/graph_ingestion/validate_graph.py:154-497`). CLOSED by the delta: A-6 / AC-048 tests were added.
- The Cypher collectors for H-01 … H-18 and R-01 … R-08 (`collect_h06`, `collect_h14` with CSV read-back, `collect_h16_h18`, and others) are not exercised by any unit test. AC-028 and AC-029 test only the pure gate functions. The code was reviewed by hand and no defect was found. Its first real execution will be the pilot (R-7), which is the designed safety net.
- **Recommendation**: add fake-session tests for at least `collect_h06`, `collect_h14` and `run_validation`'s gate wiring before the full run.

### 🔵 Low Issues / Suggestions (not fixed)

1. **L-1**: `product_mapping.extract_attributes` (`product_mapping.py:199`) uses `value.strip()` rather than the sanitizer-aware `_visible`. A details value made only of NUL characters becomes an `Attribute` with a null `attribute_value` after sanitisation. That fails H-10 (fails safe).
2. **L-2**: blank tests differ between Python `str.strip()` (transform, templates) and Cypher `trim()` (H-03, H-10, eligibility) for rare control characters. A mismatch fails a gate (fails safe).
3. **L-3**: the import wrapper does not check the CSV SHA-256 against `lineage.outputs` before importing. Stale CSVs from an aborted transform would be caught only later, by H-18 or H-14. Suggested addition: an optional `--lineage` check.
4. **L-4**: `--legacy-style-quoting=false` is not passed explicitly; the code relies on the 5.14 default. Backslash and quote fidelity is verified by H-14 on the pilot.
5. **L-5**: the full-text smoke token is the longest features-only token of a seeded product. It can still be a common word, so the product may fall outside the top 50 and give a false failure. That failure triggers the `features_text` fallback and blocks the stamp (fails safe). A document-frequency-aware choice would be more robust.
6. **L-6**: `export_v1_snapshot.py`, run without `--verify-only`, would rewrite the catalogue from whatever graph it is connected to (for example v2 after the switch). The files are git-tracked, so this is recoverable.
7. **L-7**: re-running `fulltext-index` after the fallback logs and returns `FULLTEXT_FIELDS`, although the index uses the fallback fields. The stamp reads the fields from `SHOW INDEXES`, so it is correct.
8. **L-8**: `post_import_v2.main` with an injected `session_factory` and no connector would construct a real `Neo4jConnector` in `vector-indexes`. This is a test hazard only; the guard tests refuse earlier.
9. **L-9**: the transform does not detect duplicate node IDs. Examples: one `review_id` under two `parent_asin`s, or two IDs that differ only by NUL / U+001F and collapse after sanitisation. The import aborts on them (`--skip-duplicate-nodes=false`), which is safe but late.
10. **L-10**: the restore test compares `db.labels()`-based snapshot counts with `UNWIND labels(n)` counts. A zero-count label token would give a false failure (fails safe).
11. **L-11**: `scripts/graph_ingestion/sample_ingest.py` (another legacy loader) has no FR-031-style guard. It is outside the spec scope.
12. **L-12**: the full test suite writes offline mock runs into the git-ignored `evaluations/` (AI-12, pre-existing). This audit's runs created `evaluations/eval_2026-10-19_1430` and `eval_2026-10-19_1444`. They were left in place.
13. **L-13**: under the H-09 `attribute_key` fallback, `post_import_v2.py all` stops at `constraints` (exit 1). The remaining steps must then be run one by one. `validate_graph.py` has `--attribute-key-fallback`, but `post_import_v2.py` has no matching switch.

## Test Results

The Anaconda interpreter (`/opt/homebrew/anaconda3/bin/python3`, Python 3.11.7, pytest 7.4.0) was used. Neo4j and Docker were not used.

**Targeted** (`python3 -m pytest tests/graph_v2 tests/test_legacy_ingest_guards.py tests/test_graph_cypher_prompt.py tests/test_provenance.py tests/test_archive_eval_run.py`):

| Test File | Tests Run | Passed | Failed | Errors |
|-----------|-----------|--------|--------|--------|
| tests/graph_v2/test_check_baseline_diff.py | 3 | 3 | 0 | 0 |
| tests/graph_v2/test_csv_io.py | 8 | 8 | 0 | 0 |
| tests/graph_v2/test_embedding_templates.py | 7 | 7 | 0 | 0 |
| tests/graph_v2/test_import_command.py | 9 | 9 | 0 | 0 |
| tests/graph_v2/test_lineage.py | 7 | 7 | 0 | 0 |
| tests/graph_v2/test_post_import.py | 30 | 30 | 0 | 0 |
| tests/graph_v2/test_product_mapping.py | 13 | 13 | 0 | 0 |
| tests/graph_v2/test_review_selection.py | 8 | 8 | 0 | 0 |
| tests/graph_v2/test_taxonomy.py | 8 | 8 | 0 | 0 |
| tests/graph_v2/test_transform.py | 14 | 14 | 0 | 0 |
| tests/graph_v2/test_validation.py | 4 | 4 | 0 | 0 |
| tests/test_legacy_ingest_guards.py | 8 | 8 | 0 | 0 |
| tests/test_graph_cypher_prompt.py | 3 | 3 | 0 | 0 |
| tests/test_provenance.py | 20 | 20 | 0 | 0 |
| tests/test_archive_eval_run.py | 13 | 13 | 0 | 0 |
| **Total** | **155** | **155** | **0** | **0** |

Before the fixes: 148 passed. The 7 new tests are 1 import-guard test and 6 parametrised v1-lookalike guard cases.

**Full suite**: `python3 -m pytest tests/ --ignore=tests/test_category_resolution.py --ignore=tests/test_challenger_empirical.py --ignore=tests/test_benchmark_alignment.py --ignore=tests/test_cypher_ranking.py`
- Before the fixes: 760 passed, 5 skipped.
- After the fixes: **767 passed, 5 skipped**, 0 failed.

**Extra smoke check**: `preflight_v2.main` was run on `tests/fixtures/graph_v2/` with `--skip-v1 --skip-docker` and a fake embedder. It exited 0, wrote no file under `datasets/graph_build/`, and `p10_timing.dry_run_peak_rss_bytes` was present.

## Files Modified by Audit

| File | Changes Made | Severity Addressed |
|------|-------------|-------------------|
| `scripts/graph_ingestion/import_graph_v2.py` | Fail-closed V1 guard under `--execute` (l.148-152); `.env` loaded with `override=False` (l.41, 367); docstring updated | High (H-1) |
| `scripts/graph_ingestion/post_import_v2.py` | `GUARD_TAXON_COUNT_QUERY` (l.97); `check_graph_guard` also requires the lineage Taxon count (l.195-210); docstring updated | High (H-2) |
| `src/knowledge_graph/graphdb/setup_indexes.py` | `.consume()` on the procedure and DDL calls (l.64-69, 81) | Medium (M-1) |
| `src/knowledge_graph/graph_v2/transform.py` | Product records released after the product-side write; exclusion set deleted after pass 1 (l.449-460) | Medium (M-2) |
| `scripts/graph_ingestion/preflight_v2.py` | `peak_rss_bytes()` (l.110) and `p10_timing.dry_run_peak_rss_bytes` (l.335) | Medium (M-2) |
| `scripts/graph_ingestion/README.md` | R-7 explicit pilot paths and pilot build params; notes on the V1 env requirement and the H-15 `seaborn` dependency | Medium (M-3, M-4) |
| `tests/graph_v2/test_import_command.py` | New `test_refuses_execute_without_v1_volume_name` | High (H-1) |
| `tests/graph_v2/test_post_import.py` | Fakes answer the Taxon guard query; new `test_guard_v1_lookalike_graph` (6 cases) | High (H-2) |

## Decisions for the User

1. **FR-021 guard (H-2)**: confirm adding the Taxon-count condition. It is stricter than the literal spec and is needed for NFR-004 when `catalogue_missing_in_meta = 0`. @pm-specs may want to amend FR-021 and AC-027.
2. **Import guard (H-1)**: confirm the fail-closed rule: `--execute` requires `NEO4J_DATA_VOLUME_V1`, read from the shell or the repository `.env`.
3. **Pilot build params (M-3)**: the spec does not define them. Proposal: `graph_versions/v2/pilot/build_params.json` with the pilot-lineage values (`accepted_catalogue_missing`, `accepted_untitled_count`, `expected_review_count`, `expected_embed_reviews`) and the same `product_content_rule`, approved at CP-5. The alternative is a spec change so that `--pilot` validation takes these thresholds from the pilot lineage.
4. **NFR-002 (M-2)**: judge `p10_timing.dry_run_peak_rss_bytes` at CP-1. The estimated peak after the fix is about 3.3 GB, slightly above the 3 GB target, on a 16 GB host.
5. **H-15 environment (M-4)**: run `validate_graph.py` with the Anaconda interpreter, or do AI-13 (add `seaborn` to `.venv`) before R-7.
6. **M-5**: optionally, have @engineer add fake-session tests for the `validate_graph.py` collectors before the full run.

## Verdict

**PASS WITH FIXES.** The code phase meets the specification. Two High safety gaps in the volume guards were fixed and covered by new tests. Three Medium issues were fixed in code or documentation, and two remain as operational items or recommendations. No architectural change was made; the design (catalogue-first transform, offline `neo4j-admin import`, external volumes, validation gate, `GraphVersion` stamp) is sound. The runbook (AC-040 … AC-045) can proceed through its checkpoints once the user confirms decisions 1–3. No graph operation was performed during this audit.

---

## Delta audit (post-audit follow-ups, 2026-10-19)

**Scope**: only the changes made after the first audit.
- Spec amendments in §13 A-1 … A-6, with the new AC-047 and AC-048 and the updated FR-019/021/026/037/038 and NFR-002/004.
- `seaborn` installed in `.venv` and added to `requirements.txt` (A-5).
- @engineer's A-3:
  - `pilot_build_params` in `src/knowledge_graph/graph_v2/validation.py`;
  - `BuildPaths`, `FULL_PATHS`, `PILOT_PATHS`, `build_paths()` and `shared_input()` in `lineage.py`;
  - `resolve_paths`, `check_pilot_mode` and `effective_build_params` in `scripts/graph_ingestion/validate_graph.py`;
  - default paths in `build_graph_v2.py`;
  - README R-6 and R-7.
- @engineer's A-6: `tests/graph_v2/test_validate_graph_collectors.py`, and the AC-047 tests in `tests/graph_v2/test_validation.py`.

**Safety rules**: same as the first audit. No Docker, no Neo4j, no raw JSONL, no commits. The four bolt test files were excluded.

**Delta verdict: PASS.** No Critical, High or Medium issues; 3 Low. No code was changed by this delta audit.

### Checks

| Check | Result | Evidence |
|---|---|---|
| Only the three counts are substituted | ✅ | `validation.pilot_build_params` (l.108-120) is a `model_copy(update=…)` of `accepted_catalogue_missing` ← `catalogue_missing_in_meta`, `expected_review_count` ← `kept` and `expected_embed_reviews` ← `embed_selected`. The test asserts that the set of changed `BuildParams` fields is exactly these three. `accepted_untitled_count`, `review_cap` and `product_content_rule` stay as read. |
| Substitution only under `--pilot` | ✅ | `run_validation` gets its params from `effective_build_params(inputs, args.pilot)`. Without `--pilot` it returns the read object unchanged (asserted with `is`). The gate functions are unchanged. |
| H-01, H-03, H-08 and H-10 behaviour (AC-047 a–c) | ✅ | (a) Pilot-shaped fake graph: H-01, H-03, H-08 and H-10 pass. (b) Full-build-shaped fake graph: H-01, H-08 and H-10 fail. (c) H-03 fails with `max = 3` from build_params, although the observed count equals the lineage `title_empty`. In pilot mode the H-01 catalogue count is the sampled catalogue (`load_inputs`, `in_sample`), as §5.5 requires. |
| `build_params_sha256` = hash of the file read (AC-047 d) | ✅ | `load_inputs` hashes `args.build_params`; `build_report` uses `inputs.file_hashes["build_params"]`. Asserted. |
| Mode mismatch exits 2 | ✅ | `check_pilot_mode` runs in `load_inputs` before any session or embedder is created. A pilot lineage without `--pilot`, and `--pilot` with a full lineage, both raise `InputVerificationError`, and `main` returns 2. The test passes a session factory that fails if it is called. `run_validation` also re-checks, and `main` maps that case to 2. The second direction (`--pilot` with a full lineage) is stricter than FR-026's text and consistent with its intent. |
| Path consistency between build and validate | ✅ | Both scripts take their defaults from `lineage.build_paths` and `shared_input`. With `--sample-mod`, `build_graph_v2` writes `datasets/graph_build/v2_pilot/import` and `graph_versions/v2/pilot/lineage.json`; `validate_graph --pilot` reads exactly those, plus `graph_versions/v2/pilot/embedding_report.json`. It writes `graph_versions/v2/pilot/validation_report.json` and reads the full `graph_versions/v2/build_params.json`. The full-build defaults also match. `test_pilot_default_paths_consistent` asserts all of this; explicit flags still override. |
| README R-7 matches §6.3 and §6.4 | ✅ | All §6.4 artefact paths match: import CSVs, reports, lineage, `import_run.json`, embedding report, validation report and `pilot_report.json`. The full build's `build_params.json` is used, with no pilot build params file. The `post_import_v2.py` and `validate_graph.py --pilot` commands match the §6.3 R-7 command, and the A-3 count substitution is explained. The `NEO4J_DATA_VOLUME_V1` requirement (A-2) is in Notes, and the outdated `seaborn` warning is gone (A-5). |
| AC-048 coverage | ✅ | One or more fake-session tests for each collector named in AC-048: `collect_h01_h04`, `collect_h05`, `collect_h06` (fixture splits), `collect_h07_h08`, `collect_h09`, `collect_h10` (both content rules), `collect_h11` (fake embedder), `collect_h12_h13`, `collect_h14` (round trip from the fixture import dir, plus altered and missing nodes), `collect_h15` (fake grounding and connector, empty pilot sample), `collect_h16_h18` and `collect_report_only` (R-01 … R-08 mapping, plus error and missing-v1-file handling). The `run_validation` wiring test checks gate IDs, captured arguments, `graph_counts` and the hash. A parametrised exception test confirms that each failing collector fails exactly its own gates with `passed: false`. No Neo4j, Docker or `datasets/raw/` is used. |
| No regression of H-1 / H-2 / M-1 / M-2 | ✅ | H-1: `import_graph_v2.py:148-152` (fail-closed; `if not v1` also covers an empty value, as A-2 requires) and `:41`, `:367` (`load_dotenv`, `override=False`). H-2: `post_import_v2.py:97`, `:203-206` (Taxon guard). M-1: `setup_indexes.py:69`, `:81` (`.consume()`). M-2: `transform.py:453`, `:460`, `preflight_v2.py:335`. Their tests (`test_refuses_execute_without_v1_volume_name`, `test_guard_v1_lookalike_graph` ×6) pass. |

### 🔵 Low (delta, not fixed)

1. **DL-1**: `build_graph_v2.config_from_args(args, repo_root)` uses `repo_root` for the default paths but passes the module constant `REPO_ROOT` as `TransformConfig.repo_root`, which sets the git scope for `--require-clean`. There is no effect in production, where they are equal. It is inconsistent only when a test injects another root.
2. **DL-2**: `build_graph_v2.py` now runs with no arguments, using the full-build defaults. A bare invocation starts the 22.6 GB transform and overwrites `datasets/graph_build/v2/import/` and `graph_versions/v2/lineage.json`. This is not a graph operation and `--require-clean` is still in the runbook, but users should know a bare call is a real build.
3. **DL-3**: `post_import_v2.py` keeps full-build path defaults: there is no `--pilot` switch, so R-7 passes the pilot paths explicitly. A pilot run that forgets `--lineage` is refused by the FR-021 guard (counts differ) rather than writing anything. This is acceptable as documented.

### Test results (delta)

The project `.venv/bin/python` (Python 3.11.7) was used. Neo4j and Docker were not used.

| Run | Result |
|---|---|
| `tests/graph_v2/test_validation.py` + `tests/graph_v2/test_validate_graph_collectors.py` | 42 passed |
| Targeted (`tests/graph_v2 tests/test_legacy_ingest_guards.py tests/test_graph_cypher_prompt.py tests/test_provenance.py tests/test_archive_eval_run.py`) | 193 passed (155 at the first audit + 38 new) |
| Full suite, 4 bolt files excluded | **805 passed, 5 skipped**, 0 failed (767 at the first audit + 38 new) |

The full suite again wrote one offline mock run into the git-ignored `evaluations/` folder (`eval_2026-10-19_1908`, pre-existing AI-12). No file was created under `datasets/graph_build/` or `graph_versions/`.

### Updated status of first-audit items

- M-3 is closed (A-3, AC-047), M-4 is closed (A-5) and M-5 is closed (A-6, AC-048).
- M-1 and the H-items remain fixed.
- M-2 is accepted per A-4: the user judges the measured peak memory at CP-1.
- Decisions 1–5 of the first audit were accepted by the user and recorded in spec §13.

### Overall verdict (after delta)

**PASS WITH FIXES** (unchanged). The fixes are the first audit's H-1, H-2, M-1 and M-2. The post-audit follow-ups conform to the amended specification and add no new defects. Every unit-testable acceptance criterion (AC-001 … AC-039, AC-046 … AC-048) is met. AC-040 … AC-045 remain runbook checks.
