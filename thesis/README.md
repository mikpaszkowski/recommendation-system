# Master's Thesis Scientific Contribution Registry

> **Thesis Title**: *Explainable Hybrid GraphRAG for Conversational Recommendation*  
> **Canonical Vision Reference**: [`production_artifacts/Vision_Report.md`](../production_artifacts/Vision_Report.md)  
> **Evaluation Rubric & Skill**: [`.agents/skills/thesis_evaluator/SKILL.md`](../.agents/skills/thesis_evaluator/SKILL.md)  
> **Auditing Agent**: `@thesis-evaluator`  

---

## Purpose

This registry catalogs all codebase innovations, architectural mechanisms, and empirical artifacts that satisfy the **10-Point Academic Rubric** and qualify as substantive scientific contributions for the Master's Thesis document.

Each contribution is documented in a dedicated markdown file conforming to the naming pattern:
```
thesis/<N>-doc-<one-two-words>.md
```
where `<one-two-words>` is a 1–2 word slug describing the scientific scope.

---

## Academic Contribution Index

| # | Document | Scope | Research Question ($RQ$) | Primary Thesis Chapter | Status |
|---|---|---|---|---|---|
| 1 | [`1-doc-dialogue-state.md`](./1-doc-dialogue-state.md) | `dialogue-state` | $\mathbf{RQ_1}$: Impact of canonical dialogue state representation and constraint reconciliation on attribute hallucination and constraint adherence | Chapter 3: System Architecture & Dialogue State Modeling | ✅ Documented |
| 2 | [`2-doc-preference-benchmark.md`](./2-doc-preference-benchmark.md) | `preference-benchmark` | $\mathbf{RQ_2}$: Impact of Few-Shot and guided CoT vs Zero-Shot prompting on constraint schema compliance and intent accuracy | Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |
| 3 | [`3-doc-robust-retrieval.md`](./3-doc-robust-retrieval.md) | `robust-retrieval` | $\mathbf{RQ_3}$: Improvement in retrieval yield and precision via Waterfall Entity Resolution, Schema Injection, and EAV numeric modeling compared to zero-shot LLM-to-Cypher generation | Chapter 4: Hybrid GraphRAG Retrieval & Multi-Agent Verification | ✅ Documented |
| 4 | [`4-doc-hybrid-scoring.md`](./4-doc-hybrid-scoring.md) | `hybrid-scoring` | $\mathbf{RQ_4}$: Decoupling boundaries vs preferences via additive scoring and MACS progressive relaxation to improve Recall@K and eliminate the Boolean 'Recall Cliff' | Chapter 4: Hybrid Semantic-Structural Retrieval & Knowledge Representation | ✅ Documented |
| 5 | [`5-doc-synthesized-grounding.md`](./5-doc-synthesized-grounding.md) | `synthesized-grounding` | $\mathbf{RQ_5}$: Impact of a multi-agent verification loop (CriticAgent) coupled with Synthesized Grounding prompt logic on explanation coherence and semantic violations | Chapter 4: Explainable Hybrid GraphRAG Generation | ✅ Documented |
| 6 | [`6-doc-orthogonal-gating.md`](./6-doc-orthogonal-gating.md) | `orthogonal-gating` | $\mathbf{RQ_6}$: To what extent does Orthogonal Gating of exponentially-decayed historical graph paths and immediate conversational evidence improve recommendation explainability and ranking metrics (NDCG@K) compared to single-context retrieval methods? | Chapter 4: Hybrid GraphRAG Retrieval & Multi-Agent Verification | ✅ Documented |
| 7 | [`7-doc-evaluation-framework.md`](./7-doc-evaluation-framework.md) | `evaluation-framework` | $\mathbf{RQ_7}$: Decoupled two-tiered evaluation of GraphRAG candidate retrieval (Tier 1 IR ranking) vs. LLM generative explanation (Tier 2 with Hard Dilution Cap) for failure mode detection and benchmark reproducibility | Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |
| 8 | [`8-doc-catalog-stratification.md`](./8-doc-catalog-stratification.md) | `catalog-stratification` | $\mathbf{RQ_8}$: To what extent does retrieval accuracy degrade on long-tail items? | Chapter 4: Experimental Methodology | ✅ Documented |
| 9 | [`9-doc-pipeline-alignment.md`](./9-doc-pipeline-alignment.md) | `pipeline-alignment` | $\mathbf{RQ_9}$: To what extent does aligning the evaluation execution pipeline with the live multi-agent conversational architecture improve metric integrity and edge-case telemetry compared to bypassed single-turn IR evaluation? | Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |
| 10 | [`10-doc-fusion-ablation.md`](./10-doc-fusion-ablation.md) | `fusion-ablation` | $\mathbf{RQ_{10}}$: In multi-index GraphRAG retrieval with graph-node fan-out, to what extent do per-channel MaxP and rank-based fusion reduce hub bias in the top-K, and does ranking quality change when the LLM-extracted request is held fixed? (Methodological Artifact; coverage bias reduced, no measurable hit-rate change on n = 21) | Chapter 4: Hybrid Semantic-Structural Retrieval; Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |
| 11 | [`11-doc-evaluation-protocol.md`](./11-doc-evaluation-protocol.md) | `evaluation-protocol` | $\mathbf{RQ_{11}}$: Which conclusions about multi-channel fusion and constraint adherence in an LLM-driven GraphRAG CRS remain supportable under same-request pre-registered paired tests, three-valued (satisfied / violated / unknown) constraint verdicts and provenance-verified citable runs? (Methodological Artifact; no primary comparison significant on n = 21 tuning-side queries, as predicted; two-valued scoring would reverse the arm order) | Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |
| 12 | [`12-doc-clarification-gating.md`](./12-doc-clarification-gating.md) | `clarification-gating` | $\mathbf{RQ_{12}}$: Are clarification turns caused by extraction failure rather than underspecification, and can a domain-agnostic head-noun rule plus a fail-closed, self-declared `product_type_decided` flag remove spurious CLARIFY without guessing on vague requests? (Methodological Artifact, narrow; spurious CLARIFY 0/21 in 3 citable runs, in-sample; null-rule negative result; clarification recall not yet measured) | Chapter 3: Dialogue State Modeling; Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |
| 13 | [`13-doc-graph-integrity.md`](./13-doc-graph-integrity.md) | `graph-integrity` | $\mathbf{RQ_{13}}$: To what extent do silent construction defects in the grounding KG (data-less ghost products with identical embeddings, zeroed review fields, held-out interactions in the review evidence) distort coverage statistics and retrieval conclusions, and which conclusions change under a catalogue-first, split-aware, gate-validated, version-stamped rebuild with code, benchmark and model fixed? (Methodological Artifact, rubric 60/90 + PASS (was 54/90). v1 defects measured, including 12.5% of the v1 review input being official valid/test pairs and up to 35% of citable v1 top-10 slots held by metadata-less ghost nodes. **Update 2026-10-20**: v2 built and validated (18/18 gates; untitled 104,281 → 8; review-embedded coverage 2.2% → 99.995%). The v1 → v2 re-baseline on legacy-21 shows no significant change for any arm (all $p_{Holm} \ge 0.875$; rrf3 MRR +0.093, CI [−0.004, +0.208]). Explanations are untested hypotheses, see §7) | Chapter 3/4: Knowledge Graph Construction; Chapter 5: Experimental Methodology & Threats to Validity | ✅ Documented (updated 2026-10-20) |
| 14 | [`14-doc-stratified-benchmark.md`](./14-doc-stratified-benchmark.md) | `stratified-benchmark` | $\mathbf{RQ_{14}}$: To what extent does title-blind conversational query synthesis and query-time review masking expose retrieval vulnerabilities across distinct catalog strata ($S_0$–$S_4$), and does down-weighting review channels in Reciprocal Rank Fusion mitigate review-cap bias without statistically significant recall degradation? (Methodological Artifact and Empirical Benchmark; rubric 86/90 + PASS; 251 queries across 158 Taxons; review masking rescues 7 items, $+4.76\text{ pp}$ HR@20; bias metrics $p < 0.004$; exposes Taxon hierarchy recall cliff) | Chapter 4: Hybrid Semantic-Structural Retrieval; Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |
| 15 | [`15-doc-taxonomic-lexical-fusion.md`](./15-doc-taxonomic-lexical-fusion.md) | `taxonomic-lexical-fusion` | $\mathbf{RQ_{15}}$: To what extent does combining variable-depth taxonomic subtree matching (`[:BROADER*0..7]`), taxonomic progressive generalization, and 4-channel Reciprocal Rank Fusion ($RRF_4$) with an online BM25 lexical channel overcome the title-blind retrieval collapse in hybrid GraphRAG recommender systems? (Algorithmic & Empirical Contribution; rubric 88/90 + PASS; $HR@20 +10.48\text{ pp}$, $p = 0.0010$, $95\%\text{ CI } [+0.0476, +0.1619]$ on $n = 105$; strata $S_0$–$S_4$ yield triples from $9.52\%$ to $27.38\%$) | Chapter 4: Hybrid Semantic-Structural Retrieval; Chapter 5: Empirical Evaluation & Comparative Analysis | ✅ Documented |

## Evaluation Summary
- **Total Thesis Documents**: 15
- **Active Research Questions**: $\mathbf{RQ_1}$ … $\mathbf{RQ_{15}}$
- **Latest Evaluated Scope (2026-10-20, Stage 1 — Graph v2 Structural & Lexical Consumption: `GV2-07` … `GV2-09`)**:
  - **Verdict**: QUALIFIES: Algorithmic & Empirical Contribution (**Contribution 15: `15-doc-taxonomic-lexical-fusion.md`**).
  - **Artifacts**: `src/tools/graph_search_tool.py`, `src/tools/score_fusion.py`, `src/knowledge_graph/graphdb/resolver_service.py`, `evaluations/benchmarks/r2b_tuning_report.json`, `tests/test_stage1_taxon_and_lexical.py`.
  - **Key Findings**: Resolving intent against 1,183 `:Taxon` nodes with Cypher variable-length traversal (`[:IN_TAXON]->(:Taxon)-[:BROADER*0..7]->(:Taxon)`) and adding a 4th full-text Lucene BM25 channel ($RRF_4$) triples title-blind candidate yield ($0.0952 \to 0.2738$) and achieves statistically significant gains across all metrics ($\Delta HR@20 = +10.48\text{ pp}$, $p = 0.0010$; $\Delta NDCG@10 = +0.0260$, $p = 0.0213$; $\Delta MRR = +0.0292$, $p = 0.0002$ on $n = 105$).
- **Previous Evaluated Scope (2026-10-20, Release R2b — Stratified Benchmark v2 & RS-02/RS-25 Tuning)**:
  - **Verdict**: QUALIFIES: Methodological Artifact & Primary Empirical Benchmark (**Contribution 14: `14-doc-stratified-benchmark.md`**).
  - **Artifacts**: `evaluations/benchmarks/benchmark_v2.json` (251 queries: 200 across $S_0$–$S_4$, 30 ambiguous, 21 legacy; SHA-256 `3ae073ff...`), `evaluations/benchmarks/benchmark_v2_manifest.json`, `evaluations/benchmarks/r2b_tuning_report.json`.
  - **Key Findings**: Lexical leakage elimination reduces apparent recall from $90.5\%$ to $9.5\%$ on $S_0$–$S_4$, isolating coarse Category vs. Taxon hierarchy mismatch; query-time review masking ($G\text{-}9$) establishes review-channel attribution ($\Delta\text{HR@20} = +4.76\text{ pp}$, 7 unique rescues); redefined bias metrics (`review_cap_bias@5`, `head_popularity_bias@5`) resolve the $1.000$ saturation flaw on Graph v2 ($p < 0.004$).
- **Previous Evaluated Scope (2026-10-20, Stage 0 Graph v2 Consumption Package: `GV2-01` … `GV2-06`)**:
  - **Verdict**: Software Engineering / Methodological Hardening (**DOES NOT QUALIFY** as a standalone new thesis chapter under Criterion 4 Anti-Triviality / Plumbing Filter).
  - **Scope & Academic Alignment**: Closes the theoretical vs. implementation gaps in **Contribution 5 (`5-doc-synthesized-grounding.md`)** and **Contribution 6 (`6-doc-orthogonal-gating.md`)**:
    - `GV2-01`: Rich Graph v2 textual attributes (`features`, `details_text`, `description`, `avg_rating`) wired to `CriticAgent` and `PromptConstructor`, resolving the blind rejection flaw (previously 8/21 queries in benchmark suffered 100% Critic candidate pruning).
    - `GV2-02`: Review sorting by `r.helpful_vote DESC, r.timestamp DESC` in per-product subquery (`AI-06`).
    - `GV2-03`: Multi-value Cypher predicates for `brands[]` and `categories[]`.
    - `GV2-04`: Unit-variation deduplication in additive scoring (`128`, `128GB`, `128 GB` award $\le 1\times$ bonus).
    - `GV2-05`: Critic fail-closed enforcement on error (`is_recommended=false`), top-3 RRF partial match fallback with Critic rejection caveats on `rejected_all`, and forwarding of `relaxed_constraints` to generation for transparent disclosure.
    - `GV2-06`: Removal of fabricated 5.0★ rating fallback in KECR Cypher query and clarification of deterministic Cypher evidence path extraction vs. trained neural model.
  - **Documentation Action**: Updated `thesis/5-doc-synthesized-grounding.md` (§6) and `thesis/6-doc-orthogonal-gating.md` (§6) with dated hardening notes; 9 regression tests in `tests/test_stage0_graph_v2_wiring.py`.
- **Previous Evaluated Scope (2026-10-20, graph v2 executed)**: the graph v2 build, validation, stamp and v1 → v2 re-baseline (`64ef49b` … `65a0ba0`; records in `graph_versions/v2/`). The results are added to contribution 13 as a dated §7, and the 2026-10-19 text is unchanged.
  - **Gates**: 18/18 hard gates passed. Ghost signature 0, held-out pairs 0, untitled products 8; `GraphVersion` v2 stamped at commit `0a32604`.
  - **Re-baseline**: three citable v2 runs (`eval_2026-10-20_1114`, `_1128`, `_1142`, commit `4248d03`) against the archived v1 runs. No arm changes significantly (paired randomization, Holm). The rrf3 gain and the falls of vector_only and cypher_only are within the noise at n = 21.
  - **New v1 fact (F-10)**: metadata-less nodes held 35% of vector_only and 10% of rrf3 top-10 slots in the citable v1 runs.
  - **Qualification**: category resolution differs for 12 of 21 queries between the graphs. A v1 → v2 difference is attributable to the graph as a whole, not to ghost filling alone.
  - **Execution findings**: four pipeline defects (MPS memory, a non-scaling full-text smoke test, string-matched write-back, a driver parameter clash), two of which passed the 5% pilot. All were fixed before validation and stamping.
  - **Rubric**: 54 → 60/90 (criteria 6, 7, 8 +1; criterion 9 +2; criterion 10 +1). The verdict is unchanged: Methodological Artifact.
- **Earlier Evaluated Scope (2026-10-19, graph v2 code)**: the uncommitted graph v2 rebuild (Vision 2026-10-19-018 … 021). It is code only, audited PASS WITH FIXES (`production_artifacts/Audit_Report_Graph_Rebuild.md`), and not executed against Neo4j. It is registered as contribution 13. Its v1 facts are measured, and its v2 effects are hypotheses until the graph is built and the v1 baseline is re-run at a fixed commit.
- **Graph-version rule (FR-028/029)**: a live run is citable only on a graph with one validated `GraphVersion` node. The archived R2a runs stay citable as **graph v1 evidence**; new runs on v1 are not citable. Since 2026-10-20 the citable **graph v2 evidence** is `eval_2026-10-20_1114`, `_1128` and `_1142`.
- **Correction notes added 2026-10-20 (graph v2 executed)**. Results were not rewritten. The notes point to doc 13 §7 and `graph_versions/v2/baseline_comparison.json`:
  - `8-doc-catalog-stratification.md` (C-4 … C-6): the v2 recount is now possible but not yet done. Category nodes fall from 71 to 38, and category resolution differs for 12 of 21 queries. Stratum S1 "cold" has about 13 candidates on v2 (G-9 redefinition pending for R2b). Review-node counts are capped at 20, so popularity strata must use the metadata `review_count`.
  - `10-doc-fusion-ablation.md` (C-8 … C-11): the v1 → v2 arm re-baseline shows no significant change. Coverage bias@K is 1.000 for every arm on v2 and no longer separates arms. The 4.7%-coverage premise of the RS-02 rule no longer holds. Two v1 confounds are noted: the category-resolution shift, and ghost nodes in v1 top-10 lists (F-10).
  - `11-doc-evaluation-protocol.md` (C-4 … C-8): the FR-029 predicate was exercised on the first v2 runs, and `cypher_only` illustrates why the exact randomization test is primary. Table 5 and the RS-02 input are v1-only. Category resolution affects type-precision across versions. v2 catalogue price coverage is 43%. S1 has about 13 candidates.
  - Docs 3, 4, 6, 7 and 12: unchanged. Their 2026-10-19 notes still hold, and the v2 execution does not invalidate them further.
- **Correction notes added 2026-10-19 (graph v2 evaluation)**, following Vision 2026-10-19-021. Results were not rewritten:
  - `3-doc-robust-retrieval.md`: the EAV numeric schema never existed on the live graph (no `numeric_value`, only 4 attribute keys). The Lucene tier and HyDE corrections are restated.
  - `4-doc-hybrid-scoring.md`: numeric soft and hard specs never ran live; the `price IS NULL` boundary admitted v1 ghosts.
  - `6-doc-orthogonal-gating.md`: temporal decay had no valid input (v1 timestamps 0) and the historical half yields no paths; v2 makes AI-03 feasible.
  - `7-doc-evaluation-framework.md`: on v1, Groundedness conflates hallucination with missing listing text; citability now needs a validated graph version.
  - `8-doc-catalog-stratification.md`: counts cover only the titled 61% of products; the coarse-taxonomy claim was a v1 ingest artefact; substring noise.
  - `10-doc-fusion-ablation.md` (C-7): the attribute channel held only colour, material, style and size; the review sample was not helpfulness-ordered; coverage bias@K needs redefinition on v2.
  - `11-doc-evaluation-protocol.md`: `citable` certified provenance, not graph validity; the predicate is extended; §4.4 and §4.5 figures are v1 quantities.
  - `12-doc-clarification-gating.md`: unchanged, because its existing graph-version limitation already covers the change and no claim is invalidated.
- **Citation rule (Vision 2026-10-18-015)**: thesis text cites only archived runs with `citable: true`. The R1-era runs in `evaluations_archive/` (`eval_2026-10-09_1336`, `_2026-10-17_1846`, `_2026-10-17_1937`) are `citable: false` legacy context.
- **Assessed in R2a, not registered as a standalone contribution**: the R2a exit-gate retrieval results (no pre-registered comparison significant; `wrrf3` vs `sum_legacy` significant after Holm but with untuned weights on tuning-side data). They are reported as the results section of contribution 11 and as the citable replication in contribution 10's correction note.
- **Note on contribution 4**: The unbounded vector term $S_{vec}$ (multi-index `sum(score)`) described in `4-doc-hybrid-scoring.md` is superseded by the bounded fused score of contribution 10. It survives only as the `sum_legacy` control arm.
- **Correction to contribution 10 (2026-10-19)**: its coverage-bias base rate (2.15%, all nodes) is dominated by ghost nodes; the titled base rate is 0.52% (841 / 161,026), so the R1 bias is about 4× stronger than stated. A dated correction note (C-1 … C-6, including the graph-v1 scope of decision 2026-10-19-021) was added; the original numbers are unchanged.

---

## Master's Thesis Chapter Mapping

* **Chapter 1: Introduction & Research Motivation**
  * Problem statement: Hallucinations, lack of verifiable grounding, and cold-start in Conversational Recommender Systems (CRS).
  * System Vision: Explainable Hybrid GraphRAG with Multi-Agent Orchestration.
* **Chapter 2: State of the Art & Related Work**
  * Evolution of CRS: Collaborative Filtering $\rightarrow$ Deep Sequential Models $\rightarrow$ LLM Conversational Agents $\rightarrow$ GraphRAG.
  * Baseline paradigms: Matrix Factorization (`scikit-surprise`), Content-Based (`lightfm`), Vector-only retrieval vs. Structured Graph retrieval.
* **Chapter 3: System Architecture & Dialogue State Modeling**
  * Session Context modeling & Pydantic state representations (`session_schema.py`).
  * Bidirectional downstream adapters (`session_adapter.py`).
  * Dialogue State Management & Multi-turn preference accumulation (`dialogue_manager.py`).
  * Attribution and gating of clarification decisions: head-noun extraction rule, category recovery before clarifying, fail-closed `product_type_decided` flag (`orchestrator.py`, contribution 12).
* **Chapter 4: Hybrid GraphRAG Retrieval & Multi-Agent Verification**
  * Dense vector embedding of graph nodes + dynamic Cypher structural constraints.
  * Critic Agent & Knowledge-Enhanced Conversational Reasoning (KECR).
  * Path-based explainability & data provenance.
  * Fan-out-invariant multi-channel fusion (per-channel MaxP, Reciprocal Rank Fusion, bounded soft-preference bonus) and channel-level retrieval provenance (`score_fusion.py`).
  * Grounding-graph integrity: catalogue-first, split-aware, deterministic KG construction with lineage, 18 hard validation gates and a `GraphVersion` stamp (`src/knowledge_graph/graph_v2/`, contribution 13).
* **Chapter 5: Empirical Evaluation & Comparative Analysis**
  * Same-request fusion arm replay (`eval_trace.search_request`) and the label-free coverage-bias@K metric with catalogue base rate.
  * Claim-bounded evaluation protocol: three-valued constraint-satisfaction@K (gold and request flavours), pre-registered paired randomization / bootstrap / McNemar / Wilson / Holm statistics with explicit denominators, citable-run provenance and the git-tracked `evaluations_archive/` (contribution 11).
  * Clarification attribution metrics: category-extraction recall (parser-only, pipeline), spurious-CLARIFY rate by reason, target-admitting category rate (contribution 12).
  * Data validity as a precondition of citability: the ghost-product finding, held-out-interaction leakage into review evidence, version-bound citable runs, and the pre-registered v1 → v2 re-baseline protocol (contribution 13).
  * Stratified benchmark v2 and query-time review masking: title-blind conversational utterance synthesis, multi-strata evaluation ($S_0$–$S_4$), query-time review masking ($G\text{-}9$) for true cold-start measurement, bias metric redefinition (`review_cap_bias@K`, `head_popularity_bias@K`) on dense knowledge graphs, and RS-02/RS-25 empirical fusion tuning (contribution 14).
  * Two-Tiered Evaluation Architecture (`src/evaluation/`, `scripts/evaluate_*.py`).
  * Full pipeline alignment and edge-case telemetry (telemetry capture of conversational actions without artificially corrupting IR ranking metrics).
  * Tier 1 Recommendation & Retrieval Quality ($NDCG@K$, $HitRate@K$, $MRR@K$, $MAP@K$ across $K \in \{1, 3, 5, 10, 20\}$).
  * Tier 2 Inverted CoT LLM-as-a-Judge (Groundedness with Hard Dilution Cap, Explainability with fake provenance penalty, Coherence, Recoverability).
  * Versioned execution persistence and 300 DPI publication-grade visual analytics.
  * Ablation studies & baseline comparisons (Amazon Reviews 2023 unified splits).
* **Chapter 6: Conclusion & Future Research**
  * Summary of contributions and verified hypotheses.
