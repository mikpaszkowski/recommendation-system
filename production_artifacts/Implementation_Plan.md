# Implementation Plan: Explainable Hybrid GraphRAG for Conversational Recommendation

> **Last restructured**: 2026-07-08 — Reorganised from linear Phase 0–3 into **Foundation → Meta-Phase A → Meta-Phase B** to reflect the correct dependency order and academic priority (Explainability > Groundedness > Conversational Fluidity).

---

## 1. Solution Architecture (State-of-the-Art)

The system is a Multi-Agent System (MAS) that combines a Neo4j Knowledge Graph, Hybrid GraphRAG retrieval, and LLM-driven orchestration into a conversational recommender.

**Technology Stack:**
* **Database**: Neo4j (structured graph + vector index for ANN search)
* **Logic / Agents**: LangChain + procedural Python orchestration; LangGraph `SqliteSaver` for MemoCRS persistence
* **LLM API**: OpenAI GPT-4o — reasoning, extraction, critique, evaluation (LLM-as-a-Judge)
* **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (structural nodes) — upgrade path to `BGE-M3` for Phase A lexical chunks
* **Interface**: Chainlit (async chat UI)

---

## 2. Two-Axis Build Strategy

The system has two independent execution axes that share a common data foundation but have **no hard dependency on each other**:

```
┌──────────────────────────────────────────────────────────────────────┐
│  FOUNDATION  (prerequisite for both axes — must be built first)      │
│  • Infrastructure fixes (asyncio, Neo4j API, requirements.txt)       │
│  • REDIAL-first Knowledge Graph pipeline (6 steps)                   │
└───────────────────────┬──────────────────────────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
┌──────────────────────┐   ┌────────────────────────────────────┐
│  META-PHASE A        │   │  META-PHASE B                      │
│  Recommendation      │   │  Conversational Flow               │
│  Engine              │   │  (CRS packaging)                   │
│                      │   │                                    │
│  PRIMARY ACADEMIC    │   │  Builds on top of Meta-Phase A.    │
│  CONTRIBUTION        │   │  Can be developed once A is        │
│                      │   │  verifiably complete.              │
│  Fully evaluatable   │   │                                    │
│  without UI/router.  │   │                                    │
└──────────────────────┘   └────────────────────────────────────┘
```

**Why this order?**
- Meta-Phase A contains the thesis's primary academic deliverable (KECR, Explainability, Groundedness evaluation). It can be fully evaluated — Hit@K, MRR, NDCG, LLM-as-Judge — without any conversation UI.
- Meta-Phase B wraps Meta-Phase A with intent routing, persistent memory, and recoverability. It depends on A being correct first.
- If time is constrained, a complete Meta-Phase A alone constitutes a publishable thesis contribution.

---

## 3. FOUNDATION — Prerequisite for Everything
*Must be completed before any Meta-Phase A or B work begins.*

### F0 — Infrastructure Fixes (No Data Dependency — Start Immediately)

* [ ] **GAP-001 — asyncio Refactor** (`src/agents/orchestrator.py`): Convert `run()`, `_initialize_state()`, `_decide_next_step()`, `_generate_search_params()`, and `_execute_step()` to `async def`. Replace `asyncio.get_event_loop().run_until_complete()` at line 220 with `await`. Update `src/ui/app.py` to call `await orchestrator.run()`. Add `pytest-asyncio` test confirming no `RuntimeError` is raised inside a running event loop.

* [ ] **GAP-003 — Neo4j Deprecated API Migration** (`src/tools/graph_search_tool.py`, `src/knowledge_graph/graphdb/resolver_service.py`): Replace all 8 occurrences of deprecated `CALL db.index.vector.queryNodes(...)` with Cypher 25 `VECTOR SEARCH` syntax. Replace `CALL db.index.vector.createNodeIndex(...)` in `create_vector_indexes.cypher` and `setup_indexes.py` with `CREATE VECTOR INDEX ... IF NOT EXISTS` DDL.

* [ ] **GAP-011 — `requirements.txt` Hygiene**: Pin `openai>=1.0.0` (eliminates latent v0.x crash). Add `langgraph>=1.0.0`. Add `pydantic>=2.0.0`. Move unused legacy packages (`lightfm`, `scikit-surprise`, `fastapi`, `uvicorn`, `streamlit`) to `requirements-legacy.txt`. Add `.env.example` documenting `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `ENABLE_GRAPH_RETRIEVAL`.

### F1 — REDIAL-First Knowledge Graph Pipeline

> **⚠️ CRITICAL**: The entire existing graph, embeddings, and indexes were built on Amazon Electronics data only. `datasets/llm_redial/` does not exist. Zero REDIAL code exists anywhere. All existing graph data must be dropped and rebuilt following the correct order below: **LLM-REDIAL first → Amazon enrichment second → embeddings third → indexes last**.

* [ ] **F1.1 — LLM-REDIAL Acquisition & Item Extraction**: Clone `https://github.com/LitGreenhand/LLM-Redial`. Parse all dialogue JSON files. Extract the complete set of unique `movieId` / `item_id` values mentioned across all train/valid/test splits. This **canonical item set** gates everything that follows — no item enters the Knowledge Graph unless it appears in LLM-REDIAL. Script: `scripts/extract_redial_items.py` → `datasets/llm_redial/canonical_items.json`.

* [ ] **F1.2 — Schema Definition (REDIAL-first)**: Extend `src/knowledge_graph/graphdb/graph-builder/constraints.cypher` with uniqueness constraints for `(:User {user_id})`, `(:Dialogue {dialogue_id})`, `(:Turn {turn_id})`, `(:Item {item_id})`. These are the REDIAL-sourced foundation nodes.

* [ ] **F1.3 — REDIAL Core Ingestion**: Script `scripts/ingest_redial_core.py`. Create `(:User)`, `(:Dialogue)`, `(:Turn)`, `(:Item)` Neo4j nodes directly from parsed LLM-REDIAL JSON. Link `(:User)-[:HAD_DIALOGUE]->(:Dialogue)-[:HAS_TURN]->(:Turn)-[:MENTIONS]->(:Item)`. This step establishes the graph's behavioural and conversational backbone.

* [ ] **F1.4 — Amazon Metadata Enrichment** (REDIAL items only): Script `scripts/enrich_from_amazon.py`. For each item in `canonical_items.json`, look up metadata in `datasets/Electronics.*.csv` by ASIN. Create `(:Brand)`, `(:Category)`, `(:Attribute)`, `(:PriceRange)` nodes **only for items already present** in the REDIAL canonical set. Wire: `(:Item)-[:HAS_BRAND]->(:Brand)`, `(:Item)-[:BELONGS_TO_CATEGORY]->(:Category)`, `(:Item)-[:HAS_ATTRIBUTE]->(:Attribute)`.

* [ ] **F1.5 — Lexical GraphRAG Layer** (`[:CHUNK_OF]`, `[:MENTIONS]`): Script `scripts/build_graphrag_chunks.py`. For each REDIAL item, chunk its Amazon description and top Amazon reviews into overlapping 200-token segments. Create `(:Chunk {text, position})` nodes linked via `[:CHUNK_OF]->(:Item)`. Extract entity mentions (brands, categories, attributes) from chunk text and create `(:Chunk)-[:MENTIONS]->(entity)` edges. This layer is the foundation for KECR graph path traversal.

* [ ] **F1.6 — Embedding Generation**: Re-run `src/knowledge_graph/graphdb/backfill_embeddings.py` against the new REDIAL-sourced graph. Embed all `(:Item)`, `(:Brand)`, `(:Category)`, `(:Attribute)`, and `(:Chunk)` nodes using a "Rich Context String" (title + category hierarchy + primary features). **The existing embeddings (Amazon-only nodes) are invalid and must be regenerated.**

* [ ] **F1.7 — Vector Index Creation (Cypher 25 DDL)**: Drop all existing vector indexes. Run updated `setup_indexes.py` using Cypher 25 `CREATE VECTOR INDEX ... IF NOT EXISTS FOR (n:Label) ON (n.embedding) OPTIONS {indexConfig: {vector.dimensions: 384, vector.similarity_function: 'cosine'}}`. Indexes required: `item_embedding_index`, `brand_embedding_index`, `category_embedding_index`, `attribute_embedding_index`, `chunk_embedding_index`.

---

## 4. META-PHASE A — Recommendation Engine
*Primary academic contribution. Fully evaluatable without UI or conversation layer. Requires Foundation complete.*

**Boundary**: Components in this phase live in `src/tools/`, `src/knowledge_graph/`, `src/llm_interface/`, `src/agents/critic_agent.py`. They have **no dependency on** `src/agents/orchestrator.py`, `src/conversation/`, `src/user/`, or `src/ui/`. Each can be called directly from a Python script or test.

### A1 — Hybrid Search Tool Verification & Hardening
*Code exists in `src/tools/graph_search_tool.py`. Not yet verified against REDIAL-first graph.*

* [ ] **Verify all 3 search strategies** (HYBRID / VECTOR_ONLY / FILTER_ONLY) work correctly against REDIAL-sourced nodes after F0 API migration and F1 graph rebuild.
* [ ] **Verify `ResolverService`** brand/category normalization resolves correctly against REDIAL-sourced `(:Brand)`, `(:Category)` nodes via the new Cypher 25 vector indexes.
* [ ] **Write integration tests**: `tests/test_graph_search_tool.py` — assert each strategy returns ≥1 result for known REDIAL items; assert filter normalization maps "asus" → canonical brand node.
* [ ] **Add `excluded_asins` filter support** to `_build_filters()`: `WHERE node.item_id NOT IN $excluded_items` — prerequisite for GAP-010 Recoverability.

### A2 — CriticAgent Verification & Testing
*Code exists in `src/agents/critic_agent.py`. Async, but blocked by asyncio bug until F0 GAP-001 is fixed.*

* [ ] **Verify async evaluation** works end-to-end with real Neo4j candidates after F0 fix.
* [ ] **Write unit tests**: `tests/test_critic_agent.py` — mock LLM responses, assert reranking logic sorts by `fit_score`, assert `is_recommended=false` items are dropped.
* [ ] **Verify `fetch_product_attributes()`** returns correct attributes from REDIAL-enriched `(:Attribute)` and `(:Review)` nodes.

### A3 — PromptConstructor — Graph Path Injection Slots
*Code exists in `src/llm_interface/prompt_constructor.py`. Currently has no graph-path injection (confirmed GAP-007 structural gap).*

* [ ] **Add `graph_reasoning_paths` parameter** to `construct_recommendation_prompt()`. When provided, inject a `[GRAPH EVIDENCE]` section into the prompt forcing the LLM to ground its response in the supplied paths.
* [ ] **Strengthen system instruction**: Replace the current generic "explain why each item was recommended" with an explicit graph-grounding constraint: *"You MUST justify each recommendation using ONLY the graph evidence provided. Do not invent product features."*
* [ ] **Write tests**: assert that when `graph_reasoning_paths` is provided, the resulting prompt contains `[GRAPH EVIDENCE]` and the path strings.

### A4 — KECR — Knowledge-Enhanced Reasoning Path Extraction
*Not yet implemented. Primary academic contribution per Vision Report Section 4.*

* [ ] **Implement `src/tools/kecr_tool.py`** — `KnowledgePathExtractor` class with method `extract_paths(item_ids: List[str], user_preferences: Dict) -> List[str]`. For each top-K candidate item, execute a Neo4j shortest-path query connecting known user preference entities (brands, categories, attributes) to the item via any relationship type. Return human-readable path strings: `"Prefers Gaming → [:BELONGS_TO_CATEGORY] → Category:Gaming Laptops → [:HAS_ATTRIBUTE] → Attribute:GPU=RTX4070 → [:HAS_ATTRIBUTE] → Item:ASUS ROG Zephyrus"`.
* [ ] **Wire into recommendation pipeline**: After `CriticAgent.evaluate_candidates()` returns top-3, call `KnowledgePathExtractor.extract_paths()` for those 3 items. Pass the returned path strings to `PromptConstructor.construct_recommendation_prompt(graph_reasoning_paths=paths)`.
* [ ] **Write tests**: `tests/test_kecr_tool.py` — verify path extraction returns non-empty results for known REDIAL items with populated user preferences.

### A5 — Explainable Response Generation (End-to-End)
*Combines A3 + A4. The full SEARCH path from query → graph-grounded natural language recommendation.*

* [ ] **End-to-end integration test** `tests/test_recommendation_pipeline.py`: Given a structured query `{semantic_query: "gaming laptop", structured_filters: {price_max: 2000}}`, trace the full pipeline — `GraphSearchTool.search()` → `CriticAgent.evaluate_candidates()` → `KnowledgePathExtractor.extract_paths()` → `PromptConstructor` → `SimpleLLMHandler.query()` → assert the response contains at least one item name and at least one graph-path-derived justification phrase.
* [ ] **Manual review**: Run the pipeline against 5 diverse LLM-REDIAL test dialogues. Confirm responses reference graph evidence (brand names, categories, attributes) from the actual Neo4j data — not hallucinated features.

### A6 — Quantitative & Qualitative Evaluation
*Thesis finalization. Requires Foundation + A1–A5 complete.*

* [ ] **`scripts/evaluate_retrieval.py`**: Load LLM-REDIAL test split. For each dialogue, extract the ground-truth target item. Call `GraphSearchTool.search()` with the dialogue context as `semantic_query`. Compute **Hit@5, Hit@10, MRR, NDCG@10** across the full test set. Compare HYBRID vs VECTOR_ONLY vs FILTER_ONLY strategies. Output: `production_artifacts/eval_retrieval_results.csv` + summary.

* [ ] **`scripts/evaluate_generative.py`** (LLM-as-a-Judge): Sample 50–100 dialogues from the LLM-REDIAL test split. Generate full responses via the A5 pipeline. Evaluate each response using GPT-4o as judge on a 0–5 rubric for: **Groundedness** (no hallucinated features), **Explainability** (graph paths cited), **Coherence** (follows dialogue intent), **Recoverability** (handles negative feedback). Output: `production_artifacts/eval_generative_results.csv` + summary.

---

## 5. META-PHASE B — Conversational Flow
*CRS packaging layer. Wraps Meta-Phase A with intent routing, session memory, and multi-turn fluidity. Requires Foundation complete. Should begin once A1–A2 are verified.*

**Boundary**: Components in this phase primarily live in `src/agents/orchestrator.py`, `src/conversation/`, `src/user/`, `src/ui/`. They import from Meta-Phase A components but add no new recommendation logic.

### B1 — AgentOrchestrator — Full Async & Integration
*Code exists but has production-breaking asyncio bug (GAP-001, fixed in Foundation F0).*

* [ ] **Post-F0 verification**: After asyncio refactor, run `orchestrator.run()` from within a Chainlit async context. Assert no `RuntimeError`. Assert all 5 actions (SEARCH, CLARIFY, UPDATE_PROFILE, READ_PROFILE, ANSWER) route correctly.
* [ ] **Wire Meta-Phase A pipeline into SEARCH path**: Ensure orchestrator calls the updated `GraphSearchTool` (A1) → `CriticAgent` (A2) → `KnowledgePathExtractor` (A4) → updated `PromptConstructor` (A3) in sequence. The orchestrator should be a thin coordinator — no recommendation logic inside it.

### B2 — MemoCRS Persistent Memory
*In-memory only (GAP-002 — elevated to 🔴 Critical). Cross-session persistence absent.*

* [ ] **`src/user/sqlite_profile_manager.py`**: Implement `SQLiteProfileManager(AbstractProfileManager)` with `data/profiles.db` (SQLite, `sqlite3` stdlib). Store profiles as JSON blobs keyed by `user_id`. Methods: `get_profile(user_id)`, `update_profile(user_id, preferences)`, `delete_profile(user_id)`.
* [ ] **`src/conversation/sqlite_history_manager.py`**: Implement `SQLiteHistoryManager(AbstractHistoryManager)` with per-user conversation history in SQLite. Add `get_relevant_history(user_id, query, k=5)` using cosine similarity via `EmbeddingService` to retrieve semantically relevant past turns.
* [ ] **Update `AgentOrchestrator.__init__()`**: Default to `SQLiteProfileManager` and `SQLiteHistoryManager`. Add `data/` to `.gitignore`.
* [ ] **Tests**: Create profile → restart manager → assert profile recovered. Add 10 history turns → call `get_relevant_history` → assert top-k are semantically relevant.

### B3 — CLARIFY Path — Context-Aware Questioning
*Currently a 3-line hardcoded stub ignoring all context (GAP-012).*

* [ ] **Add `pending_clarification: Optional[str]`** to `ConversationState` in `src/agents/state.py`.
* [ ] **Refactor CLARIFY execution** in `AgentOrchestrator._execute_step()`: Replace hardcoded prompt with a structured template injecting `active_filters` (known constraints) and `user_profile` (known preferences). Logic: identify the highest-priority missing dimension from `[budget, use_case, brand, features]` and ask one targeted question. Pass `pending_clarification` to router so it can distinguish "user answering clarification" from "new request".
* [ ] **Tests**: Assert that with `active_filters = {category: "laptop"}` and no `price_max`, the CLARIFY response asks about budget — not a generic question.

### B4 — Recoverability Mechanism
*Not implemented (GAP-010 — Vision Section 5B metric).*

* [ ] **Add `REJECT` action to `src/llm_interface/prompts/router_prompt.py`**: Triggered by negative item feedback ("not this one", "show me something else", "I don't like that").
* [ ] **Add `excluded_items: List[str]` and `disliked_attributes: List[str]`** to `ConversationState` in `src/agents/state.py`.
* [ ] **Update orchestrator REJECT handler**: Accumulate rejected item IDs in `excluded_items`. Pass to `GraphSearchTool.search()` via the `excluded_asins` filter added in A1. Store negative signals in `ProfileTool`.
* [ ] **Tests**: User receives 3 items → says "not the first one" → next response excludes the rejected item ID.

### B5 — End-to-End Conversational Integration & Cleanup
* [ ] **Full Chainlit smoke test**: Multi-turn dialogue covering SEARCH → CLARIFY → UPDATE_PROFILE → REJECT → second SEARCH with refined results. Confirm all turns persist across a simulated session restart (via SQLite managers).
* [ ] **Remove `ResponseGenerator` dead code** (`src/llm_interface/response_generator.py` — GAP-013): Never imported. Delete.
* [ ] **Move `PreferenceAgentFlow`** (`src/dialog_manager/preference_agent_flow.py`) to `src/legacy/` with docstring: `# LEGACY: Superseded by AgentOrchestrator (Phase 2). Retained for reference only.`
* [ ] **Final dependency audit**: Confirm `requirements.txt` lists all packages actually imported in `src/`. Confirm `.env.example` is complete.

---

## 6. Gap Cross-Reference

| GAP ID | Title | Meta-Phase | Status |
|--------|-------|------------|--------|
| GAP-001 | asyncio Event Loop Fix | Foundation F0 | ❌ Not done |
| GAP-002 | MemoCRS Persistence | Meta-Phase B2 | ❌ Not done |
| GAP-003 | Neo4j Deprecated API | Foundation F0 | ❌ Not done |
| GAP-004 | LLM-REDIAL Dataset | Foundation F1.1–F1.3 | ❌ Not done |
| GAP-005 | Lexical GraphRAG Layer | Foundation F1.5 | ❌ Not done |
| GAP-006 | KECR Reasoning Paths | Meta-Phase A4 | ❌ Not done |
| GAP-007 | Explainable Generation | Meta-Phase A3+A5 | ❌ Not done |
| GAP-008 | Quantitative Evaluation | Meta-Phase A6 | ❌ Not done |
| GAP-009 | LLM-as-Judge Evaluation | Meta-Phase A6 | ❌ Not done |
| GAP-010 | Recoverability Mechanism | Meta-Phase B4 | ❌ Not done |
| GAP-011 | requirements.txt Hygiene | Foundation F0 | ❌ Not done |
| GAP-012 | CLARIFY Path Quality | Meta-Phase B3 | ❌ Not done |
| GAP-013 | ResponseGenerator Cleanup | Meta-Phase B5 | ❌ Not done |

---

## 7. Work Methodology

* **Foundation first, always**: Nothing from Meta-Phase A or B is started until all Foundation items are marked `[x]`.
* **Iterative approach**: Force the system to handle 1 LLM-REDIAL dialogue correctly end-to-end at each phase. Verify manually. Then expand.
* **KISS Principle**: No custom GNN/LoRA training. Rely on robust prompting, structured tool calls, and explicit Neo4j path-finding.
* **Evaluation-driven**: A6 evaluation scripts are written alongside A4/A5 implementation — not as an afterthought. If a component cannot be evaluated, it is not done.
