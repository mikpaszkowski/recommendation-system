# Research Report: Vision Staleness Assessment

**Date**: 2026-07-05
**Requested by**: /audit-state pipeline — Phase 1 Vision Staleness Check
**Status**: Pending Approval

---

## Executive Summary

The project Vision Report remains strategically sound and coherent — its core architectural bets (Multi-Agent orchestration, Hybrid GraphRAG, Neo4j as combined KG + vector store, LLM grounding, Chainlit UI) are all valid and current. However, a **critical phase-alignment discrepancy** exists: the Implementation Plan still marks every Phase 2 item as `[ ]` (incomplete), while the 2026-06-21 changelog entry conclusively proves Phase 2 was fully implemented. Two technology components carry **watch-level concerns** requiring attention before Phase 3 begins: Neo4j's vector procedure API is being deprecated in favour of a native `SEARCH` clause (migration required), and `all-MiniLM-L6-v2` is no longer considered state-of-the-art for production RAG (upgrade advisable). All other core technology choices remain valid and actively maintained.

---

## Vision Alignment Check

### Phase Alignment

**Finding: MISALIGNED — Critical Discrepancy**

The Vision Report (last updated: June/July 2026) does not explicitly name a "current phase", but its Phase descriptions and the Implementation Plan together imply **Phase 1 (Data Infrastructure)** is the current focus, since the Implementation Plan marks it with `(Current Focus)`.

The 2026-06-21 changelog entry tells a completely different story. Under section **"Zaktualizowana Architektura (Faza II — obecna)"** ("Updated Architecture — Phase II — current"), it documents:

| Component | Implementation Plan Item | Changelog Status |
|---|---|---|
| `AgentOrchestrator` (Router / State Machine, LangGraph) | Phase 2 `[ ]` | ✅ Implemented |
| `CriticAgent` (Context-Aware Reranking) | Phase 2 `[ ]` | ✅ Implemented |
| `GraphSearchTool` (Hybrid Vector + Cypher) | Phase 2 `[ ]` | ✅ Implemented |
| `ProfileTool` (Extract → Quantify → Update pipeline) | Phase 2 `[ ]` | ✅ Implemented |
| `EmbeddingService` (sentence-transformers) | Phase 1/2 `[ ]` | ✅ Implemented |
| `SimpleLLMHandler` (sync + async LLM interface) | Phase 2 `[ ]` | ✅ Implemented |
| UI Chainlit (`src/ui/app.py`) | Phase 2 `[ ]` | ✅ Implemented |
| Neo4j Vector Indexes (4 indexes active) | Phase 1 `[ ]` | ✅ Implemented |

**Conclusion**: The system is at **Phase 2 (complete)** in reality, not Phase 1. The Implementation Plan is 100% stale with respect to the current project state.

**Important note on Phase 1 completion**: The changelog also notes that Phase 1 items — `product_embedding_index`, `brand_embedding_index`, `attribute_embedding_index`, `category_embedding_index` — are in active use. However, the **GraphRAG layer** (`:Chunk` nodes, `[:MENTIONS]` relations, entity linking) is explicitly listed as `❌ Nadal brakuje` (still missing). This is a Phase 1 item that remains incomplete and bridges into Phase 3 needs.

---

### Implementation Plan vs. Changelog Reality

**Items marked `[ ]` in the plan but IMPLEMENTED per changelog (2026-06-21):**

- `[ ]` Dataset Migration & Schema Mapping → **Partial**: Vector indexes are live; LLM-REDIAL migration status unclear
- `[ ]` Semantic Embedding Generation → **Done**: `EmbeddingService` + `backfill_embeddings.py` confirmed operational
- `[ ]` Vector Index Configuration → **Done**: 4 Neo4j vector indexes confirmed active
- `[ ]` Hybrid Search Tool (`GraphSearchTool`) → **Done**: HYBRID / VECTOR_ONLY / FILTER_ONLY strategies
- `[ ]` Orchestrator (Router) Agent → **Done**: `AgentOrchestrator` in `src/agents/orchestrator.py`
- `[ ]` Critic Agent → **Done**: `CriticAgent` in `src/agents/critic_agent.py`
- `[ ]` ProfileTool / Entity-Based Memory → **Partially done**: `ProfileTool` implemented; persistence is in-memory only (❌ no Redis/DB)

**Items marked `[ ]` in the plan that are GENUINELY incomplete per changelog:**

- `[ ]` Lexical Graph Construction (GraphRAG) → ❌ Confirmed missing: no `:Chunk` nodes, no `[:MENTIONS]` relations
- `[ ]` Entity-Based Memory (MemoCRS persistent store) → ❌ `ProfileManager` is in-memory only, no cross-session persistence
- `[ ]` LLM-REDIAL dataset full migration → Unclear/partial — changelog does not confirm completion
- `[ ]` All Phase 3 items → Not yet begun

---

## Technology Staleness Check

### LangGraph

**Status: ✅ CURRENT — Minor Action Required**

- **Current version**: 1.2.7 (as of July 2026)
- **Major milestone**: 1.0.0 LTS released October 2025, establishing stable semantic-versioned API
- **Core graph primitives API (state, nodes, edges)**: Stable, backward-compatible
- **Deprecation to note**: `create_react_agent` prebuilt was deprecated in favour of LangChain's `create_agent` at the 1.0 transition
- **Python requirement**: 3.10+ (verify project environment)
- **LTS support**: The 1.0 branch is LTS until at least mid-2027; old 0.4.x is in maintenance mode until Dec 2026
- **Recommendation**: Audit usage of `create_react_agent` in `src/agents/orchestrator.py`. Otherwise, no urgent changes needed.

### Neo4j Vector Indexes

**Status: ⚠️ WATCH — Migration Required Before Phase 3**

- **Critical deprecation**: `db.index.vector.queryNodes()` and `db.index.vector.queryRelationships()` were **deprecated in Neo4j 2026.04**
- **Replacement**: Native Cypher `SEARCH` clause (Cypher 25)
- **Additional changes**:
  - Old `vector-1.0` index provider deprecated → `vector-2.0` is now default
  - New native `VECTOR` data type (e.g., `VECTOR<FLOAT32>(1024)`) replaces storing embeddings as plain float lists
  - In-index filtering (vector search + predicates) now supported natively
- **Driver change**: Official Drivers v6.0+ required for native VECTOR type
- **Current project exposure**: `GraphSearchTool` uses `product_embedding_index` with what is likely the old procedure-based API — this needs to be validated and migrated before Neo4j upgrades break the system
- **Recommendation**: Before Phase 3, audit all Cypher queries in `src/tools/graph_search_tool.py` and `src/knowledge_graph/graphdb/` for `db.index.vector.queryNodes()` calls and replace with `SEARCH` clause.

### LLM-REDIAL Dataset

**Status: ✅ CURRENT — Access Process Noted**

- **Availability**: Dataset is live on GitHub (`LitGreenhand/LLM-Redial`) and actively used in 2025/2026 CRS research
- **Scale**: ~47.6k multi-turn dialogues, 482.6k utterances, multi-domain
- **Access**: Partial data available directly from repo; full dataset requires email request to authors (standard academic procedure)
- **Research standing**: Still cited and used in state-of-the-art CRS benchmarks alongside original ReDial; recent papers address its known limitations (repetition shortcuts, popularity bias) — this is an active research area that validates our dataset choice
- **Recommendation**: Confirm full dataset access has been requested/obtained. Dataset choice remains strategically correct.

### OpenAI Embeddings (`text-embedding-3-small`)

**Status: ✅ CURRENT — No Immediate Action Required**

- **Model status**: Not deprecated; actively maintained by OpenAI as of July 2026
- **Cost**: ~$0.02/1M tokens — highly economical
- **Context**: Still recommended for general-purpose English retrieval in cost-sensitive production RAG pipelines
- **Competitive landscape**: Newer alternatives exist (`text-embedding-3-large`, Gemini Embedding 2, Cohere Embed v4, BGE-M3) but none make `text-embedding-3-small` obsolete for this project's scope
- **Switching cost**: Switching would require full re-indexing of all embedded nodes — high friction, low benefit given thesis scope
- **Recommendation**: Retain `text-embedding-3-small` for thesis. If retrieval quality is insufficient during Phase 3 evaluation, consider `text-embedding-3-large` as first upgrade before exotic alternatives.

### Sentence-Transformers (`all-MiniLM-L6-v2`)

**Status: ⚠️ WATCH — Upgrade Advisable for Phase 3**

- **Model status**: Functional but **no longer considered state-of-the-art** as of 2025/2026
- **Key limitations**: 512-token context window; predates modern training techniques; consistently outperformed on MTEB benchmarks
- **Current usage in project**: `EmbeddingService` (used by `ResolverService`, `GraphSearchTool`, `BackfillService` for brand/attribute/category normalization)
- **Recommended alternatives**:
  - `BGE-M3` (BAAI) — top MTEB rankings, multilingual, multi-vector, open weights
  - `ModernBERT Embed` — architectural improvement on BERT foundations with better speed+accuracy
  - `BGE-small` — if speed/RAM constraints persist
- **Risk assessment**: The 512-token limit is unlikely to be a bottleneck for short product descriptions, brand names, and category labels. However, for Phase 3 chunk-level GraphRAG retrieval, a more capable model would improve accuracy.
- **Recommendation**: Retain for Phase 2 resolver operations (short texts, speed matters). Evaluate `BGE-M3` or `ModernBERT Embed` specifically for the Phase 3 GraphRAG chunk retrieval layer before deployment.

---

## Overall Vision Assessment

**Vision Status**: PARTIALLY STALE

**Phase Alignment**: ❌ NO — Implementation Plan is misaligned. The plan marks Phase 2 items as `[ ]` (incomplete) but the 2026-06-21 changelog confirms Phase 2 was fully implemented. The project is currently between Phase 2 (complete) and Phase 3 (not started), with one Phase 1 item (GraphRAG lexical layer) still outstanding.

**Key Finding**: The strategic vision remains fully valid, but the Implementation Plan must be updated to reflect reality — Phase 0, 1 (partial), and 2 are complete; Phase 3 is the current focus; and two technology components (Neo4j vector procedure API, `all-MiniLM-L6-v2`) require migration attention before or during Phase 3.

**Technologies requiring action:**

| Technology | Status | Action |
|---|---|---|
| Neo4j Vector Procedures (`db.index.vector.queryNodes`) | ⚠️ DEPRECATED in 2026.04 | Migrate to `SEARCH` clause (Cypher 25) before Neo4j upgrade |
| `all-MiniLM-L6-v2` | ⚠️ WATCH | Evaluate `BGE-M3` for Phase 3 chunk retrieval |
| LangGraph `create_react_agent` | ⚠️ DEPRECATED | Audit and replace with `create_agent` |

---

## Recommended Actions (Priority Order)

1. **[URGENT] Update Implementation Plan**: Mark Phase 2 items as `[x]` to reflect reality. Update "Current Focus" to Phase 3.
2. **[HIGH] Audit Neo4j vector queries**: Identify all `db.index.vector.queryNodes()` calls and plan migration to Cypher 25 `SEARCH` clause.
3. **[MEDIUM] Audit LangGraph `create_react_agent`**: Check `src/agents/orchestrator.py` for deprecated API usage.
4. **[MEDIUM] Confirm LLM-REDIAL full access**: Validate full dataset is accessible for Phase 3 evaluation.
5. **[LOW] Evaluate embedding upgrade**: Benchmark `BGE-M3` vs `all-MiniLM-L6-v2` specifically for chunk retrieval before Phase 3 GraphRAG implementation.

---

## Sources

1. LangGraph v1.2.7 — PyPI / GitHub / langchain.com official docs (July 2026)
2. LangGraph 1.0.0 release notes and migration guide — langchain.com
3. Neo4j vector deprecation (2026.04) — neo4j.com official documentation
4. Neo4j Cypher 25 / native VECTOR type — neo4j.com
5. LLM-REDIAL GitHub repository — `LitGreenhand/LLM-Redial`
6. LLM-REDIAL ACL Anthology paper — aclanthology.org
7. OpenAI Embeddings documentation — openai.com/docs/guides/embeddings
8. MTEB Leaderboard — huggingface.co/spaces/mteb/leaderboard
9. BGE-M3 model card — huggingface.co/BAAI/bge-m3
10. Sentence-Transformers all-MiniLM-L6-v2 — huggingface.co
