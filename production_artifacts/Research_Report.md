# Research Report: R1 — Rank-Based Multi-Channel Fusion for Hybrid Retrieval (AFP-002)

**Date**: 2026-10-17
**Requested by**: User (`/implement` pipeline, release R1 of `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md`)
**Status**: Approved 2026-10-17 (Gate #1). Recorded as Vision Report decision 2026-10-17-013.
**Scope**: Work packages RS-01 (per-channel ranked lists + fusion), RS-05 (soft-bonus scale), RS-02 (review-channel ablation), RS-20 part (popularity-bias@K, type-precision@K)
**Previous report**: The 2026-10-06 SOTA CRS literature report previously at this path is preserved in git history (`git show e6593f7:production_artifacts/Research_Report.md`).

---

## 1. Research Questions

| # | Question |
|---|---|
| Q1 | How should many matches **of one product inside one channel** (many attributes, many reviews) be aggregated? |
| Q2 | How should **channels** (product, attribute, review) be fused? Options: RRF, convex combination, CombSUM/CombMNZ, AFP-002's adaptive late fusion. |
| Q3 | Where should fusion run (Cypher or Python), and how does it interact with the `WHERE` post-filter? |
| Q4 | How do the soft-preference bonus and the fusion score coexist? |
| Q5 | How can R1 be evaluated beyond hit rate on 21 queries? |

---

## 2. Findings

### Q1: Within-channel aggregation → **max (MaxP)**, not sum

- Today each channel effectively uses **SumP**: `sum(score)` over every matching attribute or review node. This is the source of hub bias (AFP-002 §1: Senso earbuds at 225.2; C920 at rank 253).
- In passage-based document ranking, Dai & Callan (SIGIR 2019) compared FirstP, MaxP and SumP for aggregating passage scores into a document score. **MaxP was the most effective**, and it has become the standard aggregation (Lin, Nogueira & Yates, *Pretrained Transformers for Text Ranking*, 2021).
- A product is the "document"; its attribute and review nodes are "passages". **Recommendation**: in each channel, a product's score is its single best match, and the product appears **once** in that channel's list.

### Q2: Cross-channel fusion → **RRF as default, convex combination as ablation**

| Method | Formula | Hub-safe | Needs score calibration | Needs tuning | Monotonic |
|---|---|---|---|---|---|
| CombSUM (today, with SumP) | Σ scores | ❌ | yes | — | yes |
| CombMNZ (Fox & Shaw, 1994) | Σ scores × #lists matched | ❌ (rewards volume more) | yes | — | yes |
| AFP-002 adaptive late fusion | Σ w·s / Σ w over channels present | ✅ | yes | weights | ❌ extra weaker evidence lowers the score |
| **RRF** (Cormack, Clarke & Büttcher, SIGIR 2009) | Σ_c w_c / (k + rank_c) | ✅ | **no** (ranks only) | k (default 60) | ✅ |
| Convex combination (CC) of normalised scores | Σ_c α_c · norm(s_c) | ✅ (with MaxP) | normalisation | α per channel | ✅ |

- **RRF** is scale-free. The product, attribute and review indexes hold different kinds of text, so their cosine distributions are not comparable, and ranks avoid calibrating them. A product found by several channels outranks one found by a single channel. This matches the user's agreement decision (roadmap P-4).
- **Guardian caveat:** Bruch, Gai & Ingber (*An Analysis of Fusion Functions for Hybrid Retrieval*, ACM TOIS 2023, arXiv:2210.11934) find that:
  - RRF is **sensitive to its parameters**;
  - a tuned **convex combination outperforms RRF**, in-domain and out-of-domain, and needs only a few labelled examples to tune;
  - CC is largely agnostic to the choice of normalisation.
- **Recommendation**:
  - Implement RRF as the default. It is parameter-light and sound before we have a tuning split.
  - Add CC (min-max normalised MaxP scores, fixed α) as an ablation arm from the **same per-channel lists**, which costs little.
  - Tune both (`k` for RRF, α for CC) only after R2 provides a tuning/test split, so nothing is fitted to the 21 test queries.
- **Absent-channel effect** (applies to RRF and CC alike): a product absent from a channel gets 0 from it. Only 2.2% of products have embedded reviews, so the review channel systematically favours that set. This is the reason for the **3-vs-2-channel ablation** (RS-02) and for **popularity-bias@K**.

### Q3: Fusion location and post-filter

- **Fuse in Python.** Run one Cypher query per channel, returning `(product id, best similarity)` after MaxP and after the `WHERE` filter. Then rank, fuse and sort in Python. Benefits:
  - the fuser is unit-testable without Neo4j;
  - per-channel ranks are available for `eval_trace` (the seed of the evidence ledger, RS-18);
  - the same lists feed RRF and CC.
- **Rank after filtering.** Rank inside each channel among products that pass the hard filters. Products removed by the filter then don't consume rank positions, and ranks reflect the eligible set. The ANN-then-filter recall loss itself is fixed in R3 (RS-07).
- **Ties:** one attribute node gives thousands of products the same similarity.
  - Use **competition ranking** (tied products share the best rank) so ties are treated fairly; the other channels then separate them.
  - Truncate each channel deterministically at a fixed depth (ordered by similarity, then `parent_asin`).
- The Neo4j 5.14 instance has no Cypher 25 `VECTOR SEARCH`. Keep `build_vector_search_query` (`db.index.vector.queryNodes`) and route the rule conflict to Vision decision D-4.

### Q4: Soft-preference bonus

- Today: `+0.2 × polarity` per substring match on title, brand or match reasons (`graph_search_tool.py` additive block). RRF scores lie in roughly [0.0, 0.05], so one brand match would outweigh the entire fusion.
- **Recommendation**: make the bonus proportional to the fusion scale. Express it as a fraction of the maximum attainable fused score (e.g. `β × max_fused`, β configurable, default 0.25 per matched preference). That way a soft match can reorder close candidates but cannot lift a product far above stronger fused matches. The alternative is to fuse it as a fourth ranked list; that is an R4 concern, where soft preferences become feature checks (RS-12).

### Q5: Evaluation beyond 21-query hit rate

- **Baseline caveat**: the aggregates in `eval_2026-10-09_1336/summary.json` are pooled over the three strategies (63 rows). The hybrid-only baseline, recomputed from `retrieval_metrics.json`, is HR@1 0.048, HR@5 0.190, HR@10 0.238, HR@20 0.381, strict NDCG@5 0.110, MRR 0.100.
- **popularity-bias@K**: the share of top-K products that belong to the review-embedded set (5,715 products, 2.2% of the catalogue). It directly measures the hub hypothesis and needs no target label.
- **type-precision@K**: the share of top-K products in the requested category. It catches the accessory trap (chargers returned for a phone request).
- **Regression checks** kept from AFP-002: C920 (`B006JH8T3S`) for `ret_021`; no runaway score for the Senso earbuds (`B01G8JO5F2`).
- **Arms**:
  - `sum` (baseline `eval_2026-10-09_1336`)
  - RRF with 3 channels
  - RRF with 2 channels
  - CC with 3 channels
  - weighted RRF (0.60/0.25/0.15)

---

## 3. Recommended Approach

1. Per-channel Cypher returns each product **once** with its **max** similarity, after hard filters.
2. Python fuser: competition-ranked lists → **RRF** (`k = 60`, equal weights, configurable) by default; **CC** and weighted RRF selectable for ablation.
3. Configurable channel set (product, attribute, review) for the 3-vs-2 ablation.
4. Soft bonus rescaled to the fused-score range (`β × max_fused`).
5. Per-channel rank, per-channel similarity and fused score on every item and in `eval_trace`.
6. `popularity-bias@K` and `type-precision@K` in `scripts/evaluate_retrieval.py`; live eval for all arms.

---

## 4. Guardian Assessment

| Check | Verdict |
|---|---|
| Vision §3.3 Hybrid Semantic-Structural Retrieval | ✅ Aligns: same indexes and filters, honest fusion |
| No custom model training | ✅ None (no learned parameters; any tuning in R2 is of 1–3 scalars) |
| Amazon Reviews 2023 only / KG grounding | ✅ Unchanged |
| Explainability (Vision §2) | ✅ Improves: per-channel ranks are a faithful record of why a product was retrieved |
| Approved AFP-002 | ⚠️ Deviates in method. RRF supersedes adaptive late fusion, which is non-monotonic; see the revision note in `Proposed_Fix_Vector_Aggregation.md`. Resolved by Vision decision 2026-10-17-013 (D-1). |
| `python-conventions.md` (Cypher 25 `VECTOR SEARCH`) | ⚠️ Not satisfiable on Neo4j 5.14; unchanged in R1, routed to D-4 |
| Risk | RRF may not beat a tuned CC (Bruch et al.). Mitigated by running CC as an arm from the same lists. |

**Codebase impact**:
- `src/tools/graph_search_tool.py`: `_execute_hybrid_search`, `_execute_vector_search`, additive scoring block.
- New fusion helper (e.g. `src/tools/score_fusion.py`).
- `scripts/evaluate_retrieval.py` and `src/evaluation/metrics.py`: new metrics and arms.
- New unit tests.
- `AgentOrchestrator` is unchanged, apart from passing fusion metadata into `eval_trace` if it isn't already forwarded.

---

## 5. Sources

- Cormack, Clarke & Büttcher (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods.* SIGIR.
- Bruch, Gai & Ingber (2023). [*An Analysis of Fusion Functions for Hybrid Retrieval*](https://arxiv.org/abs/2210.11934). ACM TOIS.
- Dai & Callan (2019). *Deeper Text Understanding for IR with Contextual Neural Language Modeling.* SIGIR. Summarised in Lin, Nogueira & Yates, [*Pretrained Transformers for Text Ranking: BERT and Beyond*](https://arxiv.org/pdf/2010.06467).
- Fox & Shaw (1994). *Combination of Multiple Searches.* TREC-2.
- Neo4j, [*Hybrid retrieval for GraphRAG applications using the GraphRAG Python package*](https://neo4j.com/blog/developer/hybrid-retrieval-graphrag-python-package/) (normalises per-index scores before merging).
- Project: `production_artifacts/action_items/Proposed_Fix_Vector_Aggregation.md`, `Retrieval_Score_Redesign_Roadmap.md`, `Live_Graph_Audit_2026-10-10.md`.
