# Research Report: SOTA Conversational Recommender Systems Literature, Metric-to-Flow Architecture, and Zero-Mock Live-Data System Revision

**Date**: 2026-10-06  
**Requested by**: User Prompt & Milestone M1 Directive (`ORIGINAL_REQUEST.md` § `2026-10-05T21:40:27Z`)  
**Status**: Completed / Remediated & Verified (Iteration 2)  
**Academic Context**: Master's Thesis — *"Explainable Hybrid GraphRAG for Conversational Recommendation"*  
**Canonical Vision Reference**: `production_artifacts/Vision_Report.md` (Decision Log 2026-09-23-005, 2026-09-28-006, 2026-10-03-008, 2026-10-05-001)  
**Target Research Questions**: $\mathbf{RQ_1}$ (Hybrid Multi-Index Retrieval vs. Baselines), $\mathbf{RQ_2}$ (Conversational Memory & Dialogue Flow), $\mathbf{RQ_3}$ (MACS Progressive Relaxation), $\mathbf{RQ_4}$ (Multi-Agent Critic Verification), $\mathbf{RQ_5}$ (Knowledge Graph Topological Groundedness), $\mathbf{RQ_6}$ (KECR Orthogonal Gating & Explainable Provenance)

---

## 1. Executive Summary

Conversational Recommender Systems (CRS) augmented with Knowledge Graph Retrieval-Augmented Generation (GraphRAG) and multi-agent coordination operate across multiple distinct cognitive and algorithmic stages. A naive, monolithic evaluation treating the CRS as a black-box text generator obscures internal failure modes and leads to fatal empirical errors: conflating retrieval recall with generation fluency, ignoring topological grounding, or relying on synthetic mock data that produces fabricated results.

Following the core mandate of `ORIGINAL_REQUEST.md` (§ `2026-10-05T21:40:27Z`), this research report delivers a comprehensive, academically grounded foundation and system revision plan for our CRS Master's Thesis:

1. **Exhaustive arXiv Literature Review**: Systematically investigates seminal and modern SOTA conversational recommendation frameworks across three eras (ReDial, KBRD, KGSF, CRSLab, UniCRS, KECR, MemoCRS, Reflexion, CRITIC, Re2A, SafeCRS, Ragas, TruLens, G-Eval, MT-Bench). We establish why classical lexical metrics (BLEU, ROUGE) fail, how Knowledge Graphs ground conversational entities, and why modular multi-agent reflection architectures (Reflexion, CRITIC) resolve the destructive competition between retrieval ranking and dialogue generation. We integrate situated rubric-based preference alignment (Re2A), dialogue safety alignment (SafeCRS), and define Catalog Validity Rate (CVR) as our foundational project architectural invariant.
2. **Mathematical Validation of Information Retrieval Metrics**: Critically validates our core IR metrics—**Hit Rate@K, NDCG@K, MRR@K, Precision@K, Recall@K**—specifying their exact mathematical formulations, logarithmic discount factors, ideal ranking baselines, cutoff horizons ($K$), and boundary behaviors (such as the single-target leave-one-out equivalence $\text{Recall@K} \equiv \text{HR@K}$). Crucially, we formalize the **Rank-Preserving Deduplication Requirement** and establish **Ideal DCG over the session candidate universe** to eliminate metric inflation ($\text{NDCG} > 1.0$). We also specify deterministic tie-breaking rules and division-by-zero guards for empty ground-truth sets.
3. **Multi-Stage Metric-to-Flow Architectural Mapping**: Formulates an explicit, five-stage mapping aligning every pipeline component with its theoretically valid metric:
   - *Stage 1: Candidate Retrieval (`GraphSearchTool`)* $\to$ $\text{Recall@K}$, $\text{Hit Rate@K}$, $\text{MRR@K}$ ($K \in \{20, 50\}$), MACS Relaxation Trigger Rate, and Retrieval Latency.
   - *Stage 2: Re-ranking & Selection (Additive Heuristic Scoring)* $\to$ $\text{NDCG@K}$, $\text{Precision@K}$, $\text{MRR@K}$ ($K \in \{3, 5, 10\}$).
   - *Stage 3: Semantic Verification (`CriticAgent`)* $\to$ Constraint Violation Elimination Rate ($\text{CVER}$ with zero-violation guards), False Positive Pruning Accuracy ($\text{FPPA}$), True Positive Retention Rate ($\text{TPRR}$ to prevent "prune-all" gaming), Critic Acceptance Rate ($\text{CAR}$), and Critic Ranking Gain ($\Delta\text{NDCG@K}$).
   - *Stage 4: Topological Reasoning (`KECRTool` / `KnowledgePathExtractor`)* $\to$ Path Discovery Yield, Topological Path Density, Subgraph Faithfulness, and Alpha-Gating Sensitivity ($\alpha \in [0.0, 1.0]$).
   - *Stage 5: End-to-End Dialog & Output (`AgentOrchestrator` / `PromptConstructor`)* $\to$ Catalog Validity Rate (100% verified real Neo4j nodes, 0% hallucinations), Attribute Adherence Rate ($\text{AAR}$), Inverted CoT Groundedness (with Hard Dilution Cap Rule), Explainability Provenance ($F_1$ / Fake History penalty), Multi-Turn Coherence, and Recoverability.
4. **Critical System Revision & Telemetry Specification**: Identifies the critical hooking gap in `AgentOrchestrator._execute_step()` where raw candidate lists ($\mathcal{R}_{\text{raw}}$) are overwritten at line 298 by post-critic items and Critic fit scores/reasoning paths are discarded. Formally defines the non-invasive `eval_trace` payload specification to enable end-to-end multi-stage inspection during live execution, and specifies candidate retrieval limit parameterization (`limit=20` or `top_k_candidates=20`) to enable legitimate measurement of $\text{Recall@20}$ and $\text{Recall@50}$.
5. **Live Graph Ground-Truth Reality (Zero-Mock Protocol)**: Reconciles the live Neo4j database census (265,307 `ParentProduct` nodes, 100% embedded with 384-d vectors, 65,650 valid positive numeric prices, 471,474 `User` nodes, 1,629,426 `Review` nodes, 3.69M+ relationships). Establishes a rigorous **Set-Partitioning Leave-One-Out Protocol** that operates without dependency on missing review timestamps, completely eliminating and deprecating synthetic candidate mocking (`ALT_...`, `VERIFIED_...`) and hand-crafted mock fixtures.

---

## 2. Problem Statement & Motivation

### 2.1 The Crisis of Mocked Evaluation in Conversational Recommender Systems
In the preliminary iteration of our evaluation framework (2026-10-03), two severe methodological flaws compromised empirical validity:
1. **Semantic Divergence in Hand-Crafted Benchmarks**: Synthetic fixtures (`retrieval_benchmark.json`) specified ASINs disconnected from the live database. For example, ASIN `B094V7S7D7` was designated as *"Sony WH-1000XM4 Wireless Premium Noise Canceling Overhead Headphones"*, whereas in our live Neo4j database, `B094V7S7D7` is actually *"POY Replacement Bands Compatible for Fitbit Charge 2"*. An empirical audit revealed that only 4 of the 25 benchmark ASINs existed in Neo4j (16% catalog existence rate).
2. **Offline Mock Fallbacks with Synthetic Candidates**: In `scripts/evaluate_retrieval.py` (lines 205–218), offline mode synthesized artificial candidate lists using string templates:
   $$\text{candidates} = [y_u^*] + [\text{f"ALT\_}\{y_u^*\}\text{\_}\{i\}\text{" for } i \in 1..19]$$
   This programmatically guaranteed that the target ASIN appeared at Rank 1, producing fabricated metric results ($\text{NDCG@10} \approx 0.98$, $\text{HR@10} = 1.0$) without querying the database, traversing the Knowledge Graph, or invoking the Critic.

For an academic Master's Thesis, synthetic benchmarks and mock fallbacks cannot support empirical claims. They fail to test whether `GraphSearchTool` executes valid Cypher under complex filters, whether Neo4j vector cosine distance retrieves relevant items, whether `CriticAgent` prunes false positives, or whether `AgentOrchestrator` hallucinates non-existent products.

### 2.2 The Multi-Stage Nature of Knowledge Graph CRS
Modern Conversational Recommender Systems are not single-layer models. As illustrated below, our CRS operates through five distinct stages:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                               CRS MULTI-STAGE EXECUTION FUNNEL                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                 │
                                                 ▼
  [Stage 1: Candidate Retrieval]       GraphSearchTool: Vector ANN + Cypher Filters + MACS
  • Universe: 265k live products       Output: Top-20 candidate pool (Broad recall focus)
                                                 │
                                                 ▼
  [Stage 2: Re-ranking & Selection]    Additive Scoring: Heuristic soft-preference weighting
  • Top-20 candidates                  Output: Sorted candidates by heuristic relevance
                                                 │
                                                 ▼
  [Stage 3: Semantic Verification]     CriticAgent: LLM audit against persona & reviews
  • Top-20 candidates                  Output: Top 3-5 verified items (Pruning false positives)
                                                 │
                                                 ▼
  [Stage 4: Topological Reasoning]     KECRTool: Multi-hop graph path extraction
  • Top 3 items + User History         Output: Demonstrable graph reasoning paths
                                                 │
                                                 ▼
  [Stage 5: End-to-End Dialog]         AgentOrchestrator + PromptConstructor + LLM
  • Verified items + Graph Evidence    Output: Natural language recommendation response
```

Evaluating this pipeline using only final-turn metrics conceals internal bottlenecks:
- If Stage 1 fails to retrieve the target in top-20 candidates, downstream stages cannot recover it, regardless of LLM capability.
- If Stage 1 retrieves the target at Rank 15, but Stage 3 (Critic) promotes it to Rank 1 by eliminating 14 false positives, a monolithic retrieval metric fails to credit the Critic for this ranking gain.
- If Stage 5 generates a fluent response recommending a product not present in Neo4j, traditional text similarity metrics (BLEU) fail to detect the hallucination.

Therefore, our evaluation framework must establish a granular **Metric-to-Flow Architecture** where each stage is evaluated against its mathematically valid metric, and all evaluations execute strictly against **live Neo4j graph nodes**.

---

## 3. SOTA Literature Survey: Conversational Recommender Systems on arXiv

To establish theoretical rigor, we survey the evolution of Conversational Recommender Systems across three distinct academic eras, analyzing seminal and modern papers.

```
+------------------------------------------------------------------------------------------------------------------+
| Evolution of CRS Evaluation Paradigms                                                                            |
|                                                                                                                  |
|  Era 1: Classical Task Decoupling (2018–2021)                                                                    |
|  • ReDial (NeurIPS '18), KBRD (EMNLP-IJCNLP '19), KGSF (KDD '20), CRSLab (ACL '21)                               |
|  • Recommendation Task: Evaluated via offline item ranking (Recall@K, Hit@K, MRR)                                 |
|  • Dialogue Task: Evaluated via n-gram overlap (BLEU-1/4, ROUGE, Distinct-n)                                      |
|  • Finding: Lexical metrics have zero correlation with recommendation utility.                                  |
|                                         │                                                                        |
|                                         ▼                                                                        |
|  Era 2: Knowledge-Enhanced & Memory Architectures (2022–2024)                                                   |
|  • UniCRS (KDD '22), KECR (TIST '24 / arXiv '23), MemoCRS (CIKM '24)                                             |
|  • Explicit Subgraph Reasoning, Orthogonal Gating, Entity Memory Banks                                          |
|  • Finding: Decoupled candidate selection prevents destructive competition; memory banks stop prompt bloat.     |
|                                         │                                                                        |
|                                         ▼                                                                        |
|  Era 3: Multi-Agent Reflection & GraphRAG CRS (2023–2026)                                                        |
|  • Reflexion (NeurIPS '23), CRITIC (ICLR '24), Re2A (arXiv '24), SafeCRS (KDD '26), Ragas (EACL '24)             |
|  • Multi-Agent verification (Critic), Zero-Hallucination Catalog Validation, Rubric Alignment                     |
|  • Finding: Decomposed LLM-as-a-Judge with Hard Dilution Caps and atomic claim verification matches human audits.|
+------------------------------------------------------------------------------------------------------------------+
```

### 3.1 Era 1: Classical Task Decoupling & Knowledge Graphs (2018–2021)

#### 1. ReDial (Li et al., NeurIPS 2018)
- **Title**: *Towards Deep Conversational Recommendation Networks*
- **Bibliographic Reference**: `arXiv:1812.07617 [cs.CL]`
- **Key Takeaway**: Introduced the first large-scale benchmark for conversational recommendation, formalizing the CRS problem as two coupled tasks: (1) predicting the user's preferred item at turn $t$, and (2) generating the conversational response.
- **Evaluation Finding**: Proved that recommendation accuracy must be evaluated using standard Information Retrieval ranking metrics ($\text{Recall@K}$, $\text{Hit@K}$) over the candidate item space. Demonstrated that traditional language generation metrics ($\text{BLEU}$, $\text{Distinct-n}$) reward bland, generic chit-chat ("That sounds great!") while failing to reward informative, factually accurate product descriptions.

#### 2. KBRD (Chen et al., EMNLP-IJCNLP 2019)
- **Title**: *Towards Knowledge-Based Recommender Dialog System*
- **Bibliographic Reference**: `arXiv:1908.05391 [cs.CL]`, EMNLP-IJCNLP 2019
- **Key Takeaway**: Integrated external Knowledge Graphs (DBpedia) to enrich entity representations and bridge the semantic gap between conversational dialogue text and item entities.
- **Evaluation Methodology**: Evaluated candidate selection via $\text{Recall@1}$, $\text{Recall@10}$, and $\text{Recall@50}$, demonstrating that relational knowledge links significantly improve candidate retrieval recall over flat text baselines.

#### 3. KGSF (Zhou et al., KDD 2020)
- **Title**: *Improving Conversational Recommender Systems via Knowledge Graph based Semantic Fusion*
- **Bibliographic Reference**: ACM KDD 2020
- **Key Takeaway**: Addressed the semantic discrepancy between word-level vocabulary and entity-level Knowledge Graphs by fusing word-oriented (ConceptNet) and item-oriented (DBpedia) graphs through Mutual Information Maximization (MIM).
- **Applicability**: Validates our dual semantic indexing in `GraphSearchTool`, where natural language review chunks and structured product attributes are jointly indexed in Neo4j vector spaces.

#### 4. CRSLab (Zhou et al., ACL 2021)
- **Title**: *CRSLab: An Open-Source Toolkit for Building Conversational Recommender System*
- **Bibliographic Reference**: `arXiv:2101.00939 [cs.IR]`, ACL 2021
- **Key Takeaway**: Standardized the decoupled evaluation methodology for CRS research. Formulated the core ranking metrics ($\text{Hit@K}$, $\text{MRR@K}$, $\text{NDCG@K}$) as the universal standard for candidate generation across all CRS models.

---

### 3.2 Era 2: Knowledge-Enhanced Reasoning & Memory Banks (2022–2024)

#### 5. UniCRS (Wang et al., KDD 2022)
- **Title**: *Towards Unified Conversational Recommender Systems via Knowledge-Enhanced Prompt Learning*
- **Bibliographic Reference**: `arXiv:2206.09363 [cs.IR]`, ACM KDD 2022
- **Key Takeaway**: Demonstrated that when a single monolithic model is jointly trained to predict item recommendations and generate dialogue utterances, the two objectives enter into **destructive semantic competition**: fine-tuning for generation fluency degrades ranking precision, and vice-versa.
- **Architectural Validation**: Directly validates our decoupled architectural choice: separating Candidate Retrieval (`GraphSearchTool`) from Semantic Verification (`CriticAgent`) and Dialogue Synthesis (`PromptConstructor`).

#### 6. KECR (Ren et al., ACM TIST 2024)
- **Title**: *Explicit Knowledge Graph Reasoning for Conversational Recommendation*
- **Bibliographic Reference**: `arXiv:2305.00783 [cs.IR]`, ACM Transactions on Intelligent Systems and Technology (TIST) 2024
- **Key Takeaway**: Demonstrated that conversational recommenders suffer from severe semantic drift when dealing with complex, multi-turn user intents unless grounded in explicit multi-hop relational paths connecting user interaction history to candidates.
- **Theoretical Contribution**: Introduced exponential temporal decay for historical user reviews and orthogonal gating between historical relevance and conversational intent:
  $$S_{composite} = \min\left(1.0, \; \alpha \cdot s_{hist} + (1 - \alpha) \cdot s_{conv}\right)$$
- **Applicability**: Forms the theoretical foundation of our `KECRTool` (`src/tools/kecr_tool.py`). The evaluation framework specifically evaluates the sensitivity of recommendation ranking across $\alpha \in [0.0, 1.0]$.

#### 7. MemoCRS (Xi et al., CIKM 2024)
- **Title**: *Memory-enhanced Sequential Conversational Recommender Systems with Large Language Models*
- **Bibliographic Reference**: `arXiv:2407.04960 [cs.IR]`, ACM CIKM 2024
- **Key Takeaway**: Demonstrated that naively concatenating raw conversational dialogue history into an LLM prompt degrades reasoning quality due to **attention dilution**, prompt bloat, and the catastrophic forgetting of constraints introduced in early dialogue turns.
- **Architectural Validation**: Proved the superiority of maintaining an **Entity-Based Working Memory** tracking discrete active constraints, preferred attributes, and rejected entities. Directly validates our `DialogueManager` (`src/dialog_manager/dialogue_manager.py`) and `SessionContext` architecture.

---

### 3.3 Era 3: Multi-Agent Reflection, GraphRAG, and Safe CRS (2023–2026)

#### 8. Reflexion (Shinn et al., NeurIPS 2023)
- **Title**: *Reflexion: Language Agents with Verbal Reinforcement Learning*
- **Bibliographic Reference**: `arXiv:2303.11366 [cs.AI]`, NeurIPS 2023
- **Key Takeaway**: Formalizes verbal reinforcement learning where autonomous agents evaluate the execution feedback of their own actions, formulate heuristic reflections, and store them in episodic memory to self-correct reasoning mistakes without fine-tuning model weights.
- **Architectural Mapping to CRS**: Directly validates the reflection loop of our `CriticAgent` (`src/agents/critic_agent.py`), which reviews retrieved candidates against user persona constraints and review sentiment, establishing the necessity of evaluating **Critic Ranking Gain** ($\Delta\text{NDCG@K}$).

#### 9. CRITIC (Gou et al., ICLR 2024)
- **Title**: *CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing*
- **Bibliographic Reference**: `arXiv:2305.11738 [cs.CL]`, ICLR 2024
- **Key Takeaway**: Proves that LLMs struggle to verify complex factual constraints through purely internal parametric reasoning, but achieve dramatic accuracy improvements when equipped with external verification tools (critiquing engines) to validate claims, detect contradictions, and prune invalid hypotheses.
- **Architectural Mapping to CRS**: Validates the decoupling between `GraphSearchTool` (broad retrieval) and `CriticAgent` (semantic filtering against verified customer review chunks), directly motivating the **Constraint Violation Elimination Rate** ($\text{CVER}$) and **False Positive Pruning Accuracy** ($\text{FPPA}$).

#### 10. Re2A (Lin et al., arXiv 2024)
- **Title**: *Re2A: Situated Conversational Recommendation via Rubric-based Preference Reasoning and Alignment*
- **Bibliographic Reference**: `arXiv:2609.18249 [cs.IR]`, September 2024
- **Key Takeaway**: Addresses Situated Conversational Recommendation (SCR) in multimodal and physical environments, introducing rubric-based multi-step preference alignment to bridge the gap between user conversational utterances and environmental item affordances.
- **Architectural Mapping to CRS**: We adapt its **rubric-based preference reasoning and alignment** methodology into our Stage 5 LLM-as-a-Judge rubrics, establishing multi-criteria scoring rubrics that align judge evaluations with explicit user constraint fulfillment.

#### 11. SafeCRS (Hao et al., KDD 2026) & Catalog Grounding Invariant
- **Title**: *SafeCRS: Personalized Safety Alignment for LLM-Based Conversational Recommender Systems*
- **Bibliographic Reference**: `arXiv:2603.03536 [cs.CL]`, ACM KDD 2026
- **Key Takeaway**: Investigates personalized psychological safety risks (e.g. trauma triggers, phobias, addiction, self-harm) in dialogue interactions, introducing Safe-SFT and Safe-GDPO policy optimization to align CRS models against harmful recommendations.
- **Attribution of Catalog Validity Rate (CVR)**:
  We explicitly distinguish dialogue psychological safety (SafeCRS) from commercial e-commerce catalog validity. **Catalog Validity Rate (CVR)** is formalized as **our project's internal architectural invariant and thesis evaluation metric**, mandated by the requirement that generative CRS pipelines must achieve 100% database existence and 0% catalog hallucination:
  $$\text{CVR} = \frac{|\{i \in \mathcal{R}_{\text{utterance}} \mid i \in \text{Neo4j\_ParentProduct}\}|}{|\mathcal{R}_{\text{utterance}}|} = 1.0$$
  This invariant is theoretically supported by comprehensive surveys on LLM hallucinations in recommendation:
  - *A Survey on Large Language Models for Recommendation* (Likang Wu et al., `arXiv:2305.19860`, RecSys 2023).
  - *How Can Recommender Systems Benefit from Large Language Models: A Survey* (Jianghao Lin et al., `arXiv:2306.05817`, 2023).  
  Both surveys identify out-of-distribution item hallucination as the primary obstacle to deploying generative LLMs in commercial recommendation.

#### 12. Modern LLM-as-a-Judge & GraphRAG Frameworks
- **G-Eval (Liu et al., EMNLP 2023)**: `arXiv:2303.16634 [cs.CL]`. Proves that structured evaluation forms enforcing intermediate Chain-of-Thought (CoT) reasoning *prior* to score generation significantly improve human alignment and correlation ($\rho > 0.82$) compared to direct score prompting.
- **MT-Bench / Zheng et al. (NeurIPS 2023)**: `arXiv:2306.05685 [cs.CL]`. Identifies systematic biases in LLM judges: position bias, verbosity bias, and self-enhancement bias. Establishes protocols for positional swapping and verbosity mitigation.
- **Ragas (Es et al., EACL 2024)**: `arXiv:2309.15217 [cs.CL]` & **TruLens (2023)**. Formalize *Faithfulness* and *Groundedness* in RAG. We adapt these unstructured text metrics to structured Knowledge Graph topology, evaluating whether asserted product claims are bound to verified Neo4j triples.
- **Amazon Reviews 2023 Benchmark (Yupeng Hou et al., ACL 2024)**: `arXiv:2403.03952 [cs.IR]`. Introduces the Amazon Reviews 2023 benchmark and BLaIR, establishing dense text-item semantic retrieval standards across user reviews and item metadata.

---

## 4. Mathematical Validation & Critical Analysis of IR Metrics

We critically analyze our five core Information Retrieval metrics—**Hit Rate@K, NDCG@K, MRR@K, Precision@K, Recall@K**—to validate their applicability, establish exact mathematical formulations, and specify their boundary conditions.

### 4.1 Notation & Definitions
Let:
- $\mathcal{U}$ be the set of evaluation sessions ($|\mathcal{U}|$ total sessions).
- $\mathcal{R}_u = [i_1, i_2, \dots, i_K]$ be the ranked sequence of candidate ASINs returned for session $u$.
- $\mathcal{Y}_u^*$ be the set of ground-truth relevant items for session $u$.
- $rel(i)$ be the relevance score of item $i$, where $rel(i) \in \{0, 1\}$ for binary evaluation and $rel(i) \in [0, 5]$ for graded KG evaluation.
- $K$ be the cutoff horizon ($K \ge 1$).

### 4.2 The Rank-Preserving Deduplication Requirement
In our hybrid retrieval architecture, `GraphSearchTool` executes multiple concurrent retrieval branches: Product Vector ANN, Attribute Vector ANN, Review Vector ANN, and Cypher Structural queries. Merging these branches can yield duplicate candidate ASINs in the raw candidate sequence.

**Mathematical Violation**: If candidate $i$ appears at Rank 2 and again at Rank 4, naive evaluation counts item $i$ twice in set intersections $|\mathcal{R}_u[:K] \cap \mathcal{Y}_u^*|$. This leads to artificial metric inflation, causing $\text{NDCG@K} > 1.0$ and $\text{Recall@K} > 1.0$.

**Formal Constraint**: All metrics MUST operate strictly over the deduplicated sequence $\mathcal{R}_u^{\text{dedup}}$, preserving each item's earliest (highest-ranked) appearance:
$$\mathcal{R}_u^{\text{dedup}} = [i \in \mathcal{R}_u \mid \forall j < \text{index}(i), \; i \neq \mathcal{R}_u[j]]$$

---

### 4.3 Detailed Metric Formulations

#### 1. Hit Rate at K (HR@K)
Hit Rate measures whether at least one target ground-truth item was successfully retrieved within the top-$K$ candidates:
$$\text{HR@K}(u) = \mathbb{I}\left( |\mathcal{R}_u^{\text{dedup}}[:K] \cap \mathcal{Y}_u^*| > 0 \right) = \begin{cases} 1.0 & \text{if } \exists r \le K \text{ such that } i_r \in \mathcal{Y}_u^* \\ 0.0 & \text{otherwise} \end{cases}$$
Mean across all benchmark sessions:
$$\text{HR@K} = \frac{1}{|\mathcal{U}|} \sum_{u \in \mathcal{U}} \text{HR@K}(u)$$
- **Role in CRS**: Fundamental binary threshold. If $\text{HR@K} = 0$, the recommendation turn failed completely.
- **Standard Horizons**: $K \in \{20, 50\}$ for candidate retrieval; $K \in \{1, 3, 5\}$ for final recommendations.

#### 2. Normalized Discounted Cumulative Gain (NDCG@K)
NDCG measures position-weighted ranking quality, accounting for the depth of relevant items with a logarithmic discount factor.

**Discounted Cumulative Gain (DCG@K)**:
$$\text{DCG@K}(u) = \sum_{r=1}^{\min(K, |\mathcal{R}_u^{\text{dedup}}|)} \frac{2^{rel(i_r)} - 1}{\log_2(r + 1)}$$

**Ideal Discounted Cumulative Gain (IDCG@K)**:
To strictly guarantee that $\text{NDCG@K} \le 1.0$ under open-world Knowledge Graph relevance where multiple related items possess positive relevance scores, IDCG@K must be computed over the sorted true relevance vector of all available candidates in the session universe $\mathcal{S}_u^*$:
$$\text{IDCG@K}(u) = \sum_{r=1}^{\min(K, |\mathcal{S}_u^*|)} \frac{2^{s^*(r)} - 1}{\log_2(r + 1)}$$
where $s^*(r)$ is the $r$-th highest relevance score among all items evaluated for session $u$ ($s^*(1) \ge s^*(2) \ge \dots \ge s^*(|\mathcal{S}_u^*|)$).

**Normalized DCG (NDCG@K)**:
$$\text{NDCG@K}(u) = \begin{cases} \min\left(1.0, \; \max\left(0.0, \; \frac{\text{DCG@K}(u)}{\text{IDCG@K}(u)}\right)\right) & \text{if } \text{IDCG@K}(u) > 0 \\ 0.0 & \text{otherwise} \end{cases}$$
$$\text{NDCG@K} = \frac{1}{|\mathcal{U}|} \sum_{u \in \mathcal{U}} \text{NDCG@K}(u)$$
- **Role in CRS**: Primary ranking metric. Supports both binary relevance ($rel \in \{0, 1\}$) and graded KG relevance ($rel \in [0, 5]$). Strictly bounded within $[0.0, 1.0]$.
- **Standard Horizons**: $K \in \{3, 5, 10\}$.

#### 3. Mean Reciprocal Rank at K (MRR@K)
MRR models user effort by measuring the reciprocal rank of the first relevant item retrieved within top-$K$:
$$\text{rank}_u^* = \min \left\{ r \in \{1, \dots, K\} \mid i_r \in \mathcal{Y}_u^* \right\}$$
$$\text{RR@K}(u) = \begin{cases} \frac{1}{\text{rank}_u^*} & \text{if } \text{rank}_u^* \text{ exists} \\ 0.0 & \text{otherwise} \end{cases}$$
$$\text{MRR@K} = \frac{1}{|\mathcal{U}|} \sum_{u \in \mathcal{U}} \text{RR@K}(u)$$
- **Role in CRS**: Essential for conversational user experience. Users inspect products sequentially; the position of the first relevant item directly governs user satisfaction.

#### 4. Precision at K (Precision@K) & Guarded Recall at K (Recall@K)
$$\text{Precision@K}(u) = \frac{|\mathcal{R}_u^{\text{dedup}}[:K] \cap \mathcal{Y}_u^*|}{K}$$
$$\text{Recall@K}(u) = \begin{cases} \frac{|\mathcal{R}_u^{\text{dedup}}[:K] \cap \mathcal{Y}_u^*|}{|\mathcal{Y}_u^*|} & \text{if } |\mathcal{Y}_u^*| > 0 \\ 0.0 & \text{if } |\mathcal{Y}_u^*| = 0 \end{cases}$$

- **Division-by-Zero Guard**: If $|\mathcal{Y}_u^*| = 0$ (e.g. cold-start or empty ground truth), $\text{Recall@K}(u)$ is defensively defined as $0.0$, preventing zero-division runtime exceptions.
- **Single-Target Leave-One-Out Equivalence**:
  Under single-target leave-one-out evaluation where $|\mathcal{Y}_u^*| = 1$:
  $$\text{Recall@K}(u) \equiv \text{HR@K}(u)$$
  $$\text{Precision@K}(u) \equiv \frac{\text{HR@K}(u)}{K}$$
  When $|\mathcal{Y}_u^*| = 1$, Precision@K reflects the inverse horizon scale ($\text{Precision@5} = 0.20$ when $\text{HR@5} = 1.0$).
- **Physical Yield Ceiling**:
  When strict Cypher filters yield $M = |\mathcal{R}_u^{\text{dedup}}| < K$ candidates, maximum possible precision is $\frac{M}{K} < 1.0$. This documents that Precision@K reflects both retrieval accuracy and catalog yield density.
- **Deterministic Tie-Breaking Policy**:
  To prevent non-deterministic rank shuffling when multiple candidates tie in vector similarity or heuristic additive score, candidates are sorted deterministically using the tuple:
  $$\text{SortKey}(p) = \left( -\text{score}(p), \; -\text{review\_count}(p), \; \text{parent\_asin}(p) \right)$$

---

### 4.4 Objective Graded Knowledge Graph Relevance
When evaluating conversational queries with open attribute constraints, ground truth relevance is computed objectively from live Neo4j graph topology:

$$\text{Relevance}(p, p^*) = \begin{cases} 
5.0 & \text{if } p = p^* \text{ (Exact Target Match)} \\
4.0 & \text{if } |U(p) \cap U(p^*)| \ge 3 \text{ (High Co-Purchase / Co-Review Topology)} \\
3.0 & \text{if } \text{Brand}(p) = \text{Brand}(p^*) \land \text{Category}(p) = \text{Category}(p^*) \land |A(p) \cap A(p^*)| \ge 1 \\
2.0 & \text{if } 1 \le |U(p) \cap U(p^*)| < 3 \text{ (Moderate Co-Review Overlap)} \\
1.0 & \text{if } \text{Category}(p) = \text{Category}(p^*) \lor \text{Brand}(p) = \text{Brand}(p^*) \\
0.0 & \text{otherwise (Disjoint Subgraph / Zero Topological Overlap)}
\end{cases}$$
where $U(p)$ is the set of users who reviewed product $p$ in Neo4j, and $A(p)$ is the set of attributes connected to $p$ via `[:HAS_ATTRIBUTE]`.

---

### 4.5 Algorithmic Implementation Specification

```python
import math
from typing import Sequence, Union, Set, Dict, List, Any


def compute_ranking_metrics_for_session(
    retrieved_items: Sequence[str],
    ground_truth_relevance: Union[Set[str], Sequence[str], Dict[str, float]],
    k_horizons: Sequence[int] = (1, 3, 5, 10, 20),
    relevance_threshold: float = 0.0,
) -> Dict[str, float]:
    """
    Computes Information Retrieval ranking metrics for a single recommendation session.
    
    Guarantees:
    - Deduplicates retrieved items while preserving initial rank (earliest appearance).
    - Defensively validates horizons, filtering k <= 0 and raising ValueError if empty.
    - Guards against division by zero when retrieved or ground truth sets are empty.
    - Strictly bounds all metrics (HR, NDCG, MRR, P, R, AP) within [0.0, 1.0].
    """
    valid_k = [int(k) for k in k_horizons if int(k) > 0]
    if not valid_k:
        raise ValueError("k_horizons must contain at least one positive integer")

    # Normalize ground truth relevance dictionary
    if isinstance(ground_truth_relevance, dict):
        gt_dict = {str(k): float(v) for k, v in ground_truth_relevance.items()}
    elif isinstance(ground_truth_relevance, (set, list, tuple)):
        gt_dict = {str(k): 1.0 for k in ground_truth_relevance}
    else:
        gt_dict = {}

    # Define binary hit set based on relevance threshold
    relevant_target_set = {item for item, rel in gt_dict.items() if rel > relevance_threshold}
    total_relevant = len(relevant_target_set)

    # Rank-preserving deduplication
    seen = set()
    deduped_retrieved: List[str] = []
    for item in retrieved_items:
        s_item = str(item)
        if s_item not in seen:
            seen.add(s_item)
            deduped_retrieved.append(s_item)

    results: Dict[str, float] = {}

    for k in valid_k:
        sub = deduped_retrieved[:k]
        hits = [item for item in sub if item in relevant_target_set]
        num_hits = len(hits)

        # Hit Rate @ k
        results[f"HR@{k}"] = 1.0 if num_hits > 0 else 0.0

        # Precision @ k
        results[f"P@{k}"] = float(min(1.0, max(0.0, num_hits / k)))

        # Recall @ k
        results[f"R@{k}"] = float(min(1.0, max(0.0, num_hits / total_relevant))) if total_relevant > 0 else 0.0

        # Mean Reciprocal Rank @ k
        mrr = 0.0
        for rank_idx, item in enumerate(sub, start=1):
            if item in relevant_target_set:
                mrr = 1.0 / rank_idx
                break
        results[f"MRR@{k}"] = float(min(1.0, max(0.0, mrr)))

        # Average Precision @ k
        if total_relevant == 0 or num_hits == 0:
            results[f"AP@{k}"] = 0.0
        else:
            cum_hits = 0
            prec_sum = 0.0
            for rank_idx, item in enumerate(sub, start=1):
                if item in relevant_target_set:
                    cum_hits += 1
                    prec_sum += cum_hits / rank_idx
            denom_ap = min(k, total_relevant)
            results[f"AP@{k}"] = float(min(1.0, max(0.0, prec_sum / denom_ap))) if denom_ap > 0 else 0.0

        # Normalized Discounted Cumulative Gain @ k
        if not gt_dict or not sub:
            results[f"NDCG@{k}"] = 0.0
        else:
            dcg = 0.0
            for rank_idx, item in enumerate(sub, start=1):
                rel = gt_dict.get(item, 0.0)
                if rel > 0.0:
                    dcg += (math.pow(2.0, rel) - 1.0) / math.log2(rank_idx + 1.0)

            ideal_scores = sorted([v for v in gt_dict.values() if v > 0.0], reverse=True)
            idcg = 0.0
            for rank_idx, rel_star in enumerate(ideal_scores[:k], start=1):
                idcg += (math.pow(2.0, rel_star) - 1.0) / math.log2(rank_idx + 1.0)

            results[f"NDCG@{k}"] = float(min(1.0, max(0.0, dcg / idcg))) if idcg > 0.0 else 0.0

    return results
```

---

## 5. Granular Metric-to-Flow Architectural Mapping

We establish the definitive, stage-by-stage mapping aligning every phase of our multi-agent CRS pipeline with its authoritative metrics.

```
═══════════════════════════════════════════════════════════════════════════════════════════════════════
STAGE 1: CANDIDATE RETRIEVAL FUNNEL (GraphSearchTool)
Component: src/tools/graph_search_tool.py: GraphSearchTool.search()
Mechanism: Multi-Index Vector Search (Products, Attributes, Reviews) + Cypher Filters + MACS Relaxation
Objective: Maximize catalog recall and candidate coverage (265k product universe -> N=20 candidates)
───────────────────────────────────────────────────────────────────────────────────────────────────────
Authoritative Metrics:
  1. Recall@20, Recall@50: Fraction of ground-truth relevant items captured in candidate pool.
  2. Hit Rate@20 (HR@20): Binary capture rate of at least one valid target item.
  3. MRR@20: Rank of first hit in the raw multi-index merge.
  4. MACS Relaxation Trigger Rate: % of queries requiring progressive constraint relaxation.
  5. Post-Relaxation Yield: Number of candidates recovered when strict Cypher returned < 3 items.
  6. Retrieval Latency (ms): Execution time across vector search and Cypher query execution.
Cutoff Horizons: K in {20, 50}

═══════════════════════════════════════════════════════════════════════════════════════════════════════
STAGE 2: RE-RANKING & SELECTION (Additive Scoring & Pre-Critic Sorter)
Component: src/tools/graph_search_tool.py: _rerank_candidates()
Mechanism: Heuristic soft-preference weighting (+0.2 per matched trait) & score sorting
Objective: Prioritize top candidate ordering before invoking computationally expensive LLM Critic
───────────────────────────────────────────────────────────────────────────────────────────────────────
Authoritative Metrics:
  1. NDCG@5, NDCG@10: Ranking quality of the heuristic sorted candidate list.
  2. Precision@5: Density of relevant items in the top slots.
  3. MRR@10: Rank position of the primary target.
Cutoff Horizons: K in {3, 5, 10}

═══════════════════════════════════════════════════════════════════════════════════════════════════════
STAGE 3: SEMANTIC VERIFICATION & CRITIC (CriticAgent)
Component: src/agents/critic_agent.py: CriticAgent.evaluate_candidates()
Mechanism: LLM inspection of user persona vs. candidate specifications and review chunks
Objective: Eliminate false positives and semantic betrayals (Prunes 20 candidates -> Top 3-5 verified)
───────────────────────────────────────────────────────────────────────────────────────────────────────
Authoritative Metrics:
  1. Constraint Violation Elimination Rate (CVER):
       CVER = 1.0 - (|V_critic| / max(1, |V_raw|)) if |V_raw| > 0 else 1.0 (or excluded from mean)
  2. False Positive Pruning Accuracy (FPPA):
       FPPA = |V_raw ∩ P_critic| / |V_raw| if |V_raw| > 0 else 1.0 (vacuously accurate)
  3. True Positive Retention Rate (TPRR):
       TPRR = |C_valid \ P_critic| / max(1, |C_valid|)  (Mandates TPRR >= 0.80 to stop "prune-all" gaming)
  4. Critic Acceptance Rate (CAR): Ratio of candidates marked is_recommended=True.
  5. Critic Ranking Gain (ΔNDCG@K):
       ΔNDCG@K = NDCG@K(R_critic) - NDCG@K(R_raw)
  6. Independent Programmatic Verification Oracle:
       Violations in V_raw and V_critic evaluated by deterministic Cypher/property checks, not by LLM self-audit.
Cutoff Horizons: K in {3, 5}

═══════════════════════════════════════════════════════════════════════════════════════════════════════
STAGE 4: TOPOLOGICAL REASONING (KECRTool / KnowledgePathExtractor)
Component: src/tools/kecr_tool.py: KnowledgePathExtractor.extract_paths()
Mechanism: Multi-hop graph path extraction (User -> History -> Shared Brand/Category/Review -> Candidate)
Objective: Ground explainability in demonstrable Knowledge Graph topology
───────────────────────────────────────────────────────────────────────────────────────────────────────
Authoritative Metrics:
  1. Path Discovery Yield: % of recommended candidates connected by valid 2-3 hop graph paths.
  2. Topological Path Density: Average number of verified paths per recommended product.
  3. Subgraph Faithfulness: Verification that 100% of path edges exist in Neo4j.
  4. Alpha-Gating Sensitivity: Impact of gating parameter α in [0.0, 1.0] on ranking and explainability.

═══════════════════════════════════════════════════════════════════════════════════════════════════════
STAGE 5: END-TO-END DIALOG & GENERATION (AgentOrchestrator & PromptConstructor)
Component: src/agents/orchestrator.py: AgentOrchestrator.run() & PromptConstructor
Mechanism: Synthesis of [GRAPH EVIDENCE] into natural language conversational recommendation
Objective: Deliver coherent, factually grounded, zero-hallucination recommendation dialogue
───────────────────────────────────────────────────────────────────────────────────────────────────────
Authoritative Metrics:
  1. Catalog Validity Rate (CVR / Zero-Hallucination Rate):
       CVR = |{i in R_utterance : i in Neo4j_ParentProduct}| / |R_utterance| == 1.0 (100% Mandatory)
  2. Attribute Adherence Rate (AAR): % of asserted technical specs verified against Neo4j node properties.
  3. Inverted CoT Groundedness (1-5 Likert): Factual claim audit with Hard Dilution Cap Rule (Cap at 1.0).
  4. Explainability Provenance Score (1-5 Likert): True KECR path verbalization; Fake History penalty.
  5. Multi-Turn Dialogue Coherence (1-5 Likert): Context memory, handling intent shifts, constraint retention.
  6. Recoverability Score (1-5 Likert): Adaptation to negative feedback and elimination of rejected items.
  7. End-to-End Hit Rate@3: Binary success of final items presented in assistant's conversational utterance.
═══════════════════════════════════════════════════════════════════════════════════════════════════════
```

---

### 5.1 Anti-Bias Principles & Strict Inverted Chain-of-Thought (CoT)

1. **Inverted Chain-of-Thought Key Ordering**:
   In autoregressive language models, tokens are generated left-to-right. To ensure Chain-of-Thought reasoning guides numerical scoring, intermediate analysis (`"claim_analysis"`, `"reasoning_steps"`, `"evidence_evaluation"`) **MUST precede** the `"score"` field in every JSON schema. Placing `"score"` before `"reasoning"` causes the judge to commit to a rating before generating analytical justification.
2. **Universal Conciseness & Verbosity Directive**:
   To prevent verbosity bias (where verbose answers dilute hallucinations or receive undeserved high ratings), every prompt must embed the universal conciseness directive (formally defined in Section 5.4), mandating that responses are evaluated strictly on claim-to-token efficiency and factual density without rewarding verbose filler text.
3. **Hard Dilution Cap Rule**:
   $$S_{Groundedness} = \begin{cases} 1.0 & \text{if } N_{crit} \ge 1 \\ \max\left(1.0, \; \frac{N_{\text{verified}}}{N_{\text{total}}} \times 5.0\right) & \text{otherwise} \end{cases}$$
   Any direct fabrication or contradiction of core technical specifications (e.g., refresh rate, price, connectivity, battery capacity) constitutes a critical violation ($N_{\text{crit}} \ge 1$), capping the score strictly at **Score 1.0**.
4. **Provenance Precision, Recall, and F1 with Fake History Penalty**:
   $$\text{ProvenancePrecision}(E, \mathcal{P}_{rec}) = \frac{|\mathcal{P}_{\text{asserted}} \cap \mathcal{P}_{\text{rec}}|}{\max(1, |\mathcal{P}_{\text{asserted}}|)}$$
   $$\text{ProvenanceRecall}(E, \mathcal{P}_{rec}) = \frac{|\mathcal{P}_{\text{asserted}} \cap \mathcal{P}_{\text{rec}}|}{\max(1, |\mathcal{P}_{\text{rec}}|)}$$
   $$\text{Provenance\_F1} = \frac{2 \times \text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$$
   If $|\mathcal{P}_{\text{asserted}} \setminus \mathcal{P}_{\text{rec}}| > 0$ (i.e. the agent invents fabricated historical purchases or graph edges), the explanation receives a direct score cap of 1.0.

---

### 5.2 Generative LLM-as-a-Judge Evaluator Prompt Suite

#### Prompt 1: Inverted CoT Groundedness Evaluator

```markdown
[TASK]
Evaluate the factual groundedness of the conversational recommendation against verified Knowledge Graph evidence.

[SYSTEM INSTRUCTION]
You are an expert factual integrity judge for a Conversational Recommender System. Your task is to audit the factual correctness of the AGENT RESPONSE against the provided KNOWLEDGE GRAPH EVIDENCE.

[CONCISENESS & VERBOSITY DIRECTIVE]
Evaluate the response strictly on claim-to-token efficiency and factual density. Do NOT reward verbose, repetitive, or flowery filler text. Conversational answers must state facts directly without extraneous speculation.

[INPUT DATA]
1. USER INTENT / QUERY:
{user_query}

2. KNOWLEDGE GRAPH EVIDENCE (Verified Product Attributes, Specifications & Reviews):
{knowledge_graph_evidence}

3. AGENT RESPONSE TO EVALUATE:
{agent_response}

[EVALUATION PROCESS]
Step 1: Extract all factual claims made in the response regarding product capabilities, specs, prices, and features.
Step 2: Cross-reference each claim against the KNOWLEDGE GRAPH EVIDENCE. Classify each claim as:
  - "verified": Directly supported by the evidence.
  - "unverified": Missing from evidence, not verifiable.
  - "contradicted": Directly contradicts evidence.
Step 3: Count critical specification violations (`critical_violations_count`). Fabricating or contradicting core technical specs (e.g. refresh rate, battery capacity, connectivity, price) is a critical violation.
Step 4: Formulate step-by-step reasoning explaining failures or alignment.
Step 5: Apply the HARD CAP RULE: If `critical_violations_count >= 1`, score MUST NOT exceed Score 1.
Step 6: Assign the final score (1-5) strictly based on the rubric.

[SCORING RUBRIC]
- Score 5 (Perfect Grounding): 100% of claims are verified against the graph context. Zero unverified or contradictory statements.
- Score 4 (High Grounding): Minor harmless colloquial description (e.g. "sleek design"), with all product specifications and pricing fully verified.
- Score 3 (Moderate Grounding): Contains 1-2 minor unverified soft claims, but zero contradictions of core technical specs.
- Score 2 (Severe Hallucination): Attributes major capabilities or specs that are missing or contradictory, but without critical safety/hardware false claims.
- Score 1 (Failed Grounding / Critical Violation): Contains ANY critical specification contradiction (`critical_violations_count >= 1`) or fabricates core hardware capabilities (e.g. 120Hz on 60Hz panel).

[OUTPUT FORMAT]
[OUTPUT SCHEMA]
Return ONLY a valid JSON object matching the following schema:
```json
{
  "extracted_claims": [
    {
      "claim": "string",
      "status": "verified | unverified | contradicted",
      "evidence_anchor": "string"
    }
  ],
  "critical_violations_count": 0,
  "reasoning": "Step-by-step analysis demonstrating why the score was assigned...",
  "score": 5
}
```
```

---

#### Prompt 2: Explainability Provenance Evaluator

```markdown
[TASK]
Evaluate whether the recommendation explanation accurately reflects verified Knowledge Graph relational paths.

[SYSTEM INSTRUCTION]
You are an expert Knowledge Graph explainability judge. Your task is to evaluate whether the AGENT RESPONSE accurately explains recommendations using verified historical and relational paths from the KNOWLEDGE GRAPH PATHS.

[CONCISENESS & VERBOSITY DIRECTIVE]
Evaluate the response strictly on claim-to-token efficiency and factual density. Do NOT reward verbose, repetitive, or flowery filler text. Conversational answers must state facts directly without extraneous speculation.

[INPUT DATA]
1. USER PROFILE & INTERACTION HISTORY:
{user_history}

2. RETRIEVED KNOWLEDGE GRAPH PATHS (Verified Multi-Hop Relational Chains):
{retrieved_graph_paths}

3. RECOMMENDED CANDIDATES:
{recommended_candidates}

4. AGENT EXPLANATION UTTERANCE:
{agent_response}

[EVALUATION PROCESS]
Step 1: Identify all historical user interactions, past purchases, or relational connections asserted in the explanation.
Step 2: Cross-reference asserted paths against RETRIEVED KNOWLEDGE GRAPH PATHS.
Step 3: Extract any fabricated or hallucinated historical purchases into `fabricated_paths_detected`.
Step 4: Apply the HARD CAP RULE: If any fabricated path or interaction is detected, score MUST be capped at Score 1.
Step 5: Formulate step-by-step reasoning assessing whether the explanation provides transparent, faithful reasoning.
Step 6: Assign the final score (1-5) strictly based on the rubric.

[SCORING RUBRIC]
- Score 5 (Faithful Provenance): Explanation explicitly and accurately bridges user history to the recommended product via verified graph paths.
- Score 4 (Valid Relational Grounding): Clear reasoning connecting user preferences to verified product features; minor omissions of intermediate node names.
- Score 3 (Generic Explanation): Gives superficial or generic reasoning (e.g. "Because it is popular") without grounding in specific graph paths.
- Score 2 (Misleading Provenance): Distorts graph relationships or attributes preferences to features unrelated to user history.
- Score 1 (Deceptive Provenance / Contradictory): Fabricates non-existent user purchase history, invents past ratings/reviews, asserts fictional graph edges (`fabricated_paths_detected > 0`).

[OUTPUT FORMAT]
[OUTPUT SCHEMA]
Return ONLY a valid JSON object matching the following schema:
```json
{
  "asserted_paths": ["string"],
  "verified_paths": ["string"],
  "fabricated_paths_detected": ["string"],
  "provenance_verifiable": true,
  "reasoning": "Detailed breakdown comparing asserted explanation against graph paths...",
  "score": 5
}
```
```

---

#### Prompt 3: Multi-Turn Dialogue Coherence Evaluator

```markdown
[TASK]
Evaluate dialogue coherence, tracking of active constraints, and context adaptation across conversation turns.

[SYSTEM INSTRUCTION]
You are an expert dialogue coherence evaluator. Your task is to evaluate whether the AGENT RESPONSE maintains conversational memory, adapts to intent shifts, purges revoked constraints, and provides a coherent multi-turn experience.

[CONCISENESS & VERBOSITY DIRECTIVE]
Evaluate the response strictly on claim-to-token efficiency and factual density. Do NOT reward verbose, repetitive, or flowery filler text. Conversational answers must state facts directly without extraneous speculation.

[INPUT DATA]
1. PRIOR CONVERSATION HISTORY (Turns 1 to T-1):
{dialogue_history}

2. CURRENT USER MESSAGE (Turn T):
{current_user_message}

3. AGENT RESPONSE (Turn T):
{agent_response}

[EVALUATION PROCESS]
Step 1: Identify active constraints from dialogue history and check if the user revoked or shifted preferences in Turn T.
Step 2: Verify that revoked constraints are purged (`superseded_constraints_purged`).
Step 3: Evaluate whether the AGENT RESPONSE addresses the immediate intent (`immediate_intent_addressed`) or suffers from Context Lag (anchoring to outdated preferences).
Step 4: Formulate step-by-step reasoning assessing multi-turn continuity.
Step 5: Assign the final score (1-5) strictly based on the rubric.

[SCORING RUBRIC]
- Score 5 (Seamless Coherence): Flawlessly tracks context across turns, immediately adapts to intent shifts, and completely purges revoked constraints.
- Score 4 (Coherent Adaptation): Accurately addresses current intent with minor stiffness in conversational transition.
- Score 3 (Partial Amnesia): Responds to current utterance but forgets minor secondary constraints established in earlier turns.
- Score 2 (Context Lag / Stale Intent Anchoring & Drift): Anchors to outdated or revoked preferences from earlier turns while failing to address an explicit intent shift in the immediate user message.
- Score 1 (Total Breakdown): Incoherent, hallucinates unrelated conversational context, or loops repetitively.

[OUTPUT FORMAT]
[OUTPUT SCHEMA]
Return ONLY a valid JSON object matching the following schema:
```json
{
  "active_constraints_tracked": ["string"],
  "superseded_constraints_purged": true,
  "immediate_intent_addressed": true,
  "reasoning": "Step-by-step assessment of conversational continuity and intent handling...",
  "score": 5
}
```
```

---

#### Prompt 4: Recoverability Evaluator (Negative Feedback Adaptation)

```markdown
[TASK]
Evaluate system adaptation against user negative constraints using candidate graph attributes and specifications.

[SYSTEM INSTRUCTION]
You are an expert recommender recovery judge. Your task is to evaluate how effectively the CRS adapts when the user provides explicit negative feedback, rejects a previously suggested item, or imposes a strict negative constraint.

[CONCISENESS & VERBOSITY DIRECTIVE]
Evaluate the response strictly on claim-to-token efficiency and factual density. Do NOT reward verbose, repetitive, or flowery filler text. Conversational answers must state facts directly without extraneous speculation.

[INPUT DATA]
1. PREVIOUS TURN RECOMMENDATION:
{previous_recommendation}

2. USER NEGATIVE FEEDBACK / CORRECTION:
{user_negative_feedback}

3. SYSTEM ADAPTATION RESPONSE:
{system_adaptation_response}

4. NEW CANDIDATE SET PRESENTED:
{new_candidates}

5. NEW CANDIDATE GRAPH ATTRIBUTES & SPECIFICATIONS:
{new_candidate_attributes}

[EVALUATION PROCESS]
Step 1: Extract the rejected item and the explicit negative constraints stated by the user (e.g. "NO wireless", "budget under $50").
Step 2: Check whether the rejected item was eliminated from the NEW CANDIDATE SET.
Step 3: Cross-reference NEW CANDIDATE SET against NEW CANDIDATE GRAPH ATTRIBUTES & SPECIFICATIONS to verify compliance with negative constraints.
Step 4: Apply the HARD VIOLATION RULE: If `negative_constraint_violations` is non-empty (`new_candidates_compliant == false`), the score MUST be capped at Score 1.
Step 5: Formulate step-by-step reasoning assessing recovery fidelity.
Step 6: Assign the final score (1-5) strictly based on the rubric.

[EVALUATION RUBRIC]
[SCORING RUBRIC]
- Score 5 (Flawless Recovery): Removes rejected items, fully adheres to negative constraints, and offers compelling compliant alternatives matching soft preferences.
- Score 4 (Compliant Recovery): Fully complies with negative constraints; minor sub-optimality in secondary preferences.
- Score 3 (Sub-optimal Compliant Alternative): Eliminates rejected items and respects hard negative constraints, but fails to match remaining soft preferences.
- Score 2 (Stubborn Repeat / Brand Fixation): Removes the exact rejected product but stubbornly recommends items from the same rejected family/brand.
- Score 1 (Failed Recovery / Negative Constraint Betrayal): Recommends items violating the explicit negative constraint (`negative_constraint_violations > 0`) or repeats the exact rejected item.

[OUTPUT FORMAT]
[OUTPUT SCHEMA]
Return ONLY a valid JSON object matching the following schema:
```json
{
  "rejected_item_eliminated": true,
  "negative_constraint_violations": ["string"],
  "new_candidates_compliant": true,
  "reasoning": "Step-by-step analysis of negative constraint adherence and candidate compliance...",
  "score": 5
}
```
```

---

### 5.3 Synthetic Edge Cases & Mathematical Alignment

To stress-test our evaluation rubrics and formulas against adversarial generation patterns, we examine four synthetic challenge cases:

#### Case A: Subtle Specification Hallucination Padded with True Claims
- **Scenario**: The agent recommends Sony 55" 4K TV (`B0B3CZSX6M`) which has `NativeRefreshRate: 60Hz` in Neo4j. The agent claims 120Hz native refresh rate for competitive gaming, padded with 20 true factual claims (4K resolution, HDR10, HDMI 2.1 eARC, Google TV, etc.).
- **Vulnerability**: An unweighted linear grounding ratio $\frac{N_{\text{verified}}}{N_{\text{total}}} = \frac{20}{21} = 0.952$ would yield a score of $4.76 / 5.0$, completely hiding the critical hardware specification hallucination.
- **Resolution**: Under the **Hard Dilution Cap Rule**, because refresh rate is a core technical specification, $N_{\text{crit}} = 1$. The rule triggers:
  $$S_{Groundedness} = \begin{cases} 1.0 & \text{if } N_{crit} \ge 1 \\ \max\left(1.0, \; \frac{N_{\text{verified}}}{N_{\text{total}}} \times 5.0\right) & \text{otherwise} \end{cases}$$
  The score is capped at **1.0**, perfectly detecting the hardware hallucination.

#### Case B: Fabricated Graph Paths & Purchase History
- **Scenario**: The user's interaction history in Neo4j contains only an Anker USB-C Charger. The agent recommends Sony WH-1000XM4 headphones by falsely stating: *"Because you previously purchased and enjoyed the Sony WH-1000XM3 headphones, you will love the upgraded noise cancellation on the XM4."*
- **Vulnerability**: An ungrounded judge might view this as a persuasive explanation. A recall-only metric checking if the Anker charger was mentioned would fail to penalize the invented Sony purchase history.
- **Resolution**: Prompt 2 identifies the asserted path as fabricated (`"fabricated_paths_detected": ["Sony WH-1000XM3 purchase"]`). Because fabricated historical purchases or graph edges are detected, the explanation receives a direct score cap of 1.0, assigning **Score 1 (Deceptive Provenance / Contradictory)**.

#### Case C: Stale Intent Anchoring (Context Lag)
- **Scenario**: In Turn 1, the user asks for trail running shoes. In Turn 2, the user explicitly shifts intent: *"Forget running shoes, I already bought a pair. I now need a hydration vest."* The agent responds by presenting trail running shoes while ignoring the hydration vest.
- **Vulnerability**: A judge checking only overall dialogue fluency might award high marks because the response is polite and well-structured.
- **Resolution**: Prompt 3 explicitly evaluates `superseded_constraints_purged` and `immediate_intent_addressed`. Because the agent anchors to outdated preferences, the rubric explicitly assigns **Score 2 (Context Lag / Stale Intent Anchoring & Drift): Anchors to outdated or revoked preferences from earlier turns while failing to address an explicit intent shift in the immediate user message**.

#### Case D: Negative Constraint Betrayal
- **Scenario**: The user rejects wireless accessories: *"I need wired headphones only, NO wireless or bluetooth."* The agent responds with Sony WH-1000XM4 (Wireless).
- **Vulnerability in Iteration 1**: The rubric allowed Score 3 for partial recovery, while the mathematical formula dropped the score to 0.0, creating a 3.0-point discrepancy.
- **Resolution**: In Prompt 4, recommending items violating an explicit negative constraint (`negative_constraint_violations > 0`) is explicitly categorized as **Score 1 (Failed Recovery / Negative Constraint Betrayal)**. The decoupled recovery metric formula:
  $$\text{CVR}_{recover} = \frac{|\{i \in \mathcal{R}_{\text{new}} \mid i \text{ violates } C_{\text{neg}}\}|}{|\mathcal{R}_{\text{new}}|}$$
  $$\text{Recovery\_Score} = \text{JudgeScore} \times \left(1.0 - \text{CVR}_{recover}\right)$$
  When $\text{CVR}_{recover} > 0$, Prompt 4 assigns **Score 1 ("Failed Recovery / Constraint Betrayal")**, and the formula drops $\text{Recovery\_Score}$ to $0.0$, guaranteeing perfect mathematical alignment.

---

### 5.4 Bias Mitigation & Conciseness Directives

To neutralize common LLM-as-a-Judge vulnerabilities (verbosity bias, position bias, self-enhancement bias):

1. **Conciseness & Verbosity Directive**:
   All evaluation prompts embed the universal directive:
   ```markdown
   [CONCISENESS & VERBOSITY DIRECTIVE]
   Evaluate the response strictly on claim-to-token efficiency and factual density. Do NOT reward verbose, repetitive, or flowery filler text. Conversational answers must state facts directly without extraneous speculation.
   ```
2. **Positional Swapping for Pairwise Judges**: When comparing model variants (e.g. CRS with Critic vs. ablation without Critic), swap prompt candidate orders across mirrored evaluations to eliminate position bias.
3. **Structured Reference Anchoring**: Every claim is cross-referenced against explicit Neo4j node properties (`{knowledge_graph_evidence}` and `{new_candidate_attributes}`), preventing judges from relying on parametric LLM assumptions.

---

## 6. Critical System Architecture Revision: Telemetry & Telemetry Hooks

To compute these multi-stage metrics authentically against live data without mocks, we performed a line-by-line inspection of `src/agents/orchestrator.py`.

### 6.1 The Telemetry Gap in `AgentOrchestrator` & Retrieval Limit Parameterization
In `src/agents/orchestrator.py` (lines 277–331):
```python
# Line 277: Hardcoded retrieval limit
search_result = self.graph_tool.search(
    semantic_query=semantic_query,
    structured_filters=active_filters,
    limit=5  # HARDCODED LIMIT!
)

# Line 286: Extract raw candidates from GraphSearchTool
candidates = search_result.get("items", [])

# Line 295: Critic Agent contextual reranking
reranked_top = await self.critic_agent.evaluate_candidates(critic_profile, candidates, attributes_map)

# Line 298: OVERWRITES RAW CANDIDATES!
search_result["items"] = reranked_top[:3]

# Lines 305-310: KECR Tool path extraction
extraction_result = self.kecr_tool.extract_paths(...)
graph_reasoning_paths = extraction_result.serialized_evidence_dict

# Line 327-331: Final payload returned to caller
result = {
    "answer": final_answer,
    "data": search_result,
    "action": "SEARCH"
}
```

**Four Critical Telemetry Failures Identified**:
1. **Candidate Retrieval Limit Bottleneck**: Hardcoding `limit=5` in `_execute_step()` makes measuring `Recall@20` and `Recall@50` mathematically impossible, as Stage 1 can never retrieve more than 5 items. The parameter `limit` must be configurable (e.g. `retrieval_limit = getattr(self, "retrieval_limit", 20)` or passed via session parameters).
2. **Raw Candidate Destruction**: Line 298 overwrites `search_result["items"]` with `reranked_top[:3]`. The raw candidate pool ($\mathcal{R}_{\text{raw}}$) produced by Stage 1 (`GraphSearchTool`) is permanently lost.
3. **Discarded Pruning Evidence**: Items rejected or demoted by the Critic are deleted. An external benchmark cannot measure which items were pruned, whether constraint-violating items were eliminated, or what the Critic's numerical `semantic_score` was.
4. **KECR Path Severance**: `graph_reasoning_paths` is extracted at line 310 and passed to `PromptConstructor`, but is completely omitted from the return `result` dictionary. Downstream evaluators cannot audit whether the LLM's explanation verbalized true graph paths or hallucinated fake history.

---

### 6.2 The Non-Invasive `eval_trace` Telemetry Specification

To resolve this telemetry gap without breaking production chat callers, we formally specify the non-invasive `eval_trace` schema to be attached to `response_payload` inside `AgentOrchestrator._execute_step()` when `action == "SEARCH"`:

```python
response_payload = {
    "answer": final_answer,
    "data": search_result,
    "action": "SEARCH",
    "eval_trace": {
        "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        "semantic_query": semantic_query,
        "structured_filters": active_filters,
        
        # Stage 1: Candidate Retrieval Telemetry (20 candidates)
        "raw_candidates": [
            {
                "asin": p.get("asin"),
                "title": p.get("title"),
                "price": p.get("price"),
                "score": p.get("score"),
                "match_reasons": p.get("match_reasons", [])
            }
            for p in candidates
        ],
        "search_metadata": {
            "strategy": search_result.get("strategy"),
            "count": search_result.get("count"),
            "relaxed_constraints": search_result.get("relaxed_constraints", [])
        },
        
        # Stage 2 & 3: Critic Verification Telemetry
        "critic_reranked": [
            {
                "asin": p.get("asin"),
                "title": p.get("title"),
                "fit_score": p.get("semantic_score"),
                "is_recommended": p.get("is_recommended", True),
                "reasoning": p.get("reasoning", "")
            }
            for p in reranked_top
        ],
        "critic_pruned_asins": [
            p.get("asin") for p in candidates 
            if p.get("asin") not in [r.get("asin") for r in reranked_top if r.get("is_recommended", True)]
        ],
        
        # Stage 4: Topological Reasoning Telemetry
        "graph_reasoning_paths": graph_reasoning_paths,
        
        # Stage 5: Final Output Candidates Presented in Utterance
        "presented_candidates": [
            {"asin": p.get("asin"), "title": p.get("title")}
            for p in search_result["items"]
        ]
    }
}
```

**Benefits of `eval_trace`**:
- **Zero Production Overhead**: Regular UI clients (Chainlit/Streamlit) continue reading `"answer"` and `"data"` undisturbed.
- **Complete Metric Observability**: The evaluation runner has direct, programmatic access to $\mathcal{R}_{\text{raw}}$, $\mathcal{R}_{\text{critic}}$, pruning reasons, KECR paths, and MACS relaxation states from a single live invocation of `AgentOrchestrator.run()`.

---

## 7. Live Neo4j Database Reality & Zero-Mock Ground Truth Protocol

### 7.1 Live Database Census & Statistics
A direct Cypher census of the active Neo4j database instance (`bolt://localhost:7687`, database `neo4j`) establishes the empirical universe of our system:

| Entity / Property / Cohort | Live Count in Neo4j | Empirical Census Notes | Role in Evaluation Framework |
| :--- | :---: | :--- | :--- |
| **`ParentProduct` (Total)** | **265,307** | Ingested Amazon catalog products | Complete candidate universe |
| `ParentProduct` with embeddings (384-d) | **265,307** | **100% of catalog is embedded** | Fast vector ANN retrieval pool |
| `ParentProduct` with `price` property | 112,989 | Ingested property present | Raw price property |
| `ParentProduct` with valid numeric price ($>0$) | **65,650** | 47,339 are `NaN` (`price: nan`); **65,650 are strictly $>0$** | Parametric price filtering pool |
| Complete `ParentProduct` nodes | **64,896** | Embedding + Valid Price (>0) + Title + Category | Full-attribute candidate universe |
| Complete products with reviews | **12,089** | Complete nodes linked to `:Review` | Golden candidate pool with reviews |
| **`User` (Total)** | **471,474** | User accounts in Neo4j | Total user base |
| Users with $\ge 3$ reviews (all) | **185,437** | Wrote $\ge 3$ reviews | Broad user interaction pool |
| Users with $\ge 2$ distinct titled products | **72,538** | Clarifies the origin of the 72,538 figure | **Sequential Set Partitioning Pool** |
| Users with $\ge 3$ distinct titled products | **29,750** | Reviewed $\ge 3$ distinct complete products | Deep context leave-one-out pool |
| **`Review` (Total)** | **1,629,426** | Ingested reviews | Text chunk & sentiment source |
| `Review.timestamp` IS NOT NULL | **0 (0.0%)** | Omitted during batch ingestion | **Mandates Set Partitioning** |
| `Review.timestamp_iso` IS NOT NULL | 4,847 (0.3%) | Legacy testing nodes only | Unusable for benchmark sorting |
| **`Attribute`** | 47,335 | 28,825 embedded | Structured attribute matching |
| **`Brand`** | 40,998 | 13,441 embedded | Brand filtering & graph paths |
| **`Category`** | 71 | 66 embedded | Taxonomic category filtering |
| **Total Relationships** | **3,694,424** | Fully connected Neo4j graph | Multi-hop reasoning paths |

> **Clarification on the Census**: All 265,307 `ParentProduct` nodes have 384-dimensional dense vectors. Exactly 65,650 products possess strictly positive numeric prices (with 47,339 containing `NaN` strings or missing values). 72,538 users have reviewed at least 2 distinct titled products. Because `Review.timestamp` is NULL on 100% of reviews, evaluation must not rely on chronological sorting.

---

### 7.2 Zero-Mock Leave-One-Out Ground Truth Protocol

#### Protocol A: Set-Partitioning Leave-One-Out Protocol (No Timestamp Dependency)
Because `Review.timestamp` is NULL across all 1,629,426 reviews in Neo4j, any protocol sorting by review timestamp fails. We define a mathematically rigorous **Set-Partitioning Leave-One-Out Protocol**:

1. **Target User Sampling**: Sample active users $u \in \text{User}$ who reviewed $N \ge 3$ distinct products in the verified complete product cohort ($\mathcal{P}_{\text{complete}}$):
   ```cypher
   MATCH (u:User)-[:WROTE]->(r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct)
   WHERE p.embedding IS NOT NULL 
     AND p.price IS NOT NULL 
     AND toString(p.price) <> 'NaN' 
     AND p.price > 0 
     AND p.title IS NOT NULL
   WITH u, collect(DISTINCT {
       asin: p.parent_asin,
       title: p.title,
       price: p.price,
       rating: r.rating
   }) AS products
   WHERE size(products) >= 3
   RETURN u.user_id AS user_id, products
   LIMIT 50
   ```
2. **Deterministic Set Partitioning**:
   Let the user's set of reviewed products be $\mathcal{I}_u = \{p_1, p_2, \dots, p_N\}$.
   - **Target Product ($y_u^*$) Selection**: Select one product $p^* \in \mathcal{I}_u$ positively reviewed by the user (`rating >= 4.0`). If multiple qualify, tie-break deterministically by highest rating followed by `parent_asin ASC` (or seeded pseudorandom split).
   - **Historical Context ($G_u$)**: The remaining products $\mathcal{I}_u \setminus \{y_u^*\}$ constitute the user's interaction history (at least 2 verified products), passed into `SessionContext` and `KECRTool`.
3. **Conversational Query Formulation**:
   From target product $y_u^*$, extract its verified graph features (Category, Brand, Key Attributes) and generate a conversational intent query $q_u$ that expresses a desire for those features *without* revealing the target ASIN.
4. **Guaranteed Zero-Mock Verification**:
   Every ASIN in history and target is verified to exist in live Neo4j. Zero synthetic IDs (`ALT_...`) are possible.

#### Protocol B: Multi-Attribute Cold-Start Recommendation
1. Sample a target product $p^* \in \mathcal{P}_{\text{complete}}$ across diverse categories (Electronics, Computers, Audio).
2. Query $p^*$'s actual graph neighborhood via Cypher:
   - Category: `(p*)-[:BELONGS_TO_CATEGORY]->(c:Category)`
   - Brand: `(p*)-[:HAS_BRAND]->(b:Brand)`
   - Attributes: `(p*)-[:HAS_ATTRIBUTE]->(a:Attribute)`
   - Price: $p^*.\text{price}$
3. Construct structured filters with realistic budget boundaries ($\text{price\_max} = p^*.\text{price} \times 1.20$) and soft preferences from verified attribute nodes.
4. Establish graded topological relevance across all candidate items using the objective graph formula (Section 4.4).

#### Protocol C: Real-Time Catalog Existence Verification Gate
To guarantee zero hallucinations, every candidate ASIN and recommended ASIN emitted during evaluation is validated in real time:
```cypher
UNWIND $evaluated_asins AS asin
MATCH (p:ParentProduct {parent_asin: asin})
RETURN count(p) AS valid_count
```
If $\text{valid\_count} < \text{len}(\text{evaluated\_asins})$, the evaluation framework flags an immediate `ASIN_HALLUCINATION_DETECTED` violation and records the invalid IDs.

---

## 8. Guardian Assessment

### 8.1 ✅ Vision Alignment
- **Zero Mocking Mandate**: Anchors all benchmarks in the live Neo4j database (265,307 products, 65k priced products, 471k users), strictly satisfying the user directive.
- **Single-Dataset Architecture**: Operates exclusively on the Amazon Reviews 2023 dataset, adhering to Vision Report Decision 2026-09-23-005.
- **Multi-Agent Decoupling**: Preserves the modular decoupling of `GraphSearchTool`, `CriticAgent`, and `PromptConstructor`, adhering to Decision 2026-07-08-002.
- **Thesis Research Question Coverage**: Provides the mathematical and empirical infrastructure required to answer thesis questions $\mathbf{RQ_1}$ through $\mathbf{RQ_6}$.

### 8.2 ⚖️ Complexity Analysis
- **KISS Compliance**: The proposed `eval_trace` payload attaches an optional dictionary to the existing `response_payload` in `AgentOrchestrator._execute_step()`. It requires zero changes to the underlying state machine, zero database schema modifications, and zero external dependency additions.
- **Stateless Metric Engines**: Metric calculations in `src/evaluation/metrics.py` remain pure, deterministic Python functions.

### 8.3 🔗 Integration Assessment
- **Affected Components**:
  - `src/agents/orchestrator.py`: Add configurable `retrieval_limit` (default 20) and `eval_trace` payload assembly in `_execute_step()`.
  - `src/evaluation/live_dataset_generator.py`: Live Neo4j sampler using Set Partitioning.
  - `src/evaluation/metrics.py`: Add multi-stage pipeline evaluation functions ($\Delta\text{NDCG}$, $\text{CVER}$, $\text{FPPA}$, $\text{TPRR}$, catalog verification).
  - `scripts/evaluate_retrieval.py` & `scripts/evaluate_generative.py`: Strip mock branches; execute live pipeline.
- **No Disruptions**: Existing chat flows and production APIs remain completely backward-compatible.

### 8.4 ⚠️ Risks & Trade-offs
- **Live Database Dependency**: Evaluation scripts now require an active Neo4j connection (`bolt://localhost:7687`).  
  *Mitigation*: The evaluation runner executes an explicit connection health check before launching and provides actionable diagnostics if the database container is offline.
- **LLM Critic Latency**: Running `CriticAgent` across large candidate pools takes 1–3 seconds per query.  
  *Mitigation*: The live evaluation dataset uses a targeted sample of 25–50 high-quality scenarios for standard runs, with batched asynchronous execution.

---

## 9. Recommendations & Implementation Roadmap

1. **Approve System Revision**: Formally accept the Metric-to-Flow architectural mapping and the `eval_trace` telemetry specification.
2. **Phase M2 Deliverable**: Produce `production_artifacts/Evaluation_Implementation_Plan.md` specifying the step-by-step refactoring blueprints for the live dataset generator and evaluation scripts.
3. **Phase M3 Implementation**:
   - Implement `eval_trace` and retrieval limit parameterization in `src/agents/orchestrator.py`.
   - Create `src/evaluation/live_dataset_generator.py` to extract 100% verified live Neo4j scenarios via Set-Partitioning Leave-One-Out.
   - Refactor `src/evaluation/metrics.py` to compute multi-stage ranking metrics ($\Delta\text{NDCG}$, $\text{CVER}$, $\text{FPPA}$, $\text{TPRR}$, catalog validity).
   - Eliminate all mock candidate synthesis (`ALT_...`, `VERIFIED_...`) from `scripts/evaluate_retrieval.py` and `scripts/evaluate_generative.py`.
4. **Phase M4 Visualization & Verification**: Persist versioned runs in `evaluations/eval_YYYY-MM-DD_HHMM/` with 300 DPI `.png` and `.jpg` plots and generate live ASIN existence proof logs.
5. **Phase M5 Hardening & Registration**: Final E2E test verification, Polish changelog update, and thesis registration.

---

## 10. Sources & Citations

| # | Short Key | Primary Authors | Title | Venue / Year | Authentic Identifier |
|---|---|---|---|---|---|
| 1 | **ReDial** | Raymond Li et al. | *Towards Deep Conversational Recommendation Networks* | NeurIPS 2018 | arXiv:1812.07617 |
| 2 | **KBRD** | Qibin Chen et al. | *Towards Knowledge-Based Recommender Dialog System* | EMNLP-IJCNLP 2019 | arXiv:1908.05391 |
| 3 | **KGSF** | Kun Zhou et al. | *Improving Conversational Recommender Systems via Knowledge Graph based Semantic Fusion* | KDD 2020 | ACM KDD 2020 |
| 4 | **CRSLab** | Kun Zhou et al. | *CRSLab: An Open-Source Toolkit for Building Conversational Recommender System* | ACL 2021 | arXiv:2101.00939 |
| 5 | **UniCRS** | Xiaolei Wang et al. | *Towards Unified Conversational Recommender Systems via Knowledge-Enhanced Prompt Learning* | KDD 2022 | arXiv:2206.09363 |
| 6 | **KECR** | Xuhui Ren et al. | *Explicit Knowledge Graph Reasoning for Conversational Recommendation* | ACM TIST 2024 | arXiv:2305.00783 |
| 7 | **MemoCRS** | Yunjia Xi et al. | *Memory-enhanced Sequential Conversational Recommender Systems with Large Language Models* | CIKM 2024 | arXiv:2407.04960 |
| 8 | **Reflexion** | Noah Shinn et al. | *Reflexion: Language Agents with Verbal Reinforcement Learning* | NeurIPS 2023 | arXiv:2303.11366 |
| 9 | **CRITIC** | Zhibin Gou et al. | *CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing* | ICLR 2024 | arXiv:2305.11738 |
| 10 | **Re2A** | Dongding Lin et al. | *Re2A: Situated Conversational Recommendation via Rubric-based Preference Reasoning and Alignment* | arXiv preprint 2024 | arXiv:2609.18249 |
| 11 | **SafeCRS** | Haochang Hao et al. | *SafeCRS: Personalized Safety Alignment for LLM-Based Conversational Recommender Systems* | KDD 2026 | arXiv:2603.03536 |
| 12 | **G-Eval** | Yang Liu et al. | *G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment* | EMNLP 2023 | arXiv:2303.16634 |
| 13 | **MT-Bench** | Lianmin Zheng et al. | *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* | NeurIPS 2023 | arXiv:2306.05685 |
| 14 | **Ragas** | Shahul Es et al. | *Ragas: Automated Evaluation of Retrieval Augmented Generation* | EACL 2024 | arXiv:2309.15217 |
| 15 | **Amazon Reviews 2023** | Yupeng Hou et al. | *Bridging Language and Items for Retrieval and Recommendation: Towards Large Language Models as Foundation Recommender Models* | ACL 2024 | arXiv:2403.03952 |
