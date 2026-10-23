# Chapter 17: Attribute Rarity Weighting, Graded Taxonomic Proximity, and Adaptive Filter-First Routing

**Document Version**: 1.0.0  
**Date**: 2026-10-21  
**Author**: Academic Scientific Evaluator (`@thesis-evaluator`)  
**Status**: Thesis-Ready Contribution Document  
**Canonical Vision Reference**: `production_artifacts/Vision_Report.md` (Decision 2026-10-21-025)  
**Implementation Anchor**: `src/tools/graph_search_tool.py` (`RS-03`, `RS-10`, `RS-07`), `production_artifacts/Technical_Specification_R3_1.md`  
**Empirical Source**: Frozen `tuning` split ($n = 105$ queries), Graph v2 Live Neo4j instance ($N = 265,307$ products, $1,183$ taxa)

---

## 1. Abstract & Academic Context

Conversational Recommender Systems (CRS) operating over heterogeneous e-commerce knowledge graphs encounter three persistent structural failure modes during retrieval:
1. **Attribute Channel Frequency Distortion (The Hub Problem)**: High-degree generic attributes (e.g., `Color=Black`, connected to $44,265$ products, $16.68\%$ of the catalog) dominate vector ANN channels, forming massive tie-blocks in Reciprocal Rank Fusion ($RRF$) that crowd out discriminative technical specifications (e.g., `Style=Ergonomic Split Keyboard`, degree $= 1$).
2. **The Binary Category Cliff**: Conventional systems treat categorical constraints as strict boolean gates. This induces severe false negatives when user requests target narrow subcategories (e.g., classifying `Floorstanding Speakers` as a zero-score mismatch when the user requested `Bookshelf Speakers`), treating close taxonomic siblings identically to out-of-domain accessory traps (e.g., `Camera Bags`).
3. **Selective Subtree Starvation**: For long-tail categories ($|\mathcal{V}_P(\tau)| \le 500$), global vector Approximate Nearest Neighbor (ANN) search exhibits severe recall degradation because top-$K$ index pruning occurs before database graph filtering.

In this chapter, we present the mathematical formulation, algorithmic implementation, and empirical verification of **Release R3.1: Precision Refinements for GraphRAG Retrieval**, encompassing:
- Normalized Inverse Document Frequency (IDF) attribute rarity weighting ($\text{RS-03}$),
- Continuous graded taxonomic proximity scoring via Longest Common Prefix (LCP) tree distance ($\text{RS-10}$),
- Adaptive selectivity-directed filter-first routing for niche subtrees ($\text{RS-07}$).

---

## 2. Theoretical Motivation & Research Questions

### 2.1 Research Questions (RQ)

- **RQ 17.1 (Attribute Rarity and Channel Specificity)**: Can an information-theoretic inverse document frequency (IDF) formulation dynamically downweight generic high-degree attributes in a multi-channel GraphRAG pipeline without penalizing legitimate dense semantic matches?
- **RQ 17.2 (Graded Taxonomic Proximity vs. Boolean Gating)**: Does replacing binary pass/fail category filtering with a continuous, LCP-derived topological distance penalty prevent catastrophic candidate starvation while enforcing graceful degradation for sibling and cousin categories?
- **RQ 17.3 (Selectivity-Driven Retrieval Routing)**: Does adaptive filter-first routing for small taxonomy subtrees ($|\mathcal{T}| \le 500$) guarantee $100\%$ candidate subspace recall, overcoming the global vector ANN truncation bottleneck?

---

## 3. Mathematical Formulation & System Architecture

### 3.1 Attribute Channel Normalized IDF Weighting ($\text{RS-03}$)

Let $\mathcal{G} = (\mathcal{V}_P, \mathcal{V}_A, \mathcal{E}_{\text{ATTR}})$ represent the bipartite sub-graph linking parent products $p \in \mathcal{V}_P$ to attribute nodes $a \in \mathcal{V}_A$ via directed edges $(p, a) \in \mathcal{E}_{\text{ATTR}}$. Let $N = |\mathcal{V}_P| = 265,307$ denote the total catalog size.

The degree $\deg(a)$ corresponds to the document frequency of attribute node $a$:
$$\deg(a) = \left| \{ p \in \mathcal{V}_P \mid (p, a) \in \mathcal{E}_{\text{ATTR}} \} \right|$$

Standard vector search computes raw cosine similarity between query attribute embedding $\mathbf{q}_{\text{attr}}$ and attribute node embedding $\mathbf{e}_a$:
$$\text{sim}_{\text{raw}}(p, a) = \cos(\mathbf{q}_{\text{attr}}, \mathbf{e}_a)$$

To eliminate the hub dominance of common attributes, we apply a smooth, normalized Inverse Document Frequency (IDF) transformation bounded in the open interval $(0, 1]$:

$$\omega_{\text{IDF}}(a) = \frac{\ln\left(1.0 + \frac{N}{1.0 + \deg(a)}\right)}{\ln(1.0 + N)}$$

The effective MaxP similarity score for candidate product $p$ along the attribute retrieval channel is defined as:

$$S_{\text{attr}}(p) = \max_{a \in \mathcal{N}_{\text{attr}}(p)} \left( \text{sim}_{\text{raw}}(p, a) \times \omega_{\text{IDF}}(a) \right)$$

#### Quantitative Scaling Behavior:
- For generic `Color=Black` ($\deg = 44,265$):
  $$\omega_{\text{IDF}} = \frac{\ln\left(1 + \frac{265307}{44266}\right)}{\ln(265308)} = \frac{\ln(6.993)}{12.488} \approx \mathbf{0.155}$$
  (Scores are attenuated by $-84.5\%$).
- For rare `Style=Ergonomic Split Keyboard` ($\deg = 1$):
  $$\omega_{\text{IDF}} = \frac{\ln\left(1 + \frac{265307}{2}\right)}{\ln(265308)} = \frac{\ln(132654.5)}{12.488} \approx \mathbf{0.944}$$
  (Scores retain $94.4\%$ of their raw similarity).
- **Dynamic Distinction**: Rare technical specifications achieve a **$5.8\times$ to $6.1\times$ higher similarity scaling** over generic color/size hubs, resolving the RRF tie-block distortion.

In Neo4j Cypher, this is evaluated inline without auxiliary tables:
```cypher
CALL db.index.vector.queryNodes('attribute_embedding_index', $k, $vector)
YIELD node AS hit, score AS score
MATCH (node:ParentProduct)-[:HAS_ATTRIBUTE]->(hit)
WHERE {where_clauses}
WITH node, hit, score, count { (:ParentProduct)-[:HAS_ATTRIBUTE]->(hit) } AS deg
WITH node,
     score * (log(1.0 + 265307.0 / (1.0 + deg)) / log(265308.0)) AS score,
     'Attribute Match: ' + coalesce(hit.attribute_name, '') + '=' + coalesce(hit.attribute_value, '') + ' [deg=' + toString(deg) + ']' AS reason
ORDER BY score DESC, reason ASC
WITH node, max(score) AS similarity, head(collect(reason)) AS reason
RETURN node.parent_asin AS asin, similarity, reason
ORDER BY similarity DESC, asin ASC
LIMIT $depth
```

---

### 3.2 Graded Taxonomic Proximity via LCP Distance ($\text{RS-10}$)

Rather than enforcing a hard binary cutoff, we calculate the topological graph distance between the user's resolved category path $\mathbf{p}_{\text{target}}$ and candidate product's primary taxonomy lineage $\mathbf{p}_{\text{cand}}$.

Each path is an ordered sequence of taxonomy node labels from root to leaf:
$$\mathbf{p} = [ \tau_0, \tau_1, \dots, \tau_m ]$$

The Lowest Common Ancestor (LCA) is identified via the Longest Common Prefix (LCP):
$$\text{LCP}(\mathbf{p}_{\text{target}}, \mathbf{p}_{\text{cand}}) = [ \tau_0, \dots, \tau_{L-1} ] \quad \text{where } \tau_i = \tau'_i \; \forall i < L$$

The undirected shortest-path tree distance $\Delta_{\text{tax}}$ is given by:
$$\Delta_{\text{tax}}(\mathbf{p}_{\text{target}}, \mathbf{p}_{\text{cand}}) = \begin{cases}
0 & \text{if } L = |\mathbf{p}_{\text{target}}| \text{ (exact leaf or descendant)} \\
(|\mathbf{p}_{\text{target}}| - L) + (|\mathbf{p}_{\text{cand}}| - L) & \text{otherwise}
\end{cases}$$

The distance is mapped to a piecewise penalty multiplier $\mu(\Delta_{\text{tax}}) \in (0, 1]$:
$$\mu(\Delta_{\text{tax}}) = \begin{cases}
1.00 & \text{if } \Delta_{\text{tax}} = 0 \quad \text{(Exact leaf or specialization)} \\
0.85 & \text{if } 1 \le \Delta_{\text{tax}} \le 2 \quad \text{(Immediate parent or sibling)} \\
0.70 & \text{if } 3 \le \Delta_{\text{tax}} \le 4 \quad \text{(Cousin sharing grandparent)} \\
0.20 & \text{if } \Delta_{\text{tax}} \ge 5 \quad \text{(Distant branch or out-of-domain)}
\end{cases}$$

Candidate fusion scores are rescaled prior to final truncation:
$$S_{\text{final}}(p) = S_{\text{fused}}(p) \times \mu(\Delta_{\text{tax}}(\mathbf{p}_{\text{target}}, \mathbf{p}_p))$$

This guarantees that:
- Relevant products in sibling categories (e.g. `Floorstanding Speakers` vs. `Bookshelf Speakers`, $\Delta=2, \mu=0.85$) remain viable recommendation alternatives if user preferences align,
- Out-of-domain false positives (e.g. `Camera Bags`, $\Delta=6, \mu=0.20$) are heavily suppressed even if they share spurious lexical tokens or high generic vector similarity.

---

### 3.3 Adaptive Selectivity-Directed Filter-First Routing ($\text{RS-07}$)

When user intent targets a small, highly selective sub-tree ($|\mathcal{V}_P(\tau)| \le 500$), global vector ANN search suffers from catastrophic candidate starvation: top-$K$ pruning over $265,307$ products drops candidates before Cypher graph filtering evaluates them.

To guarantee $100\%$ subspace recall, the system adaptively switches execution strategy based on resolved taxon selectivity:

$$\text{Strategy} = \begin{cases}
\text{Filter-First Exact Subtree Scoring} & \text{if } 1 \le |\mathcal{V}_P(\tau)| \le 500 \\
\text{ANN-First with Dynamic Oversampling} & \text{if } |\mathcal{V}_P(\tau)| > 500
\end{cases}$$

Under Filter-First execution:
1. Cypher navigates **downwards from the target taxonomy node**:
   ```cypher
   MATCH (ancestor:Taxon)
   WHERE toLower(ancestor.name) = toLower($category_filter)
   MATCH (ancestor)<-[:BROADER*0..7]-(leaf:Taxon)<-[:IN_TAXON]-(node:ParentProduct)
   WHERE 1=1 AND ({non_category_hard_filters})
   OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
   WITH DISTINCT node, b, collect(DISTINCT leaf.name) AS taxa, collect(DISTINCT leaf.path) AS taxon_paths
   RETURN node.parent_asin AS asin, node.title AS title, node.price AS price, b.name AS brand,
          taxa AS category, head(taxon_paths) AS primary_taxon_path,
          node.features AS features, node.details_text AS details_text,
          node.description AS description, node.avg_rating AS avg_rating,
          node.embedding AS embedding
   ```
2. In Python, vector cosine similarity and full-text token matching are computed directly against the bounded candidate pool ($N \le 500$):
   $$S(p) = 0.85 \times \cos(\mathbf{q}, \mathbf{e}_p) + 0.15 \times \text{LexicalMatch}(\mathbf{q}, \text{title}_p)$$
3. **Complexity & Latency**: For `Bookshelf Speakers` ($|\mathcal{V}_P| = 237$), the entire subtree query executes in **$232.4\text{ ms}$**, yielding zero candidate starvation.

---

## 4. Empirical Verification & Verification Matrix

The implementation was systematically audited against the acceptance criteria defined in `production_artifacts/Technical_Specification_R3_1.md`:

| Criterion | Target Behavior | Empirical Result |
|---|---|---|
| **AC-R3.1-01** | Attribute MaxP query calculates degree-based IDF; suppresses generic hubs | **PASS**: Query structure verified. Math test confirms `Color=Black` factor $\approx 0.155$ vs. rare attribute $\approx 0.944$ ($5.8\times$ ratio). |
| **AC-R3.1-02** | Topological LCP distance calculation accuracy across tree tiers | **PASS**: Distance verified: exact leaf ($0$), parent ($1$), sibling ($2$), cousin ($3, 4$), distant ($6$). Multipliers map exactly ($1.00 \to 0.85 \to 0.70 \to 0.20$). |
| **AC-R3.1-03** | Fused candidate scores scale by distance multiplier and record telemetry | **PASS**: Fused test verified exact match leapfrogging distant candidate; `taxon_proximity` telemetry logged. |
| **AC-R3.1-04** | Subtree selectivity trigger ($|\mathcal{V}_P| \le 500$) activates filter-first order | **PASS**: Filter-first executes with $100\%$ candidate yield on selective categories ($N=237$) in $232\text{ ms}$. Categories $> 500$ bypass cleanly. |
| **AC-R3.1-05** | Regression testing across all pre-existing suites | **PASS**: **$65 / 65$ unit tests passed** in $12.70\text{ s}$ with zero regressions. |

### 4.2 End-to-End Live Evaluation (`eval_2026-10-22_2254`)

The combined impact of Release R3.1's attribute rarity weighting, graded taxonomic distance, and adaptive filter-first routing was evaluated in the full multi-agent conversational recommender system against live Neo4j:

* **Evaluation Run**: [`eval_2026-10-22_2254`](file:///Users/mikolajpaszkowski/recommendation-system/evaluations_archive/eval_2026-10-22_2254/README.md) (Archived, `citable: True`, commit `4fb77f7`).
* **Zero Constraint Violations**: Candidate ranking achieved strict zero constraint violation across all top-5 recommendations ($CS@5\text{ viol} = 0.000$) while maintaining $100\%$ candidate yield on selective subtrees.
* **Hub Bias Elimination**: Degree-based IDF weighting prevented generic attribute hubs (`Color=Black`) from blocking specific technical attributes, allowing 4-channel RRF (`wrrf4`) to achieve $MRR = 0.3301$ and $HR@20 = 0.5714$.

---

## 5. Master's Thesis Conclusions & Academic Significance

1. **Information-Theoretic Regularization in Knowledge Graph Retrieval**: Rather than treating graph edges as unweighted relational links, combining graph degree metrics with inverse document frequency provides an effective, domain-agnostic mechanism to overcome the hub distortion problem in conversational recommendation.
2. **Topological Soft Gating**: Discrete hierarchical taxonomies are often criticized as too rigid for conversational search. Our continuous LCP distance penalty transforms a discrete classification tree into a smooth proximity space, enabling principled trade-off ranking between category specificity and attribute relevance.
3. **Adaptive Hybrid Retrieval Architecture**: By demonstrating that retrieval routing should be dynamically governed by sub-tree candidate density ($|\mathcal{V}_P| \le 500$), this work provides a blueprint for production-grade GraphRAG systems that balance the latency advantages of vector ANN indices with the recall guarantees of structured graph queries.
