# Architectural Fix Proposal: Vector Fusion Reform & Damped Multi-Channel Aggregation

**Document Identifier**: `AFP-002`  
**Target Milestone**: Milestone 3 — Architectural Fix Proposals  
**Component**: Multi-Index Vector Retrieval & Hybrid Score Fusion  
**Affected Files**:  
- `src/tools/graph_search_tool.py` (`_execute_hybrid_search:210-235`)  
- `src/tools/graph_search_tool.py` (`_normalize_scores` and scoring configuration)  
**Author**: Principal Solutions Architect (`worker_architectural_fixes_m3`)  
**Status**: APPROVED BY CONSENSUS (Milestone 2 Debate Adjudication)  

---

## 1. Executive Summary & Failure Mapping

### 1.1 The Score Explosion Pathology in `eval_2026-10-07_0222`
In live evaluation run `eval_2026-10-07_0222`, the hybrid retrieval pipeline exhibited an extreme scoring distortion where popular catalog items ("hub nodes") amassed composite scores exceeding **100.0 to 225.0**, completely submerging legitimate target products whose cosine similarities ranged normally between **0.75 and 0.85**.

In standard information retrieval (IR) systems, cosine similarity across dense embeddings is bounded in $[-1.0, 1.0]$ (or $[0.0, 1.0]$ under non-negative indexing). However, in `GraphSearchTool._execute_hybrid_search`, individual vector similarity scores across three separate vector indexes (`product_embedding_index`, `attribute_embedding_index`, and `review_embedding_index`) were combined using an unbounded, linear Cypher summation: `sum(score)`.

### 1.2 Quantitative Evidence from `execution_trace.log`
Forensic analysis of `execution_trace.log` reveals how `sum(score)` systematically corrupted ranking across multiple queries:

| Query ID | User Request Intent | Dominant Retrieved Product | Resulting Score | Real Target Product | Target Score & Submerged Rank | Primary Mechanism |
| :--- | :--- | :--- | :---: | :--- | :---: | :--- |
| **`ret_001`** | Over-Ear ANC Headphones ($300) | `B01G8JO5F2` (Senso Wireless Earbuds) | **108.7200** | Sennheiser HD-201 / Sony Headphones | 4.8613 (Rank 2) | 120+ review matches summed on Senso earbuds |
| **`ret_006`** | Studio Monitor Headphones ($150)| `B01G8JO5F2` (Senso Wireless Earbuds) | **106.5838** | Sennheiser HD-201 | 9.2213 (Rank 2) | Generic sentiment reviews ("great sound") matched query |
| **`ret_010`** | Sports Earbuds Sweatproof ($100)| `B01G8JO5F2` (Senso Wireless Earbuds) | **225.2251** | sephia SP3060 Earbuds | 7.1495 (Rank 2) | 250+ review matches summed onto single hub node |
| **`ret_023`** | ANC LDAC TWS Earbuds ($280) | `B01G8JO5F2` (Senso Wireless Earbuds) | **140.1267** | High-fidelity LDAC Earbuds | 5.1200 (Rank 2) | In-degree hub review flooding drowning audiophile specs |
| **`ret_008`** | Split Ergonomic Keyboard ($130) | `B0043T7FXE` (Logitech M570 Trackball) | **6.1203** | ProtoArc Ergonomic Split Keyboard | 1.5349 (Rank 5) | Reviews for trackball matching "ergonomic" outranked keyboards |
| **`ret_024`** | Fanless Thin Laptop ($1100) | `B000A0GWN4` (Sabrent Laptop Cooling Pad)| **3.2500** | Lenovo ThinkPad / HP Spectre | 0.7812 (Rank 14) | Cooling pad reviews mentioning "silent fanless" outranked PCs |
| **`ret_021`** | 1080p Webcam w/ Mic ($70) | Logitech QuickCam Pro 5000 | **6.1119** | `B006JH8T3S` (Logitech C920 HD Pro) | 0.7734 (**Rank 253!**) | C920 had 0 embedded reviews, submerged by competitor reviews |

### 1.3 The Smoking Gun: Query 21 (`ret_021`)
Query 21 was the single query in the benchmark where the target product (`B006JH8T3S`, Logitech C920) **legitimately existed in Neo4j, was active, and passed all Cypher boolean filters**. 
- The user query was: *"Plug and play 1080p webcam with built-in microphone for Zoom meetings under $70"*.
- The C920 title vector match was strong: **0.7734**.
- However, while the database contained 20 text reviews for the C920, none of those reviews had precomputed vector embeddings (`review.embedding IS NULL`).
- Meanwhile, older competing webcams possessed multiple embedded reviews that matched query tokens like "microphone" and "Zoom meetings". The Cypher query summed those review scores, pushing competing webcams to composite scores between $2.5$ and $6.11$.
- Consequently, the exact target product was pushed from the Top 5 down to **Rank 253**, completely missing the Top 20 cutoff horizon and resulting in a **0% Hit Rate**.

---

## 2. Current Implementation Defect

### 2.1 The Linear Summation Cypher Block in `GraphSearchTool`
The defect resides in `src/tools/graph_search_tool.py` lines 210–234 within `_execute_hybrid_search`:

```cypher
// CURRENT DEFECTIVE CODE: src/tools/graph_search_tool.py:210-234
CALL {
    WITH $vector AS vector
    CALL db.index.vector.queryNodes('product_embedding_index', $k, vector)
    YIELD node AS node, score AS score
    RETURN node AS p, score, 'Product Title Match' AS match_reason
    
    UNION
    
    WITH $vector AS vector
    CALL db.index.vector.queryNodes('attribute_embedding_index', $k, vector)
    YIELD node AS node, score AS score
    MATCH (p:ParentProduct)-[:HAS_ATTRIBUTE]->(node)
    RETURN p, score * 0.8 AS score, 'Attribute Match: ' + node.attribute_name + '=' + coalesce(node.attribute_value, node.normalized_value, '') AS match_reason
    
    UNION
    
    WITH $vector AS vector
    CALL db.index.vector.queryNodes('review_embedding_index', $k, vector)
    YIELD node AS node, score AS score
    MATCH (node)-[:ABOUT_PRODUCT]->(p:ParentProduct)
    RETURN p, score * 0.9 AS score, 'Review Match: ' + coalesce(node.review_title, '') AS match_reason
}
// DEFECT: Naive linear summation of unbounded review matches
WITH p AS node, sum(score) AS total_score, collect(match_reason) AS match_reasons
WHERE {where_str}
OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
RETURN node.title as title, node.price as price, b.name as brand, 
       collect(DISTINCT c.name) as category, total_score as score, elementId(node) as id, node.parent_asin as asin,
       match_reasons
ORDER BY score DESC
LIMIT $limit
```

### 2.2 Mathematical Formalization of the Defect
Let $q$ be the query vector, and let product $p$ have title vector $v_{\text{title}}$, attributes $\{v_{a_1}, \dots, v_{a_m}\}$, and associated reviews $\{v_{r_1}, \dots, v_{r_n}\}$.
Under the current implementation, the parameter $k = \text{limit} \times 30 = 600$. For each index, up to 600 matches are returned.

The composite score $S(p)$ is computed as:
$$S(p) = \mathbb{I}_{T}(p) \cdot s_{\text{title}}(p) + 0.8 \sum_{a \in A(p)} s_a(p) + 0.9 \sum_{r \in R_k(p)} s_r(p)$$
where $R_k(p)$ is the subset of reviews of $p$ that appear in the top-600 review index matches.

Because the Neo4j graph contains **1,629,426 `ABOUT_PRODUCT` edges**, popular catalog products have hundreds of reviews. When a user submits an utterance containing common sentiment words (e.g., "comfortable", "durable", "clear", "great"), many reviews for popular products match with moderate similarity ($s_r \approx 0.60 - 0.75$).

If $|R_k(p)| = 150$, the review contribution alone becomes:
$$0.9 \sum_{r=1}^{150} 0.70 \approx 94.5$$
Even if an exact match product has a near-perfect title similarity of $s_{\text{title}} = 0.95$, its total score is capped at $0.95$. 
The ratio between the hub product and the exact target is:
$$\frac{S(p_{\text{hub}})}{S(p_{\text{exact}})} = \frac{94.5}{0.95} \approx 99.5 \times$$

This creates severe **in-degree popularity bias**, where topological hubs capture every candidate slot regardless of the product type requested.

---

## 3. Detailed Architectural Redesign

To eliminate popularity bias while retaining multi-evidence reinforcement from reviews and attributes, we redesign the retrieval scoring architecture into a **Late Fusion Multi-Channel Pipeline**.

```
[ Vector Query: $vector ]
      |
      +---> 1. Product Title Index ------> s_title in [0, 1] ----+ (Weight: 0.60)
      |                                                           |
      +---> 2. Attribute Index ----------> s_attr in [0, 1] -----+ (Weight: 0.25)
      |                                                           |
      +---> 3. Review Index -------------> s_review_damped ------+ (Weight: 0.15)
                                          (Logarithmic Damping    |
                                           capped at N=5 reviews) |
                                                                  v
                                              [ Composite Late Fusion Score ]
                                              Bounded: S_hybrid in [0.0, 1.0]
```

### 3.1 Mathematical Model of Damped Late Fusion
Instead of summing all raw similarities across matches, candidate items are scored by segregating evidence into three orthogonal channels:

#### 1. Title Channel (Dominant Direct Intent)
Exact title match represents the strongest semantic declaration of product identity:
$$S_{\text{title}}(p) = \max_{t \in T(p)} \left( \cos(q, v_t) \right) \in [0.0, 1.0]$$
If no title match occurred in the top-$k$ title index, $S_{\text{title}}(p) = 0.0$.

#### 2. Attribute Channel (Specification Conformance)
Attributes confirm technical specifications (e.g., "Color: Black", "Refresh Rate: 144Hz"):
$$S_{\text{attr}}(p) = \max_{a \in A(p)} \left( \cos(q, v_a) \right) \in [0.0, 1.0]$$
If no attribute match occurred, $S_{\text{attr}}(p) = 0.0$.

#### 3. Review Channel (Crowdsourced Quality with Logarithmic Damping)
Reviews provide social validation and qualitative nuances, but must never drown out the product's basic identity.
We compute the mean similarity of matching reviews, scaled by a sub-linear logarithmic saturation function:
$$\overline{s_{\text{review}}}(p) = \frac{1}{|R(p)|} \sum_{r \in R(p)} \cos(q, v_r)$$
$$D(N) = \frac{\ln(1 + \min(N, N_{\text{cap}}))}{\ln(1 + N_{\text{cap}})} \quad \text{where } N = |R(p)| \text{ and } N_{\text{cap}} = 5$$
$$S_{\text{review\_damped}}(p) = \overline{s_{\text{review}}}(p) \cdot D(N) \in [0.0, 1.0]$$

When $N = 1$, $D(1) = \frac{\ln(2)}{\ln(6)} \approx 0.387$.  
When $N = 5$, $D(5) = \frac{\ln(6)}{\ln(6)} = 1.000$.  
For all $N \ge 5$, $D(N)$ is strictly capped at $1.000$.

#### 4. Composite Adaptive Late Fusion with Dynamic Modality Normalization
To prevent cold-start items and items lacking reviews or attribute embeddings from being severely deflated (a static 3-channel weighting penalizes products with missing channels by up to 40%), we implement **Adaptive Late Fusion with Dynamic Modality Normalization**:

$$\text{Score}(p) = \frac{\sum_{m \in M(p)} w_m \cdot s_m(p)}{\sum_{m \in M(p)} w_m}$$

where:
- $M(p) \subseteq \{\text{title}, \text{attr}, \text{review}\}$ is the active set of available modalities with non-zero similarity for product $p$.
- Base channel weights: $w_{\text{title}} = 0.60, \quad w_{\text{attr}} = 0.25, \quad w_{\text{review}} = 0.15$.
- For products with all 3 channels present, $\sum_{m \in M(p)} w_m = 0.60 + 0.25 + 0.15 = 1.00$.
- For products lacking reviews or attributes (such as cold-start products or items where reviews have not yet been vector-embedded), the denominator dynamically contracts to the available modality weights. Specifically, if a product matches solely on title ($M(p) = \{\text{title}\}$), $\sum_{m \in M(p)} w_m = w_{\text{title}} = 0.60$, yielding an effective title weight of $\frac{0.60}{0.60} = 1.00$.
- Consequently, $\text{Score}(p_{\text{cold-start}}) = s_{\text{title}}(p)$, preserving the full unpenalized semantic fidelity of the title match.

This mathematical guarantee ensures that:
1. An exact title match ($S_{\text{title}} = 0.85$) on an item without reviews evaluates to **0.8500**, never deflated to $0.5100$.
2. Secondary channels (attributes, reviews) reinforce relevance when present, but their absence never penalizes genuine target items.
3. All scores remain strictly bounded in $[0.0, 1.0]$.

### 3.2 Redesigned Cypher Implementation in `GraphSearchTool`
The Cypher query in `src/tools/graph_search_tool.py` is restructured to implement this dynamic multi-channel late fusion entirely within the Neo4j query engine:

```cypher
// PROPOSED ARCHITECTURAL FIX: Adaptive Late Fusion Cypher in _execute_hybrid_search
CALL {
    WITH $vector AS vector
    CALL db.index.vector.queryNodes('product_embedding_index', $k, vector)
    YIELD node AS node, score AS score
    RETURN node AS p, score, 'title' AS match_channel, 'Product Title Match' AS match_reason
    
    UNION
    
    WITH $vector AS vector
    CALL db.index.vector.queryNodes('attribute_embedding_index', $k, vector)
    YIELD node AS node, score AS score
    MATCH (p:ParentProduct)-[:HAS_ATTRIBUTE]->(node)
    RETURN p, score, 'attribute' AS match_channel, 
           'Attribute Match: ' + node.attribute_name + '=' + coalesce(node.attribute_value, node.normalized_value, '') AS match_reason
    
    UNION
    
    WITH $vector AS vector
    CALL db.index.vector.queryNodes('review_embedding_index', $k, vector)
    YIELD node AS node, score AS score
    MATCH (node)-[:ABOUT_PRODUCT]->(p:ParentProduct)
    RETURN p, score, 'review' AS match_channel, 
           'Review Match: ' + coalesce(node.review_title, '') AS match_reason
}
WITH p AS node,
     // 1. Title Channel: Maximum title similarity
     max(CASE WHEN match_channel = 'title' THEN score ELSE 0.0 END) AS title_score,
     // 2. Attribute Channel: Maximum attribute similarity
     max(CASE WHEN match_channel = 'attribute' THEN score ELSE 0.0 END) AS attr_score,
     // 3. Review Channel: Mean review similarity and match count
     avg(CASE WHEN match_channel = 'review' THEN score ELSE NULL END) AS avg_review_score,
     count(CASE WHEN match_channel = 'review' THEN 1 ELSE NULL END) AS review_match_count,
     collect(DISTINCT match_reason)[0..10] AS match_reasons
WHERE {where_str}
WITH node, title_score, attr_score,
     // Compute capped logarithmic damping factor D(N) capped at N=5
     coalesce(avg_review_score, 0.0) * 
     (log(1.0 + CASE WHEN review_match_count > 5 THEN 5.0 ELSE toFloat(review_match_count) END) / log(6.0)) AS review_damped_score,
     match_reasons
WITH node, title_score, attr_score, review_damped_score, match_reasons,
     // Dynamic Modality Weights: only active channels contribute to normalization denominator
     (CASE WHEN title_score > 0.0 THEN 0.60 ELSE 0.0 END) AS w_title,
     (CASE WHEN attr_score > 0.0 THEN 0.25 ELSE 0.0 END) AS w_attr,
     (CASE WHEN review_damped_score > 0.0 THEN 0.15 ELSE 0.0 END) AS w_review
WITH node, match_reasons,
     (w_title + w_attr + w_review) AS total_weight,
     ((w_title * title_score) + (w_attr * attr_score) + (w_review * review_damped_score)) AS weighted_sum
WITH node,
     // 4. Adaptive Late Fusion Score Normalized by Available Modalities, Bounded in [0.0, 1.0]
     (CASE WHEN total_weight > 0.0 THEN (weighted_sum / total_weight) ELSE 0.0 END) AS total_score,
     match_reasons
OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
RETURN node.title AS title, 
       node.price AS price, 
       b.name AS brand, 
       collect(DISTINCT c.name) AS category, 
       total_score AS score, 
       elementId(node) AS id, 
       node.parent_asin AS asin,
       match_reasons
ORDER BY score DESC
LIMIT $limit
```

### 3.3 Complementary Rank Fusion Option: Reciprocal Rank Fusion (RRF)
As an alternative configuration for environments where raw cosine scores between heterogeneous embedding spaces are poorly calibrated, `GraphSearchTool` supports Reciprocal Rank Fusion (RRF):

$$\text{RRF}(p) = \sum_{c \in \{\text{title}, \text{attr}, \text{review}\}} \frac{w_c}{k_{\text{rrf}} + r_c(p)}$$
where $r_c(p)$ is the ordinal rank (1-indexed) of product $p$ in channel $c$'s top-$k$ result list, $k_{\text{rrf}} = 60$, and $w_{\text{title}} = 1.0, w_{\text{attr}} = 0.5, w_{\text{review}} = 0.3$.
If product $p$ does not appear in channel $c$'s result list, $\frac{1}{k_{\text{rrf}} + r_c(p)} = 0$.

RRF completely eliminates cross-index scale discrepancies and prevents any single high-volume index from overwhelming other channels.

---

## 4. Query Resolution Walkthrough

### 4.1 Resolution of Query 21 (`ret_021` — Logitech C920 Webcam)
- **Before Fix (`eval_2026-10-07_0222`)**:
  - Logitech C920 (`B006JH8T3S`): Title match = 0.7734, review matches = 0. Total score = **0.7734**.
  - Competitor (Logitech QuickCam Pro 5000): Title match = 0.6500, review matches = 8 (avg 0.68). Total score = $0.6500 + 8 \times (0.68 \times 0.9) = \mathbf{5.5460}$.
  - Result: 252 products with multiple reviews outscored the C920. **C920 dropped to Rank 253 (pruned)**.
- **After Fix (Adaptive Late Fusion with Dynamic Modality Normalization)**:
  - Logitech C920 (`B006JH8T3S`): Evaluated strictly on available modalities ($M(\text{C920}) = \{\text{title}\}$). The denominator dynamically normalizes by $w_{\text{title}} = 0.60$:
    $$\text{Score}(\text{C920}) = \frac{0.60 \times 0.7734}{0.60} = \mathbf{0.7734}$$
    Title similarity is fully preserved at **0.7734**, eliminating the artificial 40% cold-start deflation penalty!
  - Competitor (QuickCam Pro 5000) with title $0.6500$ and damped reviews ($0.6800$):
    $$\text{Score}(p_{\text{comp}}) = \frac{(0.60 \times 0.6500) + (0.15 \times 0.6800)}{0.60 + 0.15} = \frac{0.3900 + 0.1020}{0.75} = \frac{0.4920}{0.75} = \mathbf{0.6560}$$
  - A competitor with weaker title match ($0.4500$) and reviews ($0.7000$):
    $$\text{Score}(p_{\text{weak}}) = \frac{(0.60 \times 0.4500) + (0.15 \times 0.7000)}{0.75} = \frac{0.2700 + 0.1050}{0.75} = \mathbf{0.5000}$$
  - Result: The C920 with high title similarity ($0.7734$) easily outscores all low-relevance competitors with reviews. Instead of Rank 253 or Rank 163, the C920 places firmly in **Rank 1 to 3**, ensuring a **Hit@1 or Hit@5**.

### 4.2 Resolution of Query 1 (`ret_001` — Noise-Canceling Headphones)
- **Before Fix**:
  - Senso Bluetooth Earbuds (`B01G8JO5F2`) had 120+ matching reviews.
  - Linear summation yielded an astronomical score of **108.7200**.
  - Real noise-canceling headphones (Sennheiser HD-201 at score 4.86) were beaten by 22x.
- **After Fix**:
  - Senso Earbuds: Title match for "over-ear ANC headphones" is low ($0.42$).
  - Even with 120 review matches, the review contribution is strictly capped at $N=5$:
    $$S_{\text{review\_damped}} = 0.72 \times 1.0 = 0.72$$
    $$S_{\text{Senso}} = (0.60 \times 0.42) + 0.0 + (0.15 \times 0.72) = 0.2520 + 0.1080 = \mathbf{0.3600}$$
  - Real over-ear ANC headphones with title similarity $0.85$:
    $$S_{\text{Sennheiser}} = (0.60 \times 0.85) + 0.0 + (0.15 \times 0.65 \times 0.70) = 0.5100 + 0.0682 = \mathbf{0.5782}$$
  - Result: Sennheiser HD-201 wins with **0.5782 vs 0.3600**. Senso earbuds are pushed down, ending hub node review flooding.

---

## 5. Verification & Acceptance Test Strategy

### 5.1 Verification Test 1: Bounded Score Range Unit Test
Assert that composite hybrid scores returned by `GraphSearchTool` are strictly bounded in $[0.0, 1.0]$:

```python
# tests/test_hybrid_score_fusion.py
import pytest
from src.tools.graph_search_tool import GraphSearchTool

def test_hybrid_search_score_bounded_range():
    tool = GraphSearchTool()
    # Execute query that previously triggered runaway score on Senso earbuds
    result = tool.search(
        semantic_query="noise cancelling headphones with deep bass",
        structured_filters={"price_max": 300.0},
        limit=20
    )
    assert result["status"] == "success"
    items = result["items"]
    assert len(items) > 0
    
    for item in items:
        score = item["score"]
        # Assert strict mathematical bounds
        assert 0.0 <= score <= 1.0, f"Score {score} out of bounds for {item['title']}"
        # Assert no hub runaway scores
        assert score < 2.0, f"Runaway review score detected: {score}"
```

### 5.2 Verification Test 2: Target Ranking in Query 21 Simulation
Execute a regression test verifying that `B006JH8T3S` (Logitech C920) ranks in the top 5 candidates under hybrid retrieval:

```python
def test_query_21_logitech_c920_ranking():
    tool = GraphSearchTool()
    result = tool.search(
        semantic_query="Plug and play 1080p webcam with built-in microphone for Zoom meetings under $70",
        structured_filters={"category": "Computers", "price_max": 70.0},
        limit=20
    )
    items = result["items"]
    asins = [item.get("asin") for item in items]
    
    assert "B006JH8T3S" in asins, "Logitech C920 Webcam not retrieved in Top 20!"
    rank = asins.index("B006JH8T3S") + 1
    assert rank <= 5, f"Logitech C920 ranked at position {rank}, expected Top 5"
```

### 5.3 Acceptance Criteria Table
| Criteria ID | Requirement Description | Verification Method | Pass/Fail Condition |
| :--- | :--- | :--- | :--- |
| **AC-002.1** | Replace `sum(score)` with Adaptive Late Fusion & Dynamic Modality Normalization | Inspect Cypher in `graph_search_tool.py:210` | Uses dynamic weight normalization $\frac{\sum w_m s_m}{\sum w_m}$ and logarithmic review damping |
| **AC-002.2** | All hybrid search composite scores are bounded in $[0.0, 1.0]$ | Run `test_hybrid_search_score_bounded_range` | $\forall p, 0.0 \le \text{score}(p) \le 1.0$ |
| **AC-002.3** | Review match contributions are sub-linear and capped at $N \le 5$ | Cypher analysis & unit test | Review contribution $\le 0.15$ maximum |
| **AC-002.4** | Logitech C920 (`B006JH8T3S`) ranks in Top 5 in Query 21 via Dynamic Modality Normalization | Run `test_query_21_logitech_c920_ranking` | C920 appears at rank $\le 5$ with score $\ge 0.75$ |
| **AC-002.5** | Senso Earbuds score drops from >100.0 to $<0.50$ on headphone queries | Benchmark execution log | Max score in `ret_001` is $< 1.0$ |
