# Technical Specification: Stage 1 — Graph v2 Structural & Lexical Consumption (GV2-07 .. GV2-09)

**Document Version**: 1.0.0  
**Date**: 2026-10-20  
**Author**: @pm-specs (Product Manager — Spec Writer)  
**Status**: Pending Review / Approved for Implementation  
**Canonical Vision Reference**: `production_artifacts/Vision_Report.md` (Decision 2026-10-20-024)  
**Implementation Tasks**: `GV2-07`, `GV2-08`, `GV2-09` from `production_artifacts/Implementation_Plan.md`

---

## 1. Executive Summary & Problem Statement

### 1.1 The Context & The Recall Cliff
Release R2b introduced the stratified benchmark `benchmark_v2.json` (251 queries) and verified that while legacy queries achieved $HR@20 = 90.48\%$, queries across strata $S_0$–$S_4$ suffered a catastrophic recall cliff to $9.52\%$ across all retrieval arms (`rrf3`, `wrrf3`, `rrf2`, `cc3`, `sum_legacy`).

Empirical investigation of Neo4j logs revealed that the recall cliff was not caused by embedding quality or benchmark difficulty, but by an architectural mismatch between `GraphSearchTool` and **Graph v2**:
1. **Disconnected Category Filter**: `GraphSearchTool._build_filters` still executed Cypher matching `(:Category)-[:SUBCATEGORY_OF*0..3]->(:Category)`, relationships that do not exist on Graph v2 (`GQLSTATUS 01N42`). This caused 100% of category-filtered products to fail the graph existence clause and fall back to title token matching (`node.title CONTAINS ...`). Because benchmark queries are strictly title-blind, valid catalog products were systematically discarded.
2. **Unused 1,183-node Taxon Taxonomy**: Graph v2 contains 1,183 `:Taxon` nodes connected to products via `(:ParentProduct)-[:IN_TAXON]->(:Taxon)` and structured via `(:Taxon)-[:BROADER*1..7]->(:Taxon)`. `ResolverService.resolve_category` only knew the 38 coarse `Category` nodes, failing to resolve fine-grained product types (e.g. `Bookshelf Speakers`, `Bluetooth Network Adapters`).
3. **Unused Online Full-Text Index**: Graph v2 possesses an online Lucene index `product_fulltext_index` covering `title`, `description`, `features`, and `details_text` that is completely unconsumed during multi-channel retrieval.
4. **Destructive MACS Relaxation**: When yield $< 3$, MACS relaxation dropped the category constraint completely, rather than generalizing upward along the `[:BROADER]` hierarchy.

### 1.2 Objective & Scope
Stage 1 implements full structural and lexical consumption of Graph v2:
- **`GV2-07` (`Taxon` Resolution & Subtree Filtering)**: Migrate `ResolverService` and `GraphSearchTool` to `:Taxon`, implementing hierarchical Cypher filtering and MACS `BROADER` step-up relaxation.
- **`GV2-08` (Full-Text Lexical Channel in RRF)**: Integrate `product_fulltext_index` as channel `lexical` in `score_fusion.py` and `GraphSearchTool`, enabling `rrf4` and `wrrf4` presets.
- **`GV2-09` (Selectivity-Based Filter-Before-ANN)**: Dynamically scale vector oversampling factor `ann_k_per_limit` when subtrees are small ($< 5,000$ products) to eliminate candidate starvation.

---

## 2. Architectural Design & Component Specifications

### 2.1 Component 1: `ResolverService` (`src/knowledge_graph/graphdb/resolver_service.py`)

#### Requirements:
1. `resolve_category(text: str, k: int = 3) -> List[Dict]` must query `:Taxon` nodes instead of `:Category`.
2. **Tier 1 (Exact Match)**:
   ```cypher
   MATCH (node:Taxon)
   WHERE toLower(node.name) = toLower($text)
   RETURN node.name AS name, node.path AS path, node.product_count AS product_count, node.depth AS depth, 1.0 AS score
   LIMIT $k
   ```
3. **Tier 2 (Word-Boundary Regex Match)**:
   Match word-boundary regex on `node.name` with plural and inflection tolerance, ordering by `node.product_count DESC` to prioritize standard category hubs:
   ```cypher
   MATCH (node:Taxon)
   WHERE node.name =~ $pattern
   RETURN node.name AS name, node.path AS path, node.product_count AS product_count, node.depth AS depth, 0.85 AS score
   ORDER BY node.product_count DESC
   LIMIT $k
   ```
4. **Tier 3 (Semantic Similarity Fallback)**:
   Because `:Taxon` has exactly 1,183 nodes without precomputed database embeddings, `ResolverService` loads/caches the 1,183 taxon names and precomputes or lazy-loads their dense embeddings in memory (`(1183, 384)` matrix). Tier 3 computes dot-product cosine similarity in $< 8\text{ ms}$ on CPU, returning top-$k$ matches above `min_score`.
5. **Returned Candidate Schema**:
   Each match dictionary contains:
   `{"name": str, "path": List[str], "product_count": int, "depth": int, "score": float}`.

---

### 2.2 Component 2: `GraphSearchTool` (`src/tools/graph_search_tool.py`)

#### 2.2.1 Hierarchical Cypher Subtree Filter (`_build_filters`)
Replace the broken `(:Category)-[:SUBCATEGORY_OF*0..3]->(:Category)` clause with the Graph v2 taxonomic subtree expression:

```cypher
(
    EXISTS {
        MATCH (node)-[:IN_TAXON]->(leaf:Taxon)-[:BROADER*0..7]->(ancestor:Taxon)
        WHERE toLower(ancestor.name) = toLower($category_filter)
           OR toLower(leaf.name) = toLower($category_filter)
    }
    OR (
        NOT EXISTS { MATCH (node)-[:IN_TAXON]->(:Taxon) }
        AND {title_condition}
    )
)
```
- Matching either `leaf.name` or `ancestor.name` allows a user search for `Speakers` to match items in `Bookshelf Speakers`, and vice-versa.
- The `title_condition` is strictly quarantined: it only activates for edge-case products that have no `IN_TAXON` relationship, preventing title keyword false-positives on classified products.
- Multi-category filters (`categories`) use the corresponding `ANY(cat IN $categories_filter WHERE toLower(ancestor.name) = toLower(cat) OR toLower(leaf.name) = toLower(cat))`.

#### 2.2.2 MACS Taxonomic Relaxation via `BROADER` (`search`)
In `GraphSearchTool.search`:
When candidate count $< 3$ and `category` is present in `filters`:
1. Check if the current category has a parent Taxon in Graph v2:
   ```cypher
   MATCH (child:Taxon)-[:BROADER]->(parent:Taxon)
   WHERE toLower(child.name) = toLower($current_cat)
   RETURN parent.name AS parent_name
   LIMIT 1
   ```
2. If `parent_name` is returned:
   - Update `filters["category"] = parent_name`.
   - Record in `relaxed_constraints`: `"Broadened category filter from '{current_cat}' to parent category '{parent_name}'"`.
   - Re-execute search (`_execute_hybrid_search`).
3. If yield is still $< 3$ (or no parent exists / already at top-level category):
   - Drop category constraint (`filters.pop("category", None)`).
   - Record in `relaxed_constraints`: `"Dropped explicit category constraint (relying purely on vector search)"`.
   - Re-execute search.

#### 2.2.3 Full-Text Lexical Channel (`_build_channel_query` & `_execute_fused_search`)
1. **Query Sanitization**:
   Implement `_sanitize_lucene_query(text: str) -> str`:
   - Strip Lucene special characters: `+ - && || ! ( ) { } [ ] ^ " ~ * ? : \ / $`.
   - Extract alphanumeric search tokens and join with space.
   - If empty after sanitization, fall back to `"*"`.
2. **Channel Cypher Generation**:
   When `channel == "lexical"`:
   ```cypher
   CALL db.index.fulltext.queryNodes('product_fulltext_index', $query_text) YIELD node, score
   {where_line}
   WITH node, score, 'Fulltext Lexical Match' AS reason
   ORDER BY score DESC, reason ASC
   WITH node, max(score) AS similarity, head(collect(reason)) AS reason
   RETURN node.parent_asin AS asin, similarity, reason
   ORDER BY similarity DESC, asin ASC
   LIMIT $depth
   ```
3. **Parameter Binding**:
   In `_execute_fused_search`, pass `params["query_text"] = self._sanitize_lucene_query(text)`.

#### 2.2.4 Dynamic ANN Oversampling for Selective Subtrees (`GV2-09`)
In `_execute_fused_search`:
1. If a category filter is active, look up `product_count` for the resolved category.
2. If `product_count` is known and `product_count < 5,000`:
   - Scale `ann_k = limit * min(60, max(30, int(30 * (5000 / max(product_count, 500))))))`.
   - This ensures vector search retrieves up to 60 candidates per limit (e.g. 600 items instead of 300) before Cypher post-filtering, preventing candidate starvation on small product niches.

---

### 2.3 Component 3: `score_fusion.py` (`src/tools/score_fusion.py`)

#### Requirements:
1. Update `CHANNELS: Tuple[str, ...] = ("product", "attribute", "review", "lexical")`.
2. Add new preset arms to `FUSION_ARMS`:
   - `"rrf4"`: `FusionConfig(name="rrf4", channels=("product", "attribute", "review", "lexical"))`
   - `"wrrf4"`: `FusionConfig(name="wrrf4", channels=("product", "attribute", "review", "lexical"), weights={"product": 0.35, "attribute": 0.20, "review": 0.15, "lexical": 0.30})`
   - `"cc4"`: `FusionConfig(name="cc4", method="cc", channels=("product", "attribute", "review", "lexical"))`
   - `"lexical_only"`: `FusionConfig(name="lexical_only", channels=("lexical",), weights={"lexical": 1.0})`
3. Preserve backward compatibility: `rrf3`, `wrrf3`, `rrf2`, `cc3`, `sum_legacy` remain fully functional and unchanged.

---

## 3. Data Models & API Contracts

### 3.1 Channel Evidence & Item Schema
In `GraphSearchTool`, retrieved items retain complete channel evidence:
```json
{
  "asin": "B002AQSTXM",
  "title": "TRENDnet Low Energy Micro Bluetooth 4.0 Class I USB 2.0...",
  "price": 15.02,
  "score": 0.0483,
  "fusion": {
    "method": "rrf4",
    "channels": {
      "product": {"rank": 4, "similarity": 0.7812, "reason": "Product Title Match"},
      "attribute": {"rank": 12, "similarity": 0.6540, "reason": "Attribute Match: Color=Black"},
      "lexical": {"rank": 2, "similarity": 28.601, "reason": "Fulltext Lexical Match"}
    }
  }
}
```

---

## 4. Acceptance Criteria & Test Plan

| ID | Criterion | Verification Method |
|---|---|---|
| **AC-S1-01** | `ResolverService.resolve_category` resolves fine-grained leaf taxa (`Bookshelf Speakers`, `Bluetooth Network Adapters`, `Camera Brackets`) with score $\ge 0.70$ and returns `path` and `product_count`. | Unit tests in `tests/test_stage1_taxon_and_lexical.py`. |
| **AC-S1-02** | `GraphSearchTool._build_filters` generates Cypher matching `(:ParentProduct)-[:IN_TAXON]->(leaf:Taxon)-[:BROADER*0..7]->(ancestor:Taxon)`. Tested against live sample query (`B002AQSTXM`), matching correctly without title fallback. | Live Neo4j test query & unit tests. |
| **AC-S1-03** | MACS relaxation steps up 1 level of `BROADER` when candidate count $< 3$ before dropping the category filter entirely. | Mocked/live search relaxation test asserting `relaxed_constraints` contains `"Broadened category filter..."`. |
| **AC-S1-04** | `CALL db.index.fulltext.queryNodes` executes with sanitized Lucene queries, handling punctuation, special characters (`$`, `-`, `/`), and returning valid `ChannelHit` objects with BM25 scores. | Unit test with queries containing punctuation and dollar values. |
| **AC-S1-05** | `score_fusion.py` supports all 4 channels (`product`, `attribute`, `review`, `lexical`) across `rrf4`, `wrrf4`, `cc4` and `lexical_only` without regression on existing 3-channel arms. | `pytest tests/test_score_fusion.py tests/test_stage1_taxon_and_lexical.py`. |
| **AC-S1-06** | End-to-end evaluation on `benchmark_v2.json` (`--split tuning`) shows significant recovery in $HR@20$ on strata $S_0$–$S_4$ compared to the 9.52% baseline. | `scripts/evaluate_retrieval.py --benchmark evaluations/benchmarks/benchmark_v2.json --split tuning`. |

---

## 5. File Modification Plan

1. **`src/knowledge_graph/graphdb/resolver_service.py`**:
   - Rewrite `resolve_category` to target `:Taxon`.
   - Add in-memory embedding cache/matrix for all 1,183 taxa for Tier 3 semantic fallback.
   - Update `validate_category_candidates` to inspect Taxon hierarchy.
2. **`src/tools/graph_search_tool.py`**:
   - Update `_build_filters` for `IN_TAXON` / `BROADER` traversal.
   - Add `_sanitize_lucene_query` helper.
   - Add `lexical` channel query generation in `_build_channel_query`.
   - Update MACS relaxation in `search` to step up `BROADER`.
   - Add dynamic ANN oversampling in `_execute_fused_search`.
3. **`src/tools/score_fusion.py`**:
   - Add `"lexical"` to `CHANNELS` and define `rrf4`, `wrrf4`, `cc4`, `lexical_only`.
4. **`tests/test_stage1_taxon_and_lexical.py`**:
   - Comprehensive test suite covering Taxon resolution, Lucene sanitization, MACS step-up, 4-channel fusion, and Cypher generation.
