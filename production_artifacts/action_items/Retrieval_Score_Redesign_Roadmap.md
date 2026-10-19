# Retrieval Score Redesign: Roadmap & Design (AFP-002 and Follow-ups)

**Date**: 2026-10-17
**Branch**: `feature/afp-002-vector-aggregation`
**Status**: Roadmap agreed with the user. **R1 implemented 2026-10-17** (audit PASS WITH FIXES, `production_artifacts/Audit_Report.md`; live eval `evaluations/eval_2026-10-17_1937`). **R2a implemented 2026-10-18** (RS-23, RS-20 rest, run archive; audit PASS WITH FIXES, exit gate PASS: spurious CLARIFY 0/21 in three citable live runs at `88cdbdf`, `evaluations_archive/eval_2026-10-18_2340`, `_2349`, `_2358`; Vision decisions 2026-10-18-014 … 017). Next: **R2b** (RS-21 benchmark v2, RS-02 evidence).
**Source**: Brainstorm session 2026-10-10 → 2026-10-17. The full record is in `_bmad-output/brainstorming/brainstorm-retrieval-score-relevance-2026-10-10/.memlog.md` (192 entries).
**Supersedes**: The fusion design in `Proposed_Fix_Vector_Aggregation.md` §3.1–3.2 (adaptive late fusion). See the revision note in that document.
**Tracked in**: `production_artifacts/Implementation_Plan.md` (items tagged `RS-xx` and `R1`–`R5`).

---

## 1. Problem

The retrieval score should measure **how well a product matches what the user asked for**. Today it measures **how many pieces of text about the product look a bit like the query**.

- `GraphSearchTool._execute_hybrid_search` and `_execute_vector_search` (`src/tools/graph_search_tool.py`) union three vector indexes and `sum(score)` per product:
  - weights: product ×1.0, attribute ×0.8, review ×0.9;
  - depth: `k = limit × 30 = 600` nodes per index.
- **Product-side fan-out is the bug.** A product matched by many attribute or review nodes collects many small scores (hub bias). Query-side fan-out (several query versions, one score each per product) is bounded and safe.
- The `WHERE` filter runs **after** the ANN search, so recall is lost and MACS relaxation fires.
- The additive soft-preference bonus (`+0.2 × polarity` per substring match) would dominate any bounded score.
- AFP-002's adaptive late fusion (normalising by the channels present) is **non-monotonic**: extra but weaker evidence *lowers* a product's score.

**Live baseline** `eval_2026-10-09_1336` (21 queries, `hybrid` strategy only, recomputed from `retrieval_metrics.json`):

| HR@1 | HR@5 | HR@10 | HR@20 | strict NDCG@5 | MRR |
|---:|---:|---:|---:|---:|---:|
| 0.048 | 0.190 | 0.238 | 0.381 | 0.110 | 0.100 |

> **Correction (2026-10-17)**: an earlier version of this table (HR@1 0.079, HR@5 0.127, HR@20 0.206, NDCG@5 0.100, MRR 0.099) quoted `summary.json`, whose aggregates are pooled over the `hybrid`, `vector_only` and `cypher_only` strategies (63 rows). R1 adds per-strategy aggregates (Technical Specification FR-010).

### Live data facts (graph v1; read-only queries, 2026-10-10 and 2026-10-14)

> **Correction (2026-10-19, Vision 2026-10-19-021)**: the figures in this section describe the **v1 graph** only. 104,281 of the 265,307 v1 products are ghosts (no title, price or category; identical blank-template embedding), so the "47% have reviews", "53% no reviews / cold", "4.7% / 2.2% review-embedding coverage" and "71 categories" figures do not hold as statements about the catalogue. In v1, 12% of titled products have reviews, and 85% of the 5,715 review-embedded products are ghosts. All of them are recomputed on graph v2 (`production_artifacts/Technical_Specification_Graph_Rebuild.md`). **Graph v2 has not been built yet** (code only, 2026-10-19): the live Neo4j is still v1, and no v2 figure exists. The v1 numbers are kept below as history.

| Fact | Value |
|---|---|
| `ParentProduct` nodes / embedded | 265,307 / 100% |
| Priced products (`price > 0`) | 65,650 (25%) |
| Products with ≥ 1 review | 123,720 (47%); almost all have ≥ 3 reviews, 59,371 have ≥ 10, max 3,229 |
| Products with no reviews | 141,587 (53%) |
| Priced products with reviews | 12,182 of 65,650 (18.6%) |
| `Review` nodes with text | 1,629,191 |
| Embedded reviews | 76,814 (4.7%), covering 5,715 products (2.2%). The embedding backfill was never finished. |
| `Attribute` nodes | 47,335; one node links to up to 20,969 products |
| Products with attributes | 83,437 (31%) |
| Categories | 71 |
| `BOUGHT_TOGETHER` | absent |
| Review properties | no timestamp, no helpful votes |

**Consequence (v1 reading, superseded by the correction above)**: the low 2.2% was *embedding* coverage, not *review* coverage. Also, "no reviews" is the **normal case** (53% of all products, 81% of priced ones), not an edge case. The 53% and 81% include ghosts; the "normal case" claim is re-tested on v2.

---

## 2. Design Principles (decided by the user)

| ID | Principle |
|---|---|
| P-1 | **Three layers of a match**: what the product **IS** (type), what it **HAS/DOES** (features), and how it is **EXPERIENCED** (reviews). |
| P-2 | **Unknown ≠ zero**, applied as an order: **confirmed > unknown > contradicted**. Missing evidence is never scored as a mismatch, but it loses to confirmed evidence. |
| P-3 | **Channel roles**: product embeddings **find**; attributes **find** (a recall channel, especially for brand+model-only titles); reviews **verify** and never find candidates. |
| P-4 | **Ranking order**: (1) requested-feature fit → (2) channel agreement (found by several channels, RRF) → (3) review experience. Each level only breaks ties left by the level above. A product found by both channels beats one found by a single channel only when their feature fit is equal. |
| P-5 | **LLM reranker** (final 20–30 candidates, one batched call): may **remove** clear non-matches and **reorder**. Every removal or move cites a reason from the product's evidence and is written to `eval_trace`. A wrong product type is removed; a missing feature is demoted with a stated trade-off. On LLM error, the deterministic order is used. |
| P-6 | **Fit and quality are separate axes.** The best-fit product is shown even with bad reviews, the well-loved alternative is shown next to it, and the switch is explained. |
| P-7 | **Adaptive search order**: little information means narrowing with filters first; rich information on similarity-ready data means similarity first. Measured by filter selectivity. |
| P-8 | **Two scores**: an absolute score gates "is anything good enough"; a relative score ranks. When the gate fails, say plainly that we don't carry it and show the closest alternatives, each trading off a different requirement. |
| P-9 | **One normaliser, two sides**: products (offline) and user requests (query time) are labelled into the same typed feature vocabulary and compared label to label. Embeddings find; labels verify. |
| P-10 | **Training is allowed** when it improves quality or speed (e.g. a distilled review classifier). This needs a Vision Report decision (D-2). |

### Review evidence rules (experience layer)

- Classify **sentences**, not whole reviews, as product experience or noise. The noise list is fixed and domain-independent: delivery, packaging, seller, customer service, returns, price paid. Product aspects are open-ended and discovered per category.
- **Boundary rule**: anything about the item's own physical or functional state is product experience; anything about people or process is noise.
- **Dead on arrival**:
  - with a damaged package or device → unlucky unit (transit);
  - with an intact package and undamaged device → counts against product quality.
  - The cause is decided from the whole review.
- **Scoring**: minimum mentions (≈ 3) plus a Bayesian-smoothed positive share (reusing the `bayes_rating` pattern in `_execute_cypher_search`). Below the minimum the aspect is UNKNOWN. This is aspect-based sentiment analysis (ABSA).
- **Two aspect families**, recorded as a "silence semantics" property per aspect:
  - **Opinion-driven** (comfort, sound, fit): the denominator is the reviews that mention the aspect; silence means unknown.
  - **Complaint-driven** (reliability, defects, safety): the denominator is all product-experience reviews (a defect rate); silence counts as positive.
- **Reliability** is scored like comfort, against a **category baseline** prior (2% dead-on-arrival may be normal for cheap earbuds and alarming for a laptop).

---

## 3. Work Package Catalogue

All packages discussed in the session. **Decided** = chosen by the user; **Idea** = proposed, not yet confirmed. Size: S ≈ hours, M ≈ 1–2 days, L ≈ a week or more.

| ID | Change | Group | Size | Status | Release | Related |
|---|---|---|---|---|---|---|
| RS-01 | Replace `sum(score)` with one ranked list per channel (each product once) fused by **RRF** | Fusion | S | ✅ Done (R1) | R1 | AI-01 |
| RS-02 | Remove the review index from candidate finding (reviews verify only); run as ablation first | Fusion | S | ✅ Ablation done (R1: `rrf2`); default decided on the R2b tuning split (rule in Vision 2026-10-18-015 §4), confirmed on test in R3 | R1 / R2b | AI-01 |
| RS-03 | Attribute channel as a precise finder: IDF/rarity weighting, AND-matching inside the resolved category | Fusion | M | Decided role; method is an idea | R3 | — |
| RS-04 | Tiered ranking: feature fit → RRF agreement → review experience | Fusion | M–L | Decided | R4 | — |
| RS-05 | Rescale the soft-preference bonus to the RRF scale, or fuse it as its own list | Fusion | S | ✅ Done (R1) | R1 | — |
| RS-06 | Two scores (absolute gate, relative rank); calibrate the gate by hiding targets; metric: correct-abstention rate | Fusion | M | Decided | R4 | — |
| RS-07 | Adaptive order: filter-first with exact scoring vs ANN-first with oversampling, chosen by filter selectivity | Query side | M | Decided | R3 | — |
| RS-08 | Query versions in parallel: raw message, HyDE (LLM-written ideal product, on the merged AI-07 call), IS/HAS pieces, user profile | Query side | M | Decided | R3 | AI-07, AI-10 |
| RS-09 | Product-type (head-noun) signal plus "accessory for X" detection | Query side | M | Idea | R4 | — |
| RS-10 | Graded category distance (same leaf > sibling > cousin) instead of pass/fail | Query side | S–M | Idea | R3 | AFP-003 |
| RS-11 | Typed canonical feature vocabulary (boolean / ordinal / numeric+unit / categorical); local-LLM labelling that quotes its source text; regex tier for common features; quality audit (~200 products) | Graph data | L | Decided | R5 | AFP-005 |
| RS-12 | Interim feature check: full-text index with synonym sets and negation patterns → confirmed / contradicted / unknown | Graph data | M | Idea | R4 | — |
| RS-13 | Review aspect pipeline (rules in §2): local-LLM sentence labels → distilled classifier (DistilBERT/SetFit) over 1.6M reviews, with the LLM auditing a sample | Graph data | L | Decided | R5 | D-2 |
| RS-14 | Complement edges: `COMPATIBLE_WITH` from "for X" text, plus a co-review proxy from `WROTE` edges | Graph data | M | Idea | Later | AI-03 |
| RS-15 | Reverse HyDE / doc2query: offline, each product writes the requests its buyer would make | Graph data | L | Idea | Later | — |
| RS-16 | Preference edges `(User)-[:PREFERS {polarity, confidence, source}]` scoped by category, weakening with taxonomy distance; precedence: current message > stated past preference > inferred preference | Graph data | M | Decided | Later | B2 |
| RS-17 | Batched LLM listwise rerank (`evaluate_candidate_tradeoffs`) with the powers in P-5 | Rerank | M | Decided | R4 | AI-08 |
| RS-18 | Per-product evidence ledger written during ranking; used for contrastive ("why this, not that") and uncertainty-honest explanations | Explanation | M | Idea | R5 (seeded in R1) | A5 |
| RS-19 | Two lanes ("what you asked for" / "you might also want"), alternatives that each trade off a different requirement, "we don't carry it" response | Conversation | M | Decided | Later | B3 |
| RS-20 | Label-free metrics: type-precision@K, constraint-satisfaction@K, popularity-bias@K | Evaluation | S–M | ✅ Done. R1: popularity-bias@K (since R2a reported as `review-coverage-bias@K`, code key `popularity_bias@k`), type-precision@K; R2a: three-valued constraint-satisfaction@K against gold constraints | R1 / R2a | — |
| RS-21 | Benchmark split into hard cases (no reviews, brand+model titles, accessory traps, many-feature trade-offs) + tuning/test split + title-token leakage check. _Amended by Vision 2026-10-18-014: strata S0–S4 plus an ambiguous set, about 230 queries, hashed split, measured leakage._ | Evaluation | M | Decided, open | R2b | — |
| RS-22 | Ablation arms: each query version, 3 vs 2 channels, deterministic vs + LLM rerank, correct-abstention rate | Evaluation | with others | Idea | R1–R4 | AI-10 |
| RS-23 | Spurious CLARIFY from missed category extraction: in `eval_2026-10-17_1846`, 4 of 21 queries (`live_eval_charger_01`, `mouse_02`, `keyboard_01`, `keyboard_02`) name the product type plainly, yet `LLMPreferenceParser` extracted no `category`, so the guardrail asked a clarifying question and every arm scored a miss. The 2026-10-09 run had none. Measure extraction recall per query; report retrieval metrics on SEARCH-only queries next to all queries; fix the extraction prompt or merge with AI-07. _Done in R2a (2026-10-18): head-noun prompt rule and category recovery gated by `product_type_decided`; gate 0/21 spurious CLARIFY in three citable runs. Open: clarification recall on the ambiguous stratum (R2b), deterministic vocabulary fallback (RS-24), parser merge (AI-07)._ | Evaluation | S–M | ✅ Done (R2a) | R2a | AI-07 |
| RS-24 | Domain-agnostic product-type matching, replacing the word-regex category filter: (1) text normalisation with a configurable language analyzer or lemmas on both sides (P-9); (2) catalogue-derived product-type vocabulary and synonym sets built at ingestion (with RS-11); (3) product type as a ranked signal with a hard filter only on confident matches (with RS-09, RS-17). Trigger: `ret_021`, where "Webcams" rejects the C920 (title "Webcam", category "Computers"; 22 vs 742 eligible products). A rule-based English plural fix was rejected 2026-10-17: it does not extend to fashion or cosmetics (glasses/glass, jeans, synonyms, compounds) | Retrieval | M–L | Decided | R3 | RS-07, RS-09, RS-11 |

---

## 4. Roadmap

| Release | Scope | Depends on | Exit gate |
|---|---|---|---|
| **R1, this branch** | RS-01, RS-05, RS-02 (as ablation), RS-20 (popularity-bias@K, type-precision@K), per-channel ranks in `eval_trace` (seed of RS-18) | — | Live eval vs `eval_2026-10-09_1336` |
| **R2a** (done 2026-10-18) | RS-23 (category extraction recall, fix), RS-20 (constraint-satisfaction@K), paired statistics, citable-run provenance, `evaluations_archive/` | R1 metrics | **PASS**: zero spurious CLARIFY on legacy-21 in each of three citable live runs at one clean commit |
| R2b | RS-21 (benchmark v2), RS-02 evidence (`rrf2` default rule) | R2a | Benchmark frozen **before** any weight tuning; clarification recall on the ambiguous stratum not below its pre-fix value |
| R3 | RS-07, RS-24, RS-03, RS-08 (incl. AI-10 HyDE arm), RS-10 | R1 fuser, R2 benchmark | Per-arm ablation on the R2 test split |
| R4 | RS-12 → RS-04, RS-09, RS-17 (AI-08), RS-06 | R3 | type-precision@K, constraint-satisfaction@K, correct-abstention rate |
| R5 | RS-11 (replaces RS-12 inputs), RS-13, RS-18 | R4; decision D-2 | Label precision/recall audit |
| Later (Meta-Phase B) | RS-16, RS-19, RS-14, RS-15 | R4–R5 | — |

Why this order:
- **R1** is the actual AFP-002 fix and can be measured right away. Its fuser is the backbone that R3's query versions plug into.
- **R2** must come before tuning, so weights aren't fitted to the 21 test queries.
- **R5** is offline work over the full graph, and RS-13 needs decision D-2.

---

## 5. R1 Specification Intent

**Goal**: remove hub bias by replacing `sum(score)` with Reciprocal Rank Fusion over per-channel ranked lists.

### Requirements

| ID | Requirement |
|---|---|
| R1-1 | Each channel (product, attribute, review) yields one ranked list in which **each product appears once**, ranked by its best (max) similarity in that channel. |
| R1-2 | Fusion: `RRF(p) = Σ_c w_c / (k + rank_c(p))`. Default `k = 60` and equal weights, both configurable. A product absent from a channel gets no contribution from it. AFP-002's 0.60/0.25/0.15 runs as a weighted-RRF ablation, not as the default. |
| R1-3 | Applies to both `_execute_hybrid_search` and `_execute_vector_search`. Prefer fusing in Python from the per-channel results, so it can be unit-tested and the per-channel ranks can be logged. |
| R1-4 | Rescale the soft-preference bonus (`graph_search_tool.py` additive scoring block) so it cannot outweigh an RRF score of ~0.016–0.033, or fuse it as its own ranked list. |
| R1-5 | Ablation switch: RRF over three channels vs two (without the review channel). |
| R1-6 | Each candidate's per-channel ranks, per-channel best similarity and RRF score are written into the result and `eval_trace`. This is the first column of the evidence ledger (RS-18). |
| R1-7 | `scripts/evaluate_retrieval.py` adds **popularity-bias@K** (share of top-K from the 5,715 review-embedded products vs their 2.2% catalog share; _since R2a named `review-coverage-bias@K`, with a second, titled-products base rate of 0.52% next to the 2.15% all-node rate, audit M-1_) and **type-precision@K** (share of top-K in the requested category/product type). |
| R1-8 | Parameterized Cypher only. MACS, Critic, KECR and the router are unchanged in R1. |

### Acceptance

- Unit tests:
  - A product matched by many attribute or review nodes gets no more credit than one match per channel.
  - RRF ordering is deterministic, including tie handling.
  - The soft bonus cannot override fusion order beyond its configured scale.
- Live eval (`--mode live`, Anaconda Python):
  - Compared with `eval_2026-10-09_1336` on HR@1/5/20, NDCG@5 and MRR.
  - Popularity-bias@K must drop.
  - The result is reported honestly whether it improves or not.
- Both arms are reported: 3 channels vs 2.

### Open spec questions

1. Rank each channel **before or after** the `WHERE` post-filter? The full fix for post-filtering is RS-07 in R3.
2. **Tie-breaking** in the attribute channel, where one attribute gives thousands of tied products. A product-embedding tie-break is the candidate; the full fix is RS-03 in R3.
3. **Per-channel candidate depth** (today `k = 600` nodes).

### Out of scope for R1

Feature labels, tiers, the gate, LLM rerank, query versions, review aspects.

---

## 6. Evaluation Plan

- **New metrics**: popularity-bias@K (renamed `review-coverage-bias@K` in R2a, because it measures review-embedding coverage, not popularity) and type-precision@K (R1), constraint-satisfaction@K (R2a), correct-abstention rate (R4), label precision/recall (R5).
- **Statistics and citable runs** (R2a, Vision 2026-10-18-015): paired tests with Holm correction, three repeated runs for end-to-end claims, and only archived `citable: true` runs (`evaluations_archive/`) are cited in the thesis.
- **Benchmark strata** (R2b): cold products (no reviews), sparse titles (brand+model only), accessory traps, many-feature trade-offs. Plus a tuning/test split and a title-token leakage check per query.
- **Ablation arms** (thesis evidence):

  | Arm | Release |
  |---|---|
  | `sum` baseline vs RRF | R1 |
  | 3 vs 2 channels | R1 |
  | Weighted vs equal RRF | R1 |
  | Raw vs HyDE vs IS/HAS pieces vs fused query versions | R3 |
  | Deterministic order vs + LLM rerank, counting overrides | R4 |
- **Live evaluation only**. Offline mock runs are not thesis evidence.

---

## 7. Decisions Needed (Vision Report, via @pm-research)

| ID | Decision | Why |
|---|---|---|
| D-1 | ✅ **Recorded 2026-10-17** as Vision decision 2026-10-17-013. AFP-002 implemented via RRF (not adaptive late fusion) | Adaptive late fusion is non-monotonic; RRF is scale-free and rewards cross-channel agreement |
| D-2 | Relax "no custom model training" for small supervised or distilled models when they improve quality or speed | Needed for RS-13 (classifier over 1.6M reviews) |
| D-3 | Correct decision 2026-09-28-006: HyDE is claimed but does not exist in `src/` or `scripts/` | Doc/code gap; HyDE arrives with RS-08 |
| D-4 | Cypher 25 `VECTOR SEARCH` rule vs the live Neo4j **5.14** (no `VECTOR SEARCH`); GAP-003 is marked done, but `vector_search_helper.py` emits `db.index.vector.queryNodes` | The rule cannot be followed on the current database version |

---

## 8. Open Questions Not Yet Answered

- **Who counts as a review witness**: any reviewer, or verified purchasers only? `Review.verified` exists.
- **When does a review expire?** Reviews have no timestamp. A backfill from `processed_reviews.csv` `sort_timestamp` is already listed in AI-03.
- **Where are aspects computed?** Precomputed per product and aspect (implied by RS-13), or at query time.
- **Placement of experience evidence**: does review evidence (P-4, level 3) ever reorder across feature tiers? Current answer: no, only within a tier.

---

## 9. References

- `Proposed_Fix_Vector_Aggregation.md` (AFP-002, original proposal and failure evidence: `ret_021` C920 at rank 253, Senso earbuds at 225.2)
- `Live_Graph_Audit_2026-10-10.md` (F-01 … F-08, AI-01 … AI-13)
- `_bmad-output/brainstorming/brainstorm-retrieval-score-relevance-2026-10-10/brainstorm-intent.md` (condensed R1 intent)
- RRF: Cormack, Clarke & Büttcher, *Reciprocal Rank Fusion outperforms Condorcet and individual rank learning methods*, SIGIR 2009.
