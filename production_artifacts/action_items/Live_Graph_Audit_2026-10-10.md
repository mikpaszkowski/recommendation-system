# Live Graph & Pipeline Audit — 2026-10-10

**Date**: 2026-10-10
**Branch**: `feature/foundation-graph-improvement` (base commit `2fdf251`)
**Scope**: Compare the implemented pipeline and evaluation harness against the **live** Neo4j graph. Verify the status of Meta-Phases A4–A6.
**Method**: Code inspection, read-only Cypher queries against the live database (docker `neo4j-recommendation`, Neo4j 5.14.0), inspection of `evaluations/eval_*` run manifests, and targeted pytest runs.
**Tracked in**: `production_artifacts/Implementation_Plan.md` (items tagged `AI-xx`).

---

## 1. Live Graph Census

The live database holds the **full Amazon Electronics ingest** produced by `scripts/graph_ingestion/batch_ingest.py`, not the 30-product curated subset described in `production_artifacts/graph_state_snapshot.md` (that document is stale).

| Label | Count | | Relationship | Count |
|---|---:|---|---|---:|
| `Review` | 1,629,426 | | `ABOUT_PRODUCT` | 1,634,273 |
| `User` | 471,474 | | `WROTE` | 1,624,586 |
| `ParentProduct` | 265,307 | | `HAS_BRAND` | 160,135 |
| `Attribute` | 47,335 | | `BELONGS_TO_CATEGORY` | 159,475 |
| `Brand` | 40,998 | | `HAS_ATTRIBUTE` | 111,015 |
| `Category` | 71 (34 with `level`) | | `REVIEWS` | 4,847 (no properties; legacy curated build) |
| `Variant` / `Product` / `PriceRange` | 31 / 25 / 3 | | `SUBCATEGORY_OF` | 33 |
| | | | `BOUGHT_TOGETHER` | **0 (does not exist)** |

- `Review` node properties are `review_id`, `review_title`, `review_body`, `rating`, `verified` and `embedding`. They have **no timestamp** and **no `helpful_votes`**.
- 185,437 users have ≥ 3 reviews via `WROTE`.

---

## 2. Findings

### F-01 — AFP-002 (Vector Aggregation) was approved but never implemented
- `src/tools/graph_search_tool.py:239` (hybrid) and `:295` (vector-only) still fuse the three vector indexes with unbounded `sum(score)`, with `k = limit * 30` per index.
- `action_items/Proposed_Fix_Vector_Aggregation.md` describes this failure mode (FM-2, "hub node" scores of 100–225 submerging targets at 0.75–0.85).
- The Vision Report decision log and the changelog record AFP-001, 003, 004 and 005, but **not AFP-002**.
- **Impact**: This is a probable major contributor to the low live hit rate (F-05).

### F-02 — KECR historical paths cannot fire on the live graph
`src/tools/kecr_tool.py` (Subquery 1) assumes a schema that the full ingest does not produce:

| KECR expects | Live graph has |
|---|---|
| `(rev:Review)-[r:REVIEWS]->(p_past)` (line 188) | `(rev:Review)-[:ABOUT_PRODUCT]->(p)`; the 4,847 `REVIEWS` edges are property-less legacy edges |
| `r.rating`, `r.verified` on the relationship | `rating`, `verified` on the `Review` node |
| `r.timestamp_iso IS NOT NULL` (line 191) | No timestamp on reviews. `datasets/processed_data/processed_reviews.csv` does have `sort_timestamp`, which could be backfilled. |
| `[:BOUGHT_TOGETHER]` (line 202) | Does not exist |
| `c.level >= $min_category_level` (line 211) | `level` is set on 34 of 71 categories |

- **Impact**: `s_hist` is always 0, so only `CONVERSATIONAL_MATCH` / `SPARSE_FALLBACK` evidence is produced. The personalised "because you bought X" explanations promised by the Vision Report never appear.
- Unit and integration tests (`tests/unit/test_kecr_tool.py`, `tests/integration/test_kecr_orchestrator.py`) mock Neo4j, so they cannot detect this.

### F-03 — `user_id` never refers to a real graph user
- `src/ui/app.py:20` hard-codes `user_id = "test_user_chainlit"`.
- `scripts/evaluate_retrieval.py` passes the benchmark query ID as `user_id`, and `live_eval_dataset.json` has no user field.
- Session isolation in Chainlit comes from a per-chat `AgentOrchestrator`, not from the ID. The only consumer that needs a real ID is KECR (F-02).
- **Impact**: Personalisation is neither demonstrable in the UI nor measured in evaluation.

### F-04 — Tier 2 (generative) evaluation does not evaluate the system
- `scripts/evaluate_generative.py` never invokes `AgentOrchestrator`. It judges the hand-written `generated_response` fields in `evaluations/benchmarks/generative_benchmark.json` (15 samples).
- Only **3 of 15** candidate ASINs in that benchmark exist in the live graph. This conflicts with the Zero-Mock decision (Vision Report, 2026-10-05-001).
- The judge defaults to `gpt-4o-mini` (`src/evaluation/judge.py`), which is weaker than the system model (`gpt-4o` since 2026-10-10).

### F-05 — Only one full live retrieval run exists; most runs were mock
- 16 of 19 runs in `evaluations/` used `--mode offline` (deterministic mock), most with 5 queries. These report HR@5 = 1.0.
- The only full live run, `eval_2026-10-09_1336` (21 queries), reports: strict HR@1 = 0.079, HR@5 = 0.127, HR@20 = 0.206, strict NDCG@5 = 0.100, MRR = 0.099.
- `tests/test_challenger_distinguishing_features.py:213` runs the offline evaluation as a subprocess, so **every full pytest run writes a new mock `eval_*` directory**.

### F-06 — Critic receives almost no review evidence
- `GraphSearchTool.fetch_product_attributes` (`src/tools/graph_search_tool.py:387-388`) applies `LIMIT 20` to reviews **across all candidates combined**, not per product. With 20 candidates, most get no reviews at all.
- It also orders by `r.helpful_votes, r.timestamp_iso`, neither of which exists on `Review`, so the order is arbitrary.
- `CriticAgent._evaluate_single_product` fails **open**: on any LLM or parse error it sets `is_recommended = True` (`src/agents/critic_agent.py:146`).
- The A2 batched method `evaluate_candidate_tradeoffs` (MACS disclosure) is never called. The orchestrator uses the legacy per-item method, and `relaxed_constraints` never reaches the Critic.

### F-07 — Redundant and conflicting LLM extraction per SEARCH turn
A SEARCH turn makes about 24 LLM calls:
- 1 preference parser call (current message only)
- 1 router call
- 1 search-param generator call
- ~20 Critic calls, one per candidate (`candidate_limit = 20`)
- 1 final-answer call

The parser and `_generate_search_params` both extract filters. On conflict the latter silently wins. Its prompt example maps "under 1500" to `price_max` **150** (`src/agents/orchestrator.py:58`).

### F-08 — Minor
- The category title filter builds Cypher by string interpolation instead of parameters (`src/tools/graph_search_tool.py:476-480`). This violates `.claude/rules/python-conventions.md`.
- The repo `.venv` lacks `seaborn`, so `src.evaluation` fails to import there. The Anaconda interpreter has the full dependency set.
- Stale docs:
  - `production_artifacts/graph_state_snapshot.md` (graph size).
  - `scripts/graph_ingestion/README.md` mentions OpenAI embeddings and a non-existent `scripts/run_a1_flow.py`.
  - `Implementation_Plan.md` A4/A6 statuses (corrected alongside this audit).

---

## 3. Meta-Phase A4–A6 Status Verdict

| Phase | Plan said | Actual |
|---|---|---|
| **A4 — KECR** | Not done | **Partial.** Implemented and wired into `AgentOrchestrator` (STEP 3d.5), with mocked tests. Historical half is non-functional on the live graph (F-02, F-03). Implemented as a pattern-matching dual-context query, not shortest-path. |
| **A5 — Explainable generation E2E** | Not done | **Not done.** `[GRAPH EVIDENCE]` injection is wired, but `tests/test_recommendation_pipeline.py` does not exist and there is no recorded live manual review. |
| **A6 — Evaluation** | Not done | **Tier 1 done**: `scripts/evaluate_retrieval.py` works live, with a staged `eval_trace`. **Tier 2 partial**: judge rubrics are implemented, but the system's output is not evaluated (F-04). |

---

## 4. Changes Applied on 2026-10-10

| Change | File |
|---|---|
| Default LLM `gpt-4o-mini` → `gpt-4o` (shared by router, parser, Critic, generator) | `src/llm/simple_llm_handler.py` |
| Critic prompt and fallback strings translated from Polish to English | `src/agents/critic_agent.py` |
| Evaluation default mode `offline` → `live` | `scripts/evaluate_retrieval.py`, `scripts/evaluate_generative.py` |
| Live retrieval eval no longer silently falls back to mock when the orchestrator fails to start; it raises instead | `scripts/evaluate_retrieval.py` |
| AFP proposals moved to `production_artifacts/action_items/` | — |

Verification: 46 tests passed across `test_critic_agent`, `test_benchmark_alignment`, `test_agent_orchestrator`, `test_preference_parser`, `unit/test_kecr_tool` and `integration/test_kecr_orchestrator`. The uncommitted catalog-safe WIP passes its unit acceptance criteria (54 tests). Its live criterion is still unverified (AI-02).

---

## 5. Action Items

Priority: **P1** blocks thesis results, **P2** degrades quality, **P3** hygiene. **D** marks a decision that the user must make first.

| ID | Pri | Action | Finding | Plan phase |
|---|---|---|---|---|
| AI-01 | P1 | Implement AFP-002 bounded multi-index score fusion (`action_items/Proposed_Fix_Vector_Aggregation.md`), then re-run the live retrieval eval | F-01 | A1 |
| AI-02 | P1 | Verify the catalog-safe demotion WIP live: `live_eval_phone_01` returns ≥ 5 candidates including `B08GNRGB67`, and the Cypher has no `storage` `EXISTS` clause. Then commit. | — | A1 |
| AI-03 | P1 | Rewrite the KECR historical subquery for the live schema (`ABOUT_PRODUCT`, rating and verified on the `Review` node). Backfill `Review` timestamps from `processed_reviews.csv` `sort_timestamp`, or drop time decay. Drop or build `BOUGHT_TOGETHER`. Add a live-graph test asserting a historical path for a known reviewer. | F-02 | A4 |
| AI-04 | P1 | Make Tier 2 judge real system output: run `AgentOrchestrator` over the live benchmark, capture `answer` and `eval_trace`, then judge. Retire or regenerate `generative_benchmark.json`. | F-04 | A6 |
| AI-05 | P2 | Attach real reviewer `user_id`s (≥ 3 reviews) to `live_eval_dataset.json` scenarios. Allow selecting a real reviewer in Chainlit. | F-03 | A4 / B6 |
| AI-06 | P2 | Fetch reviews per product (e.g. top-N per ASIN) instead of a global `LIMIT 20`. Order by existing properties. | F-06 | A2 |
| AI-07 | P2 | Merge preference extraction and search-param generation into a single LLM call with one source of truth for filters. Fix the "1500 → 150" prompt example. | F-07 | B1 |
| AI-08 | D | Critic design: per-item legacy vs batched A2 `evaluate_candidate_tradeoffs` (≈ 20 → 1 calls, MACS disclosure). Decide fail-open vs fail-closed on LLM error. | F-06, F-07 | A2 |
| AI-09 | D | Judge model for Tier 2 (currently `gpt-4o-mini` grading `gpt-4o`). | F-04 | A6 |
| AI-10 | D | Evaluate the `ideas.txt` direction as an ablation, after AI-01: LLM-generated target-product description → pure vector retrieval. | — | A6 |
| AI-11 | P3 | Parameterise the category title filter Cypher. | F-08 | A1 |
| AI-12 | P3 | Stop the offline subprocess test from writing into `evaluations/`, e.g. by passing a temp output dir. | F-05 | A6 |
| AI-13 | P3 | Refresh stale docs (`graph_state_snapshot.md`, `scripts/graph_ingestion/README.md`) and add `seaborn` to `.venv`. | F-08 | Foundation |
