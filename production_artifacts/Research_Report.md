# Research Report: R2 — Evaluation Foundation (Stratified Benchmark, Constraint Satisfaction, Spurious CLARIFY)

**Date**: 2026-10-18
**Requested by**: User (`/implement` pipeline, release R2 of `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md`)
**Status**: Approved 2026-10-18 (Gate #1, R2-D1 … R2-D8 as proposed). Recorded in the Vision Report Decision Log.
**Scope**: RS-21 (stratified benchmark, tuning/test split, leakage check), RS-20 rest (constraint-satisfaction@K), RS-23 (spurious CLARIFY, category-extraction recall), RS-02 (evidence for removing the review channel from candidate finding), evaluation-run archiving and reproducibility
**Previous report**: The R1 report (rank-based multi-channel fusion) previously at this path is preserved in git history (`git show 32f68cd:production_artifacts/Research_Report.md`).

---

## 1. Research Questions

| # | Question |
|---|---|
| Q1 | Why do 4–5 of 21 live queries that plainly name a product type end as CLARIFY, and what fix stays domain-agnostic? |
| Q2 | How many queries does the benchmark need for the arms to be distinguishable, and which statistical test should be used? |
| Q3 | Which strata, inclusion rules and utterance-generation procedure give a benchmark without title-token leakage, and does this amend decision 2026-10-06-002? |
| Q4 | How should the tuning/test split be built and frozen? |
| Q5 | How is constraint-satisfaction@K defined when many values are unknown? |
| Q6 | What evidence should R2 produce for the RS-02 decision (review channel out of candidate finding)? |
| Q7 | How should cited evaluation runs be archived and made reproducible? |

---

## 2. Findings

### Q1: Spurious CLARIFY (RS-23) — three layers fail together

**Evidence** (`evaluations/eval_2026-10-17_1937/execution_trace.log`; the five CLARIFY queries are `charger_01`, `mouse_02`, `keyboard_01`, `keyboard_02`, `keyboard_03`):

| Query | Product noun in the utterance | Parser `category` | Parser's own `ready_for_recommendation` |
|---|---|---|---|
| `charger_01` | "compact 65W GaN **wall charger**" | none (price only) | `true` |
| `mouse_02` | "rechargeable ergonomic vertical **mouse**" | none | `false`, missing `["category"]` |
| `keyboard_01` | "ergonomic split-key wired USB **keyboard**" | none (price only) | `true` |
| `keyboard_02` | "pocket-sized tri-folding Bluetooth **keyboard**" | none | `false`, missing `["category","price"]` |
| `keyboard_03` | "wireless living room **keyboard**" | none | `false`, missing `["category"]` |

In every case the product noun is the **head of a long noun phrase with many modifiers**. The parser moves the modifiers into `soft_preferences`, and the head noun ends up only in `situational_context`. GPT-4o runs at `temperature=0` (`src/llm/simple_llm_handler.py`), yet the count changes between runs: 0 in `eval_2026-10-09_1336`, 4 in `_1846`, 5 in `_1937`. So no prompt-only fix can be shown to work from a single run.

**Causal chain in the code**:
1. **Extraction** (`src/llm_interface/preference_parser.py`, `src/llm_interface/prompts/preference_extract_prompt.py`).
   - The injected schema block says "ALL other specifications MUST be classified as soft_preferences" and stresses spec → soft.
   - Nothing says "if a product noun is present, a `category` constraint is required".
   - All six few-shot examples have short product nouns ("laptop", "monitor").
   - `example_1` itself puts `operating_system` into `hard_constraints`, which breaks the prompt's own taxonomy rule.
   - The injected schema is still the static 3-domain `src/llm_interface/domain_schemas.json` (monitor, laptop, headphones). See §4: decision 2026-09-29-007 is not implemented.
2. **Readiness override** (`src/dialog_manager/dialogue_manager.py`, `_evaluate_dialogue_state`, lines 476–508). It recomputes readiness deterministically: the critical attribute is `category`, with synonyms `{category, product_category, product_type, type}`. This replaces the parser's own `ready=true` (`charger_01`, `keyboard_01`).
3. **Guardrail** (`src/agents/orchestrator.py`, lines 252–257). The router LLM returned SEARCH every time; the guardrail flips it to CLARIFY. It ignores the `has_category` value computed a few lines above, which only feeds the brand immunisation:
   ```python
   elif action == "SEARCH" and not ready and missing:
       if "category" in missing:
           action = "CLARIFY"
   ```
4. **The second extraction never runs.** `_generate_search_params` (which emits `structured_filters.category`) is called only inside the SEARCH branch of `_execute_step`. The system has two sources of truth for filters (AI-07), and the one that would have found the category is skipped.

**Fix options**:

| Option | Domain-agnostic | Cost | Risk | Verdict |
|---|---|---|---|---|
| A. Prompt fix: "the head noun of the requested product is a `category` hard constraint; its modifiers are soft preferences"; one example with a long modified noun phrase; remove the `operating_system` contradiction; a consistency rule (never report `category` missing while `situational_context` names a product) | Yes (head-noun rule holds for "linen midi dress", "fragrance-free moisturiser") | S | Non-deterministic; must be measured over repeated runs | **Adopt** |
| B. Deterministic fallback against the catalogue category vocabulary (71 category names, or the category embedding index) | Only with lemmas/synonyms, which is RS-24. A string matcher now repeats the English-plural rule rejected 2026-10-17; the embedding resolver drifts across domains ("charger for my laptop" → Laptops; AFP-003 margin issues) and returns taxonomy labels, not product types | M | Duplicates RS-24; wrong hard filters | **Defer to RS-24 (R3)** |
| C. Category-recovery step before clarifying: when the guardrail would switch SEARCH → CLARIFY, first take the category from every source (`has_category`, then a `_generate_search_params` result); clarify only if none has a product type. `_generate_search_params` must be allowed to return `category: null` when the user hasn't decided | Yes (LLM-based, no vocabulary) | S | Over-searching on truly vague queries (Vision §2 "does not guess"); measured by the ambiguous stratum below | **Adopt** |
| D. Fold into AI-07 (merge the parser and `_generate_search_params` into one call) | Yes | M–L; touches B1 orchestrator work and RS-08 | Scope growth in an evaluation release | **Not in R2.** AI-07 inherits the R2 category-extraction metrics as its regression gate |

Option C adds at most one LLM call, and only on turns that would otherwise clarify (≈ 20% today). `_generate_search_params` already runs on every SEARCH turn. Clarification precedent: ClariQ (Aliannejadi et al., 2020) treats "does this request need clarification" as its own labelled prediction task. An unnecessary question is a measurable false positive, not a safe default.

The "actually under 1500 → UPDATE `price_max` to 150" line in `SEARCH_GENERATION_PROMPT` is listed under AI-07. It is a one-line fix, and constraint-satisfaction@K (Q5) would penalise the behaviour it teaches. I recommend fixing it in R2a.

**Metrics (new)**:
- **Category-extraction recall (CER)**: among queries with gold `type_explicit = true`, the share where a category is present. Reported twice:
  - *parser-only*: an `LLMPreferenceParser` hard constraint (the AI-07 regression number);
  - *pipeline*: any source the guardrail consults, after recovery.
  - Legacy-21: 21/21 on 2026-10-09, 17/21 in `_1846`, 16/21 in `_1937`.
- **Target-admitting category rate**: the share of queries where the target passes the extracted category filter (`GraphSearchTool.match_category([target], extracted)`). This catches a "present but wrong" category, the `ret_021` "Webcams" pattern, without new labels.
- **Spurious-CLARIFY rate**: CLARIFY on `type_explicit` queries / `type_explicit` queries.
- **Clarification recall** on the ambiguous stratum (gold action CLARIFY). It must not drop below its pre-fix value.
- A `clarify_reason` field in `eval_trace` (parser-missing, guardrail, router), so each CLARIFY can be attributed.

**Reporting rule (SEARCH-only vs all queries)**. Today one summary table mixes denominators (checked in `src/evaluation/metrics.py`):
- HR, MRR and NDCG use `np.mean` over all queries, so CLARIFY counts as a miss.
- `popularity_bias@K` and `type_precision@K` use `_mean_skip_none`, so they are averaged over the **16 SEARCH queries only** in `_1937` (CLARIFY returns no candidates).

R2 should make the denominator explicit in every aggregate:
- **all-queries**: CLARIFY on a `type_explicit` query = miss; CLARIFY on an ambiguous query = correct;
- **SEARCH-only**, with its `n` printed next to each value;
- for comparisons across runs, the **intersection** of queries that were SEARCH in both runs.

Arms replayed in the same run already share the same SEARCH set.

### Q2: Benchmark size and statistical power

**Why 21 queries cannot separate the arms.** In a paired comparison of hit/miss outcomes, only discordant queries (one arm hits, the other misses) carry information (McNemar / sign test):
- With the exact two-sided test at α = 0.05, 5 discordant queries cannot reach significance even at 5–0 (p = 0.0625).
- 6 discordant queries need 6–0; 8 need 8–0; 10 need 9–1.
- R1's arms disagreed on **2 of 21** queries, so no test, at any split, could have found a significant difference.

R1's audit also attributed the HR@1 rise (0.048 → 0.238) to extraction differences between runs, not to fusion. Run-to-run LLM noise is as large as the effects being measured.

**Minimum detectable difference in HR@K** (paired, two-sided α = 0.05, power 0.8; normal approximation for paired proportions, Connor 1987). Here *d* is the share of queries on which the two arms disagree; a difference larger than *d* is impossible:

| n queries | d = 0.10 | d = 0.20 | d = 0.30 |
|---:|---:|---:|---:|
| 21 | not detectable | not detectable | not detectable |
| 60 | not detectable | 0.16 | 0.19 |
| 100 | 0.088 | 0.12 | 0.15 |
| 120 | 0.080 | 0.11 | 0.14 |
| 200 | 0.062 | 0.088 | 0.11 |

- The 95% Wilson interval for HR@20 = 0.286 at n = 21 is [0.14, 0.50]; at n = 200 it is about ±0.06.
- This matches the IR literature: topic-set size drives error rates more than expected (Voorhees & Buckley, SIGIR 2002); power analysis gives the number of topics needed (Webber, Moffat & Zobel, CIKM 2008); topic set size design gives formulas from variance estimates (Sakai, IRJ 2016).

**Test choice**:
- Primary inferential metric: a **continuous per-query measure** (reciprocal rank of the target, NDCG@10), using a **paired randomization (permutation) test or paired bootstrap**. Smucker, Allan & Carterette (CIKM 2007) found randomization, bootstrap and t-test agree, while sign and Wilcoxon tests are less reliable; Urbano, Lima & Hanjalic (SIGIR 2019) give a large-scale simulation of error rates. Rank shifts such as `phone_02` (4 → 2) are invisible to HR@20 but visible to RR.
- HR@K: report with Wilson CIs and an exact McNemar p-value.
- **Multiple arms**: 5 arms give 10 pairwise tests. Pre-register a few primary comparisons (`rrf3` vs `sum_legacy`, `rrf2` vs `rrf3`) and apply Holm correction to the rest (Carterette, ACM TOIS 2012).
- **LLM noise**: compare arms only by within-run replay (already in place, so extraction is shared). For end-to-end claims, run r = 3 repeats on the test split and report the mean and range.
- Several utterance variants per target (UQV100-style query variability, Bailey et al., SIGIR 2016) reduce utterance noise. They are clustered, though: average them per target and do not count them as extra n.

**Recommendation**: about **200 retrieval queries** (5 strata × 40, minimum 30 per stratum) plus **30 ambiguous queries**. Pooled test-split claims (≈ 120 queries) can then detect ≈ 0.08–0.11 HR differences, and continuous metrics can detect smaller ones. Per-stratum test results (≈ 24 each) are descriptive, with CIs; only large effects (≈ 0.25+) per stratum are detectable, and the report must say so.

### Q3: Strata, inclusion rules, utterance generation, leakage

**Findings on the current benchmark** (`live_eval_dataset.json`, built by `scripts/extract_live_eval_dataset.py`):
1. **Popularity-selected targets.** Each category pool is the 50 products with the most reviews (`ORDER BY rev_count DESC LIMIT 50`, `rev_count >= 1` in 6 of 7 categories). Products with no reviews are 53% of the catalogue and 81% of priced products, and none can be a target. The hard cases R2 needs are excluded by construction.
2. **The 2026-10-06-002 selection metrics were never computed.** The 21 targets, utterances and "discriminative justifications" are hand-written in `TARGET_CONFIGS`. No CSS, CSI or IC computation exists in the script. Peer density uses product-embedding cosine only, with manual `override_peers`.
3. **Brand/model leakage despite the ban.** 7 of 21 utterances name the target brand or model line: Fujifilm Instax Mini, Samsung Galaxy (×2, one with "S9+"), Apple iPhone, Apple 20W, Logitech, Apple MacBook Air M1. Decision 2026-10-06-002 pillar 4 prohibits this.
4. **`structured_filters` are derived from the target, not the request.** Every entry stores `brand` = the target's brand and a `price_max`, including utterances that state neither (e.g. `camera_02`, `phone_01`, `phone_02`; `phone_03` has brand "Amazon Renewed"). These fields must not be used as gold constraints (Q5).
5. **Circular graded relevance.** Peers get grade 0.45 / 0.20 by product-embedding similarity to the target, which favours the product-embedding channel. Strict metrics should be primary; graded NDCG is secondary and flagged as channel-biased until judged labels exist.
6. The generator hard-codes `price_max: 50.0` for `charger_01`, while the committed JSON has 60.0 (AFP-001). Regenerating would silently undo AFP-001.

**Proposed strata** (each computable on Neo4j 5.14 without full-text indexes):

| Stratum | Inclusion rule | Tests |
|---|---|---|
| S0 Control | 2026-10-06-002 pillars 1–2 (≥ 3 reviews, ≥ 5 attributes, peer density) | Continuity with R1 |
| S1 Cold | No `(:Review)-[:ABOUT_PRODUCT]->` edge; `price > 0`; embedded | The normal catalogue case |
| S2 Sparse title | ≤ 2 content tokens after removing brand tokens, alphanumeric codes and stop words; ≥ 3 attributes | Attribute channel as finder (P-3) |
| S3 Accessory trap | Product type T where ≥ 30% of products whose title contains T's head noun sit in a different leaf category | Type precision; RS-09 / RS-24 |
| S4 Trade-off | ≥ 4 stated requirements; on known attribute values no pool product meets all; target = best partial match (judged) | P-4 feature-fit ordering |
| A Ambiguous | No product type, or open indecision between types; gold action = CLARIFY | Clarification recall (RS-23) |

**Tags** (reported as slices, not strata):
- `brand_anchored` (the utterance names a brand);
- `budget_stated`;
- `target_review_embedded`: whether the target is among the 5,715 products with embedded reviews.

**Note on `popularity-bias@K`**: the reference set is "products whose reviews were embedded before the backfill stopped" (4.7% of reviews, 2.2% of products). That measures **review-embedding coverage**, not popularity.
- Recommendation: rename it to `review-coverage-bias@K` in reports, keeping the metric key for compatibility.
- Record the `target_review_embedded` share per stratum. The review channel can only ever find covered targets, and S1 targets are uncovered by definition.
- If the share of covered targets differs between strata, coverage bias and arm effects are confounded. Report HR by `target_review_embedded` and correct the narrative.

**Category spread**: sample targets from ≥ 12 of the 71 live categories, not 7 hand-picked ones. The graph is Electronics-only, so the domain-agnostic claim (fashion, cosmetics) stays a design property and cannot be tested empirically. The thesis must say so.

**Utterance generation without leakage**:
1. **Title-blind generation**: the generator LLM sees the category, graph attributes, description excerpts, and (for S4) the conflicting requirements. It never sees the title or brand, except for `brand_anchored` items. It returns the utterance **and** the gold constraint list it encoded.
2. **Graph validation**: the target must satisfy every gold hard constraint whose value is known. The budget is drawn as target price × U(1.1, 1.5), rounded, so a budget equal to the target price cannot leak.
3. **Automatic leakage checks** per query, stored in the benchmark:
   - title-token overlap (content tokens shared with the title, excluding the product-type head noun) / title content tokens;
   - distinctive-token leak: shared tokens with document frequency < 1% within the category pool, plus any alphanumeric model code (e.g. "S9+", "M525", "C920"), which counts as a hard leak;
   - lexical triviality: a pure-Python TF-IDF ranking of the category pool's titles against the utterance places the target at rank 1.
   - Test-split items must have no hard leak, overlap ≤ 0.3 and must not be lexically trivial. Brand mentions are allowed only with the `brand_anchored` tag.
4. **Human review** of every test-split utterance by the user, for realism (est. 3–4 hours for ≈ 140 items).
5. **Known biases of synthetic queries**:
   - fully synthetic collections inflate absolute scores but largely preserve system rankings (Rahmani et al., SIGIR 2024; follow-up arXiv:2506.10301);
   - LLM user simulators inflate CRS results through target leakage (Zhu, Huang & Sang, 2024, analysing iEvaLM, Wang et al., EMNLP 2023);
   - so R2 should claim **relative arm differences**, with absolute HR reported under that caveat;
   - same-family bias (GPT-4o writing queries for a GPT-4o parser) is a residual risk; generating with a different model family is optional.
6. **Optional, later R2c**: ESCI-style judged relevance (Exact / Substitute / Complement / Irrelevant, Reddy et al., 2022; used by the TREC 2023 Product Search track) on pooled top-20 results from all arms. It replaces the circular embedding-peer grades; Complement maps directly onto accessory traps. Only the labelling scheme is adopted, not the ESCI data, to stay on Amazon Reviews 2023 only. Treating strata as capability tests follows CheckList (Ribeiro et al., ACL 2020).

**Vision impact**: RS-21 conflicts with 2026-10-06-002 in four places:
- pillars 1–2 exclude S1 and S2;
- pillar 4's absolute brand ban conflicts with the `brand_anchored` slice and is already violated by 7 of 21 queries;
- the "14–21 total items across 7 categories" size conflicts with the power analysis;
- the CSS/CSI criteria were never computed.

A Vision decision amending 2026-10-06-002 is required (§5).

### Q4: Tuning/test split

- **Grouped, stratified, hashed**: `split = test if int(sha256(salt + parent_asin), 16) % 100 < 60 else tuning`, applied within each stratum. Hashing by target product keeps one product (and its query variants) in one split.
- Expected size: ≈ 80 tuning + 120 test retrieval queries, plus 12 / 18 ambiguous.
- **Legacy-21** has been examined repeatedly. It goes to **tuning** as the RS-23 development set and is reported separately as a continuity series.
- **Freeze**: commit the benchmark file, its SHA-256 and the salt. The Vision decision records the hash. `scripts/evaluate_retrieval.py` gains `--split {tuning,test,legacy}` and refuses `test` without `--confirm-test`. Each test access is appended to a committed access log.
- **Rule**: all prompt iteration (RS-23 included), weight or `k` tuning and arm selection happen on tuning. The test split is run once per release on the final configuration. Repeated adaptive use of a holdout overfits it (Dwork et al., *The reusable holdout*, Science 2015).

### Q5: constraint-satisfaction@K (RS-20 rest)

- **Gold constraints** come from the utterance (generator output, plus hand annotation for legacy-21), never from the target. They go in a new field `gold_constraints: [{attribute, operator, value}]`.
- **Verdict per (item, constraint)**, checked on the live graph:

| Constraint | Satisfied / violated | Unknown |
|---|---|---|
| price (`less_than`, `greater_than`) | `p.price > 0` compared with the bound | `price IS NULL` or ≤ 0 (75% of products; the Cypher filter lets NULL through) |
| brand include / exclude | `HAS_BRAND` name, same case-insensitive mutual containment as `_build_filters` | No `HAS_BRAND` edge and the title is not decisive |
| numeric attribute (e.g. "≥ 128 GB") | `Attribute.numeric_value` on an attribute whose `attribute_name` matches the one annotated from the target's graph data | No matching attribute; the vocabulary problem is RS-11 |
| category | Not part of CS@K; covered by `type_precision@K` | — |

  Category is left out because `match_category` inherits the word-regex flaw (RS-24), which would score true matches such as the C920 as violations.
- **Aggregates** (P-2: unknown is never scored as a mismatch):
  - `cs_sat@K`, `cs_viol@K`, `cs_unk@K`: shares of (item × constraint) verdicts;
  - `cs_known@K = sat / (sat + viol)`, the judged-only measure, analogous to bpref (Buckley & Voorhees, SIGIR 2004) and condensed lists (Sakai, SIGIR 2007);
  - `violation_free@K`: share of top-K items with zero violations.
  - Coverage (`1 − cs_unk`) is always printed next to the result.
- **Two flavours**:
  - against gold constraints: end to end, so parser errors and MACS budget widening count;
  - against the extracted `search_request`: retrieval adherence, as a diagnostic.
- Expected signal: hard filters make known violations rare when extraction is right. CS@K exposes missed price or brand extraction, MACS relaxation and unpriced items flooding the top-K.

### Q6: Evidence for RS-02 (tuning split only)

**Question**: should `rrf2` become the default, with reviews used for verification only (P-3)?

**Evidence to produce**, from one tuning-split run with all arms replayed and r = 3 repeats:
1. Paired difference `rrf2 − rrf3` in RR / NDCG@10 and HR@20, with a bootstrap CI.
2. **Unique review finds**: queries where the target is in `rrf3`'s top-K but not `rrf2`'s, and per-channel ranks in `eval_trace` show the review channel was decisive.
3. The same broken down by `target_review_embedded` and stratum. The review channel cannot help S1 and only ever helps the 2.2% of covered products.
4. Review-coverage bias@K and p50 latency (R1: 0.212 → 0.062 at K = 5; 757 → 642 ms).

**Pre-registered rule**: adopt `rrf2` if the lower CI bound of ΔHR@20 ≥ −0.05 **and** unique review finds ≤ 2% of tuning queries. Then confirm once on test in R3, together with the other arms.
- At n ≈ 100 (tuning + legacy) with low discordance, the CI half-width is about ±0.05–0.06, so a tighter margin cannot be shown honestly.
- The decision is conditional on the current 4.7% review-embedding coverage and should be revisited if the backfill is finished.
- Reviews stay available for verification (RS-13), so no evidence is discarded.

### Q7: Archiving and reproducibility

**Facts**:
- `.gitignore` line 19 ignores `/evaluations/*`, so runs cited as thesis evidence exist only locally.
- Both R1 runs (`eval_2026-10-17_1846`, `_1937`) record `git_commit 989c1cd` in `manifest.json`. The R1 code ran uncommitted and was committed later as `99b8506`, so the recorded hash does not identify the evaluated code.
- `scripts/evaluate_retrieval.py:get_git_commit` records only HEAD.

**Recommendation**, consistent with 2026-10-03-008's `eval_YYYY-MM-DD_HHMM` naming:
1. **Manifest hardening**:
   - `git describe --always --dirty`;
   - a `git_dirty` flag;
   - a SHA-256 of `git diff HEAD -- src scripts` plus a list of untracked files under `src/` and `scripts/`;
   - the benchmark SHA-256, split and salt;
   - the resolved OpenAI model ID returned by the API (e.g. a dated `gpt-4o` snapshot), not just the alias;
   - the Neo4j server version and a graph snapshot (product count, review-embedded product count, category count);
   - the Python version.
2. **Dirty-tree policy**: by default the eval **warns** on uncommitted changes under `src/` or `scripts/` and writes `citable: false` into the manifest. A `--require-clean` flag refuses to run. Only `citable: true`, `mode: live` runs may be archived.
3. **Committed archive**: a git-tracked `evaluations_archive/<run_id>/` holding `manifest.json`, `summary.json`, `retrieval_metrics.csv`, a compact per-query JSONL (query ID, action, `clarify_reason`, per-arm top-20 ASINs, target rank, per-channel ranks, CS verdicts), and the SHA-256 of the full `execution_trace.log` (~48k lines per run). The trace stays local or in an external store, referenced by hash. A small `scripts/archive_eval_run.py <run_id>` does the copy. Thesis text may cite only archived runs.
4. AI-12: keep test-written mock runs out of `evaluations/` so they cannot be archived by mistake.

---

## 3. Recommended Approach and Release Split

**Order: R2a, then R2b.** The benchmark build reuses R2a's metrics and leakage checks, and the RS-23 fix is developed on legacy-21, which is tuning data anyway.

### R2a — Metrics, RS-23 fix, archive (≈ 2–3 days, M)
1. RS-23 prompt fix (option A), plus removing the `operating_system` example contradiction (S).
2. RS-23 category-recovery step in the guardrail (option C), `_generate_search_params` allowed to return a null category, and `clarify_reason` in `eval_trace` (S).
3. The "1500 → 150" prompt line fixed (S, taken from AI-07).
4. Metrics: CER (parser-only and pipeline), target-admitting category rate, spurious-CLARIFY rate, clarification recall, explicit denominators (all / SEARCH-only / intersection), `review-coverage-bias@K` label (S).
5. constraint-satisfaction@K with satisfied / violated / unknown, known-only and coverage; `gold_constraints` hand-annotated for legacy-21 (M).
6. Statistics helper: paired randomization and bootstrap, exact McNemar, Wilson CI, Holm (S).
7. Manifest hardening, dirty-tree policy, `evaluations_archive/`, archive script (S).

**Exit gate**: spurious-CLARIFY = 0 on legacy-21 across 3 repeated runs; unit tests for all metrics; archived citable runs.

### R2b — Stratified benchmark (≈ 1 week, M–L, plus ≈ 3–4 h of user review)
1. Generator v2 (a new script that does not overwrite the legacy one): strata Cypher S0–S4 and A, title-blind generation with gold constraints, graph validation, leakage and lexical-triviality checks, `target_review_embedded` tag, ≥ 12 categories (M–L).
2. Hashed grouped split, freeze, `--split` / `--confirm-test`, test-access log (S).
3. Human review of test utterances (user).
4. Tuning-split baseline (all arms, r = 3) and the RS-02 decision memo (S–M).

**Exit gate (roadmap R2)**: benchmark frozen and hash recorded before any weight tuning; no `type_explicit` query lost to a spurious CLARIFY on the tuning split across 3 runs; clarification recall on the ambiguous stratum ≥ its pre-fix value.

**Optional R2c**: ESCI-style judged pools to replace embedding-peer grades.

**Out of scope**: AI-07 merge, RS-24 vocabulary matching, any weight or `k` tuning (that is R3, on tuning only).

---

## 4. Guardian Assessment

| Check | Verdict |
|---|---|
| Vision §5 metrics (NDCG, HR) | ✅ Kept; CS@K, CER and clarification metrics are additions |
| Vision §2 Active Clarification | ✅ Protected: option C is gated by clarification recall on the ambiguous stratum |
| 2026-10-05-001 Zero-Mock | ✅ All targets and verdicts come from live nodes; utterances are synthetic, as before; live mode only |
| 2026-10-03-008 versioned runs | ✅ Naming kept; archive adds commit-safe evidence |
| **2026-10-06-002 benchmark framework** | ⚠️ **Conflict.** Pillars 1–2 exclude S1/S2; pillar 4's brand ban is already violated (7/21) and conflicts with `brand_anchored`; the 14–21-item size is underpowered; CSS/CSI were never computed. **Needs an amending decision.** |
| 2026-10-07-010 graded NDCG (AFP-001) | ⚠️ Embedding-similarity peer grades are circular (favour the product channel); demote to secondary until judged labels exist |
| **2026-09-29-007 dynamic domain schemas** | ⚠️ **Not implemented**: no `scripts/extract_domain_schemas.py` and no `dynamic_domain_schemas.json`; the parser injects the static 3-domain `src/llm_interface/domain_schemas.json`. Doc/code gap like D-3; record a correction. Not fixed in R2 |
| No custom training / Amazon Reviews 2023 only | ✅ None; ESCI is used as a labelling scheme only, not as data |
| KISS | ✅ No new dependencies (TF-IDF and statistics in pure Python/NumPy); no vocabulary layer before RS-24 |
| Risk | RS-23 fix is non-deterministic (mitigated by r = 3 gates); synthetic queries overestimate absolute HR (claim relative differences); the Electronics-only graph cannot test cross-domain claims |

**Codebase impact**:
- `src/llm_interface/prompts/preference_extract_prompt.py`
- `src/agents/orchestrator.py` (guardrail, `SEARCH_GENERATION_PROMPT`, `eval_trace.clarify_reason`)
- `src/evaluation/metrics.py`
- `scripts/evaluate_retrieval.py` (split, denominators, manifest, CS@K)
- new generator script and `scripts/archive_eval_run.py`
- `.gitignore` (whitelist `evaluations_archive/`)
- new tests

`DialogueManager` is unchanged; recovery happens in the guardrail.

---

## 5. Decisions Needed (Vision Report, via @pm-research)

| ID | Decision |
|---|---|
| R2-D1 | Amend 2026-10-06-002: pillars 1–2 apply to S0 only; strata S1–S4 and A with their own inclusion rules; the brand ban becomes measured leakage (hard leak = model code or unflagged brand; overlap ≤ 0.3; not lexically trivial) with a `brand_anchored` slice; size ≈ 200 + 30 across ≥ 12 categories; CSS/CSI dropped as selection gates in favour of graph-verified distinguishing features |
| R2-D2 | Frozen hashed tuning/test split (60% test, grouped by `parent_asin`, stratified); legacy-21 goes to tuning; test is run once per release |
| R2-D3 | Statistical protocol: primary metric RR/NDCG@10 with paired randomization/bootstrap; HR with Wilson CI and exact McNemar; Holm across arms; r = 3 for end-to-end claims |
| R2-D4 | RS-23 fix = prompt (A) + category recovery (C); catalogue fallback deferred to RS-24; AI-07 inherits CER as its regression gate |
| R2-D5 | CS@K definition (satisfied / violated / unknown; known-only plus coverage; category excluded in favour of type-precision) |
| R2-D6 | RS-02 pre-registered rule (ΔHR@20 lower bound ≥ −0.05 and unique review finds ≤ 2% on tuning; conditional on 4.7% review-embedding coverage) |
| R2-D7 | Citable-run policy: dirty-tree detection, `citable` flag, committed `evaluations_archive/` |
| R2-D8 | Correction note: 2026-09-29-007 not implemented (static `domain_schemas.json` in use) |

---

## 6. Sources

- Voorhees & Buckley (2002). [*The Effect of Topic Set Size on Retrieval Experiment Error*](https://www.nist.gov/node/707561). SIGIR.
- Webber, Moffat & Zobel (2008). [*Statistical Power in Retrieval Experimentation*](https://people.eng.unimelb.edu.au/ammoffat/abstracts/wmz08cikm.html). CIKM, 571–580.
- Sakai (2016). [*Topic set size design*](https://link.springer.com/article/10.1007/s10791-015-9273-z). Information Retrieval Journal 19(3), 256–283.
- Smucker, Allan & Carterette (2007). [*A Comparison of Statistical Significance Tests for Information Retrieval Evaluation*](https://ir.webis.de/anthology/2007.cikm_conference-2007.67). CIKM, 623–632.
- Carterette (2012). [*Multiple Testing in Statistical Analysis of Systems-Based Information Retrieval Experiments*](https://ir.webis.de/anthology/2012.tois_journal-ir0anthology0volumeA30A1.3). ACM TOIS 30(1).
- Urbano, Lima & Hanjalic (2019). [*Statistical Significance Testing in IR: An Empirical Analysis of Type I, II and III Errors*](https://arxiv.org/pdf/1905.11096). SIGIR, 505–514.
- Connor (1987). *Sample size for testing differences in proportions for the paired-sample design.* Biometrics 43(1), 207–211.
- Buckley & Voorhees (2004). [*Retrieval Evaluation with Incomplete Information*](https://ir.webis.de/anthology/2004.sigirconf_conference-2004.5/). SIGIR.
- Sakai (2007). *Alternatives to Bpref.* SIGIR.
- Dwork, Feldman, Hardt, Pitassi, Reingold & Roth (2015). *The reusable holdout: Preserving validity in adaptive data analysis.* Science 349(6248).
- Zhu, Huang & Sang (2024). [*How Reliable is Your Simulator? An Analysis on the Limitations of Current LLM-based User Simulators for Conversational Recommendation*](https://arxiv.org/abs/2403.16416).
- Wang et al. (2023). *Rethinking the Evaluation for Conversational Recommendation in the Era of Large Language Models* (iEvaLM). EMNLP.
- Rahmani et al. (2024). [*Synthetic Test Collections for Retrieval Evaluation*](https://arxiv.org/abs/2405.07767v1). SIGIR; follow-up [*Towards Understanding Bias in Synthetic Data for Evaluation*](https://arxiv.org/html/2506.10301v1).
- Reddy et al. (2022). [*Shopping Queries Dataset: A Large-Scale ESCI Benchmark for Improving Product Search*](https://ar5iv.arxiv.org/html/2206.06588). arXiv:2206.06588.
- Campos et al. (2023). [*Overview of the TREC 2023 Product Search Track*](https://arxiv.org/pdf/2311.07861).
- Aliannejadi et al. (2020). [*ConvAI3: Generating Clarifying Questions for Open-Domain Dialogue Systems (ClariQ)*](https://arxiv.org/pdf/2009.11352).
- Ribeiro, Wu, Guestrin & Singh (2020). *Beyond Accuracy: Behavioral Testing of NLP Models with CheckList.* ACL.
- Bailey, Moffat, Scholer & Thomas (2016). *UQV100: A Test Collection with Query Variability.* SIGIR.
- Project:
  - `production_artifacts/Audit_Report.md` (R1, M-3)
  - `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md`
  - `thesis/10-doc-fusion-ablation.md` (R1 paired sign tests; the 16-of-21 denominator; coverage vs popularity bias)
  - `evaluations/eval_2026-10-17_1846`, `evaluations/eval_2026-10-17_1937` (local only)
