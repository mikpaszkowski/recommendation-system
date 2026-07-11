# Implementation Plan: Explainable Hybrid GraphRAG for Conversational Recommendation

> **Last restructured**: 2026-07-08 — Reorganised from linear Phase 0–3 into **Foundation → Meta-Phase A → Meta-Phase B**.
> **Foundation revised**: 2026-07-11 — LLM-REDIAL dependency removed from Foundation. Amazon-curated subset strategy adopted for the initial graph build. REDIAL integration deferred to Meta-Phase B.

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
│  Recommendation      │   │  Conversational Flow +             │
│  Engine              │   │  REDIAL Integration                │
│  (Primary thesis     │   │  (CRS packaging)                   │
│   contribution)      │   │                                    │
└──────────────────────┘   └────────────────────────────────────┘
```

**Why Amazon-curated subset first (not REDIAL)?**
- LLM-REDIAL dataset requires author approval (email request) — blocks development
- Amazon dataset is already downloaded (1.63M reviews, 9,271 products, 161K metadata entries)
- A curated Amazon subset (20–30 active users, 10–30 well-reviewed products) lets us build and test the entire pipeline end-to-end without waiting for access
- The schema is designed to be **REDIAL-compatible from day one**: `:User`, `:Item`, `:Dialogue`, `:Turn` node types are reserved — REDIAL data slots in without schema changes in Meta-Phase B

---

## 3. FOUNDATION — Prerequisite for Everything
*Must be completed before any Meta-Phase A or B work begins.*

### F0 — Infrastructure Fixes (No Data Dependency — Start Immediately)

* [ ] **GAP-001 — asyncio Refactor** (`src/agents/orchestrator.py`): Convert `run()`, `_initialize_state()`, `_decide_next_step()`, `_generate_search_params()`, and `_execute_step()` to `async def`. Replace `asyncio.get_event_loop().run_until_complete()` at line 220 with `await`. Update `src/ui/app.py` to call `await orchestrator.run()`. Add `pytest-asyncio` test confirming no `RuntimeError` is raised inside a running event loop.

* [ ] **GAP-003 — Neo4j Deprecated API Migration** (`src/tools/graph_search_tool.py`, `src/knowledge_graph/graphdb/resolver_service.py`): Replace all 8 occurrences of deprecated `CALL db.index.vector.queryNodes(...)` with Cypher 25 `VECTOR SEARCH` syntax. Replace `CALL db.index.vector.createNodeIndex(...)` in `create_vector_indexes.cypher` and `setup_indexes.py` with `CREATE VECTOR INDEX ... IF NOT EXISTS` DDL.

* [ ] **GAP-011 — `requirements.txt` Hygiene**: Pin `openai>=1.0.0`. Add `langgraph>=1.0.0`. Add `pydantic>=2.0.0`. Move unused legacy packages (`lightfm`, `scikit-surprise`, `fastapi`, `uvicorn`, `streamlit`) to `requirements-legacy.txt`. Add `.env.example` documenting `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `ENABLE_GRAPH_RETRIEVAL`.

### F1 — Current Graph State Assessment

> **⚠️ NOT DONE — Must be verified before any graph rebuild.** Run the introspection queries below against the live Neo4j instance to establish the current database state.

* [ ] **F1.1 — Live Neo4j Introspection**: Run the following Cypher queries and record results in `production_artifacts/graph_state_snapshot.md`:

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

> **Strategy**: Select a small, representative slice of the Amazon Electronics dataset that exercises all graph features (dense users, cold-start users, popular products, obscure products). The existing graph will NOT be deleted — a new Neo4j database (`neo4j` → `kg_curated`) will be used for the fresh build.

**Selected users and products (based on dataset analysis — 2026-07-11):**

* [ ] **F2.1 — Select Active Users (20 users)**: Use the top 20 most active reviewers identified in the dataset analysis. These users have 147–532 reviews each, spanning hundreds of distinct products — ideal for testing multi-turn preference accumulation and profile richness.

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

* [ ] **F2.2 — Select Cold-Start Users (5 users)**: Pick 5 users with exactly 1 review to simulate cold-start scenarios for evaluation.

  ```
  Cold-start users (1 review each — sample):
  1. AHZYQWEOFG4GKOFO2A3I7KLVEYDA
  2. AFRBIEE3U37BWO56ILWIH7Y7Y4LA
  3. AFHVNPC6357YJ5I5WFRJPE5SA6AA
  4. AH4GXL7PEROO3HI3IO4BGRB7J4QQ
  5. AFOISMISSFFNL4DYVAZLKTBG5GTA
  ```

* [ ] **F2.3 — Select Well-Reviewed Products (20 products)**: Top 20 products by review count — each has 243–519 reviews and 241–475 unique reviewers. Rich attribute and review data for KECR path extraction.

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

* [ ] **F2.4 — Select Low-Review Products (5 products)**: Products with 1–2 reviews for cold-item evaluation.

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

> **Important**: Do NOT delete or modify the existing Neo4j database. Create a separate database for the curated graph. In Neo4j Desktop / Aura: create a new database named `kg_curated`. Set `NEO4J_DATABASE=kg_curated` in `.env` when running the new pipeline.

* [ ] **F3.1 — Write Curated Subset Extractor** (`scripts/extract_curated_subset.py`): Reads `processed_reviews.csv` and `combined_product_data.csv` / `processed_metadata.csv`. Filters to the 25 selected users + 5 cold-start users and 20 selected products + 5 cold-start products. Writes out:
  - `datasets/curated/curated_reviews.csv` — reviews involving selected users AND selected products
  - `datasets/curated/curated_products.csv` — metadata for selected products
  - `datasets/curated/selection_manifest.json` — records exact IDs chosen and selection rationale

* [ ] **F3.2 — Adapt / Reuse Ingestion Script**: Evaluate `sample_ingest.py` for reuse:
  - **Reuse**: Core graph-building logic (node creation, relationship wiring, price bucket derivation, attribute extraction) is sound and well-structured.
  - **Adapt**: Update file path arguments to accept the curated CSVs (currently expects raw JSONL). Add `--database` argument to target `kg_curated`. Ensure schema creates `:User` nodes (already in `constraints.cypher`) for future REDIAL compatibility.
  - **New script**: If adaptation is too invasive, write `scripts/ingest_curated.py` wrapping the same logic but reading from `datasets/curated/`.

* [ ] **F3.3 — Run Constraints & Ingestion**: Against `kg_curated` database:
  1. Apply `constraints.cypher` (already has `:User` unique constraint — REDIAL-compatible)
  2. Run adapted ingestion script
  3. Verify with `MATCH (n) RETURN labels(n)[0], count(n)` — expect ~25 `:User`, ~25 `:ParentProduct`, N `:Brand`, M `:Category`, K `:Attribute`, L `:Review` nodes

* [ ] **F3.4 — Embedding Generation**: Run `backfill_embeddings.py` against `kg_curated`.
  - Embeds: `Attribute` (name + normalized value), `Brand` (name + domain), `Category` (name + parent hierarchy), `ParentProduct` (title + category + top-5 features + description)
  - Model: `sentence-transformers/all-MiniLM-L6-v2` → 384-dim vectors
  - **⚠️ GAP-003 prerequisite**: Must migrate deprecated index API before this step

* [ ] **F3.5 — Vector Index Creation (Cypher 25 DDL)**: Create indexes on `kg_curated`:
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
  ```

* [ ] **F3.6 — Graph Verification**: After build, confirm end-to-end connectivity:
  ```cypher
  -- Spot check: one product, its brand, category, attributes, reviews, user
  MATCH (u:User)-[:WROTE]->(r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct)
        -[:HAS_BRAND]->(b:Brand)
  RETURN u.user_id, r.rating, p.title, b.name LIMIT 5;

  -- Embedding spot check
  MATCH (p:ParentProduct) WHERE p.embedding IS NOT NULL
  RETURN p.title, size(p.embedding) AS dims LIMIT 3;
  ```

---

## 4. META-PHASE A — Recommendation Engine
*Primary academic contribution. Fully evaluatable without UI or conversation layer. Requires Foundation complete.*

**Boundary**: Components in this phase live in `src/tools/`, `src/knowledge_graph/`, `src/llm_interface/`, `src/agents/critic_agent.py`. No dependency on `src/agents/orchestrator.py`, `src/conversation/`, `src/user/`, or `src/ui/`.

### A1 — Hybrid Search Tool Verification & Hardening
* [ ] Verify all 3 search strategies work against `kg_curated` after F0 API migration
* [ ] Verify `ResolverService` brand/category normalization against new graph
* [ ] Write integration tests: `tests/test_graph_search_tool.py`
* [ ] Add `excluded_asins` filter support to `_build_filters()` (prerequisite for B4 Recoverability)

### A2 — CriticAgent Verification & Testing
* [ ] Verify async evaluation end-to-end after GAP-001 asyncio fix
* [ ] Write unit tests: `tests/test_critic_agent.py`
* [ ] Verify `fetch_product_attributes()` returns correct data from curated graph

### A3 — PromptConstructor — Graph Path Injection Slots
* [ ] Add `graph_reasoning_paths` parameter to `construct_recommendation_prompt()`
* [ ] Add `[GRAPH EVIDENCE]` section to prompt with graph-grounding constraint
* [ ] Write tests asserting path injection when paths provided

### A4 — KECR — Knowledge-Enhanced Reasoning Path Extraction
* [ ] Implement `src/tools/kecr_tool.py` — `KnowledgePathExtractor` class
* [ ] Neo4j shortest-path queries connecting user preference entities → item
* [ ] Wire into recommendation pipeline after CriticAgent top-3 selection
* [ ] Write tests: `tests/test_kecr_tool.py`

### A5 — Explainable Response Generation (End-to-End)
* [ ] End-to-end integration test: `tests/test_recommendation_pipeline.py`
* [ ] Manual review: 5 diverse test queries against curated graph

### A6 — Quantitative & Qualitative Evaluation
* [ ] `scripts/evaluate_retrieval.py` — Hit@5, Hit@10, MRR, NDCG@10
* [ ] `scripts/evaluate_generative.py` — LLM-as-Judge: Groundedness, Explainability, Coherence, Recoverability

---

## 5. META-PHASE B — Conversational Flow + REDIAL Integration
*CRS packaging layer. Builds on top of Meta-Phase A. Also includes LLM-REDIAL dataset integration when access is granted.*

### B1 — AgentOrchestrator Full Async & Integration
* [ ] Post-GAP-001 verification in Chainlit async context
* [ ] Wire Meta-Phase A pipeline into SEARCH path

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

### B5 — LLM-REDIAL Integration *(requires dataset access)*
> **Note**: LLM-REDIAL requires author approval. Request access at: `https://github.com/LitGreenhand/LLM-Redial`. This step is deferred until access is granted.

* [ ] **LLM-REDIAL Acquisition**: Clone `LitGreenhand/LLM-Redial` once access granted. Parse dialogue JSON files. Extract canonical item set.
* [ ] **REDIAL Node Ingestion** (into `kg_curated` or a new `kg_redial` database): Create `(:Dialogue)`, `(:Turn)` nodes from REDIAL conversations. Link to existing `(:Item)` nodes via `[:MENTIONS]`. Create `(:User)` nodes for REDIAL users (schema already supports this).
* [ ] **Amazon Enrichment for REDIAL items**: For REDIAL items not in the curated subset, look up Amazon metadata and add to graph.
* [ ] **Cross-dataset evaluation**: Re-run A6 evaluation scripts using REDIAL test split as ground truth.

### B6 — End-to-End Integration & Cleanup
* [ ] Full Chainlit smoke test: SEARCH → CLARIFY → UPDATE_PROFILE → REJECT → refined SEARCH
* [ ] Remove `ResponseGenerator` dead code (GAP-013)
* [ ] Move `PreferenceAgentFlow` to `src/legacy/`
* [ ] Final dependency audit

---

## 6. Gap Cross-Reference

| GAP ID | Title | Phase | Status |
|--------|-------|-------|--------|
| GAP-001 | asyncio Event Loop Fix | Foundation F0 | ❌ Not done |
| GAP-002 | MemoCRS Persistence | Meta-Phase B2 | ❌ Not done |
| GAP-003 | Neo4j Deprecated API | Foundation F0 | ❌ Not done |
| GAP-004 | LLM-REDIAL Dataset | Meta-Phase B5 | ⏳ Deferred (access required) |
| GAP-005 | Lexical GraphRAG Layer | Foundation F3 | ❌ Not done |
| GAP-006 | KECR Reasoning Paths | Meta-Phase A4 | ❌ Not done |
| GAP-007 | Explainable Generation | Meta-Phase A3+A5 | ❌ Not done |
| GAP-008 | Quantitative Evaluation | Meta-Phase A6 | ❌ Not done |
| GAP-009 | LLM-as-Judge Evaluation | Meta-Phase A6 | ❌ Not done |
| GAP-010 | Recoverability Mechanism | Meta-Phase B4 | ❌ Not done |
| GAP-011 | requirements.txt Hygiene | Foundation F0 | ❌ Not done |
| GAP-012 | CLARIFY Path Quality | Meta-Phase B3 | ❌ Not done |
| GAP-013 | ResponseGenerator Cleanup | Meta-Phase B6 | ❌ Not done |

---

## 7. Work Methodology

* **Foundation first, always**: Nothing from Meta-Phase A or B is started until all Foundation items are marked `[x]`.
* **Amazon curated subset as testbed**: The 25-user / 25-product curated graph gives a fast, manageable environment to verify the full pipeline before scaling up.
* **REDIAL-compatible schema from day one**: `:User` and `:Item` node types in `constraints.cypher` already support REDIAL extension. No schema migration needed when REDIAL access is granted.
* **Iterative approach**: Handle 1 query correctly end-to-end before expanding.
* **KISS Principle**: No custom GNN/LoRA training. Rely on robust prompting, structured tool calls, and explicit Neo4j path-finding.
* **Evaluation-driven**: A6 evaluation scripts written alongside A4/A5 implementation — not as an afterthought.
