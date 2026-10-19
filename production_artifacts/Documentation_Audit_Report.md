# Documentation Audit Report

**Date**: 2026-10-19
**Auditor**: Documentation Auditor Agent (@doc-cleaner)
**Scope**: `/implement` Phase 6, Graph v2 rebuild (Vision 2026-10-19-018 … 021). Code only: **no graph operation has run, the live Neo4j is still the v1 graph.** No v2 result is claimed anywhere.

Sources checked: `Technical_Specification_Graph_Rebuild.md` (incl. §13), `Research_Report_Graph_Rebuild.md`, `Audit_Report_Graph_Rebuild.md`, Vision Decision Log 2026-10-19-018 … 021, `src/knowledge_graph/graph_v2/`, `scripts/graph_ingestion/*_v2.py`, `validate_graph.py`, `export_v1_snapshot.py`, `check_baseline_diff.py`, `src/knowledge_graph/docker-compose.yml`, `.env.example`.

## Executive Summary

The v2 work left 13 documents stating v1 facts as current: the ingest path (`batch_ingest.py`), the Docker start commands (compose now needs an external volume), the `Variant` / `PriceRange` schema, and the coverage figures that Vision 2026-10-19-021 invalidates. 12 files were fixed with dated notes or targeted edits that keep v1 history. 6 items needed your approval; the user resolved them on 2026-10-19 (see "Decisions for the User" and "Follow-up Pass" below).

## Documentation Inventory (scoped to the v2 change)

| File | Status | Notes |
|---|---|---|
| `scripts/graph_ingestion/README.md` | ✅ v2 section / ⏰ legacy section (fixed) | v2 runbook matches CLI flags and defaults in `build_graph_v2.py`, `import_graph_v2.py`, `post_import_v2.py`, `validate_graph.py`, `export_v1_snapshot.py`, `preflight_v2.py`, `check_baseline_diff.py`. A-3 (no pilot `build_params.json`) and A-5 (seaborn) are already reflected. Legacy section claimed OpenAI embeddings and Cypher 25 vector indexes |
| `README.md` (root) | ⏰ fixed | Pointed to `batch_ingest.py` and `cd src/knowledge_graph; docker-compose up` |
| `src/README.md` | ⏰ fixed | No `graph_v2/`; named a non-existent `knowledge_graph/neo4j_connector.py` (real path `graphdb/`) |
| `src/knowledge_graph/README.md` | 🗑️ Deleted 2026-10-19 (user-approved) | Wrong import path, missing `example_usage.py`, never-implemented "Planned" schema, old compose command |
| `src/knowledge_graph/DOCKER.md` | ⚠️ fixed | Contradicted `docker-compose.yml` (external volume, `NEO4J_DATA_VOLUME` required, memory from env, `down -v` no longer removes the graph) |
| `src/knowledge_graph/QUICKSTART.md` | 🗑️ Deleted 2026-10-19 (user-approved) | Had obsolete `Product` examples and `graphrag` imports; `DOCKER.md` now points to `graphdb/neo4j_connector.py` |
| `production_artifacts/graph_state_snapshot.md` | ⏰ banner added (AI-13) | July curated-subset state; rewrite flagged |
| `production_artifacts/action_items/README.md` | ⏰ fixed | Added the graph rebuild row and a v1-figures note |
| `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` | ⏰ fixed | "Live data facts" correction note; the "Consequence" sentence marked superseded |
| `production_artifacts/action_items/Proposed_Fix_Vector_Aggregation.md` | ⏰ fixed | "2.2% / 47%" marked as v1 and invalidated |
| `production_artifacts/action_items/Live_Graph_Audit_2026-10-10.md` | ⏰ fixed | Header note (v1; F-02 timestamp backfill cannot work; legacy structures) |
| `docs/kg_pipeline/schema.md` | ⏰ banner added, rewrite flagged | Design-time schema with `Variant`, `PriceRange`, `RATED`, `REVIEWS` |
| `diagrams/nodes_edges_mermaid.md`, `diagrams/general_kg_state_of_the_art_mermaid.md` | ⏰ comment added, redraw flagged | Show `Variant` / `PriceRange` |
| `diagrams/conversation_flow.md` | ⏰ flagged only | Node box lists `:Item ... :PriceRange` |
| `docs/kg_pipeline/extensibility.md`, `chainlit.md`, `production_artifacts/Project_State_Report.md`, `evaluations_archive/README.md` | ✅ | No v1/v2 conflicts found |
| `.env.example`, `src/knowledge_graph/docker-compose.yml` | ✅ | Match the spec (FR-020) |

## Findings by Severity

### ⚠️ Conflicting
- `DOCKER.md` vs `docker-compose.yml`: docs said `cd src/knowledge_graph && docker-compose up`, heap 512m/2G, page cache 1G, and `down -v` deletes data. Compose is external-volume, `NEO4J_DATA_VOLUME` required, heap 2G (initial = max), page cache 2G, tx timeout 60s. Resolved in favour of compose.
- Roadmap / AFP-002 "47% have reviews", "53% cold", 4.7% / 2.2% coverage vs Vision 2026-10-19-021 (invalidated; 12% of titled products have reviews in v1). Resolved with dated correction notes; the original v1 numbers stay as history.
- `Live_Graph_Audit` F-02 suggests backfilling review timestamps from `processed_reviews.csv`; Vision -021 item 6 says `sort_timestamp` is 0 in all v1 reviews. Noted in the audit header.

### ⏰ Outdated
- Root `README.md`, `scripts/graph_ingestion/README.md` (legacy part), `src/README.md`, `graph_state_snapshot.md`, `docs/kg_pipeline/schema.md`, diagrams. See the fixes below.
- ~~`CLAUDE.md` project-structure list lacks `src/knowledge_graph/graph_v2/`~~ Resolved 2026-10-19: line added by the user-approved edit.
- ~~`Implementation_Plan.md` GAP-003 "Done", F3.5 DDL, F2/F3 curated-subset story, no F4~~ Resolved 2026-10-19: F4 and dated notes on F2, F3, F3.5 and GAP-003 added (user-approved). AI-13 remains open (the snapshot rewrite waits for v2).

### 📋 Duplicated
- v1 coverage figures appear in the Roadmap (§1 table and R1-7), AFP-002 §1, the Research Report R2 and Vision decisions. Canonical correction: Vision 2026-10-19-021. Other documents now carry a short note and link rather than a restatement.

### 🔗 Stale References
- `src/README.md`: `neo4j_connector.py` and `resolver_service.py` live in `graphdb/`. Fixed.
- `QUICKSTART.md` and `src/knowledge_graph/README.md` (wrong paths, `graphrag...` imports, missing `example_usage.py`): both files deleted on 2026-10-19 with user approval. The follow-up pass (below) found no remaining links to them.

### 🕳️ Missing
- A schema document for v2 (the spec §5.1 is the only source). Propose creating it after the v2 build, from `graph_versions/v2/lineage.json`.
- `graph_versions/` (v1 freeze, v2 record) has no README; it appears only after the CPs run.
- `src/knowledge_graph/graph_v2/` has module docstrings in the spec only; no package README. Optional.
- Neo4j version constraint (5.14 Community: procedures, not DDL) is documented in `scripts/graph_ingestion/README.md` now; `create_indexes.py` still contains DDL (code; noted, not touched).

### ✅ Valid
`scripts/graph_ingestion/README.md` v2 section, `.env.example`, `docker-compose.yml`, `extensibility.md`, `chainlit.md`, the A-1 … A-6 amendment status lines in spec §13 versus code (A-3 and A-6 were marked "to implement" at the time of the spec; `pilot_build_params` and `tests/graph_v2/test_validate_graph_collectors.py` now exist in the tree, so the spec's "Code status" column for those two rows is stale; the spec is protected and not edited).

## Fixes Applied

| File | Change | Reason |
|---|---|---|
| `README.md` | Getting Started: env + external volume, compose from repo root, step 3 now states v1 vs v2 ingest and that nothing is built; `graph_v2/` in the directory list | Stale ingest and Docker path |
| `src/README.md` | `knowledge_graph/` entry corrected, `graph_v2/` added | Stale path, new package |
| `src/knowledge_graph/README.md` | Dated status banner (later superseded: file deleted 2026-10-19) | Rewrite flagged instead |
| `src/knowledge_graph/DOCKER.md` | Start command, external volume, memory env vars, `down -v` semantics, volume list | Contradicted compose |
| `src/knowledge_graph/QUICKSTART.md` | Compose command; `test_connector.py` path (later superseded: file deleted 2026-10-19) | Stale |
| `production_artifacts/graph_state_snapshot.md` | Historical / stale banner pointing to v1 census and v2 records (AI-13) | Stale since 2026-10-10 |
| `production_artifacts/action_items/README.md` | Graph rebuild row; v1-figures note | Index completeness, Vision -021 |
| `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` | Correction note under "Live data facts (graph v1…)"; "Consequence" marked superseded | Vision -021 |
| `production_artifacts/action_items/Proposed_Fix_Vector_Aggregation.md` | v1 / invalidated note on 2.2% / 47% | Vision -021 |
| `production_artifacts/action_items/Live_Graph_Audit_2026-10-10.md` | Header note | v1 record, F-02 timestamp idea cannot work |
| `docs/kg_pipeline/schema.md` | Banner: design-time schema, v1 differences, v2 schema pointer | `Variant` / `PriceRange` etc. |
| `diagrams/nodes_edges_mermaid.md`, `diagrams/general_kg_state_of_the_art_mermaid.md` | Mermaid `%%` comment (no rendering change) | Show dropped structures |
| `scripts/graph_ingestion/README.md` | Legacy section: batch_ingest MERGE/MATCH state, procedure-form vector indexes on 5.14, no OpenAI key for embeddings | Stale claims |

## Proposed Actions

| Action | File | Status |
|---|---|---|
| Edit (protected config) | `CLAUDE.md` Project Structure | **Resolved 2026-10-19**: user approved; `src/knowledge_graph/graph_v2/` line added |
| Add item F4 | `production_artifacts/Implementation_Plan.md` | **Resolved 2026-10-19**: user approved; F4 plus dated notes on F2, F3, F3.5 and GAP-003 added. AI-13 still open |
| Rewrite or delete | `src/knowledge_graph/README.md` and `QUICKSTART.md` | **Resolved 2026-10-19**: user approved deletion; `DOCKER.md` points to the runbook and `graphdb/neo4j_connector.py` |
| Major rewrite | `production_artifacts/graph_state_snapshot.md` | **Deferred by the user until v2 is built.** Replace with a generated v1 snapshot (`graph_versions/v1/snapshot.json` from `export_v1_snapshot.py`) and, after the build, v2 |
| Major rewrite | `docs/kg_pipeline/schema.md` and 3 diagrams (incl. `diagrams/conversation_flow.md` node box; the `.jpg` architecture image) | **Deferred by the user until v2 is built and validated** |
| Create | v2 schema doc and `graph_versions/README.md` | After the build |
| Spec status lines | `Technical_Specification_Graph_Rebuild.md` §13 | A-3 and A-6 rows say "To implement"; code and tests for both exist now. Owner @pm-specs |
| None (verified) | `src/knowledge_graph/graphdb/create_indexes.py` | Still uses `CREATE VECTOR INDEX` DDL; the FR-034 docstring note ("Needs Neo4j >= 5.15") exists. No action |

## Decisions for the User
All four decisions were taken on 2026-10-19:
1. `CLAUDE.md` structure line: approved and applied.
2. F4 and related text updates in `Implementation_Plan.md`: approved and applied.
3. `src/knowledge_graph/README.md` / `QUICKSTART.md`: deleted.
4. `graph_state_snapshot.md`, `schema.md` and the diagrams: rewrite after the v2 build.

## Follow-up Pass (2026-10-19)

Scope: changes made after the report above (file deletions, CLAUDE.md line, F4, `--force` guard in `build_graph_v2.py`, thesis contribution 13).

| Check | Result |
|---|---|
| References to the deleted `src/knowledge_graph/README.md` / `QUICKSTART.md` | None left in docs, code or config. Only `DOCKER.md` line 401 mentions them, deliberately, as a removal note; `src/README.md` links the root README, not the deleted file. `Technical_Specification_Graph_Rebuild.md` line 964 matched a link pattern but is a protected spec, not read for edits |
| `scripts/graph_ingestion/README.md` vs `build_graph_v2.py` | The CLI (`--force`, `--dry-run`, `--sample-mod`, `--require-clean`, default paths, exit code 2) matched. The runbook did not mention `--force`. **Fixed**: R-6 now explains the refusal on existing lineage or non-empty CSV directory, `--force` for the pilot and the full build, and that `--dry-run` needs no `--force` |
| `CLAUDE.md`, `Implementation_Plan.md` F4 and notes | Verified present and consistent with the runbook (F4 links the runbook; gap table row F4 says graph operations not run) |
| `thesis/README.md` vs `thesis/13-doc-graph-integrity.md` | Consistent (read only): index row 13, "Total Thesis Documents: 13", RQ1 … RQ13, Chapter 3/4/5 mapping, correction notes for docs 3, 4, 6, 7, 8, 10, 11 and the unchanged doc 12. Doc 13's header (not executed, 12 test modules) matches the README. Referenced `.agents/skills/thesis_evaluator/SKILL.md` exists |

Files changed in this pass: `scripts/graph_ingestion/README.md`, `production_artifacts/Documentation_Audit_Report.md`.
Still open: `graph_state_snapshot.md`, `schema.md`, the 3 diagrams and the `.jpg` (deferred until v2 is built); the v2 schema doc and `graph_versions/README.md` (after the build); spec §13 status lines for A-3 and A-6 (owner @pm-specs); AI-13 in the plan.

Note on scope: `docs/changelog/changelog.md` was not read for edits or modified (historian writing in parallel). Existing changelog lines mentioning `CREATE VECTOR INDEX` working (line 1140) are historical and unchanged; they conflict with the 5.14 reality (see Implementation_Plan GAP-003 note).
