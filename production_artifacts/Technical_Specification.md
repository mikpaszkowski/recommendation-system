# Technical Specification: Foundation F0 — Infrastructure Prerequisites

**Date**: 2026-07-11
**Author**: Product Manager Agent
**Status**: Draft — Pending Approval
**Related Research**: `/audit-state` pipeline findings (GAP-001, GAP-003, GAP-011)

## 1. Executive Summary

This specification covers the three infrastructure fixes that must be completed before any Meta-Phase A or B work can begin. These are non-functional fixes that do not add features but make the existing codebase production-ready:

1. **GAP-001** — asyncio event loop fix in `orchestrator.py` (production-breaking)
2. **GAP-003** — Neo4j deprecated `db.index.vector.*` API migration to Cypher 25 syntax (12 call sites across 5 files)
3. **GAP-011** — `requirements.txt` cleanup + `.env.example` creation

All three fixes are independent and can be implemented in parallel. None require Neo4j data or a running database to implement (though GAP-003 tests will need Neo4j).

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority | Description |
|----|------------|----------|-------------|
| FR-001 | Async orchestrator | Must | `AgentOrchestrator` must be fully async — all public and private methods that call LLM or Neo4j must be `async def` |
| FR-002 | Chainlit compatibility | Must | `orchestrator.run()` must be callable with `await` directly from Chainlit's async handler — no `cl.make_async` wrapper |
| FR-003 | Cypher 25 vector search | Must | All vector search queries must use `CALL db.index.vector.queryNodes()` → replaced with centralized helper to enable future migration |
| FR-004 | Cypher 25 index creation | Must | All index creation must use `CREATE VECTOR INDEX ... IF NOT EXISTS` DDL instead of `CALL db.index.vector.createNodeIndex()` |
| FR-005 | Clean dependencies | Must | `requirements.txt` must list only packages actually imported in `src/` |
| FR-006 | Environment documentation | Must | `.env.example` must document all required environment variables |

### 2.2 Non-Functional Requirements

| ID | Requirement | Target | Description |
|----|------------|--------|-------------|
| NFR-001 | Backward compatibility | 100% | All existing interfaces (`GraphSearchTool.search()`, `ResolverService.resolve_*()`, `AgentOrchestrator.run()`) must maintain their signatures and return types |
| NFR-002 | No data dependency | Yes | All changes must be implementable without a running Neo4j instance or dataset |
| NFR-003 | Config validation | Must | Re-enable the disabled `_validate_config()` in `Neo4jConnector` |

## 3. Architecture & Tech Stack

### 3.1 Technology Choices

No new technologies introduced. These are fixes to existing code.

| Change | Before | After |
|--------|--------|-------|
| Orchestrator | Sync methods + `asyncio.get_event_loop().run_until_complete()` | Fully async methods with `await` |
| Vector queries | Inline `CALL db.index.vector.queryNodes(...)` calls | Centralized via `build_vector_search_query()` helper for single-point future migration |
| Index creation | `CALL db.index.vector.createNodeIndex(name, label, prop, dims, metric)` | `CREATE VECTOR INDEX name IF NOT EXISTS FOR (n:Label) ON (n.prop) OPTIONS {...}` |
| requirements.txt | 30 packages, many unused (lightfm, streamlit, etc.) | Split into `requirements.txt` (active) + `requirements-legacy.txt` (archived) |

### 3.2 Integration with Existing System

No architectural changes. All modifications are within existing files, maintaining existing interfaces and return types.

## 4. Detailed Changes

### 4.1 GAP-001 — Async Orchestrator Refactor

#### [MODIFY] `src/agents/orchestrator.py`

**Current problem**: `run()` is synchronous. At line 220, `asyncio.get_event_loop()` + `loop.run_until_complete()` crashes with `RuntimeError: This event loop is already running` when called from Chainlit's async context.

**Changes**:
1. Convert `run()` → `async def run()`
2. Convert `_initialize_state()` → `async def _initialize_state()`
3. Convert `_decide_next_step()` → `async def _decide_next_step()`
4. Convert `_execute_step()` → `async def _execute_step()`
5. Convert `_generate_search_params()` → `async def _generate_search_params()`
6. Replace lines 216–228 (the asyncio block) with: `reranked_top = await self.critic_agent.evaluate_candidates(profile, candidates, attributes_map)`
7. Replace all `self.llm_handler.query(messages)` calls with `await self.llm_handler.aquery(messages)`

**Key constraint**: `CriticAgent.evaluate_candidates()` is already `async def` — so once orchestrator is async, we just `await` it directly. `SimpleLLMHandler` already has `aquery()` method.

#### [MODIFY] `src/ui/app.py`

**Current problem**: Line 44 uses `cl.make_async(orchestrator.run)` to wrap the sync `run()` in an async wrapper.

**Change**: Replace `result = await cl.make_async(orchestrator.run)(...)` with `result = await orchestrator.run(...)` (direct async call).

### 4.2 GAP-003 — Neo4j Deprecated API Migration

#### Strategy: Vector Search Query Helper

Create a centralized helper function for vector search queries. This encapsulates the deprecated API in one place, making future migration to Cypher 25 `VECTOR SEARCH` a single-file change.

#### [NEW] `src/knowledge_graph/graphdb/vector_search_helper.py`

Centralized Cypher query builder for vector search. All callers use this instead of inline Cypher strings. When Neo4j 2025.x+ is confirmed, only this file needs to change.

#### [MODIFY] `src/tools/graph_search_tool.py`

Replace inline Cypher string construction at lines 108–118 and 138–147 with calls to `build_vector_search_query()`. The existing 2 `CALL db.index.vector.queryNodes()` calls (lines 109, 139) will use the helper.

#### [MODIFY] `src/knowledge_graph/graphdb/resolver_service.py`

Replace inline Cypher at lines 33–38 (`resolve_brand`), 66–71 (`resolve_attribute`), 100–105 (`resolve_category`) with calls to `build_vector_search_query()`. The existing 3 `CALL db.index.vector.queryNodes()` calls will use the helper.

#### [MODIFY] `src/knowledge_graph/graphdb/create_vector_indexes.cypher`

Replace all 3 `CALL db.index.vector.createNodeIndex(...)` lines with Cypher 25 DDL + add attribute index:

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

#### [MODIFY] `src/knowledge_graph/graphdb/setup_indexes.py`

Simplify: since `CREATE VECTOR INDEX ... IF NOT EXISTS` is idempotent, remove the `SHOW INDEXES` pre-check logic (lines 51–58). Just execute each statement directly.

#### [MODIFY] `src/knowledge_graph/graphdb/create_indexes.py`

Replace 2 `CALL db.index.vector.createNodeIndex()` calls (lines 20, 29) with `CREATE VECTOR INDEX` DDL.

#### [MODIFY] `src/knowledge_graph/graphdb/backfill_category_embeddings.py`

Replace 1 `CALL db.index.vector.createNodeIndex()` call (line 134) with `CREATE VECTOR INDEX` DDL.

### 4.3 GAP-011 — Requirements & Environment

#### [MODIFY] `requirements.txt`

Keep only packages actually imported in `src/`. Pin `openai>=1.0.0` (not `>=0.27.0`). Add `pytest-asyncio`. Add `pydantic>=2.0.0`.

#### [NEW] `requirements-legacy.txt`

Archive removed packages: `lightfm`, `scikit-surprise`, `fastapi`, `uvicorn`, `streamlit`, `openpyxl`, `joblib`, `requests`, `pyabsa`.

#### [NEW] `.env.example`

Document all required env vars: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `OPENAI_API_KEY`, `ENABLE_GRAPH_RETRIEVAL`.

### 4.4 Bonus — Neo4j Connector Validation Fix

#### [MODIFY] `src/knowledge_graph/graphdb/neo4j_connector.py`

Re-enable the disabled `_validate_config()` call at line 62–63. Remove `#TODO TEMPORARY DISABLED` comment and uncomment the call.

## 5. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-001 | `orchestrator.run()` is `async def` and can be awaited | Code inspection |
| AC-002 | No `asyncio.get_event_loop()` or `run_until_complete()` anywhere in `src/` | `grep` search |
| AC-003 | No `cl.make_async` in `app.py` | Code inspection |
| AC-004 | No `CALL db.index.vector.createNodeIndex` anywhere in `src/` | `grep` search |
| AC-005 | All vector search queries centralized via helper | Code inspection |
| AC-006 | `requirements.txt` contains only packages imported in `src/` | Cross-reference |
| AC-007 | `.env.example` exists with all required variables documented | File exists |
| AC-008 | `openai>=1.0.0` in requirements (not `>=0.27.0`) | Version check |
| AC-009 | `pytest-asyncio>=0.21.0` in requirements | Present |
| AC-010 | `Neo4jConnector._validate_config()` is called (not commented out) | Code inspection |
| AC-011 | `requirements-legacy.txt` exists with archived packages | File exists |

## 6. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Neo4j version doesn't support `CREATE VECTOR INDEX` DDL | High | Low | DDL is supported since Neo4j 5.11; our requirement is `>=5.14.0` |
| Existing tests rely on sync orchestrator | Medium | Medium | Update test calls to use `pytest-asyncio` |
| `vector_search_helper.py` query format differs from handwritten queries | Low | Low | Unit test each query format against expected Cypher string |
