# Thesis Contribution 4: Progressive Relaxation & Soft-Scored Hybrid Graph Retrieval

**Document ID**: `4-doc-hybrid-scoring`  
**Date**: 2026-09-29  
**Status**: Confirmed Master's Thesis Contribution  
**Git Scope**: `Meta_Phase_A_Execution_Plan.md` (4-Pillar Remediation Blueprint)  
**Relevant Modules**: `src/tools/graph_search_tool.py`, `src/agents/critic_agent.py`, `src/llm_interface/preference_parser.py`  

---

## Correction Note (2026-10-19, Thesis Evaluator)

The text below is kept as written on 2026-09-29. It was not rewritten. Sources: Vision decisions 2026-10-19-018 and 2026-10-19-021 (items 1 and 4), `production_artifacts/Research_Report_Graph_Rebuild.md` (Problem Statement), and `13-doc-graph-integrity.md`.

**C-1. Numeric soft and hard specifications never ran on live data.** No `Attribute` node carries `numeric_value`, and attributes hold only Material, Color, Style and Size (Vision 2026-10-19-021 item 4). The "EAV Unit Trap" probes in §4.2 therefore exercise parsing code in unit tests only. On the live graph, the $\sum w_i S_{attr_i}$ term of §3.2 can match only colour, material, style and size values, not "target technical specs". Constraint relaxation widening of numeric constraints is effective for price only, because price is the only numeric field the graph holds.

**C-2. The NaN protection admitted ghost products.** The hard boundary `price IS NULL OR price <= $price_max` is satisfied by all 104,281 v1 ghost products (no title, price or category), and also by titled products without a price. Whether ghosts reached a reported top-K was not measured. Category filtering excludes them, because ghosts have no category, but any path without a category filter does not. Graph v2 removes ghosts at construction (Vision 2026-10-19-018). The deliberate NaN protection for titled products without a price is unchanged.

**C-3. Graph version.** No retrieval figure is reported in this document. Any later figure for this mechanism must state whether it was measured on graph v1 or v2.

**C-4. Honest Nomenclature: Constraint Relaxation vs. MACS/MACR (Review E.5, 2026-10-22).** The relaxation mechanism in `GraphSearchTool` was previously labeled with pseudo-acronyms like "MACS" or "MACR" and cited with placeholder references. In reality, it is a deterministic heuristic constraint relaxation cascade (relaksacja ograniczeń: budget widening by 15% $\to$ taxonomic generalization via `Taxon [:BROADER]` $\to$ category drop), not a formal external algorithm.

---

## 1. Formal Research Context

### 1.1 Academic Problem Statement
In Conversational Recommender Systems (CRS) backed by Knowledge Graphs, translating extracted natural language preferences directly into strict Boolean database queries (e.g., Cypher `WHERE` clauses) introduces catastrophic structural brittleness known as the "Recall Cliff." Empirical analysis shows that strict conjunctive constraints ($C_1 \land C_2 \land \dots \land C_n$) frequently yield zero results due to trivial ontological mismatches (e.g., `toFloat("144Hz")` yielding `NULL`), NaN anomalies in numerical data (e.g., flagship products lacking explicit price data), and semantic substring contamination (e.g., third-party compatibility titles). 

### 1.2 Formal Research Question (RQ)
$$\mathbf{RQ_4}: \text{"To what extent does decoupling natural language preferences into 'hard boundaries' (Boolean) and 'soft preferences' (additive scoring), combined with progressive constraint relaxation, improve candidate yield and Recall@K compared to monolithic Boolean Cypher filtering?"}$$

### 1.3 Hypotheses
* **$\mathbf{H_1}$ (Alternative Hypothesis)**: Implementing an explicit constraint taxonomy with in-memory additive soft-scoring and hierarchical constraint relaxation (relaksacja ograniczeń) significantly reduces zero-candidate retrieval failures and increases overall $HitRate@K$ without compromising preference groundedness.
* **$\mathbf{H_0}$ (Null Hypothesis)**: Progressive relaxation and soft scoring do not yield a statistically significant improvement in retrieval success rates compared to strict Boolean graph constraints.

---

## 2. State-of-the-Art Gap Analysis

### 2.1 Limitations of Current Literature
Current frameworks for GraphRAG and LLM-driven recommendation often adopt monolithic Text-to-Cypher translations or inject all constraints into a single SQL/Cypher filter. This results in the over-constraining of candidate pools. While recent SOTA literature (such as DualAgent-Rec and G-CRS) highlights the necessity of constraint relaxation and dual-agent feedback, many open-source implementations still rely on rigid intersection of vector candidates and Boolean graph predicates, leading to brittle, non-recoverable search states.

### 2.2 Red Flag Defense (Novelty Justification)
* **Why this is NOT tutorial/boilerplate code**: Moving away from standard LangChain Cypher-QA chains, this contribution implements a bespoke **4-Pillar Remediation Blueprint**. It explicitly shifts negotiable dimensions out of the graph query engine and into a custom Python-based continuous additive scoring algorithm, supplemented by a deterministic constraint relaxation waterfall.
* **Core Scientific Contribution**: A robust hybrid retrieval architecture that enforces non-negotiable boundaries at the database layer while optimizing for maximum semantic recall via additive scoring and programmatic hierarchical constraint relaxation at the application layer.

---

## 3. Architecture & Algorithmic Formulation

### 3.1 Architectural Flow
```mermaid
flowchart TD
    A["LLM Preference Parser"] --> B["Constraint Taxonomy"]
    B --> C["Hard Boundaries (Cypher WHERE)"]
    B --> D["Soft Preferences (Memory)"]
    C --> E["Multi-Index Vector Search (ANN)"]
    E --> F["Additive Scoring Function"]
    D --> F
    F --> G{"Candidate Yield < 3?"}
    G -- YES --> H["Hierarchical Constraint Relaxation Waterfall"]
    H --> C
    G -- NO --> I["CriticAgent Semantic Arbitration"]
    I --> J["Final Grounded Top-K Selection"]
```

### 3.2 Formal Specifications & Data Models
The architecture enforces a strict **Constraint Taxonomy**:
1.  **Non-Negotiable Hard Boundaries ($\mathcal{H}$)**: E.g., `budget_ceiling`, `excluded_brands`. Passed directly to Cypher.
    *   *NaN Protection*: `WHERE (node.price IS NULL OR node.price <= $price_max)`
2.  **Negotiable Soft Preferences ($\mathcal{S}$)**: E.g., target technical specs, preferred brands. Evaluated via Additive Scoring:
    *   $\mathbf{S} = S_{vec} + w_{brand} S_{brand} + w_{cat} S_{category} + \sum w_i S_{attr_i}$
3.  **Hierarchical Constraint Relaxation (relaksacja ograniczeń)**: If the candidate pool size $N < 3$, a cascading function $R(\mathcal{H}, \mathcal{S})$ progressively widens numerical constraints (e.g., $price\_max \times 1.15$), steps up the Taxon hierarchy via `[:BROADER]`, and drops unfulfilled constraints, logging the `relaxed_constraints` state for conversational transparency.

### 3.3 Key Implemented Classes & Interfaces
* `GraphSearchTool`: Refactored to separate Cypher string compilation (hard constraints) from the post-hoc additive scoring algorithm (soft constraints). Implements the relaxation recursion loop.
* `CriticAgent`: Updated to intercept `relaxed_constraints` from the retrieval engine, arbitrate semantic betrayals, and dynamically generate explicit disclosure warnings to the end-user regarding unmet preferences.

---

## 4. Empirical Instrumentation & Reproducibility

### 4.1 Evaluation Metrics
| Metric | Dimension | Target / Expected Impact |
|---|---|---|
| HitRate@K | Recommendation Quality | Eliminate 0-result retrieval failures (Recall Cliff) |
| Recoverability Rate | Conversation Quality | Increase the percentage of successful conversational turns following an over-constrained query |
| Latency | System Feasibility | Ensure the in-memory additive scoring + iterative relaxation loop operates within real-time thresholds (<1500ms) |

### 4.2 Instrumentation & Benchmarks in Code
The system includes a suite of adversarial test queries in `tests/test_graph_search_tool.py` that specifically probe the known vulnerabilities of Boolean extraction:
* **The EAV Unit Trap**: Queries containing unit-bearing strings ("144Hz").
* **Flagship NaN Liquidation**: Strict budget boundaries against null-value benchmark products (e.g., AirPods Pro).
* **Negative Keyword Contamination**: Queries requiring third-party accessories but explicitly excluding the parent brand ("no Apple").

### 4.3 Empirical Baseline Run & Results (`eval_2026-10-09_1336`)

The additive scoring architecture was evaluated on the live Neo4j catalog across $N = 21$ benchmark queries. The run is preserved in `evaluations_archive/eval_2026-10-09_1336/` (and `evaluations/eval_2026-10-09_1336/`):

| Evaluation Run | Git Commit | Strategy | HR@1 | HR@5 | HR@20 | MRR | NDCG@10 | Key Empirical Finding |
|---|---|---|---|---|---|---|---|---|
| **`eval_2026-10-09_1336`** | `2fdf251` | `hybrid` ($S_{vec}$ additive) | $0.0794$ | $0.1270$ | $0.2063$ | $0.0986$ | $0.0732$ | Additive scoring eliminated the 0-result Boolean recall cliff, but unnormalized vector score summation caused generic attribute hub bias. |

*Note*: This additive formulation serves as the `sum_legacy` control arm in later multi-channel fusion ablations (see [`10-doc-fusion-ablation.md`](./10-doc-fusion-ablation.md) and [`11-doc-evaluation-protocol.md`](./11-doc-evaluation-protocol.md)).

### 4.4 Experimental Replication Protocol
Instructions for an independent researcher to replicate the experiment:
```bash
# Execute empirical vulnerability test suite
pytest tests/test_graph_search_tool.py -k "test_relaxation or test_soft_scoring" -v

# Run end-to-end evaluation benchmark
python scripts/evaluate_retrieval.py --baseline boolean_cypher --target soft_scoring
```

---

## 5. Master's Thesis Chapter Mapping

* **Target Thesis Chapter**: Chapter 4: Hybrid Semantic-Structural Retrieval & Knowledge Representation
* **Key Claims to Make in Thesis Text**:
  1. Strict semantic-to-Boolean translation in CRS results in an unacceptably high rate of 0-result failures ("Recall Cliff") due to ontological and numerical discrepancies.
  2. A decoupled architecture (Cypher for Hard Boundaries, Additive Python Scoring for Soft Preferences) combined with Progressive Relaxation mathematically ensures candidate yield without sacrificing interpretability.
* **Suggested Baseline Comparisons**: Evaluating the new 4-Pillar architecture against a traditional Text-to-Cypher RAG baseline.
* **Related Academic Citations**: 
  - DualAgent-Rec (WWW 2026 / arXiv:2601.19121)
  - G-CRS (PAKDD 2025 / arXiv:2503.06430)
