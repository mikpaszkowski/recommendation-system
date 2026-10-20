# Implementation Plan: Explainable Hybrid GraphRAG for Conversational Recommendation

> **Last restructured**: 2026-07-08 — Reorganised from linear Phase 0–3 into **Foundation → Meta-Phase A → Meta-Phase B**.
> **Foundation revised**: 2026-07-11 — LLM-REDIAL dependency removed from Foundation. Amazon-curated subset strategy adopted for the initial graph build. REDIAL integration deferred to Meta-Phase B.
> **Status audit**: 2026-10-10 — A4–A6 statuses corrected against the live graph. Open items tagged `AI-xx` reference `production_artifacts/action_items/Live_Graph_Audit_2026-10-10.md`.
> **Retrieval redesign**: 2026-10-17 — Retrieval score redesign roadmap (releases R1–R5, work packages `RS-xx`) added under A1.1. Source: `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md`.
> **R2a**: 2026-10-18 — Release R2a (RS-23 spurious-CLARIFY fix, constraint-satisfaction@K, paired statistics, citable-run provenance, `evaluations_archive/`) implemented; exit gate PASS (`production_artifacts/Audit_Report.md`, "R2a exit gate"). R2b (RS-21 benchmark v2, RS-02 evidence) is open.
> **Graph v2**: 2026-10-19 — F4 added (user-approved). 39% of live products were empty "ghost" nodes; the graph is rebuilt from the raw Amazon 2023 files (Vision 2026-10-19-018 … 021). Code done and audited; no graph operation run yet. R2b waits for F4.
> **Graph v2 built**: 2026-10-20 — F4 complete. Live Neo4j runs on volume `kg_neo4j_data_v2` (265,307 products, 8 untitled; 3,382,248 reviews; 1,183-node category tree), `GraphVersion` v2 stamped; v1 kept as a stopped container and a dump.
> **R2b complete**: 2026-10-20 — Stratified Benchmark v2 (`evaluations/benchmarks/benchmark_v2.json`, 251 queries: 40×5 `S0`–`S4` + 30 `A` + 21 `legacy`, SHA-256 `3ae073ff…1f3c`), S1 query-time review masking (`mask_review_asins`), redefined bias metrics (`review_cap_bias@k`, `head_popularity_bias@k`), and `RS-02`/`RS-25` tuning protocol (`evaluations/benchmarks/r2b_tuning_report.json`) completed and audited (PASS). Stage 1 (`GV2-07`..`GV2-09`) is next.

---

## 1. Solution Architecture (State-of-the-Art)

The system is a Multi-Agent System (MAS) that combines a Neo4j Knowledge Graph, Hybrid GraphRAG retrieval, and LLM-driven orchestration into a conversational recommender.

**Technology Stack:**
* **Database**: Neo4j (structured graph + vector index for ANN search)
* **Logic / Agents**: LangChain + procedural Python orchestration; LangGraph `SqliteSaver` for MemoCRS persistence (Meta-Phase B)
* **LLM API**: OpenAI GPT-4o — reasoning, extraction, critique, evaluation (LLM-as-a-Judge)
* **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (structural nodes); upgrade path to `BGE-M3` for chunk nodes
* **Interface**: Chainlit (async chat UI)

---

## 2. Two-Axis Build Strategy

The system has two independent execution axes that share a common data foundation but have **no hard dependency on each other**:

```
┌──────────────────────────────────────────────────────────────────────┐
│  FOUNDATION  (prerequisite for both axes — must be built first)      │
│  • Infrastructure fixes (asyncio, Neo4j API, requirements.txt)       │
│  • Amazon-curated Knowledge Graph (small, clean, REDIAL-compatible   │
│    schema — no REDIAL data yet, but schema supports future extension) │
└───────────────────────┬──────────────────────────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
┌──────────────────────┐   ┌────────────────────────────────────┐
│  META-PHASE A        │   │  META-PHASE B                      │
│  Recommendation      │   │  Conversational Flow               │
│  Engine              │   │  (CRS packaging)                   │
│  (Primary thesis     │   │                                    │
│   contribution)      │   │                                    │
└──────────────────────┘   └────────────────────────────────────┘
          │                              │
          └──────────────┬───────────────┘
                         ▼
           ┌────────────────────────────┐
           │  META-PHASE C              │
           │  Classic Baselines         │
           │  (CF, Content-Based)       │
           │  for Thesis Comparison     │
           └────────────────────────────┘
```

**Why Amazon-curated subset first (not REDIAL)?**
- LLM-REDIAL dataset requires author approval (email request) — blocks development
- Amazon dataset is already downloaded (1.63M reviews, 9,271 products, 161K metadata entries)
- A curated Amazon subset (20–30 active users, 10–30 well-reviewed products) lets us build and test the entire pipeline end-to-end without waiting for access
- The project now exclusively targets the Amazon Reviews dataset to enable a strict 1:1 comparison against classic recommendation models (Matrix Factorization, Content-Based) in Meta-Phase C.

---

## 3. FOUNDATION — Prerequisite for Everything
*Must be completed before any Meta-Phase A or B work begins.*

### F0 — Infrastructure Fixes (No Data Dependency — Start Immediately)

* [ ] **GAP-001 — asyncio Refactor** (`src/agents/orchestrator.py`): Convert `run()`, `_initialize_state()`, `_decide_next_step()`, `_generate_search_params()`, and `_execute_step()` to `async def`. Replace `asyncio.get_event_loop().run_until_complete()` at line 220 with `await`. Update `src/ui/app.py` to call `await orchestrator.run()`. Add `pytest-asyncio` test confirming no `RuntimeError` is raised inside a running event loop.

* [x] **GAP-003 — Neo4j Deprecated API Migration** (`src/tools/graph_search_tool.py`, `src/knowledge_graph/graphdb/resolver_service.py`): Replace all 8 occurrences of deprecated `CALL db.index.vector.queryNodes(...)` with Cypher 25 `VECTOR SEARCH` syntax. Replace `CALL db.index.vector.createNodeIndex(...)` in `create_vector_indexes.cypher` and `setup_indexes.py` with `CREATE VECTOR INDEX ... IF NOT EXISTS` DDL.
  * _Note (2026-10-17)_: The live Neo4j is 5.14, which has no Cypher 25 `VECTOR SEARCH`. `src/knowledge_graph/graphdb/vector_search_helper.py` therefore still emits `db.index.vector.queryNodes`. Pending decision D-4 in the retrieval redesign roadmap.
  * _Note (2026-10-19)_: `CREATE VECTOR INDEX` DDL arrived only in Neo4j 5.15, so on the live 5.14 the index scripts must use `db.index.vector.createNodeIndex`. `create_vector_indexes.cypher` was switched back to the procedure form and `setup_indexes.py` no longer falls back to DDL below 5.15 (F4, Research_Report_Graph_Rebuild.md N-4).

* [x] **GAP-011 — `requirements.txt` Hygiene**: Pin `openai>=1.0.0`. Add `langgraph>=1.0.0`. Add `pydantic>=2.0.0`. Move unused legacy packages (`lightfm`, `scikit-surprise`, `fastapi`, `uvicorn`, `streamlit`) to `requirements-legacy.txt`. Add `.env.example` documenting `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `ENABLE_GRAPH_RETRIEVAL`.

### F1 — Current Graph State Assessment

> **⚠️ NOT DONE — Must be verified before any graph rebuild.** Run the introspection queries below against the live Neo4j instance to establish the current database state.

* [x] **F1.1 — Live Neo4j Introspection**: Run the following Cypher queries and record results in `production_artifacts/graph_state_snapshot.md`:

```cypher
-- Node counts by label
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;

-- Embedding coverage per label
MATCH (n:ParentProduct) RETURN count(n) AS total,
  count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;
MATCH (n:Brand) RETURN count(n) AS total,
  count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;
MATCH (n:Category) RETURN count(n) AS total,
  count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;
MATCH (n:Attribute) RETURN count(n) AS total,
  count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;

-- Vector index status
SHOW INDEXES WHERE type = 'VECTOR';

-- Relationship counts
MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC;

-- Sample product
MATCH (p:ParentProduct) RETURN p LIMIT 1;
```

* [ ] **F1.2 — Ingestion Script Audit**: Evaluate whether `sample_ingest.py` can be reused for the curated subset (see F2). Key issues to verify:
  - Script currently expects `Electronics.jsonl` + `meta_Electronics.jsonl` (raw JSONL format). The processed CSVs (`processed_reviews.csv`, `combined_product_data.csv`) are a different format — script may need path/format adaptation.
  - Script has a `--user-limit` / `--product-limit` argument capability (check arg parser) — if present, use it for the curated subset; otherwise add it.
  - `constraints.cypher` already has `:User` node type defined — compatible with future REDIAL extension.

### F2 — Curated Amazon Subset — Dataset Selection

> _Note (2026-10-19)_: Historical. The live graph is not the curated subset: it is a full ingest of `datasets/processed_data/` (265,307 products, 39% of them empty ghosts). It is superseded by **F4 — Graph v2 Rebuild**.

> **Strategy**: Select a small, representative slice of the Amazon Electronics dataset that exercises all graph features (dense users, cold-start users, popular products, obscure products). The existing graph will NOT be deleted — a new Neo4j database (`neo4j` → `kg_curated`) will be used for the fresh build.

**Selected users and products (based on dataset analysis — 2026-07-11):**

* [x] **F2.1 — Select Active Users (20 users)** *(Skipped: live DB already contains 30 users)*: Use the top 20 most active reviewers identified in the dataset analysis. These users have 147–532 reviews each, spanning hundreds of distinct products — ideal for testing multi-turn preference accumulation and profile richness.

  ```
  Top 20 active users (by review count):
  1.  AHMNA5UK3V66O2V3DZSBJA4FYMOA  (532 reviews, 528 products)
  2.  AEIIRIHLIYKQGI7ZOCIJTRDF5NPQ  (513 reviews, 506 products)
  3.  AECTQQX663PTF5UQ2RA5TUL3BXVQ  (428 reviews, 426 products)
  4.  AG73BVBKUOH22USSFJA5ZWL7AKXA  (342 reviews, 337 products)
  5.  AGZZXSMMS4WRHHJRBUJZI4FZDHKQ  (283 reviews, 281 products)
  6.  AG375WAXLZ7PIOQKIQ6KQB4J3JVQ  (275 reviews, 270 products)
  7.  AFTZWAK3ZHAPCNSOT5GCKQDECBTQ  (262 reviews, 261 products)
  8.  AEP4KJDGBH6XPJKFEHPYSAPUNDBQ  (259 reviews, 258 products)
  9.  AHDZKPPKUT7HD47LXCBN7RQNN6KQ  (248 reviews, 247 products)
  10. AGUTZC4GHLTGYHA3KBEDRF6MHB6A  (226 reviews, 225 products)
  11. AGRPLHGW2CR6WWOHT5TOWXDGIZEQ  (217 reviews, 216 products)
  12. AFE54MELB5IGFUYBSOBGJOSOMEPA  (214 reviews, 213 products)
  13. AEBNDHJJSZXWZRVW63ELWOPXPNOA  (202 reviews, 200 products)
  14. AHTDYGXHONM2BHENDRMKMC34ZZZA  (181 reviews, 180 products)
  15. AHXZR7HLPSKRUPHX35GKRLVTX3ZA  (178 reviews, 170 products)
  16. AGBG3KK74IKWJNQVMQAGVBWJ7FAQ  (178 reviews, 176 products)
  17. AGDSEYGSA5K664EUHWKV3ARDXO2Q  (174 reviews, 173 products)
  18. AEHOFUNZP6VT74RUDDCJ2VVIT56A  (173 reviews, 173 products)
  19. AH665SQ6SQF6DXAGYIQFCX76LALA  (171 reviews, 171 products)
  20. AGAV7IY4HWGYRUIAGUZRXYUJ22DA  (170 reviews, 169 products)
  ```

* [x] **F2.2 — Select Cold-Start Users (5 users)**: Pick 5 users with exactly 1 review to simulate cold-start scenarios for evaluation.

  ```
  Cold-start users (1 review each — sample):
  1. AHZYQWEOFG4GKOFO2A3I7KLVEYDA
  2. AFRBIEE3U37BWO56ILWIH7Y7Y4LA
  3. AFHVNPC6357YJ5I5WFRJPE5SA6AA
  4. AH4GXL7PEROO3HI3IO4BGRB7J4QQ
  5. AFOISMISSFFNL4DYVAZLKTBG5GTA
  ```

* [x] **F2.3 — Select Well-Reviewed Products (20 products)** *(Skipped: live DB already contains 30 products)*: Top 20 products by review count — each has 243–519 reviews and 241–475 unique reviewers. Rich attribute and review data for KECR path extraction.

  ```
  Top 20 products (by review count):
  1.  B094V7S7D7  (519 reviews, 475 users)
  2.  B07S764D9V  (473 reviews, 465 users)
  3.  B06XRTFG29  (464 reviews, 462 users)
  4.  B07BSVLHYD  (413 reviews, 408 users)
  5.  B0BX65VLJ9  (378 reviews, 373 users)
  6.  B09CKV22L7  (366 reviews, 358 users)
  7.  B0B4SWZTZ1  (361 reviews, 360 users)
  8.  B088C3ZJHV  (348 reviews, 337 users)
  9.  B089PMMT1X  (342 reviews, 330 users)
  10. B07QYL62CZ  (335 reviews, 330 users)
  11. B073VMG4FN  (332 reviews, 326 users)
  12. B07454F4JH  (319 reviews, 319 users)
  13. B092W3K376  (316 reviews, 315 users)
  14. B0B4DCFYF9  (316 reviews, 316 users)
  15. B07WNJQFP9  (315 reviews, 309 users)
  16. B077TPFXZV  (314 reviews, 313 users)
  17. B08484Q1JB  (311 reviews, 293 users)
  18. B0BMQJYLQV  (309 reviews, 297 users)
  19. B00DS4G2AW  (301 reviews, 301 users)
  20. B0C1FRBK4K  (292 reviews, 275 users)
  ```

* [x] **F2.4 — Select Low-Review Products (5 products)**: Products with 1–2 reviews for cold-item evaluation.

  ```
  Cold-start products (1 review each):
  1. B00YBBTPUU
  2. B013FMGP1C
  3. B01H38F5PQ
  4. B083TNQF4M
  5. 6302453356  (2 reviews)
  ```

  > **Note**: The `combined_product_data.csv` contains only products that have ≥1 review (confirmed: 0 products with 0 reviews in the catalog). The 5 products above have the fewest reviews in the dataset.

### F3 — Fresh Graph Build (Curated Subset, New DB)

> _Note (2026-10-19)_: Historical, see F2 note. Neo4j Community has no second database (`kg_curated`); F4 rebuilds the single `neo4j` database into a new Docker volume.

> **Important**: Do NOT delete or modify the existing Neo4j database. Create a separate database for the curated graph. In Neo4j Desktop / Aura: create a new database named `kg_curated`. Set `NEO4J_DATABASE=kg_curated` in `.env` when running the new pipeline.

* [x] **F3.1 — Write Curated Subset Extractor** *(Skipped: DB is already curated)* (`scripts/extract_curated_subset.py`): Reads `processed_reviews.csv` and `combined_product_data.csv` / `processed_metadata.csv`. Filters to the 25 selected users + 5 cold-start users and 20 selected products + 5 cold-start products. Writes out:
  - `datasets/curated/curated_reviews.csv` — reviews involving selected users AND selected products
  - `datasets/curated/curated_products.csv` — metadata for selected products
  - `datasets/curated/selection_manifest.json` — records exact IDs chosen and selection rationale

* [x] **F3.2 — Adapt / Reuse Ingestion Script**: Evaluate `sample_ingest.py` for reuse:
  - **Reuse**: Core graph-building logic (node creation, relationship wiring, price bucket derivation, attribute extraction) is sound and well-structured.
  - **Adapt**: Update file path arguments to accept the curated CSVs (currently expects raw JSONL). Add `--database` argument to target `kg_curated`. Ensure schema creates `:User` nodes (already in `constraints.cypher`) for future REDIAL compatibility.
  - **EAV Numeric Enhancement**: Update attribute extraction (`decompose_attributes.py`) to cast known numeric strings (e.g., "120Hz" -> `120.0`) to a new `numeric_value: float` property on `Attribute` nodes, fully enabling EAV numerical reasoning (`>= 120.0`) in Cypher.
  - **New script**: If adaptation is too invasive, write `scripts/ingest_curated.py` wrapping the same logic but reading from `datasets/curated/`.

* [x] **F3.3 — Run Constraints & Ingestion**: Against `kg_curated` database:
  1. Apply `constraints.cypher` (already has `:User` unique constraint — REDIAL-compatible)
  2. Run adapted ingestion script
  3. Verify with `MATCH (n) RETURN labels(n)[0], count(n)` — expect ~25 `:User`, ~25 `:ParentProduct`, N `:Brand`, M `:Category`, K `:Attribute`, L `:Review` nodes

* [x] **F3.4 — Embedding Generation** *(Skipped: 100% embeddings present)*: Run `backfill_embeddings.py` against `kg_curated`.
  - Embeds: `Attribute` (name + normalized value), `Brand` (name + domain), `Category` (name + parent hierarchy), `ParentProduct` (title + category + top-5 features + description), and `Review` (review title + body).
  - Model: `sentence-transformers/all-MiniLM-L6-v2` → 384-dim vectors
  - **⚠️ GAP-003 prerequisite**: Must migrate deprecated index API before this step

* [x] **F3.5 — Vector Index Creation (Cypher 25 DDL)**: Create indexes on `kg_curated`:
  * _Note (2026-10-19)_: The DDL below fails on the live Neo4j 5.14 (`CREATE VECTOR INDEX` needs 5.15+). The live indexes use `db.index.vector.createNodeIndex`; F4 does the same.
  ```cypher
  CREATE VECTOR INDEX product_embedding_index IF NOT EXISTS
    FOR (n:ParentProduct) ON (n.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
  CREATE VECTOR INDEX brand_embedding_index IF NOT EXISTS
    FOR (n:Brand) ON (n.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
  CREATE VECTOR INDEX category_embedding_index IF NOT EXISTS
    FOR (n:Category) ON (n.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
  CREATE VECTOR INDEX attribute_embedding_index IF NOT EXISTS
    FOR (n:Attribute) ON (n.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
  CREATE VECTOR INDEX review_embedding_index IF NOT EXISTS
    FOR (n:Review) ON (n.embedding)
    OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
  ```

* [x] **F3.6 — Graph Verification**: After build, confirm end-to-end connectivity:
  ```cypher
  -- Spot check: one product, its brand, category, attributes, reviews, user
  MATCH (u:User)-[:WROTE]->(r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct)
        -[:HAS_BRAND]->(b:Brand)
  RETURN u.user_id, r.rating, p.title, b.name LIMIT 5;

  -- Embedding spot check
  MATCH (p:ParentProduct) WHERE p.embedding IS NOT NULL
  RETURN p.title, size(p.embedding) AS dims LIMIT 3;
  ```

### F4 — Graph v2 Rebuild (Vision 2026-10-19-018 … 021)
**Status (2026-10-20): ✅ done.** Graph v2 is the live graph: built, validated (18/18 hard gates), stamped `GraphVersion` v2, v2 baseline accepted at CP-9. Record: `graph_versions/v2/` (incl. `RUNBOOK_LOG.md`, `validation_report.json`, `baseline_comparison.json`). Code audited (PASS WITH FIXES, delta audit PASS; `production_artifacts/Audit_Report_Graph_Rebuild.md`); three post-import bugs found during the build were fixed with tests (`8b10a35`, `0a32604`). Spec: `production_artifacts/Technical_Specification_Graph_Rebuild.md`. Research: `production_artifacts/Research_Report_Graph_Rebuild.md`. Supersedes the curated-subset story of F2/F3 for the live graph. Runbook: `scripts/graph_ingestion/README.md` ("Graph v2").
* [x] **F4.1 Code**: transform package `src/knowledge_graph/graph_v2/` and `scripts/graph_ingestion/build_graph_v2.py` (catalogue-first products, K-11/K-12 review selection, `Taxon` tree, lineage); import, post-import and validation scripts; `embedding_templates.py`; legacy guards (`batch_ingest.py` MERGE → MATCH, skip-empty in `backfill_embeddings.py`, `AmazonDataProcessor` field names); G-12 prompt cleanup; `GraphVersion` in `provenance.py`; compose volume and memory via env.
* [x] **F4.2 Pre-flight** (read-only) and user-approved `graph_versions/v2/build_params.json` (CP-1, 2026-10-20). P-04 crashed twice on MPS out-of-memory before the fix in `8306d9b`; encode batch 32.
* [x] **F4.3 Start gate** (CP-2 to CP-4, 2026-10-20): R2a v1 reference runs archived and confirmed (CP-2); catalogue frozen; v1 stopped and dumped (SHA-256 in `graph_versions/v1/DUMP.json`).
* [x] **F4.4 Pilot** (5%) on a scratch volume; size and time extrapolation approved (CP-5: 18/18 gates; embedding estimate 2.25 h, store 12.5 GB).
* [x] **F4.5 Full import** (CP-6/CP-7: 94 s import, 0 bad rows; post-import about 2.6 h) into `kg_neo4j_data_v2`; post-import (constraints, embeddings with v1 templates, top-5 review embeddings, vector indexes in procedure form, full-text index).
* [x] **F4.6 Validation gate** (CP-8, report SHA-256 `d8a68b7f…8af`) H-01 … H-18 passed; `GraphVersion` v2 stamped; `graph_versions/v2/*` committed.
* [x] **F4.7 v2 baseline**: R1 arms on legacy-21, r = 3, at the allow-listed baseline commit; archived; v1 vs v2 comparison reviewed (CP-9, runs `eval_2026-10-20_1114/_1128/_1142`; no arm changes significantly, rrf3 MRR 0.226 → 0.319, p_Holm 0.875; allow-list amendment A-7).
* Unblocks: R2b benchmark freeze on v2 (with the G-9 S1 redefinition), AI-03, AI-06, RS-12, RS-03.

---

## 4. META-PHASE A — Recommendation Engine
*Primary academic contribution. Fully evaluatable without UI or conversation layer. Requires Foundation complete.*

**Boundary**: Components in this phase live in `src/tools/`, `src/knowledge_graph/`, `src/llm_interface/`, `src/agents/critic_agent.py`. No dependency on `src/agents/orchestrator.py`, `src/conversation/`, `src/user/`, or `src/ui/`.

### A1 — High-Recall Soft-Scored Hybrid Retrieval & MACS Relaxation
* [x] **Explicit Constraint Taxonomy**: Restructure preference extraction to rigidly partition Hard Boundaries (`budget_ceiling`, `excluded_brands`) from Negotiable Soft Preferences (`refresh_rate`, `ram`, `brand`).
* [x] **Soft Additive Scoring**: Remove all Cypher `WHERE` clauses for soft specifications/categories. Enforce ONLY hard boundaries in Cypher (e.g. `price IS NULL OR price <= $price_max`). Score soft preferences in Python memory additively: `Score = Score_vec + 0.3*Brand + 0.2*Cat + ...`.
* [x] **MACS Progressive Relaxation**: If candidate yield $< 3$, trigger a deterministic relaxation cascade (widen budget by 15%, drop soft specs) and record `relaxed_constraints` for downstream transparency.
* [x] **Multi-Index Semantic Search**: Parallel vector queries across product, attribute, and review indices (`CALL { ... } UNION`), returning candidates to be soft-scored.
  * _Note (2026-10-17)_: Since R1 each index runs as its own channel query (one row per product, best match) and the channels are fused by RRF in `src/tools/score_fusion.py`. The `UNION` + `sum(score)` query survives only as the `sum_legacy` ablation arm.
* [ ] Write integration tests: `tests/test_graph_search_tool.py` verifying MACS triggers on 0-result edge cases.
* [x] **AI-01** Implement AFP-002 bounded multi-index score fusion (`action_items/Proposed_Fix_Vector_Aggregation.md`): replace `sum(score)` in `GraphSearchTool._execute_hybrid_search` / `_execute_vector_search`, then re-run the live retrieval eval. **Revised 2026-10-17**: implemented as RRF, release R1 of A1.1 below.
* [ ] **AI-02** Verify the catalog-safe attribute demotion live: `live_eval_phone_01` returns ≥ 5 candidates including `B08GNRGB67`, and the generated Cypher has no `storage` `EXISTS` clause.
* [ ] **AI-11** Parameterise the category title filter Cypher in `GraphSearchTool._build_filters` (currently string-interpolated).

### A1.1 — Retrieval Score Redesign (Roadmap R1–R5)
**Status (2026-10-17): R1 implemented and audited (PASS WITH FIXES, `production_artifacts/Audit_Report.md`)** on `feature/afp-002-vector-aggregation`. Live eval: `evaluations/eval_2026-10-17_1937` (popularity bias down, hit rate unchanged within one query). **R2a followed on 2026-10-18 (see the R2 block below).** Design, principles (P-1 … P-10) and the full work-package catalogue (RS-01 … RS-25) are in `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md`.
Goal: the retrieval score measures how well a product matches the request, not how many texts about it resemble the query. Ranking order: feature fit → channel agreement (RRF) → review experience. Unknown evidence is never scored as a mismatch.

**R1 — RRF fusion (AFP-002, AI-01)**. Gate: live eval vs `eval_2026-10-09_1336`.
* [x] **RS-01** One ranked list per channel (product, attribute, review; each product once, by max similarity), fused by RRF (`k = 60`, configurable weights) in `_execute_hybrid_search` and `_execute_vector_search`.
* [x] **RS-05** Rescale the soft-preference bonus (`+0.2 × polarity`) to the RRF scale, or fuse it as its own list.
* [x] **RS-02** Ablation switch: RRF over 3 channels vs 2 (review channel off).
* [x] Per-channel ranks, similarities and RRF score in the result and `eval_trace` (seed of the RS-18 evidence ledger).
* [x] **RS-20 (part)** `popularity-bias@K` and `type-precision@K` in `scripts/evaluate_retrieval.py`.
* [x] Unit tests (fan-out gives no extra credit, deterministic RRF order, soft-bonus scale) and a live eval report for both arms.
* [x] Vision Report decision D-1 (AFP-002 implemented via RRF), via @pm-research. Recorded as 2026-10-17-013.

**R2 — Evaluation foundation** (before any weight tuning). Split by Vision decision 2026-10-18-015: **R2a** (metrics, RS-23, run archive) then **R2b** (benchmark v2, RS-02 evidence). Status (2026-10-18): **R2a implemented; audit PASS WITH FIXES; exit gate PASS** (spurious CLARIFY 0/21 in each of three citable live runs at `88cdbdf`: `eval_2026-10-18_2340`, `_2349`, `_2358`, archived in `evaluations_archive/`). R2b is open. Decisions: Vision 2026-10-18-014 … 017. Spec: `production_artifacts/Technical_Specification.md`.

*R2a (done)*
* [x] **RS-23** Spurious CLARIFY. Extraction prompt: the head noun of the requested product is a `category` hard constraint, plus a consistency rule and one long-modifier example (`src/llm_interface/prompts/preference_extract_prompt.py`). Orchestrator: before the guardrail switches SEARCH to CLARIFY it first takes a category from any source, then tries one recovery call that reuses `_generate_search_params`. A recovered category counts only when the same call reports `product_type_decided == true` (FR-007a, audit H-1). The reason is recorded as `clarify_reason` in `eval_trace`. Switch: `ORCH_CATEGORY_RECOVERY` (default on). Also fixed in the same prompt: the "1500 → 150" line in `SEARCH_GENERATION_PROMPT` (FR-011, part of AI-07). Dialogue metrics (category-extraction recall, target-admitting rate, spurious-CLARIFY rate, SEARCH-only vs all-queries denominators) are in `src/evaluation/dialogue_metrics.py`.
  * _Still open_: clarification recall on the ambiguous stratum (needs benchmark v2, R2b); the deterministic catalogue-vocabulary fallback (RS-24, R3); the parser/search-params merge (AI-07, B1).
* [x] **RS-20 (rest)** `constraint-satisfaction@K`: three-valued (satisfied / violated / unknown) verdicts against hand-annotated `gold_constraints` of the 21 legacy queries (`src/evaluation/constraint_satisfaction.py`), and against the extracted request. Numeric constraints have 0% coverage because the live graph has no `Attribute.numeric_value` (RS-11). `popularity-bias@K` is now reported as `review-coverage-bias@K` (the code key is still `popularity_bias@k`).
* [x] Paired statistics (`src/evaluation/stats.py`: randomization test, paired bootstrap, exact McNemar, Wilson CIs, Holm), citable-run provenance (`src/evaluation/provenance.py`, `--require-clean`), `per_query.jsonl`, `scripts/archive_eval_run.py`, `scripts/check_eval_gate.py` and the git-tracked `evaluations_archive/`.

*R2b (completed 2026-10-20)*
* [x] **RS-21** Benchmark v2 (Vision 2026-10-18-014, 2026-10-20-022): 251 queries in `evaluations/benchmarks/benchmark_v2.json` (`40` per stratum `S0`–`S4` = `200` retrieval queries across 158 `Taxon` leaves and 19 categories, `30` ambiguous `A` queries with `gold_action = "CLARIFY"`, plus `21` continuity `legacy` queries in `split = "tuning"`), deterministic hashed `tuning`/`test` split (`115` tuning / `136` test), automatic leakage & TF-IDF triviality gate (`0` model-code leaks, `0` unflagged brand leaks, max title token overlap `0.20 <= 0.30`, `0` TF-IDF rank-1 targets), S1 query-time review masking (`mask_review_asins`), redefined bias metrics (`review_cap_bias@k` on 20-review cap and `head_popularity_bias@k` on P90 `review_count >= 1,241`), and `--split test` confirmation guard (`--confirm-test` + `evaluations_archive/test_split_access_log.jsonl`).
* [x] **RS-02 (evidence)** Evaluated `rrf3` vs `rrf2` on the 105 retrieval tuning queries (`evaluations/benchmarks/r2b_tuning_report.json`): `rrf3` yields $\Delta\text{HR@20} = +0.0476$ (`95% CI [0.0000, +0.1048]`) with `7` unique review-channel top-20 rescues vs `2` demotions, while increasing `RevCapBias@5` by `+0.0794` ($p = 0.0004$) and `HeadPopBias@5` by `+0.0429` ($p = 0.0038$). Retained 3-channel `rrf3` over `rrf2` to preserve top-20 recall; will re-confirm once on `test` in R3.
* [x] **RS-25** Fusion tuning on the 105 retrieval tuning queries (`scripts/tune_fusion_r2b.py`, 192 grid configs over $(w_{\text{prod}}, w_{\text{attr}}, w_{\text{rev}})$ and RRF $k \in \{20, 40, 60, 100\}$): `wrrf3` (`0.60 / 0.25 / 0.15`) improves `MRR` (`0.1215` vs `0.1115`, $\Delta = +0.0100$, `95% CI [-0.0031, +0.0273]`) and `HR@5` (`0.1714` vs `0.1429`, $\Delta = +0.0286$) while significantly reducing `RevCapBias@5` (`-0.0692`, $p = 0.0002$) and `HeadPopBias@5` (`-0.0404`, $p = 0.0038$); top grid config `grid_k20_p2.0_a0.5_r0.0` reaches `MRR = 0.1276` (`95% CI [-0.0122, +0.0485]`). By the pre-registered parsimony rule, unweighted `rrf3` ($k=60$, weights $1:1:1$) remains default until `test`-split confirmation in R3.

**Graph v2 Consumption Package (added 2026-10-20, before R3 — `docs/Usprawnienie procesu rekomendacji CRS (Hybrid GraphRAG, Amazon Electronics, Neo4j + GPT-4o).md`)**.
*Stage 0 — Quick Fixes Wiring Graph v2 to the Pipeline (completed 2026-10-20)*
* [x] **GV2-01 (`DETAIL_QUERY` & product text wiring)** Include `node.features`, `node.details_text`, `node.description` and `node.avg_rating` in `GraphSearchTool.DETAIL_QUERY`, and pass them to `CriticAgent` and `PromptConstructor._format_retrieved_items` (fixing `"Features: None specified"` and Critic's 8/21 `rejected_all` blindness).
* [x] **GV2-02 (`AI-06` review sorting & per-product limit)** Fix `GraphSearchTool.fetch_product_attributes` to sort reviews by v2 properties (`r.helpful_vote DESC, r.verified DESC, r.timestamp DESC`) with a per-product subquery limit (`LIMIT $reviews_per_product`) instead of a global `LIMIT 20` on non-existent `helpful_votes`/`timestamp_iso`.
* [x] **GV2-03 (`brands` / `categories` list filters)** Handle `brands`, `exclude_brands` and `categories` list keys in `GraphSearchTool._normalize_filters` and `_build_filters`, and upgrade unhandled filter key logging from `DEBUG` to `WARNING`.
* [x] **GV2-04 (Soft-preference bonus deduplication)** Group unit variations (`generate_attribute_unit_variations`) by requirement in `GraphSearchTool.search` so a single preference awards at most one `polarity * bonus_unit` (`max` over variations, not `sum`).
* [x] **GV2-05 (Critic fail-closed, partial-match fallback & relaxation disclosure)** Change `CriticAgent._evaluate_single_product` error fallback from fail-open (`is_recommended = True`) to fail-closed (`is_recommended = False`, `semantic_score = 0`), fall back to top-3 RRF candidates marked as partial matches (`partial_match = True` + Critic reasoning) when Critic rejects all candidates, and pass `relaxed_constraints` into `PromptConstructor` so MACS compromises are disclosed in the final response.
* [x] **GV2-06 (Remove fabricated `5.0★` fallback & clarify KECR-inspired naming)** Remove `coalesce(cand.avg_rating, 5.0)` from `KnowledgePathExtractor.extract_paths` (`src/tools/kecr_tool.py`) so missing graph evidence never fabricates a 5.0★ rating, and clarify in docstrings/logs that this component performs deterministic Cypher **KECR-inspired Graph Evidence Path Extraction** rather than a trained KECR model.

*Stage 1 — Full Graph v2 Structural & Lexical Consumption (before R3)*
* [x] **GV2-07 (`Taxon` category resolution & subtree filtering; covers RS-24 / RS-10)** Switch `ResolverService.resolve_category` and `GraphSearchTool._build_filters` from the 38 coarse `Category` nodes and dropped `SUBCATEGORY_OF` edges to the 1,183-node `Taxon` hierarchy (`(:ParentProduct)-[:IN_TAXON]->(:Taxon)-[:BROADER*0..7]->(:Taxon)`), with title regex fallback only for products without `IN_TAXON`, and MACS category relaxation stepping up `BROADER` instead of dropping the category filter.
* [x] **GV2-08 (Full-text lexical channel in RRF; covers RS-03)** Add `product_fulltext_index` (`db.index.fulltext.queryNodes` over `title`, `description`, `features`, `details_text`) as a `lexical` channel in `score_fusion.py` / `GraphSearchTool`, and gate or IDF-weight the `attribute` channel (`Material`/`Color`/`Style`/`Size`) with title-similarity tie-breaking.
* [x] **GV2-09 (Selectivity-based filter-before-ANN & `product_v2` embedding arm; covers RS-07 / K-6)** Use `Taxon` subtree size to run exact filtering before scoring on small subtrees, and add the enriched `p.embedding_feat` (`Taxon` path + `features` + `details`) as a separate index/arm without breaking v1/v2 comparability.

**R3 — Search order & query side**.
* [x] **RS-07** Adaptive order by filter selectivity: filter-first with exact scoring (`_execute_filter_first_search` when `Taxon.product_count <= 500` bypassing global ANN truncation with 100% subtree recall) vs ANN-first with dynamic oversampling for broad categories. Completed 2026-10-21 (Release R3.1). Spec: `production_artifacts/Technical_Specification_R3_1.md`, Thesis: `thesis/17-doc-attribute-rarity-taxonomic-distance.md`.
* [ ] **RS-24** Domain-agnostic product-type matching instead of the word-regex category filter: language analyzer or lemmas on both sides, catalogue-derived type vocabulary and synonyms (with RS-11), type as a ranked signal with hard filtering only on confident matches (with RS-09 / RS-17). Trigger: "Webcams" rejects the C920 in `ret_021`.
* [x] **RS-03** Attribute channel as a precise finder: Normalized degree-based Inverse Document Frequency (IDF) rarity weighting ($\text{score} \times \frac{\log(1 + N / (1 + \text{deg}))}{\log(1 + N)}$) to penalize generic attributes (`Color=Black`) by 84.5% while elevating rare technical specifications (`Style=Ergonomic Split Keyboard`). Completed 2026-10-21 (Release R3.1).
* [x] **RS-08a** Dual-Channel HyDE (`hyde_product` matching `product_text_v1` for `product_embedding_index` and `hyde_review` matching `review_text_v1` for `review_embedding_index`) generated in `_generate_search_params` with zero extra LLM calls, plus `use_hyde` ablation arms (`rrf3_no_hyde`, `wrrf3_no_hyde`, `hyde_only` = AI-10). Completed 2026-10-21. Spec: `production_artifacts/Technical_Specification_HyDE.md`, Thesis: `thesis/16-doc-dual-hyde.md`, Run: `evaluations/eval_2026-10-21_0059`.
* [ ] **RS-08b** Multi-query version fusion by RRF: raw message, IS/HAS pieces, user profile (with AI-07).
* [x] **RS-10** Graded category distance via Longest Common Prefix (LCP) on `Taxon.path`: Distance 0 (exact/descendant) $\to 1.00$, Distance 1–2 (sibling) $\to 0.85$, Distance 3–4 (cousin) $\to 0.70$, Distance $\ge 5$ (distant) $\to 0.20$, recorded in `item["fusion"]["taxon_proximity"]`. Completed 2026-10-21 (Release R3.1).

**R4 — Feature fit & LLM judge**.
* [ ] **RS-12** Full-text feature check (synonym sets, negation) → confirmed / contradicted / unknown.
* [ ] **RS-04** Tiered ranking: feature fit → RRF agreement → review experience.
* [ ] **RS-09** Product-type (head-noun) signal and "accessory for X" detection.
* [ ] **RS-17** Batched LLM rerank (AI-08): may remove and reorder, cites a reason per change, deterministic fallback on error.
* [ ] **RS-06** Absolute gate + relative rank; gate calibrated by masking targets; correct-abstention rate.

**R5 — Offline graph enrichment**.
* [ ] **RS-11** Typed canonical feature vocabulary; local-LLM labelling with quoted source spans; regex tier; label precision/recall audit (~200 products).
* [ ] **RS-13** Review aspect pipeline: product vs noise sentences, opinion- vs complaint-driven aspects, minimum mentions + Bayesian share, category baselines, distilled classifier over 1.6M reviews. Requires decision D-2 (training).
* [ ] **RS-18** Per-product evidence ledger driving contrastive, uncertainty-honest explanations.

**Later (Meta-Phase B)**: RS-16 preference edges (B2), RS-19 two lanes and "we don't carry it" response (B3), RS-14 complement edges (with AI-03), RS-15 doc2query.

### A2 — Contextual Selection-then-Rerank via CriticAgent
* [x] **CriticAgent Reranking**: Refactor `CriticAgent.evaluate_candidates` to accept top $N$ pre-ranked candidates from `GraphSearchTool`.
* [x] **Semantic Arbitration**: Evaluate trade-offs based on conversational context (e.g., verifying wired vs wireless) to catch semantic betrayal.
* [x] **Transparency Injection**: Inject explicit disclosure warnings in the output if MACS `relaxed_constraints` is non-empty.
* [x] Write unit tests: `tests/test_critic_agent.py` asserting accurate reranking and penalization of non-compliant items.
  * _Note (2026-10-10)_: The disclosure logic lives in `CriticAgent.evaluate_candidate_tradeoffs`, which the orchestrator does not call. It uses the legacy per-item `evaluate_candidates`, and `relaxed_constraints` never reaches the Critic.
* [ ] **AI-08 (decision)** Choose the Critic design: per-item legacy vs batched A2 (≈ 20 → 1 LLM calls per turn, MACS disclosure). Decide fail-open vs fail-closed on LLM error.
  * _Direction (2026-10-17)_: batched listwise rerank of the final 20–30 candidates. It may remove clear non-matches and reorder, must cite a reason per change, and falls back to the deterministic order on error. Scheduled as RS-17 in A1.1 R4.
* [ ] **AI-06** Fetch reviews per product in `GraphSearchTool.fetch_product_attributes` (the current `LIMIT 20` is global across all candidates). Order by properties that exist on `Review`.

### A3 — PromptConstructor — Graph Path Injection Slots
* [x] Add `graph_reasoning_paths` parameter to `construct_recommendation_prompt()`
* [x] Add `[GRAPH EVIDENCE]` section to prompt with graph-grounding constraint
* [x] Write tests asserting path injection when paths provided

### A4 — KECR — Knowledge-Enhanced Reasoning Path Extraction
**Status (2026-10-10): ⚠️ Partial.** Implemented and wired, but the historical half is non-functional on the live graph.
* [x] Implement `src/tools/kecr_tool.py` — `KnowledgePathExtractor` class
* [x] Neo4j path queries connecting user preference entities → item (implemented as a dual-context pattern-matching query with time decay and α gating, not shortest-path)
* [x] Wire into recommendation pipeline after CriticAgent top-3 selection (`AgentOrchestrator._execute_step`, STEP 3d.5)
* [x] Write tests: `tests/unit/test_kecr_tool.py`, `tests/integration/test_kecr_orchestrator.py` (mocked Neo4j only)
* [ ] **AI-03** Rewrite the historical subquery for the live schema. Use `(:Review)-[:ABOUT_PRODUCT]->`, with `rating` and `verified` on the `Review` node. Backfill `Review` timestamps from `processed_reviews.csv` `sort_timestamp`, or drop decay. Drop or build `BOUGHT_TOGETHER`. Add a live-graph test asserting a historical path for a known reviewer.
* [ ] **AI-05** Attach real reviewer `user_id`s (≥ 3 reviews) to `live_eval_dataset.json` scenarios. Allow selecting a real reviewer in Chainlit (`src/ui/app.py` hard-codes `test_user_chainlit`).

### A5 — Explainable Response Generation (End-to-End)
**Status (2026-10-10): ❌ Not done.** `[GRAPH EVIDENCE]` injection is wired; the verification deliverables below are missing.
* [ ] End-to-end integration test: `tests/test_recommendation_pipeline.py`
* [ ] Manual review: 5 diverse test queries against the live graph

### A6 — Quantitative & Qualitative Evaluation
**Status (2026-10-10): ⚠️ Tier 1 done, Tier 2 partial.** Evaluation defaults to `--mode live` since 2026-10-10. Offline mock runs are not valid thesis evidence.
* [x] `scripts/evaluate_retrieval.py` — Hit@K, MRR, NDCG@K (strict/soft/graded), strategy ablation, staged `eval_trace`. Live baseline: `eval_2026-10-09_1336` (pre-R2, non-citable context). Since R2a (2026-10-18): per-strategy and per-arm aggregates with explicit denominators, three-valued constraint-satisfaction@K, paired statistics, a run manifest with `citable` provenance, `per_query.jsonl`, and `--require-clean`. Citable reference runs: `evaluations_archive/eval_2026-10-18_2340`, `_2349`, `_2358` (the thesis cites archived runs only).
* [ ] `scripts/evaluate_generative.py` — LLM-as-Judge: Groundedness, Explainability, Coherence, Recoverability. Rubrics are implemented in `src/evaluation/judge.py`, but the script judges hand-written responses rather than system output.
* [ ] **AI-04** Make Tier 2 judge real system output: run `AgentOrchestrator` over the live benchmark, capture `answer` and `eval_trace`, then judge. Retire or regenerate `evaluations/benchmarks/generative_benchmark.json` (only 3 of 15 ASINs exist in the graph).
* [ ] **AI-09 (decision)** Tier 2 judge model (currently `gpt-4o-mini` grading a `gpt-4o` system).
* [x] **AI-10 (decision)** After AI-01, evaluate the `ideas.txt` direction as an ablation: LLM-generated target-product description → pure vector retrieval. Completed 2026-10-21 (`evaluations/eval_2026-10-21_0059` confirms `hyde_only` outperforms `vector_only` by +136.2% MRR and +100% HR@5; documented in `thesis/16-doc-dual-hyde.md`).
* [ ] **RS-20 / RS-21** (RS-20 done, RS-21 open) Label-free metrics: `review-coverage-bias@K` (formerly `popularity-bias@K`) and `type-precision@K` done in R1; `constraint-satisfaction@K` done in R2a (2026-10-18). The stratified benchmark with a tuning/test split (RS-21) is open, scheduled in R2b.
* [ ] **AI-12** Stop `tests/test_challenger_distinguishing_features.py` from writing mock runs into `evaluations/`.

---

## 5. META-PHASE B — Conversational Flow
*CRS packaging layer. Builds on top of Meta-Phase A.*

### B1 — LangGraph Orchestration Refactor (AgentOrchestrator)
* [ ] Rewrite `AgentOrchestrator` using LangGraph `StateGraph`.
* [ ] Define `RecommenderState` TypedDict (`messages`, `active_filters`, `excluded_asins`, `candidates`, `graph_evidence`).
* [ ] Implement core graph nodes: Router, Search, Critic, KECR, Generator, Clarify.
* [ ] Implement conditional routing edges (including cyclic loops for REJECT/Refine).
* [ ] Wire Meta-Phase A tools into the LangGraph nodes.
* [ ] Verify end-to-end execution within the Chainlit async context.
* [ ] **AI-07** Merge preference extraction (`LLMPreferenceParser`) and `_generate_search_params` into one LLM call with a single source of truth for filters. _(The "1500 → 150" example in `SEARCH_GENERATION_PROMPT` was fixed in R2a, FR-011, 2026-10-18; the merge is still open. R2a added category recovery from the search-params call, which is a step toward one source of truth. The R2 category-extraction metrics are this merge's regression gate, Vision 2026-10-18-016.)_

### B2 — MemoCRS Persistent Memory
* [ ] `src/user/sqlite_profile_manager.py` — `SQLiteProfileManager`
* [ ] `src/conversation/sqlite_history_manager.py` — `SQLiteHistoryManager` with semantic retrieval
* [ ] LangGraph `SqliteSaver` checkpointer integration
* [ ] Tests: session persistence across restart

### B3 — CLARIFY Path — Context-Aware Questioning
* [ ] Add `pending_clarification` to `ConversationState`
* [ ] Replace hardcoded CLARIFY stub with context-aware template
* [ ] Tests: assert budget question asked when `price_max` missing

### B4 — Recoverability Mechanism
* [ ] Add `REJECT` action to router prompt
* [ ] Add `excluded_items: List[str]` to `ConversationState`
* [ ] Update orchestrator REJECT handler and `GraphSearchTool`
* [ ] Tests: rejected item excluded from next search

### B6 — End-to-End Integration & Cleanup
* [ ] Full Chainlit smoke test: SEARCH → CLARIFY → UPDATE_PROFILE → REJECT → refined SEARCH
* [ ] Remove `ResponseGenerator` dead code (GAP-013)
* [ ] Move `PreferenceAgentFlow` to `src/legacy/`
* [ ] Final dependency audit
* [x] **AI-13** Refresh stale docs (`production_artifacts/graph_state_snapshot.md`, `scripts/graph_ingestion/README.md`) and add `seaborn` to the project `.venv`. _Done 2026-10-20_: `seaborn` in `.venv` and `requirements.txt`; the snapshot now describes the live graph v2 and the runbook covers the v2 build and rollback.

---


---

## 6. META-PHASE C — Classic Baseline Evaluation
*Post-implementation phase. Executes after the GraphRAG solution is fully built and validated. Provides the strict academic comparison required for the thesis.*

### C1 — Unified Train/Test Split
* [ ] Split the curated Amazon Reviews dataset into Train (80%) and Test (20%) or leave-one-out.
* [ ] Ensure `kg_curated` is only populated with interactions from the Train split.

### C2 — Classic Model Implementation
* [ ] `src/baselines/cf_model.py`: Implement Matrix Factorization (SVD) using `scikit-surprise`.
* [ ] `src/baselines/cb_model.py`: Implement Content-Based filtering using `lightfm` or TF-IDF on product metadata.

### C3 — Baseline Evaluation Script
* [ ] `scripts/evaluate_baselines.py`: Run the classic models on the Test split.
* [ ] Calculate `HitRate@K` and `NDCG@K` using the exact same evaluation metrics functions as Phase A6.
* [ ] Compile final comparison table: Vector-only vs Cypher-only vs Hybrid GraphRAG vs CF vs Content-Based.

---

## 7. META-PHASE D — Legacy Adapter Deprecation & Cleanup
*Post-migration phase. Executes after Meta-Phase B is complete and all subsystems consume `SessionContext` natively. Goal: eliminate `session_adapter.py` and all legacy dict interfaces, making the typed Pydantic schema the single data contract.*

> **Rationale**: `src/dialog_manager/session_adapter.py` (714 lines) exists solely as a bidirectional translation layer between the canonical `SessionContext` schema and legacy subsystems that still expect plain `{likes, dislikes, constraints}` dicts. Once all consumers are migrated to accept `SessionContext` directly, this entire file — and its 6 mapping functions — become dead code.

### D1 — Audit & Inventory of Legacy Dict Consumers
* [ ] Map every call site that currently receives or produces a legacy preferences dict (`{likes, dislikes, constraints, intent, notes}`).
* [ ] Identify which adapter functions each consumer depends on:
  - `hard_constraints_to_structured_filters()` → `GraphSearchTool._build_filters()`, `GraphSearchTool._normalize_filters()`
  - `session_context_to_legacy_preferences()` → `PromptConstructor._format_preferences()`, `GraphQueryManager._ground_preferences()`, `PreferenceQuantifier.quantify()`, `ProfileTool`
  - `session_context_to_user_persona()` → `CriticAgent.evaluate_candidates()`
  - `session_context_to_dialogue_action()` → `AgentOrchestrator` router
  - `legacy_preferences_to_session_context()` → reverse bridge (any component producing old dicts)
  - `extract_semantic_query()` → `GraphSearchTool` semantic search input
* [ ] Produce a migration checklist with dependency order (leaf consumers first, orchestrator last).

### D2 — Migrate Leaf Consumers to Native `SessionContext`
* [ ] **GraphSearchTool**: Refactor `_build_filters()` to accept `List[HardConstraint]` directly instead of a flat filter dict. Remove reliance on `hard_constraints_to_structured_filters()`.
* [ ] **PromptConstructor**: Refactor `_format_preferences()` to read from `SessionContext.extracted_parameters` directly (soft preferences with polarity/confidence, hard constraints with operators).
* [ ] **GraphQueryManager**: Refactor `_ground_preferences()` to consume `ExtractedParameters` instead of legacy `{likes, dislikes, constraints}`.
* [ ] **PreferenceQuantifier**: Refactor `quantify()` to accept `List[SoftPreference]` natively — polarity and confidence are already first-class fields, no need for the adapter's weight calculation.
* [ ] **CriticAgent**: Refactor `evaluate_candidates()` to accept `SessionContext` directly — build the persona internally instead of via the adapter.

### D3 — Migrate Orchestrator & Top-Level Wiring
* [ ] **AgentOrchestrator** (or LangGraph `StateGraph` from B1): Replace all internal dict-based state with `SessionContext` as the canonical state type. Read `dialogue_state.suggested_system_action` directly instead of going through `session_context_to_dialogue_action()`.
* [ ] **ProfileTool**: Store and retrieve `SessionContext` objects directly — no round-tripping through legacy dicts.
* [ ] Remove all `legacy_preferences_to_session_context()` call sites — no component should produce legacy dicts anymore.

### D4 — Remove Adapter Layer & Dead Code
* [ ] Delete `src/dialog_manager/session_adapter.py`.
* [ ] Remove adapter re-exports from `src/dialog_manager/__init__.py`.
* [ ] Delete or rewrite adapter-specific tests:
  - `tests/test_session_adapter.py` (entire file — tests the now-deleted adapter)
  - `tests/test_session_schema_adversarial.py` — keep schema validation tests, remove adapter function tests
  - `tests/test_challenger_empirical.py` — remove adapter round-trip tests
  - `tests/e2e/reference_impl.py` — remove adapter reference implementations
  - `tests/e2e/conftest.py` — remove `adapter_functions` fixture
  - `tests/e2e/test_tier*` and `tests/e2e/test_e2e_session_context.py` — rewrite to test native `SessionContext` consumption
* [ ] Remove utility functions that only served the adapter: `_get_field()`, `_coerce_numeric()`, `_clamp()`, `_unwrap_session_context()`.

### D5 — Schema Simplification (Optional)
* [ ] Remove dict-emulation methods from `SessionContext` and `CurrentSessionContextWrapper` (`__getitem__`, `__contains__`, `get()`, `safe_get()`, `safe_contains()`) — these were only needed for backward compatibility with code expecting dict-like access.
* [ ] Evaluate whether `CurrentSessionContextWrapper` is still needed or if `SessionContext` alone suffices as the root type.
* [ ] Remove `HardConstraintOperator` backward-compat alias and lowercase enum aliases if no consumer relies on them.
* [ ] Final test suite pass — all tests should work against the clean, typed-only schema.

---

## 8. Gap Cross-Reference

| GAP ID | Title | Phase | Status |
|--------|-------|-------|--------|
| GAP-001 | asyncio Event Loop Fix | Foundation F0 | ❌ Not done |
| GAP-002 | MemoCRS Persistence | Meta-Phase B2 | ❌ Not done |
| GAP-003 | Neo4j Deprecated API | Foundation F0 | ✅ Done (see D-4 note: Neo4j 5.14 lacks `VECTOR SEARCH`) |
| GAP-014 | Classic Baselines | Meta-Phase C | ❌ Not done |
| GAP-005 | Lexical GraphRAG Layer | Foundation F3 | ❌ Not done |
| GAP-006 | KECR Reasoning Paths | Meta-Phase A4 | ⚠️ Partial (AI-03, AI-05) |
| GAP-007 | Explainable Generation | Meta-Phase A3+A5 | ⚠️ Partial (A3 done, A5 not done) |
| GAP-008 | Quantitative Evaluation | Meta-Phase A6 | ✅ Done (live Tier 1) |
| GAP-009 | LLM-as-Judge Evaluation | Meta-Phase A6 | ⚠️ Partial (AI-04) |
| GAP-010 | Recoverability Mechanism | Meta-Phase B4 | ❌ Not done |
| GAP-011 | requirements.txt Hygiene | Foundation F0 | ✅ Done |
| GAP-012 | CLARIFY Path Quality | Meta-Phase B3 | ❌ Not done |
| GAP-013 | ResponseGenerator Cleanup | Meta-Phase B6 | ❌ Not done |
| GAP-015 | Legacy Adapter Deprecation | Meta-Phase D | ❌ Not done |
| F4 | Graph v2 Rebuild (ghost fix) | Foundation F4 | ✅ Done 2026-10-20 (graph v2 live, stamped, baseline accepted) |
| RS-01 … RS-25 | Retrieval Score Redesign (AFP-002 and follow-ups) | Meta-Phase A1.1 | ⚠️ R1 and R2a done (RS-01, 02 ablation, 05, 20, 23); R2b (RS-21, RS-02 evidence, RS-25) and R3–R5 open |

---

## 9. Work Methodology

* **Foundation first, always**: Nothing from Meta-Phase A or B is started until all Foundation items are marked `[x]`.
* **Amazon curated subset as testbed**: The 25-user / 25-product curated graph gives a fast, manageable environment to verify the full pipeline before scaling up.
* **Unified Amazon Dataset strategy**: Focus entirely on Amazon data to ensure all baselines (LLM, CF, CB) are evaluated on the exact same dataset splits.
* **Iterative approach**: Handle 1 query correctly end-to-end before expanding.
* **KISS Principle**: No custom GNN/LoRA training. Rely on robust prompting, structured tool calls, and explicit Neo4j path-finding.
* **Evaluation-driven**: A6 evaluation scripts written alongside A4/A5 implementation — not as an afterthought.
