# Intent: Retrieval Score Redesign (AFP-002 and follow-ups)

**Source**: brainstorm session 2026-10-10 → 2026-10-17 (`.memlog.md` in this folder, 192 entries, Creative Partner mode).
**Branch**: `feature/afp-002-vector-aggregation`.
**Canonical copy**: `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` (full work-package catalogue RS-01 … RS-22).
**Downstream**: `/implement` pipeline (@pm-research → @pm-specs → @engineer → @qa → @historian → @doc-cleaner).

## Problem

The retrieval score should measure *how well a product matches what the user asked for*. Today it measures *how many pieces of text about the product look a bit like the query*:

- `GraphSearchTool._execute_hybrid_search` / `_execute_vector_search` (`src/tools/graph_search_tool.py:243`, `:299`) union three vector indexes (product ×1.0, attribute ×0.8, review ×0.9, `k = limit × 30`) and `sum(score)` per product.
- One attribute node links to up to 20,969 products, and only 5,715 products (2.2%) have embedded reviews. Products with many attributes or embedded reviews therefore collect many small scores and outrank the target (hub bias).
- The WHERE filter runs after the ANN search, so recall is lost and MACS relaxation fires.
- Live baseline `eval_2026-10-09_1336`: HR@1 0.079, HR@5 0.127, HR@20 0.206, NDCG@5 0.100, MRR 0.099.

## Design Principles (decided by the user)

1. **Three layers**: what the product IS (type), what it HAS/DOES (features), and how it is EXPERIENCED (reviews).
2. **Unknown ≠ zero**, applied as an order: confirmed > unknown > contradicted. Missing evidence is never scored as a mismatch.
3. **Channel roles**: product embeddings FIND, attributes FIND (a recall channel for sparse titles), reviews VERIFY and never find candidates.
4. **Ranking order**: feature fit first, channel agreement (found by several channels) second, review experience third. Each level only breaks ties left by the level above. Agreement wins only between products with equal feature fit.
5. **The LLM reranker** (final 20–30 candidates) may remove clear non-matches and reorder. Every removal or move cites a reason from the product's evidence. On error, the deterministic order is used.
6. **Fit and quality are separate axes.** The best fit is shown even when its reviews are bad. The well-loved alternative is shown next to it, with the reason.
7. **Training is allowed** when it improves quality or speed. This needs a Vision Report decision via @pm-research.

## Roadmap

| Release | Scope (work-package #) | Depends on | Exit gate |
|---|---|---|---|
| **R1 (this branch)** | #1 RRF fusion, #5 soft-bonus rescale, #2 review-channel ablation, popularity-bias@K + type-precision@K | — | Live eval vs `eval_2026-10-09_1336` |
| R2 | #21 stratified benchmark (cold / sparse-title / accessory-trap / trade-off) + tuning/test split + leakage check; #20 constraint-satisfaction@K | R1 metrics | Benchmark frozen before any weight tuning |
| R3 | #7 adaptive filter-first vs ANN-first by filter selectivity; #3 attribute IDF + AND within category; #8 query views (raw, HyDE via merged AI-07 call = AI-10 ablation, IS/HAS pieces); #10 graded category distance | R1 fuser, R2 benchmark | Per-arm ablation on the R2 test split |
| R4 | #12 full-text feature check (synonyms, negation → confirmed / contradicted / unknown) → #4 tiered ranking; #9 product type + "accessory for X"; #17 batched LLM rerank (AI-08); #6 absolute gate + masking calibration | R3 | type-precision@K, constraint-satisfaction@K, correct-abstention rate |
| R5 | #11 typed feature vocabulary + local-LLM span-grounded labelling (replaces #12 inputs); #13 review aspect pipeline (product vs noise sentences, complaint vs opinion aspects, minimum mentions + Bayesian share, distilled classifier); #18 evidence ledger | R4; Vision decision on training | Label precision/recall audit (~200 products) |
| Later (Meta-Phase B) | #16 preference edges, #19 two lanes + "we don't carry it", #14 complement edges, #15 doc2query | R4–R5 | — |

## R1 Intent (input for the spec)

**Goal**: remove hub bias by replacing `sum(score)` with Reciprocal Rank Fusion over per-channel ranked lists.

**Requirements**
1. Each channel (product, attribute, review) yields one ranked list in which **each product appears once**, ranked by its best (max) similarity in that channel.
2. Fusion: `RRF(p) = Σ_c w_c / (k + rank_c(p))`, default `k = 60`, equal weights. Channel weights (AFP-002's 0.60/0.25/0.15) are run as a weighted-RRF ablation, not as the default.
3. Apply this to both `_execute_hybrid_search` and `_execute_vector_search`. Prefer fusing in Python from the channel results so it can be unit-tested and the per-channel ranks can be logged.
4. Rescale the soft-preference bonus (`graph_search_tool.py:152–184`, currently `+0.2 × polarity` per match) so it cannot dominate an RRF score of ~0.016–0.033, or fuse it as its own ranked list.
5. Ablation switch: RRF over three channels vs two (without the review channel).
6. Write each candidate's per-channel ranks and RRF score into `eval_trace`. This is the first column of the future evidence ledger.
7. Add **popularity-bias@K** (share of top-K from the 5,715 review-embedded products vs their 2.2% catalog share) and **type-precision@K** to `scripts/evaluate_retrieval.py`.
8. Use parameterized Cypher only. Do not change MACS or Critic behaviour in R1.

**Acceptance**
- Unit tests: a product matched by many attribute/review nodes gets no more credit than one match per channel. RRF ordering and the soft-bonus scale are covered.
- Live eval (`--mode live`, Anaconda Python) beats `eval_2026-10-09_1336` on HR@20, and popularity-bias@K drops. Report the result honestly if it does not improve.
- Results are reported for both arms: 3 channels vs 2.

**Open spec questions**
- Rank each channel before or after the WHERE post-filter? (The full fix for post-filtering is R3 #7.)
- Tie-breaking in the attribute channel, where one attribute gives thousands of tied products. A product-embedding tie-break is the candidate. The full fix is R3 #3.
- Per-channel candidate depth (today `k = limit × 30 = 600` nodes).

**Out of scope for R1**: feature labels, tiers, gate, LLM rerank, query views, review aspects.

## Housekeeping to Route

- The live Neo4j is **5.14**, which has no Cypher 25 `VECTOR SEARCH`. `python-conventions.md` and GAP-003 ("done") conflict with `vector_search_helper.py` emitting `db.index.vector.queryNodes`.
- Vision decision 2026-09-28-006 claims HyDE is generated; it is absent from `src/` and `scripts/`.
- `production_artifacts/action_items/Proposed_Fix_Vector_Aggregation.md` must be revised. RRF supersedes the adaptive late fusion, which was non-monotonic.
- Live data facts: 1,629,191 reviews with text; 123,720 of 265,307 products (47%) have reviews. Only 76,814 reviews (4.7%) are embedded. 81% of priced products have no reviews.
