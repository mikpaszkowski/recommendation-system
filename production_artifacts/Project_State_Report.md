# Project State Report: Explainable Hybrid GraphRAG for Conversational Recommendation

**Date**: 2026-09-19
**Pipeline Trigger**: `/audit-state`

---

## 1. Phase Coverage Summary

- **Phase F0 (Infrastructure)**: ~80% complete (asyncio bug fixed, requirements mostly cleaned, vector indexing DDL migrated. `langgraph` dependency and `VECTOR SEARCH` query syntax still missing).
- **Phase F1 (Graph Assessment)**: ~50% complete (Script audit done, Neo4j live introspection queries still need to be run and recorded).
- **Phase F2 (Curated Subset Selection)**: ~80% complete (`extract_curated_subset.py` written and `subset_selection.json` created, but CSVs not yet written).
- **Phase F3 (Fresh Graph Build)**: 0% complete.
- **Meta-Phase A (Recommendation Engine)**: 0% complete.
- **Meta-Phase B (Conversational Flow)**: 0% complete.

**End-to-End Flows**: 0/5 fully wired (blocked by Foundation graph rebuild).

---

## 2. Dependency & Integration Health

- `requirements.txt`: Cleaned up (unused legacy removed). Needs `langgraph>=1.0.0` added (GAP-011). `openai>=1.0.0` is present.
- `AgentOrchestrator`: Asyncio refactoring (GAP-001) is complete.
- Neo4j Vector API: DDL statements (`CREATE VECTOR INDEX`) migrated. Query statements (`CALL db.index.vector.queryNodes`) still present in `src/knowledge_graph/graphdb/vector_search_helper.py` (GAP-003).

---

## 3. Gap Backlog

### 🔴 Critical
* **[GAP-F1.1] Live Neo4j Introspection**
  * **Missing**: `graph_state_snapshot.md` needs exact node/embedding counts from the live Neo4j database to establish the baseline.
  * **Blocks**: Safely proceeding with F3 without understanding the current data structure.
  * **Blocked By**: Nothing.
  * **Suggested `/implement` prompt**: "Run the introspection queries from `graph_state_snapshot.md` against Neo4j and update the report."

* **[GAP-F3] Curated Graph Ingestion & Embedding Build**
  * **Missing**: Adaptation of `sample_ingest.py` (or creation of `ingest_curated.py`) to load the subset CSVs into a new `kg_curated` database, apply constraints, and backfill embeddings.
  * **Blocks**: Meta-Phase A (Recommendation Engine).
  * **Blocked By**: GAP-003 (query migration), F2 completion (writing the CSVs).
  * **Suggested `/implement` prompt**: "Complete F3: write the `ingest_curated.py` script to ingest the curated subset CSVs into `kg_curated`, and run `backfill_embeddings.py`."

### 🟠 High
* **[GAP-003] Deprecated Neo4j Vector Query API**
  * **Missing**: `src/knowledge_graph/graphdb/vector_search_helper.py` uses deprecated `CALL db.index.vector.queryNodes()`. Must migrate to Cypher 25 `VECTOR SEARCH`.
  * **Blocks**: F3 Vector Index verification, Meta-Phase A hybrid search.
  * **Blocked By**: Nothing.
  * **Suggested `/implement` prompt**: "Migrate `vector_search_helper.py` to use Cypher 25 `VECTOR SEARCH` instead of the deprecated `db.index.vector.queryNodes()`."

* **[GAP-F2] Extract Curated CSVs**
  * **Missing**: `extract_curated_subset.py` extracts IDs to JSON but doesn't create the filtered `curated_reviews.csv` and `curated_products.csv`.
  * **Blocks**: F3 Graph Ingestion.
  * **Blocked By**: Nothing.
  * **Suggested `/implement` prompt**: "Update `extract_curated_subset.py` to filter the original processed CSVs and write out `curated_reviews.csv` and `curated_products.csv`."

* **[GAP-002] MemoCRS Persistence**
  * **Missing**: `InMemoryUserProfileManager` and `InMemoryHistoryManager` lose data on restart. Needs `SQLiteProfileManager` and LangGraph `SqliteSaver`.
  * **Blocks**: Persistent sessions.
  * **Blocked By**: GAP-011 (`langgraph` dependency).
  * **Suggested `/implement` prompt**: "Implement `SQLiteProfileManager` and `SQLiteHistoryManager` with LangGraph `SqliteSaver` for cross-session persistence."

### 🟡 Medium
* **[GAP-011] `requirements.txt` Hygiene (langgraph)**
  * **Missing**: `langgraph>=1.0.0` is missing from `requirements.txt`.
  * **Blocks**: GAP-002.
  * **Blocked By**: Nothing.
  * **Suggested `/implement` prompt**: "Add `langgraph>=1.0.0` to `requirements.txt`."

* **[GAP-012] CLARIFY Path Structural Deficiency**
  * **Missing**: `pending_clarification` missing from `ConversationState`.
  * **Blocks**: Proper context-aware clarification logic.
  * **Blocked By**: Nothing.

### 🔵 Low
* **[GAP-013] `ResponseGenerator` Dead Code**
  * **Missing**: `src/llm_interface/response_generator.py` is unused.
  * **Blocks**: Nothing.

---

## 4. Implementation Order Summary

| Order | Phase | Gap / Task | Description |
|-------|-------|------------|-------------|
| 1 | F0 | GAP-003 | Migrate `vector_search_helper.py` to Cypher 25 `VECTOR SEARCH`. |
| 2 | F0 | GAP-011 | Add `langgraph>=1.0.0` to `requirements.txt`. |
| 3 | F1 | GAP-F1.1 | Run Neo4j introspection queries and update snapshot. |
| 4 | F2 | GAP-F2 | Update `extract_curated_subset.py` to output CSVs. |
| 5 | F3 | GAP-F3 | Write `ingest_curated.py` and populate `kg_curated` database. |
| 6 | A | Meta-Phase A | Proceed to Recommendation Engine build (GraphSearchTool, CriticAgent, etc.) |

---

## PM Validation

*(Gap Analysis Mode / @pm-specs)*

- **Priorities Confirmation**: I confirm the priorities. We cannot build the recommendation engine (Meta-Phase A) until the `kg_curated` database exists and the deprecated Neo4j API is fixed.
- **Architectural consistency**: The order strictly enforces Foundation before Meta-Phase A, aligning with the two-axis build strategy in the Vision Report.
- **Next Sprint**:
  1. Fix `vector_search_helper.py` (GAP-003).
  2. Complete the curated CSV extraction (GAP-F2) and ingestion (GAP-F3).
