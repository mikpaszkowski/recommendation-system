# Technical Specification: Release R3.1 — Attribute IDF Weighting (RS-03), Graded Taxonomic Distance (RS-10), and Adaptive Filter-First Order (RS-07)

**Document Version**: 1.0.0  
**Date**: 2026-10-21  
**Author**: @pm-specs (Product Manager — Spec Writer)  
**Status**: Approved for Implementation  
**Canonical Vision Reference**: `production_artifacts/Vision_Report.md` (Decision 2026-10-21-025)  
**Implementation Tasks**: `RS-03`, `RS-10`, `RS-07` from `production_artifacts/Implementation_Plan.md`

---

## 1. Executive Summary & Scope

Following Stage 1 (`GV2-07` .. `GV2-09`), the retrieval engine achieved statistically significant recall improvements ($HR@20$ jumped from $0.2286$ to $0.3333$, $p = 0.0010$). However, error analysis revealed three remaining architectural limitations:
1. **Attribute Channel Frequency Distortion (`RS-03`)**: High-degree generic attributes (e.g. `Color=Black` with 44,265 products) created massive tie blocks in Reciprocal Rank Fusion, dominating the channel over rare technical specifications.
2. **Binary Category Cliff (`RS-10`)**: The category filter operated strictly pass/fail, treating sibling categories (e.g., `Floorstanding Speakers` vs `Bookshelf Speakers`) identically to distant accessory traps (e.g., `Speaker Wall Mounts`).
3. **Selective Subtree Starvation (`RS-07`)**: For long-tail categories ($< 500$ products in Graph v2), global vector ANN search risked candidate starvation prior to Cypher filtering.

Release R3.1 delivers the algorithmic enhancements resolving these bottlenecks.

---

## 2. Component Design & Architecture

### 2.1 Component 1: Attribute Channel Normalized IDF Weighting (`RS-03`)
In `GraphSearchTool._build_channel_query(channel="attribute", where_str)`:
1. Calculate the degree $\text{deg} = \text{count of products connected to the attribute node}$.
2. Weight raw cosine similarity using normalized Inverse Document Frequency (IDF):
   $$\text{similarity}_{\text{IDF}} = \text{score} \times \frac{\log(1.0 + N / (1.0 + \text{deg}))}{\log(1.0 + N)}$$
   where $N = 265,307$ (total catalog products in Graph v2).
3. MaxP Cypher Query:
   ```cypher
   CALL db.index.vector.queryNodes('attribute_embedding_index', $k, $vector)
   YIELD node AS hit, score AS score
   MATCH (node:ParentProduct)-[:HAS_ATTRIBUTE]->(hit)
   {where_line}
   WITH node, hit, score, count { (:ParentProduct)-[:HAS_ATTRIBUTE]->(hit) } AS deg
   WITH node, score * (log(1.0 + 265307.0 / (1.0 + deg)) / log(265308.0)) AS weighted_score,
        'Attribute Match: ' + coalesce(hit.attribute_name, '') + '=' + coalesce(hit.attribute_value, '') + ' [deg=' + toString(deg) + ']' AS reason
   ORDER BY weighted_score DESC, reason ASC
   WITH node, max(weighted_score) AS similarity, head(collect(reason)) AS reason
   RETURN node.parent_asin AS asin, similarity, reason
   ORDER BY similarity DESC, asin ASC
   LIMIT $depth
   ```

---

### 2.2 Component 2: Graded Category Distance (`RS-10`)
1. **Lineage Retrieval in `DETAIL_QUERY`**:
   Extend `DETAIL_QUERY` to fetch the primary taxon path:
   ```cypher
   DETAIL_QUERY = """
   MATCH (node:ParentProduct) WHERE node.parent_asin IN $asins
   OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
   OPTIONAL MATCH (node)-[:IN_TAXON]->(t:Taxon)
   OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
   WITH node, b, collect(DISTINCT t.name) AS taxa, collect(DISTINCT t.path) AS taxon_paths, collect(DISTINCT c.name) AS cats
   RETURN node.parent_asin AS asin, node.title AS title, node.price AS price, b.name AS brand,
          CASE WHEN size(taxa) > 0 THEN taxa ELSE cats END AS category,
          head(taxon_paths) AS primary_taxon_path,
          elementId(node) AS id,
          node.features AS features, node.details_text AS details_text,
          node.description AS description, node.avg_rating AS avg_rating
   """
   ```

2. **Topological Tree Distance Computation**:
   Implement static methods in `GraphSearchTool`:
   - `_compute_taxon_distance(target_path: Sequence[str], candidate_path: Sequence[str]) -> int`:
     Calculates hops up to the longest common prefix (LCP) plus hops down to candidate.
   - `_get_taxon_distance_multiplier(distance: int) -> float`:
     - Distance 0 (Exact leaf / descendant) $\to 1.00$
     - Distance 1–2 (Sibling sharing immediate parent) $\to 0.85$
     - Distance 3–4 (Cousin sharing grandparent) $\to 0.70$
     - Distance $\ge 5$ (Distant branch / out-of-domain) $\to 0.20$

3. **Score Rescaling in `_execute_fused_search`**:
   When a category filter is active and resolved to `target_path`:
   Scale fused candidate score:
   $$\text{score}_{\text{final}} = \text{score}_{\text{fused}} \times \text{multiplier}_{\text{distance}}$$
   Record `taxon_proximity: {"distance": d, "multiplier": m}` in candidate metadata and re-sort candidates.

---

### 2.3 Component 3: Adaptive Filter-First Order (`RS-07`)
In `GraphSearchTool._execute_hybrid_search`:
1. Check `Taxon.product_count` for the resolved category.
2. If `product_count` is known and $1 \le \text{product\_count} \le 500$:
   - Trigger `_execute_filter_first_search`:
     - Query Cypher to fetch all candidates in the Taxon subtree ($\le 500$ products) matching hard filters (price, brand) along with `p.embedding`.
     - In Python, compute vector dot product and full-text match against `query_vector` and query text.
     - Rank candidates directly.
   - If candidate yield $< 3$, fall back seamlessly to standard MACS relaxation.
3. If `product_count > 500`: continue with standard ANN-first search with dynamic oversampling.

---

## 3. Acceptance Criteria & Test Plan

| ID | Criterion | Verification Method |
|---|---|---|
| **AC-R3.1-01** | Attribute MaxP query computes degree-based IDF weighting, scaling down `Color=Black` while preserving high similarity for rare attributes | `tests/test_r3_1_retrieval_refinements.py` asserting degree calculation and IDF scaling |
| **AC-R3.1-02** | `_compute_taxon_distance` correctly identifies distances: 0 for exact leaf, 2 for siblings, 3 for cousins, $\ge 5$ for distant | Unit tests comparing known taxonomy paths |
| **AC-R3.1-03** | Fused candidate scores scale by `_get_taxon_distance_multiplier` ($1.00 \to 0.85 \to 0.70 \to 0.20$), and candidate telemetry includes `taxon_proximity` | Fused search test asserting score re-ranking |
| **AC-R3.1-04** | When `product_count <= 500`, `_execute_filter_first_search` activates and retrieves all subtree products, guaranteeing zero candidate starvation | Test mocking small category subtree and verifying filter-first execution path |
| **AC-R3.1-05** | Regression test: all existing suites (`83 passed`) continue to pass without failure | `pytest` regression run |
