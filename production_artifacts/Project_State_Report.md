# Project State Report

**Date**: 2026-07-05
**Inspector**: @inspector
**Baseline**: docs/changelog/changelog.md (entry dated 2026-06-21)
**Pipeline**: /audit-state Phase 2
**Status**: Pending PM Gap Analysis

---

## Executive Summary

The codebase is substantially more complete than the Implementation Plan suggests. Phase 0 is 100% complete; Phase 1 is ~63% complete (missing the GraphRAG lexical layer and LLM-REDIAL migration scripts); Phase 2 is ~88% complete (all agentic components wired, memory persistence absent); Phase 3 is 0% complete (not started).

The 2026-06-21 changelog claim that "Phase II is current" is **verified as mostly true** — `AgentOrchestrator`, `CriticAgent`, `GraphSearchTool`, and `ProfileTool` all exist and are wired end-to-end into the Chainlit UI. The single overstated claim is MemoCRS: the entity-based extraction pipeline exists, but the "persistent database" for cross-session memory does not.

Two **critical technical debts** are on the live execution path: (1) the deprecated `db.index.vector.queryNodes()` Neo4j procedure (deprecated in Neo4j 2026.04, must be migrated to `SEARCH` clause before any Neo4j upgrade), and (2) the `asyncio.get_event_loop()` pattern in `orchestrator.py` which is incompatible with Chainlit's async event loop and will raise a `RuntimeError` in production.

---

## 0. Phase 2 Completeness Discrepancy Audit

> **Finding**: The Research Report correctly identified that the Implementation Plan's `[ ]` markers are stale. Phase 2 is substantially complete per source code inspection. The changelog's description is accurate.

### Phase 2 — Verified Item Table

| Phase 2 Item | Files Checked | Verdict | Evidence |
|---|---|---|---|
| Hybrid Search Tool (`GraphSearchTool`) | `src/tools/graph_search_tool.py` | ✅ Complete + Wired | 350-line implementation. Three strategies: HYBRID (vector ANN + Cypher WHERE filters), VECTOR_ONLY, FILTER_ONLY. Filter normalization via `ResolverService`. Brands/categories resolved via vector similarity. `fetch_product_attributes()` fetches `HAS_ATTRIBUTE` and `Review` nodes for critic context. Wired into `orchestrator.py:200`. ⚠️ Uses deprecated `db.index.vector.queryNodes()` procedure (5 occurrences across search tool + resolver). |
| Orchestrator (Router) Agent | `src/agents/orchestrator.py`, `src/agents/state.py` | ✅ Complete + Wired | `AgentOrchestrator` with `run()` entry point. `ConversationState` TypedDict tracks messages, next_step, active_filters, user_profile. LLM-based intent classification using `router_prompt_template` (5 actions: SEARCH/CLARIFY/UPDATE_PROFILE/ANSWER/READ_PROFILE). Does NOT use LangGraph state machine graph — orchestration is procedural Python (not a graph). ⚠️ `asyncio.get_event_loop()` at line 220 is deprecated; will fail under Chainlit's running event loop. |
| Critic Agent | `src/agents/critic_agent.py` | ✅ Complete + Wired | 123-line async agent. `evaluate_candidates()` uses `asyncio.gather()` for parallel LLM evaluation. Polish-language system prompt ("Ekspert ds. Weryfikacji Jakości Produktów"). Returns `fit_score` (0-100), `reasoning`, `is_recommended`. Sorts recommended items by `semantic_score`. Wired in orchestrator at lines 213–231. |
| Entity-Based Memory (MemoCRS) | `src/tools/profile_tool.py`, `src/user/profile_manager.py`, `src/conversation/history_manager.py` | 🟡 Partial | Extract→Quantify→Update pipeline is implemented and wired (`LLMPreferenceParser` uses LangChain tool-calling to extract structured preferences; `PreferenceQuantifier` applies binary weights: likes→0.8, dislikes→-0.7; `InMemoryUserProfileManager` stores in `self.profiles` dict). **Missing**: No persistent storage backend. Both `InMemoryHistoryManager` and `InMemoryUserProfileManager` store data in-process memory only — all data lost on restart. No Redis, SQLite, or DB layer. No semantic retrieval of historically relevant preferences across sessions. |

### Phase 1 — Partial Items Verified

| Phase 1 Item | Files Checked | Verdict | Evidence |
|---|---|---|---|
| Semantic Embedding Generation | `src/knowledge_graph/graphdb/embedding_service.py`, `src/knowledge_graph/graphdb/backfill_embeddings.py` | ✅ Complete | `EmbeddingService` wraps `sentence-transformers` (`all-MiniLM-L6-v2`). `BackfillService` processes Attribute/Brand/Category/ParentProduct nodes in batches of 100. Functional pipeline confirmed. |
| Vector Index Configuration | `src/knowledge_graph/graphdb/create_vector_indexes.cypher`, `create_indexes.py`, `setup_indexes.py` | ✅ Complete (all 4 indexes) | Scripts create `product_embedding_index`, `brand_embedding_index`, `category_embedding_index`, `attribute_embedding_index`. All 4 confirmed in use. ⚠️ Index creation uses deprecated `db.index.vector.createNodeIndex()` procedure. |
| LLM-REDIAL Dataset Migration | `scripts/`, `datasets/` | 🟡 Partial / ❌ | Amazon Electronics data present + ingested. **No LLM-REDIAL specific ingestion scripts found** anywhere. The graph is built from Amazon Electronics data only. LLM-REDIAL migration is not evidenced in code. |
| Lexical Graph / GraphRAG Layer | All of `src/` | ❌ Missing | Zero occurrences of `:Chunk` nodes or `[:MENTIONS]` relations. No chunking logic, no entity-linking pipeline, no GraphRAG retrieval layer. Confirmed missing. |

### Overall Phase 2 Verdict

> **Phase 2 is ~88% complete** (not "fully" as the changelog states). The 3 major agentic components (GraphSearchTool, AgentOrchestrator, CriticAgent) are fully implemented and wired. The 4th item (MemoCRS / persistent entity memory) is architecturally present but persistence is absent. The Implementation Plan's `[ ]` markers are stale and must be updated.

---

## 1. Module Inventory

### `src/agents/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `orchestrator.py` | `AgentOrchestrator` | Main MAS entry point; LLM-based intent routing; coordinates search, critic, profile tools | `asyncio.get_event_loop()` deprecated (line 220); no LangGraph graph used |
| `critic_agent.py` | `CriticAgent` | Async LLM-based candidate reranking; evaluates product fit against user persona | No issues; well-implemented |
| `state.py` | `ConversationState` (TypedDict) | Shared state schema for orchestration | Clean; complete |

### `src/tools/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `graph_search_tool.py` | `GraphSearchTool` | Hybrid semantic+structured search against Neo4j | Deprecated `db.index.vector.queryNodes()` (5 uses); filter values may accumulate stale state |
| `profile_tool.py` | `ProfileTool` | Wraps Extract→Quantify→Update pipeline for user preferences | Clean; `update_preferences_from_conversation()` overwrites vs merges (dict replace, not smart merge) |

### `src/dialog_manager/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `preference_agent_flow.py` | `PreferenceAgentFlow` | Legacy Phase 0/I orchestration pipeline | Superseded by `AgentOrchestrator`; still functional but not the active entry point |

### `src/knowledge_graph/graphdb/`

| File | Class / Function | Responsibility | Issues |
|---|---|---|---|
| `neo4j_connector.py` | `Neo4jConnector` | Neo4j driver wrapper | `#TODO TEMPORARY DISABLED` at line 62 (config validation disabled) |
| `embedding_service.py` | `EmbeddingService` | `all-MiniLM-L6-v2` embedding generation | Watch: model is not SOTA (see Research Report) |
| `resolver_service.py` | `ResolverService` | Brand/Category/Attribute vector similarity resolution | Deprecated `db.index.vector.queryNodes()` (3 uses) |
| `graph_query_manager.py` | `GraphQueryManager` | Text-to-Cypher LLM agent + Neo4j execution | Legacy Phase 0 path; still functional |
| `external_llm_cypher_generator.py` | `ExternalLLMCypherGenerator` | LangChain agent for Cypher generation | Uses `from langchain.agents import create_agent`; verify against installed langchain version |
| `backfill_embeddings.py` | `BackfillService` | Batch embedding backfill for 4 node types | Clean; functional |
| `attribute_normalizer.py` | `AttributeNormalizer` | Pydantic-based dimension/storage/weight normalization | Clean |
| `cypher_generator.py` | `CypherQueryGenerator` (ABC) | Abstract base for Cypher generators | Clean |
| `graph-builder/sample_ingest.py` | multiple functions | Amazon Electronics ETL → Neo4j ingestion | 1,285 lines; Amazon data only; no LLM-REDIAL |
| `graph-builder/aspect_pipeline.py` | multiple | PyABSA ASTE pipeline for review sentiment | Functional |

### `src/llm/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `simple_llm_handler.py` | `SimpleLLMHandler` | Unified sync+async LLM interface (OpenAI/Ollama) | Clean; supports `gpt-4o-mini` default |
| `abstract_llm_handler.py` | `LLMHandlerInterface` (ABC) | Interface contract | Clean |

### `src/llm_interface/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `preference_parser.py` | `LLMPreferenceParser` | LangChain tool-calling preference extraction | Clean; robust fallback parsing |
| `prompt_constructor.py` | `PromptConstructor` | Multi-section recommendation prompt builder | Does NOT inject graph reasoning paths (Phase 3 gap) |
| `response_generator.py` | `ResponseGenerator` | LLM response generation wrapper | Exists but not used in Phase 2 active flow |
| `prompts/router_prompt.py` | — | 5-action router system prompt + PromptTemplate | Clean |
| `prompts/graph_cypher_prompt.py` | — | Cypher generation system prompt | 14KB; detailed schema description |
| `prompts/preference_extract_prompt.py` | — | Preference extraction system prompt | Clean |

### `src/personalization/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `preference_quantifier.py` | `PreferenceQuantifier`, `HeuristicQuantificationStrategy` | Binary weight quantification (likes→0.8, dislikes→-0.7) | Abstract `quantify()` raises `NotImplementedError` (expected); concrete class works |

### `src/user/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `profile_manager.py` | `InMemoryUserProfileManager` | In-memory user profile store | No persistence; merging is dict overwrite |
| `abstract_profile_manager.py` | `AbstractProfileManager` (ABC) | Profile manager interface | Clean |

### `src/conversation/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `history_manager.py` | `InMemoryHistoryManager` | In-memory per-user conversation history (max 20 turns) | No persistence across process restarts |
| `abstract_history_manager.py` | `AbstractHistoryManager` (ABC) | History manager interface | Clean |

### `src/ui/`

| File | Function | Responsibility | Issues |
|---|---|---|---|
| `app.py` | `start_chat()`, `main()` | Chainlit chat UI; wraps AgentOrchestrator | `cl.make_async()` wrapper may conflict with `asyncio.get_event_loop()` inside orchestrator — potential `RuntimeError` |

### `src/utils/`

| File | Class | Responsibility | Issues |
|---|---|---|---|
| `AmazonDataProcessor.py` | `AmazonDataProcessor` | 59KB Amazon data preprocessing utility | ETL tool; not on live inference path |
| `EnhancedAmazonDataProcessor.py` | `EnhancedAmazonDataProcessor` | Enhanced ETL wrapper | ETL tool; not on live inference path |

---

## 2. End-to-End Flow Coverage

| Flow | Status | Bottleneck |
|---|---|---|
| Flow 1: Recommendation (SEARCH path) | 🟡 Partial | Deprecated `db.index.vector.queryNodes()` (Neo4j 2026.04 deprecation); `asyncio.get_event_loop()` will raise `RuntimeError` in Chainlit production context |
| Flow 2: Profile Update | ✅ Fully wired | user → orchestrator → UPDATE_PROFILE → ProfileTool → LLMPreferenceParser → PreferenceQuantifier → InMemoryUserProfileManager |
| Flow 3: Clarification Path | ✅ Fully wired | user → orchestrator → CLARIFY → LLM prompt → answer. Minimal but complete. |
| Flow 4: Session Memory Path | 🟡 Partial | All steps wired; but memory is process-bound — restart loses all data |
| Flow 5: Multi-turn Accumulation | 🟡 Partial | Within-session: works correctly. Cross-session: broken (no persistence) |

### Flow 1 Detail: Recommendation (SEARCH) — 🟡 Partial

```
User message
  → src/ui/app.py (cl.make_async wrapper)                           ✅
  → AgentOrchestrator.run(user_id, message)                         ✅
  → _initialize_state() [InMemoryHistoryManager + UserProfileManager] ✅ (in-memory only)
  → _decide_next_step() [LLM router via router_prompt_template]      ✅
  → intent == "SEARCH"
  → _generate_search_params() [LLM → JSON: semantic_query + filters] ✅
  → GraphSearchTool.search(semantic_query, structured_filters)        ✅
    → _normalize_filters() [ResolverService brand/category resolution] ✅
    → _execute_hybrid_search()                                        ✅ ⚠️ deprecated API
    → Neo4j                                                           ✅ (assumes DB up)
  → GraphSearchTool.fetch_product_attributes(asins)                  ✅
  → asyncio.get_event_loop().run_until_complete(CriticAgent...)       ⚠️ WILL FAIL in production
  → PromptConstructor.construct_recommendation_prompt()              ✅
  → SimpleLLMHandler.query() → final answer                          ✅
  → history_manager.add_turn()                                       ✅ (in-memory only)
  → UI response                                                       ✅
```

---

## 3. Requirements Compliance

| Requirement | In `requirements.txt` | Status | Notes |
|---|---|---|---|
| `langchain`, `langchain-core`, `langchain-openai` | ✅ `>=0.3.0` | ✅ | OK |
| `neo4j` | ✅ `>=5.14.0` | ✅ | OK |
| `sentence-transformers` | ✅ `>=2.0.0` | 🟡 | Model `all-MiniLM-L6-v2` not SOTA |
| `openai` | ✅ `>=0.27.0` | 🟠 | Very outdated — should be `>=1.0.0` |
| `chainlit` | ✅ `>=1.0.0` | ✅ | OK |
| `python-dotenv`, `tqdm` | ✅ | ✅ | OK |
| `pydantic` | ✅ `>=1.8.0` | 🟡 | Should be `>=2.0` |
| `langgraph` | ❌ NOT in requirements.txt | ❌ | Listed in Implementation Plan as core tech, not imported anywhere in src/ |
| `lightfm`, `scikit-surprise`, `fastapi`, `uvicorn`, `streamlit` | ✅ in file | 🔵 | Not used in src/; leftover from legacy system |

---

## 4. Stub and Placeholder Findings

| ID | File | Line | Severity | Content |
|---|---|---|---|---|
| S-001 | `src/knowledge_graph/graphdb/neo4j_connector.py` | 62 | 🟠 High | `#TODO TEMPORARY DISABLED` — config validation disabled; missing env vars fail silently |
| S-002 | `src/agents/orchestrator.py` | 220 | 🔴 Critical | `asyncio.get_event_loop()` — deprecated; raises `RuntimeError` in Chainlit's running event loop |
| S-003 | `src/agents/orchestrator.py` | 270–272 | 🟡 Medium | Hardcoded confirmation "I've updated your preferences…" — no dynamic extraction acknowledgment |
| S-004 | `src/tools/graph_search_tool.py` | 109, 139 | 🟠 High | `CALL db.index.vector.queryNodes(...)` — deprecated Neo4j 2026.04 |
| S-005 | `src/knowledge_graph/graphdb/resolver_service.py` | 34, 67, 101 | 🟠 High | `CALL db.index.vector.queryNodes(...)` × 3 — deprecated Neo4j 2026.04 |
| S-006 | `src/knowledge_graph/graphdb/external_llm_cypher_generator.py` | 6, 39 | 🟠 High | `from langchain.agents import create_agent` — needs version audit |
| S-007 | `src/knowledge_graph/graphdb/create_vector_indexes.cypher` | various | 🟡 Medium | `CALL db.index.vector.createNodeIndex(...)` — deprecated; will fail on fresh Neo4j 2026.04+ install |
| S-008 | `src/user/profile_manager.py` | 50–51 | 🟡 Medium | Dict overwrite for preference merge; multi-turn accumulation may drop earlier preferences |

---

## 5. Phase Coverage

| Phase | Items | Complete | Partial | Missing | Coverage |
|---|---|---|---|---|---|
| Phase 0 — MVP | 4 | 4 | 0 | 0 | ✅ **100%** |
| Phase 1 — Data Infrastructure | 4 | 2 | 1 | 1 | 🟡 **~63%** |
| Phase 2 — Agentic MAS | 4 | 3 | 1 | 0 | 🟡 **~88%** |
| Phase 3 — Explainability + Eval | 4 | 0 | 0 | 4 | ❌ **0%** |

### Phase-by-Phase Breakdown

**Phase 0 — 100%**
- ✅ Basic KG schema creation and initial ingestion (`sample_ingest.py`, `constraints.cypher`)
- ✅ `LLMPreferenceParser` (`src/llm_interface/preference_parser.py`)
- ✅ Text-to-Cypher deterministic mapping (`ExternalLLMCypherGenerator`, `GraphQueryManager`)
- ✅ Session history and profile management (`InMemoryHistoryManager`, `InMemoryUserProfileManager`)

**Phase 1 — ~63%**
- 🟡 Dataset Migration (Amazon Electronics ✅, LLM-REDIAL ❌ — no ingestion scripts)
- ❌ Lexical Graph Construction / GraphRAG (`:Chunk` nodes, `[:MENTIONS]` — not started)
- ✅ Semantic Embedding Generation (`EmbeddingService`, `BackfillService`)
- ✅ Vector Index Configuration (4 indexes active)

**Phase 2 — ~88%**
- ✅ `GraphSearchTool` — fully implemented, 3 strategies, wired
- ✅ `AgentOrchestrator` — fully implemented, 5-action routing, wired to UI
- ✅ `CriticAgent` — fully implemented, async parallel evaluation, wired
- 🟡 Entity-Based Memory — extraction pipeline ✅, persistence ❌

**Phase 3 — 0%**
- ❌ Reasoning Path Extraction (KECR) — no `shortestPath()` queries anywhere
- ❌ Explainable Response Generation — `PromptConstructor` does not inject graph paths
- ❌ Quantitative Retrieval Evaluation (Hit@K, MRR, NDCG) — no evaluation scripts
- ❌ LLM-as-Judge Evaluation — no judge framework

---

## 6. Gap Backlog

### [GAP-001] asyncio Event Loop Conflict in Orchestrator
**Phase**: Phase 2 (bug in existing implementation)
**Priority**: 🔴 Critical
**Implementation Plan ref**: Phase 2 — Orchestrator (Router) Agent
**Current state**: `orchestrator.py:220` uses `asyncio.get_event_loop().run_until_complete()` to invoke async `CriticAgent.evaluate_candidates()`. `src/ui/app.py` wraps orchestrator with `cl.make_async()`.
**Missing**: The `run()` method is synchronous. When Chainlit's async event loop is already running, calling `get_event_loop().run_until_complete()` raises `RuntimeError: This event loop is already running`.
**Blocks**: [GAP-002] (fix async architecture before adding persistence)
**Blocked by**: Nothing
**Suggested /implement prompt**: "Refactor `AgentOrchestrator` to be fully `async`, converting `run()`, `_initialize_state()`, `_decide_next_step()`, and `_execute_step()` to async methods. Replace `loop.run_until_complete(critic_agent.evaluate_candidates(...))` with `await critic_agent.evaluate_candidates(...)`. Update `src/ui/app.py` to call `await orchestrator.run(...)` directly (removing `cl.make_async` wrapper)."

### [GAP-002] ProfileManager Persistence — MemoCRS Incomplete
**Phase**: Phase 2
**Priority**: 🟠 High
**Implementation Plan ref**: Phase 2 — Entity-Based Memory (MemoCRS)
**Current state**: `InMemoryUserProfileManager` (dict in memory) + `InMemoryHistoryManager` (dict in memory). Both lost on process restart.
**Missing**: Persistent storage backend; cross-session profile retrieval; semantic retrieval of relevant historical preferences.
**Blocks**: [GAP-005] (multi-session evaluation)
**Blocked by**: [GAP-001]
**Suggested /implement prompt**: "Implement `SQLiteUserProfileManager` and `SQLiteHistoryManager` that persist user profiles and conversation history to `data/profiles.db`. Implement the `AbstractProfileManager` and `AbstractHistoryManager` interfaces. Add `get_relevant_history(user_id, query, k=5)` using cosine similarity over embedded turns. Wire into `AgentOrchestrator.__init__()` as default implementations."

### [GAP-003] Deprecated Neo4j Vector API Migration
**Phase**: Phase 2 / Pre-Phase 3
**Priority**: 🟠 High
**Implementation Plan ref**: Phase 2 — Hybrid Search Tool; Phase 1 — Vector Index Configuration
**Current state**: 5 occurrences of `CALL db.index.vector.queryNodes()` in `graph_search_tool.py` (lines 109, 139) and `resolver_service.py` (lines 34, 67, 101). Index creation uses `db.index.vector.createNodeIndex()`.
**Missing**: Migration to Cypher 25 `VECTOR SEARCH` / `CREATE VECTOR INDEX` DDL syntax.
**Blocks**: [GAP-008]
**Blocked by**: Nothing
**Suggested /implement prompt**: "Audit all Cypher queries in `src/tools/graph_search_tool.py` and `src/knowledge_graph/graphdb/resolver_service.py`. Replace all `CALL db.index.vector.queryNodes('index_name', k, $vector)` calls with Cypher 25 `VECTOR SEARCH` syntax. Update `create_vector_indexes.cypher` and `create_indexes.py` to use `CREATE VECTOR INDEX` DDL. Verify against Neo4j 2026.04+ documentation."

### [GAP-004] LLM-REDIAL Dataset Migration
**Phase**: Phase 1
**Priority**: 🟠 High
**Implementation Plan ref**: Phase 1 — Dataset Migration & Schema Mapping
**Current state**: Amazon Electronics data present in `datasets/` and ingested. No LLM-REDIAL ETL code found anywhere.
**Missing**: LLM-REDIAL download/parsing script; dialogue-to-preference mapping; item cross-reference with Amazon catalog; Neo4j ingestion.
**Blocks**: [GAP-005], [GAP-008]
**Blocked by**: Nothing
**Suggested /implement prompt**: "Create `scripts/ingest_llm_redial.py` that: (1) reads LLM-REDIAL dataset from `datasets/llm_redial/`, (2) parses multi-turn dialogues into structured preference signals, (3) cross-references mentioned items with Amazon ASIN catalog in `datasets/processed_data/`, (4) creates `(:User)`, `(:Dialogue)`, `(:Turn)` nodes linked to existing `(:ParentProduct)` nodes via `[:MENTIONED]` relationships."

### [GAP-005] Lexical GraphRAG Layer (`:Chunk` nodes + `[:MENTIONS]` relations)
**Phase**: Phase 1 / Phase 3
**Priority**: 🟠 High
**Implementation Plan ref**: Phase 1 — Lexical Graph Construction (GraphRAG)
**Current state**: Zero evidence of `:Chunk` nodes or `[:MENTIONS]` relations anywhere in codebase. Reviews ingested as atomic units.
**Missing**: Chunking pipeline, `:Chunk` node creation, entity linking, `chunk_embedding_index` registration.
**Blocks**: [GAP-006], [GAP-008]
**Blocked by**: [GAP-004]
**Suggested /implement prompt**: "Create `scripts/build_graphrag_layer.py` that: (1) fetches all `(:Review)` and `(:ParentProduct)` description nodes from Neo4j, (2) chunks text into overlapping 256-token windows using `RecursiveCharacterTextSplitter`, (3) creates `(:Chunk {text, chunk_index, embedding})` nodes linked via `[:CHUNK_OF]`, (4) uses `EmbeddingService` to embed each chunk, (5) runs NER/keyword extraction to create `[:MENTIONS]` relations to `(:Brand/:Category/:Attribute)` nodes, (6) registers chunks in a new `chunk_embedding_index`."

### [GAP-006] Reasoning Path Extraction (KECR Framework)
**Phase**: Phase 3
**Priority**: 🟡 Medium
**Implementation Plan ref**: Phase 3 — Reasoning Path Extraction (KECR Framework)
**Current state**: `GraphSearchTool` returns flat product records. No `shortestPath()` or reasoning-path queries exist anywhere.
**Missing**: Neo4j `shortestPath()` queries connecting recommended items to user preferences through the graph; path injection into LLM context.
**Blocks**: [GAP-007]
**Blocked by**: [GAP-005], [GAP-003]
**Suggested /implement prompt**: "Add `GraphSearchTool.fetch_reasoning_paths(user_preferences, item_asins)` that runs: `MATCH path = shortestPath((pref:Attribute)-[*..5]-(p:ParentProduct)) WHERE p.parent_asin IN $asins AND pref.attribute_name IN $preference_names RETURN p.parent_asin, [node IN nodes(path) | labels(node)[0] + ':' + coalesce(node.name, node.title, node.attribute_name)] AS path_summary`. Inject path summaries into `PromptConstructor` as a `[GRAPH REASONING PATHS]` section."

### [GAP-007] Explainable Response Generation
**Phase**: Phase 3
**Priority**: 🟡 Medium
**Implementation Plan ref**: Phase 3 — Explainable Response Generation
**Current state**: `PromptConstructor.construct_recommendation_prompt()` injects items, preferences, profile — but not graph paths. LLM is not constrained to reference graph-derived evidence.
**Missing**: Graph path injection into prompt; system instruction requiring graph-grounded justification.
**Blocks**: [GAP-009]
**Blocked by**: [GAP-006]
**Suggested /implement prompt**: "Update `PromptConstructor.construct_recommendation_prompt()` to accept `reasoning_paths: List[Dict]`. Add a `[GRAPH REASONING PATHS]` section to the prompt. Update system instruction: 'Your explanation MUST reference specific graph paths provided. Do not mention any product feature not listed in [RETRIEVED ITEMS] or [GRAPH REASONING PATHS].' Wire `AgentOrchestrator` to call `fetch_reasoning_paths()` after candidate retrieval."

### [GAP-008] Quantitative Retrieval Evaluation Scripts
**Phase**: Phase 3
**Priority**: 🟡 Medium
**Implementation Plan ref**: Phase 3 — Quantitative Retrieval Testing (Hit@K, MRR, NDCG)
**Current state**: No evaluation scripts in `tests/` or `scripts/` (only `scripts/run_preference_parser.py` and `tests/verify_cypher_robustness.py`).
**Missing**: Evaluation harness over LLM-REDIAL test split; Hit@5/10, MRR, NDCG@10 computation; strategy comparison.
**Blocked by**: [GAP-004], [GAP-003]
**Suggested /implement prompt**: "Create `scripts/evaluate_retrieval.py` that: (1) loads LLM-REDIAL test split, (2) uses `GraphSearchTool.search()` for each dialogue to retrieve top-10 items, (3) computes Hit@5, Hit@10, MRR, NDCG@10 against ground truth, (4) compares HYBRID vs VECTOR_ONLY vs FILTER_ONLY strategies, (5) outputs results CSV + summary report."

### [GAP-009] LLM-as-Judge Evaluation Framework
**Phase**: Phase 3
**Priority**: 🔵 Low
**Implementation Plan ref**: Phase 3 — Qualitative Generative Testing (LLM-as-Judge)
**Current state**: Nothing implemented.
**Missing**: Judge prompt; evaluation pipeline; Groundedness/Explainability/Coherence/Recoverability scoring.
**Blocked by**: [GAP-007], [GAP-008]
**Suggested /implement prompt**: "Create `scripts/evaluate_generative.py` that: (1) samples 50–100 dialogues from LLM-REDIAL test split, (2) generates full responses via `AgentOrchestrator`, (3) evaluates each response using `SimpleLLMHandler` with a judge prompt scoring Groundedness (0-5), Explainability (0-5), Coherence (0-5), Recoverability (0-5) against provided graph evidence, (4) outputs scored CSV with per-sample reasoning."

---

## 7. Recommended Implementation Order

> This sequence minimises rework and ensures no gap is built on a missing foundation.

| Order | GAP | Name | Can Parallelise With | Rationale |
|---|---|---|---|---|
| 1 | [GAP-001] | asyncio Event Loop Fix | — | 🔴 Production-breaking runtime bug; fix first |
| 2 | [GAP-003] | Neo4j Deprecated API Migration | [GAP-004] | Will break on any Neo4j upgrade; blocks Phase 3 |
| 2 | [GAP-004] | LLM-REDIAL Dataset Migration | [GAP-003] | Data foundation for all Phase 3 evaluation; independent of GAP-003 |
| 3 | [GAP-002] | ProfileManager Persistence | — | Requires GAP-001 async fix; enables real multi-session evaluation |
| 4 | [GAP-005] | Lexical GraphRAG Layer | — | Requires GAP-004 data; core Phase 3 prerequisite |
| 5 | [GAP-006] | KECR Reasoning Paths | — | Requires GAP-005 (chunks) + GAP-003 (correct API) |
| 6 | [GAP-007] | Explainable Response Generation | [GAP-008] | Requires GAP-006; can run in parallel with GAP-008 |
| 6 | [GAP-008] | Quantitative Evaluation | [GAP-007] | Requires GAP-004 + GAP-003; independent of GAP-007 |
| 7 | [GAP-009] | LLM-as-Judge Evaluation | — | Requires GAP-007 + GAP-008 |

---

## 8. Dependency and Integration Health

| Check | Status | Notes |
|---|---|---|
| `requirements.txt` completeness | 🟠 | `openai>=0.27.0` severely outdated; `langgraph` missing; 5 unused legacy packages |
| `__init__.py` coverage | 🟡 | `src/dialog_manager/` and `src/personalization/` missing `__init__.py` |
| Circular imports | ✅ | No circular imports detected |
| `.env` variables documented | 🟡 | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `ENABLE_GRAPH_RETRIEVAL` used in code — config validation disabled (S-001); no `.env.example` found |
| Dead code | 🟡 | `src/knowledge-graph/graphdb/decompose_attributes.py` in hyphenated directory (not importable); `ResponseGenerator` class exists but not used in Phase 2 active flow |
| Unused dependencies | 🔵 | `lightfm`, `scikit-surprise`, `fastapi`, `uvicorn`, `streamlit` not used in `src/` |

---

*Report generated by @inspector on 2026-07-05. All findings are based on direct source code inspection. No code was modified during this audit.*

---

## PM Validation

**Date**: 2026-07-06
**PM Agent**: @pm-specs (Gap Analysis Mode)
**Input**: Project State Report (@inspector, 2026-07-05) + Vision Report + Implementation Plan + Research Report

---

### 1. Gap Priority Review

| GAP | Title | Inspector Priority | PM Verdict | Rationale |
|-----|-------|--------------------|------------|-----------|
| GAP-001 | asyncio Event Loop Conflict | 🔴 Critical | ✅ Confirmed 🔴 | Verified in `orchestrator.py:219–228`. `asyncio.get_event_loop().run_until_complete()` inside a synchronous method called from Chainlit's async context is a guaranteed `RuntimeError`. Production-blocking. Fix first. |
| GAP-002 | ProfileManager Persistence | 🟠 High | 🔄 Elevated to 🔴 Critical | Vision Section 3 names "Entity-Based Memory Architecture (MemoCRS)" as one of four core engine pillars. Without cross-session persistence the system cannot demonstrate **Conversational Fluidity** — a primary evaluation axis. This is not a convenience feature; it is architectural. |
| GAP-003 | Deprecated Neo4j Vector API | 🟠 High | ✅ Confirmed 🟠 | 8 occurrences of `db.index.vector.queryNodes()` across `graph_search_tool.py` and `resolver_service.py`. Deprecated in Neo4j 2026.04. Will silently degrade and break on any Neo4j upgrade. Blocks Phase 3. Correctly prioritised. |
| GAP-004 | LLM-REDIAL Dataset Migration | 🟠 High | ✅ Confirmed 🟠 | No LLM-REDIAL ingestion scripts exist anywhere. Vision Section 4 and Implementation Plan Phase 1 both require the dual-dataset strategy. All Phase 3 quantitative evaluation is blocked without this. The `/implement` prompt must acknowledge the author email-request access dependency. |
| GAP-005 | Lexical GraphRAG Layer | 🟠 High | ✅ Confirmed 🟠 | Zero `:Chunk` nodes or `[:MENTIONS]` relations anywhere in the codebase. Core Phase 3 prerequisite. Correctly blocked by GAP-004. |
| GAP-006 | KECR Reasoning Path Extraction | 🟡 Medium | 🔄 Elevated to 🟠 High | Vision Section 3.4 states "By injecting explicit graph reasoning pathways into the LLM's context window, the model is architecturally constrained to generate responses rooted in demonstrable data provenance." Vision Section 4 names this the **Primary Academic Contribution**. This is the thesis's thesis — must be 🟠 High. |
| GAP-007 | Explainable Response Generation | 🟡 Medium | 🔄 Elevated to 🟠 High | `PromptConstructor.construct_recommendation_prompt()` contains no graph-path injection and no graph-grounded generation constraint. The system instruction says "explain why each item was recommended" — but this is a generic reasoning instruction, not a graph-evidence constraint. The Vision requires the LLM to be "architecturally constrained to generate responses rooted in demonstrable data provenance." Currently unimplemented. |
| GAP-008 | Quantitative Retrieval Evaluation | 🟡 Medium | ✅ Confirmed 🟡 | No evaluation scripts exist. Correctly depends on GAP-004 (dataset) and GAP-003 (working API). The suggested `/implement` prompt is actionable and correctly scoped. |
| GAP-009 | LLM-as-Judge Evaluation Framework | 🔵 Low | ✅ Confirmed 🔵 | Correctly last in sequence. However: the suggested prompt includes **Recoverability** as a scoring dimension — but the system has no recoverability mechanism. Cannot meaningfully score a behaviour that doesn't exist. See GAP-010 below. |

---

### 2. Missed Gaps

#### GAP-010 — Recoverability Mechanism Absent
**Phase**: Phase 2 / Phase 3
**PM Priority**: 🟠 High
**Vision ref**: Vision Section 5B — "Recoverability: The system's ability to refine and correct its outputs based on negative user feedback or shifted preferences."
**Current state**: The router prompt mentions handling "Too expensive" feedback, but `active_filters` in `orchestrator.py` only accumulates hard constraints (brand, price, category). There is no mechanism to express negative item-level feedback ("I don't want product X", "Show me something completely different"). `CriticAgent` evaluates `fit_score` but its verdict is not stored or fed back into subsequent queries. No code handles item rejection signals.
**Missing**: A `REJECT` action in the router; `excluded_asins: List[str]` in `active_filters`; feedback signal storage in `ProfileTool`; passing exclusions to `GraphSearchTool.search()` as a `NOT IN` Cypher constraint.
**Blocks**: [GAP-009] (cannot score Recoverability in LLM-as-Judge if the mechanism does not exist)
**Blocked by**: [GAP-001]
**Suggested /implement prompt**: "Add Recoverability support to the active flow: (1) Add a `REJECT` action to `router_prompt.py` triggered by negative item feedback ('not this one', 'show me something else', 'I don't like that'). (2) Add `excluded_asins: List[str]` and `disliked_attributes: List[str]` to `ConversationState` in `state.py`. (3) Update `AgentOrchestrator._execute_step()` to accumulate rejections. (4) Pass `excluded_asins` to `GraphSearchTool.search()` as a `WHERE p.parent_asin NOT IN $excluded` Cypher filter. (5) Write a test: user receives 3 items, says 'not the first one', system returns 3 different items excluding the rejected ASIN."

---

#### GAP-011 — `requirements.txt` Dependency Hygiene
**Phase**: Infrastructure / Pre-Phase 3
**PM Priority**: 🟡 Medium
**Current state**: `openai>=0.27.0` allows pip to resolve `openai==0.28.x` (legacy pre-v1 API). All `langchain-openai>=0.3.x` calls use the new `openai` v1.x client API — if pip installs `openai` 0.x the entire LangChain stack will crash on import. Additionally: `langgraph` is listed as a core technology in the Implementation Plan but is absent from `requirements.txt`. Five packages (`lightfm`, `scikit-surprise`, `fastapi`, `uvicorn`, `streamlit`) are unused in `src/`.
**Missing**: Pin `openai>=1.0.0`; add `langgraph>=1.0.0`; add `pydantic>=2.0.0`; move legacy packages out.
**Blocked by**: Nothing
**Suggested /implement prompt**: "Update `requirements.txt`: (1) Change `openai>=0.27.0` to `openai>=1.0.0`. (2) Add `langgraph>=1.0.0`. (3) Add `pydantic>=2.0.0`. (4) Move `lightfm>=1.16`, `scikit-surprise>=1.1.3`, `fastapi>=0.68.0`, `uvicorn>=0.15.0`, `streamlit>=1.20.0` to a new `requirements-legacy.txt` with a comment explaining they are retained from the Phase 0 legacy system. (5) Add a `.env.example` file documenting all required environment variables: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `ENABLE_GRAPH_RETRIEVAL`."

---

#### GAP-012 — CLARIFY Path Structural Deficiency
**Phase**: Phase 2
**PM Priority**: 🟡 Medium
**Vision ref**: Vision Section 2 — "The agent autonomously determines when to seek clarification, asking **targeted** questions to refine the user's constraints."
**Current state**: `orchestrator.py:253–264` handles CLARIFY with a hardcoded prompt: `"The user information is incomplete. Ask a clarifying question to better understand their needs regarding: {user_message}"`. This generates a generic question with no awareness of which constraints are already known (`active_filters`), which dimensions are missing (budget? use case? brand?), or the user's existing profile.
**Missing**: A structured clarification prompt that injects `active_filters` and `user_profile` to identify the specific missing dimension and ask a targeted follow-up. A `pending_clarification` field in `ConversationState`.
**Blocked by**: [GAP-001]
**Suggested /implement prompt**: "Refactor the CLARIFY execution path in `AgentOrchestrator._execute_step()`. Replace the hardcoded prompt with a context-aware clarification prompt template that: (1) lists known constraints from `active_filters` and `user_profile`, (2) identifies the most important missing dimension from a priority list (budget → use_case → brand → features), (3) asks one specific focused question. Also add `pending_clarification: Optional[str]` to `ConversationState` in `state.py` and pass it to the router prompt so it knows a clarification is already pending."

---

#### GAP-013 — `ResponseGenerator` Dead Code
**Phase**: Phase 2 (tech debt)
**PM Priority**: 🔵 Low
**Current state**: `src/llm_interface/response_generator.py` contains a fully implemented `ResponseGenerator` class (70 lines) that is never imported anywhere in `src/`. The active flow uses `PromptConstructor` + `SimpleLLMHandler.query()` directly. Additionally, `ResponseGenerator.__init__()` constructs its own `ChatOpenAI` instance independently from the injected `llm_handler` — a hidden configuration divergence (if `llm_handler` uses `gpt-4o`, `ResponseGenerator` silently uses a different model).
**Missing**: A decision — either wire `ResponseGenerator` into the active flow as the single LLM invocation point, or delete it.
**Blocked by**: Nothing
**Suggested /implement prompt**: "Audit `ResponseGenerator` in `src/llm_interface/response_generator.py`. Since `PromptConstructor` already produces `List[BaseMessage]` and `SimpleLLMHandler.query()` already accepts them, `ResponseGenerator` is redundant. Delete `response_generator.py`. Verify no test or script imports it. Update any documentation that references it. If `ResponseGenerator` was intended as the Phase 3 explainable generation entrypoint, move that responsibility to GAP-007 (Explainable Response Generation) instead."

---

### 3. Architectural Inconsistencies

#### AI-001 — LangGraph Declared but Never Used
**Severity**: 🟡 Accepted Deviation (with conditions)
**Implementation Plan ref**: Phase 2 — "LangGraph / LangChain for state-machine orchestration"
**Finding**: Zero LangGraph imports exist anywhere in `src/`. `langgraph` is not in `requirements.txt`. `AgentOrchestrator` implements routing via procedural `if/elif` Python with a `ConversationState` TypedDict — not a LangGraph `StateGraph`.
**PM Assessment**: The procedural approach delivers equivalent routing functionality for the current 5-action router. The KISS principle (explicitly stated in Implementation Plan Section 3) argues against retrofitting LangGraph purely for architectural purity. **Recommended decision**: Adopt LangGraph's `SqliteSaver` checkpointer as the implementation strategy for GAP-002, which will naturally pull LangGraph into the dependency tree with a clear functional justification — not as a cosmetic refactor.

#### AI-002 — `openai>=0.27.0` Latent Dependency Conflict
**Severity**: 🟠 High Risk
**Finding**: `requirements.txt` pins `openai>=0.27.0`. `langchain-openai>=0.3.0` requires the `openai` v1.x API. If pip resolves `openai` to any v0.x version, the entire LangChain stack will fail to import. Fix immediately as part of GAP-011. Pin `openai>=1.0.0`.

#### AI-003 — `preference_agent_flow.py` Superseded but Retained
**Severity**: 🔵 Low (maintenance risk only)
**Finding**: `src/dialog_manager/preference_agent_flow.py` implements the Phase 0 pipeline (`PreferenceAgentFlow`), completely superseded by `AgentOrchestrator`. Not called from any active entry point. Uses dynamic `importlib` path manipulation.
**PM Assessment**: Intentional legacy retention. Recommended: add a `# LEGACY: Superseded by AgentOrchestrator (Phase 2). Retained for reference only.` docstring and move it to `src/legacy/` directory.

#### AI-004 — CLARIFY Path Does Not Track Clarification State
**Severity**: 🟡 Medium
**Finding**: When the router decides `CLARIFY`, the clarification question is sent to the user but the fact that a clarification was asked is not stored in `ConversationState`. On the next turn, the router may decide `CLARIFY` again or jump to `SEARCH` prematurely. There is no "pending clarification" state.
**PM Assessment**: Structural aspect of GAP-012. Fix requires adding `pending_clarification: Optional[str]` to `ConversationState` and passing it to the router prompt.

---

### 4. Implementation Order — PM Validation

> PM-revised sequence reflects the Vision's strategic hierarchy (Explainability > Groundedness > Conversational Fluidity) and thesis timeline pressure.

| Order | GAP | Name | PM Priority | Can Parallelise With | Rationale |
|-------|-----|------|-------------|----------------------|-----------|
| 1 | GAP-001 | asyncio Event Loop Fix | 🔴 Critical | GAP-011 | Production-breaking runtime bug; system crashes in Chainlit. Fix before any other work. |
| 1 | GAP-011 | `requirements.txt` Hygiene | 🟡 Medium | GAP-001 | Zero-effort fix. Eliminates the latent `openai` v0.x pip conflict and adds `langgraph`. Do alongside GAP-001. |
| 2 | GAP-003 | Neo4j Deprecated API Migration | 🟠 High | GAP-004 | Will break on any Neo4j upgrade; blocks all Phase 3 retrieval. No dependencies. |
| 2 | GAP-004 | LLM-REDIAL Dataset Migration | 🟠 High | GAP-003 | Data foundation for all Phase 3 evaluation. Independent of GAP-003; requires dataset access confirmation first. |
| 3 | GAP-002 | ProfileManager Persistence (MemoCRS) | 🔴 Critical | GAP-012 | Requires GAP-001. Core Vision architectural pillar. Recommended strategy: use LangGraph `SqliteSaver` to resolve AI-001 simultaneously. |
| 3 | GAP-012 | CLARIFY Path Quality | 🟡 Medium | GAP-002 | Requires GAP-001 async fix. Low effort; directly improves Conversational Fluidity metric. |
| 4 | GAP-005 | Lexical GraphRAG Layer | 🟠 High | — | Requires GAP-004 dataset. Core Phase 3 prerequisite. Embedding upgrade decision (BGE-M3 vs all-MiniLM) should be made before this step. |
| 5 | GAP-006 | KECR Reasoning Path Extraction | 🟠 High | — | Requires GAP-005 (chunks) + GAP-003 (correct API). The primary academic contribution. |
| 6 | GAP-010 | Recoverability Mechanism | 🟠 High | GAP-007 | Requires GAP-001. Must exist before Phase 3 evaluation — cannot score Recoverability in LLM-as-Judge if mechanism is absent. |
| 6 | GAP-007 | Explainable Response Generation | 🟠 High | GAP-010 | Requires GAP-006. Thesis core deliverable. Can develop in parallel with GAP-010. |
| 7 | GAP-008 | Quantitative Retrieval Evaluation | 🟡 Medium | GAP-013 | Requires GAP-004 + GAP-003. Independent of GAP-007. |
| 8 | GAP-009 | LLM-as-Judge Evaluation | 🔵 Low | — | Requires GAP-007 + GAP-008 + GAP-010. |
| 9 | GAP-013 | `ResponseGenerator` Dead Code Cleanup | 🔵 Low | — | No dependencies. Zero functional impact. |

**Key revisions vs Inspector's order:**
- GAP-002 elevated to 🔴 Critical — MemoCRS is a Vision-mandated architectural pillar, not an enhancement
- GAP-006 and GAP-007 elevated to 🟠 High — thesis primary academic contribution
- GAP-010 (Recoverability) inserted at position 6, before GAP-009, because LLM-as-Judge cannot score what doesn't exist
- GAP-011 (requirements.txt) added at position 1 alongside GAP-001
- GAP-012 (CLARIFY quality) added at position 3 alongside GAP-002
- GAP-013 (dead code cleanup) added at position 9

---

### 5. Next Sprint Recommendations

> **Top 3 gaps to implement immediately** (in order):

**1. GAP-001 — asyncio Event Loop Fix**
- **Why first**: The system is currently broken in production. `orchestrator.py:226` raises `RuntimeError: This event loop is already running` whenever Chainlit calls `AgentOrchestrator.run()` and the flow reaches the Critic Agent. Every other gap is moot if the core execution path crashes.
- **`/implement` prompt**: "Refactor `AgentOrchestrator` in `src/agents/orchestrator.py` to be fully `async`. Convert `run()`, `_initialize_state()`, `_decide_next_step()`, `_generate_search_params()`, and `_execute_step()` to `async def` methods. Replace `asyncio.get_event_loop().run_until_complete(self.critic_agent.evaluate_candidates(...))` at line 226 with `await self.critic_agent.evaluate_candidates(...)`. Update `src/ui/app.py` to call `await orchestrator.run(user_id, message)` directly, removing the `cl.make_async()` wrapper. Ensure all internal LLM calls via `SimpleLLMHandler.query()` are also awaitable (use the async variant if available, or wrap in `asyncio.to_thread()`). Write a pytest-asyncio test that calls `orchestrator.run()` from within a running event loop and asserts no RuntimeError is raised."

**2. GAP-003 — Neo4j Deprecated Vector API Migration**
- **Why second**: The deprecated `db.index.vector.queryNodes()` procedure exists in 8 places. Neo4j 2026.04 has already deprecated this — any routine Neo4j upgrade will silently break all hybrid search. Blocks Phase 3 entirely. Independent of GAP-001 and can be done in parallel on a second branch.
- **`/implement` prompt**: "Migrate all deprecated Neo4j vector search calls to Cypher 25 syntax. In `src/tools/graph_search_tool.py` (lines 109, 139) and `src/knowledge_graph/graphdb/resolver_service.py` (lines 34, 67, 101): replace all `CALL db.index.vector.queryNodes('index_name', k, $vector) YIELD node, score` patterns with Cypher 25 `VECTOR SEARCH` syntax. Update `src/knowledge_graph/graphdb/create_vector_indexes.cypher` and `create_indexes.py` / `setup_indexes.py` to replace `CALL db.index.vector.createNodeIndex(...)` with `CREATE VECTOR INDEX index_name IF NOT EXISTS FOR (n:Label) ON (n.embedding) OPTIONS {indexConfig: {vector.dimensions: 384, vector.similarity_function: 'cosine'}}`. Verify against Neo4j 2026.04+ documentation. Run `scripts/run_preference_parser.py` end-to-end to confirm search still returns results."

**3. GAP-002 — ProfileManager Persistence (MemoCRS)**
- **Why third**: Requires GAP-001 to be completed first. Addresses the second most critical architectural missing piece: the Vision's MemoCRS pillar. Without cross-session persistence every session starts from scratch. Recommended approach uses LangGraph's `SqliteSaver` checkpointer, which simultaneously resolves AI-001 (LangGraph adoption with a clear functional justification).
- **`/implement` prompt**: "Implement persistent MemoCRS storage. (1) Create `src/user/sqlite_profile_manager.py` implementing `AbstractProfileManager` with SQLite storage at `data/profiles.db` — use `sqlite3` stdlib. Store profiles as JSON-serialised blobs keyed by `user_id`. (2) Create `src/conversation/sqlite_history_manager.py` implementing `AbstractHistoryManager` with per-user conversation history in SQLite. Add `get_relevant_history(user_id, query, k=5)` method that uses cosine similarity (via `EmbeddingService`) to retrieve the k most semantically relevant past turns. (3) Update `AgentOrchestrator.__init__()` to default to `SqliteProfileManager` and `SqliteHistoryManager` instead of the in-memory variants. (4) Add `data/` to `.gitignore`. (5) Write pytest tests: create a profile, restart the manager instance, assert profile is recovered; add 10 history turns, call `get_relevant_history` with a query, assert top-k returned are semantically relevant."

---

*PM Validation completed by @pm-specs on 2026-07-06. No source code was modified during this analysis. All findings are based on direct inspection of Vision Report, Implementation Plan, Research Report, Project State Report, and source files: `src/agents/orchestrator.py`, `src/agents/state.py`, `src/llm_interface/response_generator.py`, `src/llm_interface/prompt_constructor.py`, `src/llm_interface/prompts/router_prompt.py`, `src/dialog_manager/preference_agent_flow.py`, `requirements.txt`.*

---

## Strategic Reset — 2026-07-08

**Triggered by**: User decision to mark all phases as NOT DONE / NOT VERIFIED and re-examine from scratch.

### Phase Coverage — REVISED (Post-Reset)

> [!CAUTION]
> All phases have been reset to NOT DONE / NOT VERIFIED. The primary reason: the entire Knowledge Graph, embedding pipeline, and vector indexes were built on **Amazon Electronics data only**, with no connection to the LLM-REDIAL dataset. This violates the Vision Report's REDIAL-first dual-dataset strategy. All work must be re-evaluated once the correct data foundation is established.

| Phase | Previous Assessment | Revised Status | Reason |
|---|---|---|---|
| Phase 0 — MVP | ✅ 100% | ❌ NOT VERIFIED | Code exists but was tested against Amazon-only data. Must be re-validated once REDIAL-first graph is established. |
| Phase 1 — Data Infrastructure | 🟡 ~63% | ❌ NOT DONE (0%) | The existing work (Amazon ingestion, embeddings, indexes) does not satisfy this phase. REDIAL-first pipeline does not exist. |
| Phase 2 — Agentic MAS | 🟡 ~88% | ❌ NOT VERIFIED | Code exists but cannot be trusted until Phase 1 is complete + GAP-001 (asyncio bug) + GAP-003 (deprecated Neo4j API) are fixed. |
| Phase 3 — Explainability + Eval | ❌ 0% | ❌ NOT STARTED | Unchanged. |

### Critical Finding: Wrong Dataset Foundation

The entire graph, embeddings, and indexes were built on Amazon Electronics data. The correct order per Vision Report Section 4 is:

**LLM-REDIAL items first → Amazon metadata enrichment (for REDIAL items only) → embeddings → indexes**

What was done instead: Amazon data first, REDIAL never started.

Evidence:
- `datasets/llm_redial/` — **does not exist** (directory never created, data never downloaded)
- `graph-builder/sample_ingest.py` — hardcoded to `Electronics.jsonl` / `meta_Electronics.jsonl`
- `backfill_embeddings.py` — embeds `Attribute`, `Brand`, `Category`, `ParentProduct` nodes sourced from Amazon
- `create_vector_indexes.cypher` — indexes Amazon-sourced nodes using deprecated `db.index.vector.createNodeIndex()` API
- REDIAL grep across entire codebase: **0 matches** in any `.py` or `.cypher` file

### Embedding & Vector Index Verification Required

The following Neo4j introspection queries must be run to confirm the actual database state before any new development begins:

```cypher
-- Check which vector indexes exist and their status
SHOW INDEXES WHERE type = 'VECTOR';

-- Check if embeddings were generated for existing (Amazon) nodes
MATCH (n:ParentProduct) WHERE n.embedding IS NOT NULL RETURN count(n) AS embedded_products;
MATCH (n:Brand) WHERE n.embedding IS NOT NULL RETURN count(n) AS embedded_brands;
MATCH (n:Category) WHERE n.embedding IS NOT NULL RETURN count(n) AS embedded_categories;
MATCH (n:Attribute) WHERE n.embedding IS NOT NULL RETURN count(n) AS embedded_attributes;

-- Check total node counts
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;
```

### Implementation Plan Updated

`production_artifacts/Implementation_Plan.md` has been updated:
- All `[x]` markers reset to `[ ]`
- Phase 0 marked ❌ NOT VERIFIED
- Phase 1 expanded and rewritten with REDIAL-first data pipeline order (6 sub-steps instead of 4)
- Phase 2 marked ❌ NOT VERIFIED with per-item caveats
- Critical strategy note added explaining the wrong-dataset issue

### Recommended Next Steps (Revised Priority Order)

| Priority | Action | Notes |
|---|---|---|
| 🔴 IMMEDIATE | Run Neo4j introspection queries | Determine actual database state before planning |
| 🔴 IMMEDIATE | Acquire LLM-REDIAL dataset | `git clone LitGreenhand/LLM-Redial` or email authors for full data |
| 🟠 HIGH (parallel) | Fix GAP-001 asyncio bug | No data dependency — fix while dataset is being acquired |
| 🟠 HIGH (parallel) | Fix GAP-003 Neo4j deprecated API | No data dependency — fix in parallel |
| 🟠 HIGH (parallel) | Fix GAP-011 requirements.txt | 10-minute fix — do immediately |
| 🟡 NEXT | Design REDIAL-first Neo4j schema | Define node types before writing ETL |
| 🟡 NEXT | Write REDIAL ETL pipeline | After schema is defined and dataset is available |

*Strategic reset documented by parent agent on 2026-07-08. No source code was modified during this update.*

---

## Strategic Update — 2026-07-11

### Foundation Phase Revised — NOT DONE

**Trigger**: User decision to decouple the graph rebuild from the LLM-REDIAL dataset dependency.

**Key changes:**

1. **LLM-REDIAL deferred to Meta-Phase B**: The LLM-REDIAL dataset requires author approval (email request to `LitGreenhand/LLM-Redial`). Rather than block Foundation work, the approach has been revised to use an **Amazon-curated subset** first.

2. **Amazon-curated subset strategy**: Dataset analysis (2026-07-11) identified:
   - 471,471 unique users; 123,720 products; 1,630,273 reviews in the full Amazon Electronics dataset
   - Selected: top 20 active users (147–532 reviews each) + 5 cold-start users (1 review)
   - Selected: top 20 most-reviewed products (292–519 reviews) + 5 low-review products (1–2 reviews)
   - Target: ~25 users, ~25 products, ~N reviews → small, fast, fully evaluatable graph

3. **REDIAL-compatible schema from day one**: The existing `constraints.cypher` already has `CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE`. No schema migration needed when REDIAL access is eventually granted — REDIAL `:Dialogue` and `:Turn` nodes slot in alongside existing `:User` and `:Item` nodes.

4. **Existing graph preserved**: The existing Neo4j database will NOT be deleted. The curated subset will be built in a new `kg_curated` database.

### Foundation Status — ALL ITEMS MARKED NOT DONE

| Item | Status | Reason |
|---|---|---|
| F0 — Infrastructure fixes (asyncio, Neo4j API, requirements.txt) | ❌ NOT DONE | GAP-001, GAP-003, GAP-011 unresolved |
| F1 — Live graph introspection | ❌ NOT DONE | Cypher queries not yet run |
| F1.2 — Ingestion script audit | ❌ NOT DONE | Script compatibility with processed CSVs unverified |
| F2 — Curated subset selection | ⚠️ SELECTED (not ingested) | User/product IDs identified via dataset analysis; not yet extracted to `datasets/curated/` |
| F3 — Fresh graph build (kg_curated) | ❌ NOT DONE | No data in kg_curated yet |
| F3.4 — Embedding generation | ❌ NOT DONE | Blocked by F3.3 and GAP-003 |
| F3.5 — Vector index creation | ❌ NOT DONE | Blocked by GAP-003 (deprecated API) |

### Ingestion Script Assessment

`src/knowledge_graph/graphdb/graph-builder/sample_ingest.py`:
- **Core logic**: Reusable — node creation, relationship wiring, price bucket derivation, attribute extraction are all sound
- **Issue**: Currently expects raw JSONL format (`Electronics.jsonl`, `meta_Electronics.jsonl`); processed CSVs use different column names
- **Resolution**: Adapt path arguments or write `scripts/ingest_curated.py` wrapper

`src/knowledge_graph/graphdb/backfill_embeddings.py`:
- **Status**: Fully reusable — model-agnostic, batch-based, queries by `elementId`
- **Issue**: Uses deprecated Neo4j `db.index.vector.createNodeIndex()` indirectly via create scripts (GAP-003)
- **Resolution**: Fix index creation DDL (GAP-003); backfill script itself does not need changes

