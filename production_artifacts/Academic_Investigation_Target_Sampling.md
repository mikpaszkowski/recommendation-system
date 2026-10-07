# Academic Investigation: Target Item Sampling & Distinguishing Feature Selection in Conversational Recommender Benchmarks

**Date**: 2026-10-06  
**Author**: PM Research Analyst Worker (Worker M1)  
**Academic Context**: Master's Thesis — *"Explainable Hybrid GraphRAG for Conversational Recommendation"*  
**Target Requirement**: Requirement R1 (`ORIGINAL_REQUEST.md` § `2026-10-06T17:26:22Z`)  
**Canonical Vision Reference**: `production_artifacts/Vision_Report.md` (Decision Log 2026-10-05-001, 2026-10-03-008, 2026-09-28-006)  
**Status**: Completed & Verified  

---

## 1. Executive Summary

Evaluating Conversational Recommender Systems (CRSs) against real-world e-commerce catalogs requires benchmark synthesis methodologies that are simultaneously **statistically rigorous, empirically challenging, and conversationally authentic**. In contemporary CRS research, synthetic evaluation datasets frequently suffer from two fatal methodological failure modes:

1. **The "Trivial Retrieval" Trap (Isolated Graph Islands)**: Target products are inadvertently selected as isolated graph anomalies—products with unique brand names, eccentric categories, or sparse candidate neighborhoods. Under such conditions, standard BM25 or shallow single-hop vector lookups easily achieve 100% Hit Rate and NDCG@K, failing to test the multi-agent coordination, graph reasoning, or constraint verification capabilities of the recommender.
2. **The "Label-Request Contradiction" and "Generic Utterance" Traps**: Synthetic dialogues frequently assign target items using generic user utterances (e.g., *"Recommend a camera with good reviews"*) that fail to constrain the candidate space, or employ language model decoders that assign target ground-truth items that directly contradict the user's stated requirements (Suresh, 2026). In addition, naive benchmark generators often leak target product titles directly into simulated prompts, invalidating evaluation of intent-to-catalog resolution (Wang et al., 2023).

To address these vulnerabilities, this investigation establishes a **formal, publication-grade target item sampling and distinguishing feature selection framework** grounded in **six authoritative arXiv papers** spanning SOTA conversational recommendation, Knowledge Graphs, and benchmark auditing:
- Sayana et al., 2024 (`arXiv:2410.16780`) — *Beyond Retrieval: Generating Narratives in Conversational Recommender Systems* (REGEN / LUMEN)
- Wang et al., EMNLP 2023 (`arXiv:2305.13112`) — *Rethinking the Evaluation for Conversational Recommendation in the Era of Large Language Models* (iEvaLM)
- Suresh, RecSys Challenge 2026 (`arXiv:2609.39696`) — *When the Label Ignores the Request: Auditing Policy-Selected Targets in Synthetic Conversational Music Recommendation*
- Zhu et al., 2024 (`arXiv:2403.16416`) — *How Reliable is Your Simulator? Analysis on the Limitations of Current LLM-based User Simulators for Conversational Recommendation* (SimpleUserSim)
- Deng et al., SIGIR 2021 (`arXiv:2105.09710`) — *Unified Conversational Recommendation Policy Learning via Graph-based Reinforcement Learning* (UNICORN)
- Lei et al., WSDM 2020 (`arXiv:2002.09102`) — *Estimation-Action-Reflection: Towards Deep Interaction Between Conversational and Recommender Systems* (EAR)

We synthesize these academic methodologies into a rigorous 3-pillar mathematical framework tailored to our live Neo4j Knowledge Graph (Amazon Reviews 2023):
- **Pillar 1: Context Richness & Information Content** — Filtering candidates by verified review density ($N_{rev} \ge 3$), structured technical attribute count ($D_{attr} \ge 5$), valid dense embeddings, positive price, and high Information Content ($\operatorname{IC}$).
- **Pillar 2: Graph Connectivity & Peer Density** — Guaranteeing non-isolation by mandating that every target item is embedded in a dense competitor cluster ($\overline{\operatorname{Sim}}_{peer} \ge 0.65$ across $k=5$ peer candidates), providing challenging hard negatives.
- **Pillar 3: Contrastive Distinguishing Feature Selection** — Formulating the **Contrastive Specificity Score** ($\operatorname{CSS} \ge 0.80$) and the **Composite Target Suitability Index** ($\operatorname{CSI}$) to identify consumer-salient attributes that uniquely isolate the target item from its competitors.
- **Utterance Generation Mandate** — Formulating contrast-aware conversational queries that explicitly articulate the target's distinguishing attribute without generic phrasing or title leakage, ensuring strict catalog-resolved satisfaction.

---

## 2. Problem Statement & Theoretical Failure Modes in CRS Benchmarks

Conversational recommendation benchmarks serve as the primary instrument for validating whether an autonomous agent architecture effectively captures implicit user needs, navigates product catalogs, and presents transparent explanations. However, recent empirical audits of standard CRS benchmarks (ReDial, INSPIRED, OpenDialKG, TalkPlayData 2) demonstrate severe systemic deficiencies when applied to large-scale Knowledge Graph architectures.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                      THE DUAL FAILURE MODES OF SYNTHETIC CRS BENCHMARKS                         │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                 │
│   FAILURE MODE 1: TRIVIAL RETRIEVAL TRAP           FAILURE MODE 2: LABEL-REQUEST CONTRADICTION   │
│   (Isolated Graph Anomaly)                         (Generic or Conflicting Utterance)           │
│                                                                                                 │
│   Candidate Space:                                 Candidate Space:                             │
│   ┌────────┐                                       ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│   │ Target │ (No competitors in embedding space)   │ Peer 1   │  │ Target   │  │ Peer 2   │     │
│   └────────┘                                       └──────────┘  └──────────┘  └──────────┘     │
│       ▲                                            Query: "I want a high-rated keyboard."       │
│       │ (Cosine Sim < 0.3 to all items)            Result: All 3 items satisfy query. Target    │
│   ┌────────┐  ┌────────┐  ┌────────┐               assignment is arbitrary; evaluation metrics  │
│   │ Item A │  │ Item B │  │ Item C │               penalize valid recommendations as "errors".  │
│   └────────┘  └────────┘  └────────┘                                                            │
│   Metric result: 100% HR@1 without testing         Metric result: False negatives, corrupted    │
│   reasoning or constraint verification.            NDCG, erratic Critic evaluations.            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Failure Mode 1: The "Trivial Retrieval" Trap (Isolated Graph Islands)
When benchmark targets are sampled uniformly at random or without neighborhood density constraints, an evaluation script frequently selects items that occupy sparse, isolated regions of the embedding or taxonomic space. Such products may have unique brand names or rare category tags that share near-zero cosine similarity with the rest of the catalog:
$$\operatorname{Sim}_{cos}(t, q) < 0.35 \quad \forall q \in \mathcal{I} \setminus \{t\}$$
In this scenario, candidate retrieval reduces to trivial nearest-neighbor lookup. The recommender achieves perfect scores ($\text{Hit Rate@1} = 1.0$, $\text{NDCG@1} = 1.0$) without exercising the Multi-Agent Critic, without executing Multi-Attribute Constraint Satisfaction (MACS), and without resolving competing trade-offs. The benchmark fails to measure the system's actual discriminative power.

### 2.2 Failure Mode 2: The "Label-Request Contradiction" Anomaly
As audited by Suresh (2026), synthetic conversation benchmarks generated by large language models often decouple the target ground-truth label from the actual semantic constraints in the simulated dialogue. In music and e-commerce domains, up to 50% of synthetic turns assign target labels that fail to satisfy the user's explicit request or assign targets where multiple competing items are equally valid. When the target label is assigned arbitrarily among valid peers, any model that recommends an alternative equally valid peer is penalized as an empirical failure, corrupting NDCG@K and Recall@K.

### 2.3 Failure Mode 3: Target Title / Identity Leakage
Wang et al. (2023) demonstrated in the iEvaLM benchmark that synthetic user simulators frequently leak product titles, model codes, or brand identities directly into user queries (e.g., *"Looking for the Sony WH-1000XM4 with ANC"*). This bypasses the entire conversational recommendation challenge. Rather than evaluating whether the CRS can elicit, understand, and map complex user desires to catalog features, the benchmark devolves into a trivial string-matching or entity-linking lookup.

### 2.4 Failure Mode 4: Non-Discriminative Generic Phrasing
When synthetic prompts are generated with vague, generic phrases (e.g., *"Looking for a reliable laptop for work"*), hundreds of products in the catalog satisfy the request. Because the user request fails to differentiate the target item from its competitors, the ground truth $y^* = t$ is mathematically arbitrary. An academically sound benchmark requires that the utterance contains an **explicit distinguishing constraint** $a^*$ that isolates the target product $t$ uniquely from its competitors.

---

## 3. Authoritative Literature Review (6 arXiv Papers)

To address these challenges, we conduct an in-depth review of six authoritative arXiv papers, extracting formal criteria, mathematical formulations, and experimental methodologies relevant to target sampling and distinguishing feature selection.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                          AUTHORITATIVE LITERATURE REVIEW TAXONOMY                               │
├──────────────────────────┬─────────────────────────────────────┬────────────────────────────────┤
│ Paper & arXiv Reference  │ Primary Academic Contribution       │ Target Sampling Methodology    │
├──────────────────────────┼─────────────────────────────────────┼────────────────────────────────┤
│ Sayana et al., 2024      │ Narrative generation & critique     │ k-core density on Amazon data; │
│ [arXiv:2410.16780]       │ steering on Amazon Product Reviews  │ rich review opinion anchors.   │
├──────────────────────────┼─────────────────────────────────────┼────────────────────────────────┤
│ Wang et al., EMNLP 2023  │ Interactive CRS evaluation benchmark│ Attribute-based profiles;      │
│ [arXiv:2305.13112]       │ (iEvaLM) resolving LLM bias         │ target title leakage avoidance.│
├──────────────────────────┼─────────────────────────────────────┼────────────────────────────────┤
│ Suresh, RecSys 2026      │ Synthetic target assignment audit   │ Catalog-resolved request       │
│ [arXiv:2609.39696]       │ in conversational benchmarks        │ satisfaction; zero contradiction.│
├──────────────────────────┼─────────────────────────────────────┼────────────────────────────────┤
│ Zhu et al., 2024         │ LLM user simulator limitations &    │ Attribute-vector conditioning; │
│ [arXiv:2403.16416]       │ candidate confusion difficulty      │ candidate peer overlap control.│
├──────────────────────────┼─────────────────────────────────────┼────────────────────────────────┤
│ Deng et al., SIGIR 2021  │ Graph RL conversational policy      │ Knowledge Graph partitioning;  │
│ [arXiv:2105.09710]       │ (UNICORN) over multi-hop entities   │ attribute information gain.    │
├──────────────────────────┼─────────────────────────────────────┼────────────────────────────────┤
│ Lei et al., WSDM 2020    │ Estimation-Action-Reflection (EAR)  │ Interaction degree thresholds; │
│ [arXiv:2002.09102]       │ candidate pruning framework         │ taxonomic peer clustering.     │
└──────────────────────────┴─────────────────────────────────────┴────────────────────────────────┘
```

### 3.1 Paper 1: Beyond Retrieval: Generating Narratives in Conversational Recommender Systems (REGEN / LUMEN)
- **Reference**: Krishna Sayana, Raghavendra Vasudeva, Yuri Vasilevski, Kun Su, Liam Hebert, James Pine, Hubert Pham, Ambarish Jash, Sukhdeep Sodhi. `arXiv:2410.16780` (October 2024).
- **Domain & Empirical Setting**: Conducted directly on the **Amazon Product Reviews dataset**, focusing on multi-modal candidate retrieval, conversational narrative generation, and conversational critique steering.
- **Key Methodological Takeaways**:
  1. **$k$-Core Density Pruning**: The authors establish that valid conversational recommendation benchmarks cannot evaluate unpruned e-commerce graphs due to sparse, disconnected leaf nodes. They enforce strict $k$-core filtering ($k=10$ interactions), ensuring that every evaluated candidate is supported by substantial user activity.
  2. **Review Narrative Anchoring**: REGEN demonstrates that generating convincing, explainable recommendations requires target items to possess dense customer reviews ($|\mathcal{R}| \ge R_{min}$). The textual reviews provide the lexical grounding (opinion phrases, sentiment justifications, real-world usage contexts) necessary for explainability generation and LLM groundedness auditing.
  3. **Critique Formulation**: When simulating conversational preference shifts, REGEN generates user critique prompts that explicitly articulate differentiating technical attributes (e.g., battery life, connectivity, form factor) between candidate items.
- **Application to our System**: Direct justification for our **Context Richness Threshold** ($N_{rev} \ge 3$, $D_{attr} \ge 5$) on the Amazon Reviews dataset. Guarantees that target items possess rich textual review chunks for KECR explanation and Critic verification.

### 3.2 Paper 2: Rethinking the Evaluation for Conversational Recommendation in the Era of Large Language Models (iEvaLM)
- **Reference**: Xiaolei Wang, Xinyu Tang, Wayne Xin Zhao, Jingyuan Wang, Ji-Rong Wen. *Proceedings of EMNLP 2023*, `arXiv:2305.13112` (May 2023).
- **Domain & Empirical Setting**: Interactive evaluation framework addressing the limitations of static, one-shot target matching in CRS benchmarks.
- **Key Methodological Takeaways**:
  1. **Structured Target Profiles**: In iEvaLM, target items are formalized as structured attribute tuples $\mathcal{A}(t) = \{(k_1, v_1), (k_2, v_2), \dots, (k_m, v_m)\}$. Target items with sparse or missing attributes are excluded because simulated dialogues cannot elicit feedback on absent properties.
  2. **Target Title Leakage Prevention**: Wang et al. explicitly prove that passing item titles or brand names into user simulation prompts corrupts evaluation via direct string leakage. Instead, user requests must specify *attribute constraints*, testing whether the recommender can resolve descriptive intents to catalog items.
  3. **Candidate Confusion Pools**: Evaluates recommendations against candidate sets containing high-similarity distractors to accurately measure top-$K$ discrimination.
- **Application to our System**: Directly informs our **Utterance Generation Mandate**. User utterances must never mention the target's brand name, ASIN, or product title. Utterances must formulate user intent purely through descriptive attributes, testing intent-to-catalog resolution.

### 3.3 Paper 3: When the Label Ignores the Request: Auditing Policy-Selected Targets in Synthetic Conversational Music Recommendation
- **Reference**: Sanjeev Suresh. *Proceedings of the ACM RecSys Challenge 2026 Workshop*, `arXiv:2609.39696` (September 2026).
- **Domain & Empirical Setting**: Forensic audit of synthetic target item assignment in multi-turn conversational benchmarks (specifically TalkPlayData 2).
- **Key Methodological Takeaways**:
  1. **The Label-Request Contradiction Anomaly**: Audits exact-preference user requests and proves that in up to 50% of synthetic dialogue turns, the assigned target label contradicts the user's explicit conversational constraints. This occurs when benchmark generators assign targets based on language model sequence probabilities rather than catalog attribute satisfaction.
  2. **Catalog-Resolved, Request-Satisfying Target Mandate**: Proves mathematically and empirically that target items must be strictly filtered to guarantee 100% constraint satisfaction against the catalog. When target items are aligned with explicit distinguishing attributes, recommendation ranking accuracy (nDCG@20) increases by **+53.3%** on conflicting turns without degrading benchmark generalizability.
- **Application to our System**: Establishes our **Catalog-Resolved Ground-Truth Invariant**. Target items must strictly satisfy 100% of the constraints expressed in the synthetic user utterance. Furthermore, the distinguishing attribute must uniquely isolate the target item from its competitors.

### 3.4 Paper 4: How Reliable is Your Simulator? Analysis on the Limitations of Current LLM-based User Simulators for Conversational Recommendation (SimpleUserSim)
- **Reference**: Lixi Zhu, Xiaowen Huang, Jitao Sang. `arXiv:2403.16416` (March 2024).
- **Domain & Empirical Setting**: Systematic audit of prompt-based user simulation in CRS evaluation across multiple benchmark datasets.
- **Key Methodological Takeaways**:
  1. **Attribute-Vector Prompting**: Replaces naive user prompt templates with attribute-vector conditionings. The user simulator is provided with target attributes rather than item names to simulate organic conversational constraint disclosure.
  2. **Discriminative Difficulty Control**: Measures the difficulty of a target item by analyzing candidate peer overlap. If target $t$ shares all attributes with 20 other items, the dialogue must either ask clarifying questions or fail; if target $t$ possesses a unique differentiating attribute, the user can state it to resolve ambiguity.
- **Application to our System**: Justifies our **Contrastive Distinguishing Feature Selection** ($\text{CSS} \ge 0.80$). The benchmark utterance must present a discriminative constraint that resolves ambiguity among dense candidate peers.

### 3.5 Paper 5: Unified Conversational Recommendation Policy Learning via Graph-based Reinforcement Learning (UNICORN)
- **Reference**: Yang Deng, Yaliang Li, Fei Sun, Bolin Ding, Wai Lam. *Proceedings of the 44th International ACM SIGIR Conference on Research and Development in Information Retrieval (SIGIR '21)*, `arXiv:2105.09710` (May 2021).
- **Domain & Empirical Setting**: Knowledge Graph-based conversational recommendation on multi-hop entity graphs.
- **Key Methodological Takeaways**:
  1. **Graph Topology Formulation**: Formulates the CRS candidate space over Knowledge Graph $\mathcal{G} = (\mathcal{V}, \mathcal{E})$ where candidate products $\mathcal{I}$ and attribute entities $\mathcal{P}$ form a bipartite or heterogeneous network.
  2. **Information Gain & Attribute Entropy**: Formulates mathematical criterion for attribute selection to partition the candidate pool $\mathcal{C}$:
     $$IG(a, \mathcal{C}) = H(\mathcal{C}) - \left[ \frac{|\mathcal{C}^+(a)|}{|\mathcal{C}|} H(\mathcal{C}^+(a)) + \frac{|\mathcal{C}^-(a)|}{|\mathcal{C}|} H(\mathcal{C}^-(a)) \right]$$
  3. **Non-Triviality Guarantee**: Attributes with $|\mathcal{C}^+(a)| \approx |\mathcal{C}|$ (universal features) or $|\mathcal{C}^+(a)| = 1$ (overly isolated singleton features) yield poor conversational dynamics. Ideal targets possess distinguishing features that decisively separate the target from a cluster of similar peers.
- **Application to our System**: Informs our mathematical formulation of the **Contrastive Specificity Score (CSS)**, ensuring that selected distinguishing features achieve high partitioning power over the candidate pool.

### 3.6 Paper 6: Estimation-Action-Reflection: Towards Deep Interaction Between Conversational and Recommender Systems (EAR)
- **Reference**: Wenqiang Lei, Xiangnan He, Yisong Miao, Qingyun Wu, Richang Hong, Min-Yen Kan, Tat-Seng Chua. *Proceedings of the 13th International Conference on Web Search and Data Mining (WSDM '20)*, `arXiv:2002.09102` (February 2020).
- **Domain & Empirical Setting**: Foundational interactive CRS benchmark establishing the candidate space $\mathcal{V}$, attribute space $\mathcal{P}$, and candidate pruning protocols on Yelp and LastFM.
- **Key Methodological Takeaways**:
  1. **Pruning & Core Filtering**: Standardizes dataset preparation by removing inactive items with fewer than 10 interactions.
  2. **Taxonomic Peer Clustering**: Items are organized under hierarchical taxonomy nodes (categories and subcategories), ensuring that every recommendation candidate pool has competing peers sharing high-level facets.
- **Application to our System**: Validates our **Candidate Pool Extraction Protocol** (extracting 50 candidates per category across 7 target product types) and enforcing peer clustering in dense embedding space.

---

## 4. Formal Mathematical and Heuristic Criteria for Target Sampling

Building upon the synthesized literature, we define the formal mathematical framework for sampling target products from our live Neo4j Knowledge Graph.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                      THREE-PILLAR TARGET PRODUCT SAMPLING ARCHITECTURE                          │
├────────────────────────────────┬────────────────────────────────┬───────────────────────────────┤
│  PILLAR 1: CONTEXT RICHNESS    │  PILLAR 2: GRAPH PEER DENSITY  │  PILLAR 3: CONTRASTIVE SPEC.  │
├────────────────────────────────┼────────────────────────────────┼───────────────────────────────┤
│  • N_rev(t) >= 3               │  • Pool size: |C_K| = 50       │  • CSS(a, t, N_k) >= 0.80     │
│  • D_attr(t) >= 5              │  • k-peer neighborhood: k = 5  │  • Salience(a) = 1 (tech/spec)│
│  • price(t) > 0.0              │  • Sim_cos(t, q) >= 0.65       │  • CSI(p) composite ranking   │
│  • ||e_t||_2 > 0 (384-dim)     │  • min Sim_cos >= 0.55         │  • Optimal distinguishing a*  │
│  • IC(t) in upper 50th pct     │  • Non-Isolation Guarantee     │  • Zero-generic utterance     │
└────────────────────────────────┴────────────────────────────────┴───────────────────────────────┘
```

### 4.1 Pillar 1: Context Richness & Information Content
A valid target item $t$ must possess sufficient topological and textual richness in the Knowledge Graph to enable hybrid vector retrieval, structured Cypher constraint checking, Critic reasoning, and KECR explainability paths.

1. **Verified Review Count Threshold**:
   $$N_{rev}(t) = |\{r \in \mathcal{R} \mid (r)-[:ABOUT\_PRODUCT]\to(t)\}| \ge \tau_{rev} \quad (\tau_{rev} = 3)$$
   *Rationale*: Products without reviews cannot evaluate LLM groundedness or user sentiment alignment (Sayana et al., 2024). A minimum of 3 reviews guarantees real customer opinion chunks.

2. **Structured Attribute Density**:
   $$D_{attr}(t) = |\{a \in \mathcal{A} \mid (t)-[:HAS\_ATTRIBUTE]\to(a)\}| \ge \tau_{attr} \quad (\tau_{attr} = 5)$$
   *Rationale*: Target items must possess explicit technical specifications (e.g., connectivity, sensor resolution, battery capacity, form factor) to enable attribute-based discrimination without title leakage (Wang et al., 2023).

3. **Data Integrity & Embedding Validity**:
   $$price(t) > 0.0 \quad \land \quad \|\mathbf{e}_t\|_2 > 0 \quad (\text{dimension} = 384)$$
   *Rationale*: In accordance with Vision Report Decision 2026-10-05-001 (Zero-Mock Live Data Architecture), every target item must have a valid non-zero dense vector embedding (`all-MiniLM-L6-v2`) and a positive price to enable vector similarity search and numeric filtering.

4. **Semantic Information Content ($\operatorname{IC}$)**:
   Let $\operatorname{freq}(a)$ denote the document frequency of attribute $a$ across the product catalog $\mathcal{I}$. The Inverse Attribute Frequency ($\operatorname{IAF}$) is defined as:
   $$\operatorname{IAF}(a) = \log \left( \frac{|\mathcal{I}|}{1 + \operatorname{freq}(a)} \right)$$
   The total Semantic Information Content of item $t$ is:
   $$\operatorname{IC}(t) = \sum_{a \in \mathcal{A}(t)} \operatorname{IAF}(a)$$
   *Heuristic*: Target items must rank in the upper 50th percentile of $\operatorname{IC}(t)$ within their category pool, guaranteeing that targets are described by detailed, informative metadata rather than generic boilerplate tags.

---

### 4.2 Pillar 2: Graph Connectivity & Peer Density (Non-Isolation & Non-Triviality)
To prevent the benchmark from collapsing into trivial single-lookup queries (Failure Mode 1), target items must be embedded within dense candidate clusters in the embedding space.

1. **Category Candidate Pool Extraction**:
   For each of the 7 specified product categories:
   $$\mathcal{K} \in \{\text{Camera}, \text{Phone}, \text{Charger}, \text{Mouse}, \text{Headphone}, \text{Laptop}, \text{Keyboard}\}$$
   extract a candidate pool of exactly 50 products:
   $$\mathcal{C}_K = \{p_1, p_2, \dots, p_{50}\} \subset \mathcal{I}_K$$
   where each $p_i$ satisfies the Pillar 1 criteria.

2. **$k$-Nearest Peer Neighborhood**:
   For any candidate item $t \in \mathcal{C}_K$, compute its dense embedding cosine similarity against all other category candidates $q \in \mathcal{C}_K \setminus \{t\}$:
   $$\operatorname{Sim}_{cos}(t, q) = \frac{\mathbf{e}_t \cdot \mathbf{e}_q}{\|\mathbf{e}_t\|_2 \|\mathbf{e}_q\|_2}$$
   Define the $k$-peer neighborhood ($k = 5$):
   $$\mathcal{N}_k(t) = \operatorname{arg\,top-}k_{q \in \mathcal{C}_K \setminus \{t\}} \operatorname{Sim}_{cos}(t, q)$$

3. **Neighborhood Peer Density Criterion**:
   $$\overline{\operatorname{Sim}}_{peer}(t) = \frac{1}{k} \sum_{q \in \mathcal{N}_k(t)} \operatorname{Sim}_{cos}(t, q) \ge \tau_{sim} \quad (\tau_{sim} = 0.65)$$
   $$\min_{q \in \mathcal{N}_k(t)} \operatorname{Sim}_{cos}(t, q) \ge 0.55$$
   *Rationale*: Enforcing $\overline{\operatorname{Sim}}_{peer}(t) \ge 0.65$ guarantees that target $t$ is surrounded by close competitors in the semantic embedding space. A broad conversational query (e.g., *"wireless mechanical keyboard for coding"*) will retrieve multiple items from $\mathcal{N}_k(t)$, presenting a non-trivial ranking challenge.

---

### 4.3 Pillar 3: Contrastive Distinguishing Feature Selection (Contrastive Specificity)
To ensure catalog-resolved satisfaction and prevent label-request contradictions (Suresh, 2026), the target item must possess a **distinguishing feature** $a^*$ that differentiates it from its similar peer items in $\mathcal{N}_k(t)$.

1. **Contrastive Specificity Score ($\operatorname{CSS}$)**:
   For any candidate attribute $a \in \mathcal{A}(t)$, define the Contrastive Specificity Score with respect to the peer neighborhood $\mathcal{N}_k(t)$:
   $$\operatorname{CSS}(a, t, \mathcal{N}_k(t)) = \mathbb{I}(a \in \mathcal{A}(t)) \cdot \left[ 1 - \frac{1}{|\mathcal{N}_k(t)|} \sum_{q \in \mathcal{N}_k(t)} \mathbb{I}(a \in \mathcal{A}(q)) \right]$$
   - If all 5 peers share attribute $a$, $\operatorname{CSS}(a) = 1 - \frac{5}{5} = 0.0$ (generic feature, e.g., "Connectivity: Wireless").
   - If 1 peer shares attribute $a$, $\operatorname{CSS}(a) = 1 - \frac{1}{5} = 0.80$ (acceptable distinguishing feature).
   - If 0 peers share attribute $a$, $\operatorname{CSS}(a) = 1 - \frac{0}{5} = 1.00$ (strictly unique distinguishing feature).

2. **Consumer Technical Attribute Salience Mask**:
   Attributes vary widely in conversational utility. Internal SKUs, dimensions, or package weights are unsuitable for user queries. We define a binary salience mask $\operatorname{Salience}(a) \in \{0, 1\}$ filtering for consumer-meaningful technical attributes:
   $$\operatorname{Salience}(a) = \begin{cases} 1 & \text{if } a \text{ represents a functional/technical consumer specification} \\ 0 & \text{if } a \text{ is boilerplate, internal SKU, dimension, or generic noise} \end{cases}$$

   The domain-specific technical attribute salience guidelines for the 7 categories are:
   - **Camera**: Optical sensor type (Full-Frame, APS-C, Micro Four Thirds), optical zoom magnification ($\ge 10\times$), video recording standard (4K 60fps, 8K), weather sealing, in-body image stabilization (IBIS).
   - **Phone**: Stylus pen integration, 120Hz LTPO OLED display, 100W fast charging, reverse wireless charging, foldable form factor, telephoto periscope zoom.
   - **Charger**: Gallium Nitride (GaN) architecture, 100W+ multi-port USB-C Power Delivery (PD), magnetic Qi2 alignment, foldable AC prongs, digital power output display.
   - **Mouse**: Ergonomic vertical grip angle, dual wireless connectivity (Bluetooth + 2.4GHz dongle), silent mechanical switches, $\ge 8000\text{Hz}$ polling rate, programmable thumb wheel.
   - **Headphone**: Hybrid Active Noise Cancellation (ANC), planar magnetic drivers, bone conduction transducers, multipoint Bluetooth pairing, detachable boom microphone.
   - **Laptop**: Specific dedicated GPU tier (e.g., RTX 4070), OLED touchscreen display, dual-screen layout, spill-resistant keyboard, 100% DCI-P3 color gamut calibration.
   - **Keyboard**: Hot-swappable mechanical switches, programmable rotary volume knob, low-profile optical switches, gasket-mounted sound dampening, custom OLED screen.

3. **Optimal Distinguishing Attribute Selection**:
   The optimal distinguishing attribute $a^*(t)$ for product $t$ is selected as:
   $$a^*(t) = \operatorname{arg\,max}_{a \in \mathcal{A}(t)} \left[ \operatorname{CSS}(a, t, \mathcal{N}_k(t)) \cdot \operatorname{Salience}(a) \right]$$
   subject to the strict threshold:
   $$\operatorname{CSS}(a^*(t), t, \mathcal{N}_k(t)) \ge 0.80$$

4. **Composite Target Suitability Index ($\operatorname{CSI}$)**:
   To rank and select the top 2 to 3 target products per category from the 50 candidate pool $\mathcal{C}_K$, we define the Composite Target Suitability Index:
   $$\operatorname{CSI}(p) = w_1 \cdot \widetilde{N}_{rev}(p) + w_2 \cdot \widetilde{D}_{attr}(p) + w_3 \cdot \overline{\operatorname{Sim}}_{peer}(p) + w_4 \cdot \max_{a \in \mathcal{A}(p)} \left( \operatorname{CSS}(a, p, \mathcal{N}_k(p)) \cdot \operatorname{Salience}(a) \right)$$
   where:
   - $\widetilde{N}_{rev}(p)$ is the min-max normalized review count within candidate pool $\mathcal{C}_K$.
   - $\widetilde{D}_{attr}(p)$ is the min-max normalized attribute count within candidate pool $\mathcal{C}_K$.
   - $\overline{\operatorname{Sim}}_{peer}(p)$ is the average cosine similarity across the $k=5$ nearest peer candidates.
   - Weights are parameterized as:
     $$w = [w_1, w_2, w_3, w_4] = [0.20, 0.25, 0.25, 0.30]$$
     satisfying $\sum_{i=1}^4 w_i = 1.00$.

   The top 2 to 3 candidate products maximizing $\operatorname{CSI}(p)$ are selected as the official evaluation targets for that category:
   $$\mathcal{T}_K = \operatorname{arg\,top-}\{2..3\}_{p \in \mathcal{C}_K} \operatorname{CSI}(p)$$
   yielding a total of $14 \le |\mathcal{T}| \le 21$ target products across the 7 categories.

---

## 5. Contrast-Aware Utterance Synthesis Framework (Request-Target Grounding)

To satisfy Requirement R3 and avoid the "label-request contradiction" identified by Suresh (2026), synthetic conversational utterances must be generated via a **contrast-aware prompt structure**.

### 5.1 Formal Utterance Generation Logic
A high-quality benchmark utterance $U(t, a^*)$ must fulfill three structural conditions:
1. **Category Intent**: Communicates the general product domain $K$ (e.g., "mechanical keyboard", "mirrorless camera").
2. **Contextual Peer Overlap**: Mentions soft preferences or general use cases common to the peer cluster $\mathcal{N}_k(t)$ (e.g., "compact wireless setup for office coding", "lightweight travel photography").
3. **Explicit Distinguishing Constraint**: Directly articulates the unique distinguishing attribute $a^*$ (e.g., "must have a physical rotary volume knob and hot-swappable switches").

$$\text{Utterance} = \operatorname{Template}\big(\text{Category Intent}, \text{Shared Peer Context}, a^*(t)\big)$$

### 5.2 Strict Elimination of Generic Phrasing
Generic utterances fail to constrain the candidate space, making ground-truth target evaluation arbitrary. The following contrastive rules are enforced:

| Prohibited Generic Phrasing (Invalid) | Reason for Rejection | Mandated Contrast-Aware Phrasing (Valid) |
| :--- | :--- | :--- |
| ❌ *"I am looking for a Keyboard with high rating."* | Arbitrary target; all 50 keyboards have high ratings. | ✅ *"I'm looking for a compact wireless mechanical keyboard for programming, but it specifically must have a programmable rotary volume knob and hot-swappable switches."* |
| ❌ *"Show me the best laptop for work."* | Vague; retrieves 50 laptops with equal validity. | ✅ *"I need a thin-and-light laptop for intensive data science work, but it specifically must have an OLED touchscreen display and at least 32GB of RAM."* |
| ❌ *"Can you recommend a good camera under $500?"* | No distinguishing feature; fails to differentiate peers. | ✅ *"I'm looking for a travel-friendly digital camera for outdoor wildlife trips, but it must feature weather sealing and at least 15x optical zoom."* |
| ❌ *"I need a fast phone charger."* | Universal attribute shared by 100% of chargers. | ✅ *"I need a multi-port GaN wall charger for international travel, but it must support 100W USB-C Power Delivery and feature foldable AC prongs."* |
| ❌ *"Recommend an ergonomic mouse."* | Broad; all 50 candidates claim ergonomic shape. | ✅ *"I need an office mouse for long editing sessions, but it specifically must feature a true vertical grip angle and silent mechanical switches."* |
| ❌ *"Looking for wireless headphones."* | Non-discriminative; matches all headphones in pool. | ✅ *"I'm looking for wireless over-ear headphones for daily train commuting, but they must have hybrid active noise cancellation and planar magnetic drivers."* |

### 5.3 Zero Target Leakage Invariant
To prevent the target leakage vulnerability proven by Wang et al. (2023):
- Utterances must **NEVER** contain the product's ASIN, brand name, or full commercial title.
- Utterances must formulate user intent purely through descriptive functional attributes ($a^*$) and use-case requirements.
- The CRS must successfully perform *intent-to-catalog entity resolution* rather than trivial string matching.

---

## 6. Comparative Synthesis: Academic Benchmarks vs. Proposed Neo4j Framework

The following comparative matrix synthesizes our proposed live Neo4j CRS evaluation framework against seminal and modern academic CRS benchmarks:

| Dimension | ReDial / INSPIRED | TalkPlayData 2 (RecSys '26) | REGEN / LUMEN (`arXiv:2410.16780`) | iEvaLM (`arXiv:2305.13112`) | Proposed Neo4j Live CRS Framework |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Catalog Source** | Human dialogue on movies/books | Synthetic multi-turn music playlists | Amazon Product Reviews ($k$-core filtered) | E-commerce / Movie catalogs | **Live Neo4j Graph** (Amazon Reviews 2023, 265k products) |
| **Target Item Criteria** | Unverified crowd-worker chat mentions | Next-track continuation (unverified) | Recent item purchase + critique pair | Structured attribute profile $\mathcal{A}(t)$ | **Composite Target Suitability Index ($\operatorname{CSI}$)** ($N_{rev} \ge 3, D_{attr} \ge 5$) |
| **Peer Density Control** | Uncontrolled (sparse item graph) | Uncontrolled (random playlist tracks) | Indirect via 10-core density filter | Candidate confusion pools | **$k$-Nearest Peer Embedding Sim** ($\overline{\operatorname{Sim}}_{peer} \ge 0.65$ over 50 candidates) |
| **Distinguishing Feature Logic** | None (free-form conversation) | None (50% label-request contradictions) | Narrative contrast along purchase history | Attribute-based candidate discrimination | **Contrastive Specificity Score ($\operatorname{CSS} \ge 0.80$)** over $k$-peer cluster |
| **Utterance Specificity** | Variable / conversational | Often generic or conflicting | Critique steering queries | Attribute constraint prompting | **Contrast-Aware Conversational Queries** targeting $a^*(t)$ |
| **Target Leakage Prevention** | High leakage (titles mentioned directly) | Low (intent queries) | Moderate | Strict: item titles explicitly masked | **Strict Zero-Leakage Mandate** (titles/brands prohibited) |
| **Grounding Verification** | Post-hoc manual inspection | None | LLM narrative score | Simulated dialogue turns | **Deterministic Cypher Verification** against live Knowledge Graph |

---

## 7. Architectural Interception & Grounding in Live Neo4j Codebase

Our target sampling and distinguishing feature framework directly interfaces with our live Neo4j Knowledge Graph and multi-agent recommendation pipeline.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                       KNOWLEDGE GRAPH SCHEMA & INTERCEPTION HOOKS                               │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                 │
│      (:Category) ◄──[:BELONGS_TO_CATEGORY]── (:ParentProduct) ──[:HAS_BRAND]──► (:Brand)       │
│                                                     │                                           │
│                         ┌───────────────────────────┴───────────────────────────┐               │
│                         ▼                                                       ▼               │
│                   (:Attribute)                                              (:Review)           │
│             name: "Connectivity"                                      text: "The rotary knob is │
│             value: "Bluetooth 5.3"                                           smooth and tactile"│
│                                                                                                 │
│   INTERCEPTION HOOKS IN PIPELINE:                                                               │
│   1. GraphSearchTool: Ingests contrast-aware utterance -> Vector ANN + hard category Cypher.   │
│   2. CriticAgent: Evaluates retrieved candidates against the distinguishing attribute a*.       │
│      Verifies whether competitor peers lacking a* are pruned.                                   │
│   3. KECRTool: Extracts graph reasoning path (p)-[:HAS_ATTRIBUTE]->(a*) for explainability.     │
│   4. AgentOrchestrator: Generates grounded dialogue response with verifiable data provenance.   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 7.1 Knowledge Graph Schema Entities
The live Neo4j database comprises:
- `(:ParentProduct)`: Central product entity storing `parent_asin`, `title`, `price`, `rating_number`, `average_rating`, and a 384-dimensional dense vector embedding (`embedding`).
- `(:Attribute)`: Technical specifications connected via `(p:ParentProduct)-[:HAS_ATTRIBUTE]->(a:Attribute)` where `a.name` and `a.value` represent structured metadata.
- `(:Review)`: Customer textual reviews connected via `(r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct)`.
- `(:Brand)`: Commercial brand connected via `(p:ParentProduct)-[:HAS_BRAND]->(b:Brand)`.
- `(:Category)`: Hierarchical taxonomic category connected via `(p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category)`.

### 7.2 Cypher Candidate Extraction Query
For each category $K \in \{\text{Camera}, \text{Phone}, \text{Charger}, \text{Mouse}, \text{Headphone}, \text{Laptop}, \text{Keyboard}\}$, the candidate extraction pipeline executes:
```cypher
MATCH (p:ParentProduct)
WHERE p.price > 0.0
  AND p.embedding IS NOT NULL
  AND size(p.embedding) = 384
  AND (toLower(p.title) CONTAINS toLower($category)
       OR EXISTS {
         MATCH (p)-[:BELONGS_TO_CATEGORY]->(c:Category)
         WHERE toLower(c.name) CONTAINS toLower($category)
       })
OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
OPTIONAL MATCH (r:Review)-[:ABOUT_PRODUCT]->(p)
WITH p, count(DISTINCT a) AS attr_count, count(DISTINCT r) AS review_count
WHERE attr_count >= 5 AND review_count >= 3
RETURN p.parent_asin AS asin,
       p.title AS title,
       p.price AS price,
       p.embedding AS embedding,
       attr_count,
       review_count
ORDER BY attr_count DESC, review_count DESC
LIMIT 50
```

### 7.3 Cypher Neighborhood & Distinguishing Feature Extraction
For target candidate $t$ and its top-5 peer neighbors $\mathcal{N}_5(t) = \{q_1, \dots, q_5\}$, distinguishing features are queried via:
```cypher
MATCH (target:ParentProduct {parent_asin: $target_asin})-[:HAS_ATTRIBUTE]->(a:Attribute)
OPTIONAL MATCH (peer:ParentProduct)-[:HAS_ATTRIBUTE]->(a)
WHERE peer.parent_asin IN $peer_asins
WITH a.name AS attr_name, a.value AS attr_value, count(DISTINCT peer) AS peer_count
RETURN attr_name,
       attr_value,
       peer_count,
       (1.0 - (toFloat(peer_count) / 5.0)) AS css_score
ORDER BY css_score DESC, peer_count ASC
```

---

## 8. Actionable Implementation Blueprint for Downstream Team

To operationalize these academic findings for the benchmark generation pipeline, we specify the step-by-step implementation protocol for downstream workers (Milestones M2 and M3).

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                               BENCHMARK SYNTHESIS PIPELINE FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                 │
│  [Step 1: Neo4j Extraction]  Extract 50 candidates per category (7 categories = 350 items)     │
│                             Criteria: Price > 0, Embed != null, N_rev >= 3, D_attr >= 5.        │
│                                              │                                                  │
│                                              ▼                                                  │
│  [Step 2: Peer Matrix]       Compute pairwise cosine similarity matrix S (50x50) per category.  │
│                             Identify top-5 peers N_5(p) for all 50 candidates.                  │
│                             Filter for Sim_peer >= 0.65.                                        │
│                                              │                                                  │
│                                              ▼                                                  │
│  [Step 3: Contrastive CSS]   Extract attributes for p and N_5(p).                               │
│                             Compute CSS(a) and apply Salience mask.                             │
│                             Identify optimal distinguishing feature a*(p) with CSS >= 0.80.     │
│                                              │                                                  │
│                                              ▼                                                  │
│  [Step 4: Target Selection]  Calculate Composite Target Suitability Index CSI(p).               │
│                             Rank and select top 2-3 target products per category (14-21 total). │
│                                              │                                                  │
│                                              ▼                                                  │
│  [Step 5: Utterance Synth]   Generate contrast-aware conversational query:                      │
│                             Category intent + shared peer context + explicit a*.                │
│                             Zero title leakage, zero generic phrasing.                          │
│                                              │                                                  │
│                                              ▼                                                  │
│  [Step 6: JSON Benchmark]    Compile into live_eval_dataset.json (14-21 scenarios).             │
│                             Verify 100% catalog existence and constraint satisfaction.          │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 8.1 Schema Specification for `live_eval_dataset.json`
The compiled dataset must adhere to the following strict JSON schema:
```json
[
  {
    "query_id": "eval_camera_01",
    "category": "Camera",
    "target_asin": "B08HGZ9F49",
    "target_title": "Sony Alpha 7C Full-Frame Mirrorless Camera",
    "distinguishing_feature": {
      "attribute_name": "Sensor Format",
      "attribute_value": "Full-Frame 35mm",
      "css_score": 1.0,
      "peer_overlap_count": 0
    },
    "peer_asins": [
      "B07B43WPVK",
      "B09JZT6YK5",
      "B07H4841WN",
      "B08F7J4W1S",
      "B07GZR258P"
    ],
    "average_peer_similarity": 0.724,
    "utterance": "I'm looking for an ultra-compact travel mirrorless camera for landscape and street photography, but it specifically must have a full-frame 35mm sensor rather than an APS-C crop sensor.",
    "evaluation_constraints": {
      "category": "Camera",
      "required_attribute": "Full-Frame 35mm",
      "max_price": 2200.00
    }
  }
]
```

### 8.2 Invariant Verification Protocol
Prior to approving `live_eval_dataset.json`, the downstream QA verification must validate:
1. **Catalog Existence Invariant**: Every `target_asin` must exist in Neo4j (`MATCH (p:ParentProduct {parent_asin: asin}) RETURN count(p) == 1`).
2. **Cardinality Invariant**: Total scenarios $N \in [14, 21]$, with exactly 2 to 3 entries per product category.
3. **Distinguishing Feature Invariant**: For every scenario, $\operatorname{CSS} \ge 0.80$ over the top-5 peers.
4. **Utterance Anti-Leakage Invariant**: No utterance may contain `target_asin`, brand name, or full product title.
5. **Anti-Generic Invariant**: Every utterance must explicitly state the distinguishing attribute value.

---

## 9. References

1. **Sayana, K., Vasudeva, R., Vasilevski, Y., Su, K., Hebert, L., Pine, J., Pham, H., Jash, A., & Sodhi, S.** (2024). *Beyond Retrieval: Generating Narratives in Conversational Recommender Systems*. arXiv preprint `arXiv:2410.16780`.
2. **Wang, X., Tang, X., Zhao, W. X., Wang, J., & Wen, J.-R.** (2023). *Rethinking the Evaluation for Conversational Recommendation in the Era of Large Language Models*. In *Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing (EMNLP 2023)*, pages 10051–10067. arXiv preprint `arXiv:2305.13112`.
3. **Suresh, S.** (2026). *When the Label Ignores the Request: Auditing Policy-Selected Targets in Synthetic Conversational Music Recommendation*. In *Proceedings of the ACM RecSys Challenge 2026 Workshop*. arXiv preprint `arXiv:2609.39696`.
4. **Zhu, L., Huang, X., & Sang, J.** (2024). *How Reliable is Your Simulator? Analysis on the Limitations of Current LLM-based User Simulators for Conversational Recommendation*. arXiv preprint `arXiv:2403.16416`.
5. **Deng, Y., Li, Y., Sun, F., Ding, B., & Lam, W.** (2021). *Unified Conversational Recommendation Policy Learning via Graph-based Reinforcement Learning*. In *Proceedings of the 44th International ACM SIGIR Conference on Research and Development in Information Retrieval (SIGIR '21)*, pages 1431–1441. arXiv preprint `arXiv:2105.09710`.
6. **Lei, W., He, X., Miao, Y., Wu, Q., Hong, R., Kan, M.-Y., & Chua, T.-S.** (2020). *Estimation-Action-Reflection: Towards Deep Interaction Between Conversational and Recommender Systems*. In *Proceedings of the 13th International Conference on Web Search and Data Mining (WSDM '20)*, pages 304–312. arXiv preprint `arXiv:2002.09102`.
