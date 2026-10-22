# Intent: KG Attribute Gap (RS-11, RS-12, RS-03, RS-24, R2b, thesis corrections)

**Source**: autonomous brainstorm, 2026-10-18 (`.memlog.md` in this folder: 176 entries, 118 ideas, 10 techniques).
**Feeds**: `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md` (RS-03, RS-11, RS-12, RS-24), the R2b part of `production_artifacts/Research_Report.md`, Vision decision 2026-10-18-014, and `thesis/`.
**Downstream**: `/implement` (@pm-research for the decisions and corrections, then @pm-specs).

## Problem

Parts of the system assume product attributes hold typed specifications. On the live graph they hold almost nothing but colour, material, style and size, and `numeric_value` exists nowhere. The full ingest read `processed_metadata.csv`, which kept 5 of Amazon's `details` keys. It also dropped `features_text` and the full `categories_text` path. Consumers that cannot work on this data: numeric filters in `_build_filters`, the attribute channel in the RRF fusion, KECR attribute paths, the Critic, CS@K numeric verdicts, and the R2b strata S2 and S4.

## New facts from this session (read-only, 2026-10-18)

| Fact | Value | Consequence |
|---|---|---|
| Untitled "ghost" products | 104,281 of 265,307 (39%): no title, price or category, but embedded and reviewed | They can pass the `price IS NULL` filter into top-K |
| Real (titled) products with any review | 19,439 of 161,026 (12%) | The roadmap's "47% have reviews" figure counts ghosts |
| Review-embedded products that are ghosts | 4,874 of 5,715 (85%) | The review channel and coverage-bias@K mostly measure ghosts |
| Priced products with `features_text` in the CSV | 62,131 of 65,650 (94.6%) | The evaluable catalogue already has spec text, with no re-download |
| Distinct `categories_text` paths | 975, with levels space-joined | A leaf tree can be rebuilt cheaply |
| `SUBCATEGORY_OF` edges | 33 | The AFP-003 hierarchy traversal does almost nothing |
| Products with no category | 105,933 | Mostly ghosts |
| Explicit `Key: value` pairs in features | rare | Most specs are in prose, so extraction needs an LLM; regex is a minor tier |

## Follow-up facts on ghosts (read-only, 2026-10-18, after the session)

| Fact | Value | Consequence |
|---|---|---|
| What ghosts are | 104,216 of 104,306 ghost IDs are normal `B0…` Amazon IDs; 90 are ISBN-like | Ghosts are real Electronics products whose metadata was never loaded, not junk. The ISBN-like ones (e.g. comic `0062970704`) are Amazon category noise: the ID occurs 799 times in the official `Electronics.train.csv` |
| Ghost properties | only `parent_asin` and `embedding` | Nothing to filter or explain on |
| Ghost embeddings | identical across a 50-ghost sample (cosine 0.99999…) | `backfill_embeddings.py` embedded the blank template "Product: . Category: Unknown. Features: . Description: "; every ghost scores the same for any query, so which ghost surfaces is arbitrary |
| Cause 1: source mismatch | `batch_ingest.py` read `datasets/processed_data/`: 161,001 metadata rows, 1,630,273 reviews over 123,720 products, only 19,414 in both | Metadata and reviews were sampled independently (likely `process_and_save_data`, whose `frac` keeps the first X% of lines of each file; the call parameters of March 2025 are not recorded) |
| Cause 2: ingest creates products from reviews | `batch_ingest.py:219` `MERGE (p:ParentProduct …)` in the review step | Any review whose product has no metadata creates an empty product node |
| Cause 3: blank texts are embedded | `backfill_embeddings.py` builds the product text without checking it is empty | Ghosts get an embedding and enter the product vector index |
| Unused consistent dataset | `datasets/processed_data_complete/`: same 161,001 products, 321,410 reviews, 0 reviewed products without metadata, 47,657 real products with reviews (vs 19,414 in the graph) | Produced by `process_complete_product_data` (metadata sample, then all reviews for those products); never ingested |
| Correction | Earlier wording "most ghosts are books" was wrong | — |

## Directions

### Quick wins (week 1, no LLM labelling; graph writes need approval)
1. **Ghost guard**: keep untitled products out of every channel and every coverage statistic.
2. **Store `features_text`** as `ParentProduct.features`.
3. **Rebuild the leaf category tree** from the 975 paths: a word-trie plus one GPT-4o pass, then a hand audit. This fixes `ret_021`.
4. **Add a full-text index** over title, description and features. Neo4j 5.14 supports it.
5. **Make numeric `*_min/_max/_exact` filters verify-only**, and add a startup capability manifest that switches off code paths whose data is missing.
6. **Add a KECR IDF floor**, so a path through a node shared by 21k products ("shares Color: black") is never shown.

### RS-12 (feature check)
- **One evidence contract**: a requirement maps to `confirmed | contradicted | unknown | disputed`, with a quoted span, a source tier and an extractor ID. The Critic, KECR, explanations and CS@K all consume it.
- **Interim provider**: one batched LLM verifier over the listing text of the top 20 candidates, merged with RS-17.
  - A mechanical span gate checks each verdict: the quote must be an exact substring of its source field, and the value must re-parse from it.
  - Assertion status is applied: associated-with ("compatible with iPhone 14"), conditional, and possible ("up to").
- **Other providers**: BM25 full-text is the cheap pre-check. Verdicts are cached.

### RS-11 (typed vocabulary)
- **Storage**: `(p)-[:HAS_SPEC {value, unit, raw, source, span, extractor, conf}]->(:FeatureKey {name, type, dimension, ladder})`. Value nodes stop being hubs.
- **Vocabulary is induced per leaf category**: open extraction, then key clustering, then an alias table. It is seeded with the raw `details` keys only if the metadata is downloaded again.
- **Types are inferred from the data**. Dimensions come from the UCUM tables, and ordinal ladders are confirmed by a human.
- **Every fact carries an evidence code**: STR (seller-structured), LST (listing text), REV (review), INF (inferred). INF facts are never shown as listing facts.
- **Confirmation requires two extractors to agree**.
- **Go/no-go in week 3**: a 200-product stratified random audit plus a 50-item trap set. If span-gated precision is below 0.85, labels ship as find-only.
- **Rollout**: start with priced products in the benchmark categories. Write additively under new labels, in a separate database or after a dump, and add a `GraphVersion` stamp to the eval manifest.

### RS-03 (attribute channel)
1. **Arm**: RRF without the attribute channel, on the tuning split (R3).
2. **Replacement**: a BM25 channel over title, features and description. This is the standard dense + lexical hybrid.
3. **Later**: a symbolic `HAS_SPEC` finder inside the leaf category, weighted by in-leaf IDF.
4. **Colour**: used only when the user names a colour.

### RS-24 (product type)
- **Type vocabulary in SKOS style**, built from the rebuilt leaves plus title head nouns extracted by an LLM. The labels are data, with altLabels in several languages.
- **Closed-set query classification**: an embedding shortlist of about 20 labels, from which the LLM picks up to 3 with confidences.
- **Hard filter only on agreement**: the classifier's top type must also be the dominant leaf among the top-k product hits.
- **Two types per product**: a primary type plus "for" types.
- **Low confidence** across several types triggers a clarifying question.
- **type-precision@K** is measured on leaf types.

### R2b amendment (to 2026-10-18-014)
1. **Rebuild the category tree before freezing.** S3 and type-precision depend on it.
2. **Compute stratum features from the CSV**, with a recorded source hash, so graph enrichment cannot move a query between strata.
3. **S2**: sparse title plus at least 3 span-verified facts from listing text. This replaces "at least 3 attributes".
4. **S4 and the distinguishing-feature rule** use verifier verdicts. Only peers where the feature is stated absent count; unknown peers do not.
5. **Gold constraints** carry a source span and are written by a different model family than the system's verifier.
6. **Leak checks** cover every generator input, with model codes stripped.
7. **Exclusions**: no ghosts, and no hand edits to the facts of benchmark products.
8. **Numeric CS@K**: use a separate eval judge, or report numeric constraints as "not measurable" rather than inside `cs_unk`.

### Thesis corrections
- **`thesis/3-doc-robust-retrieval.md`**: RQ3 cannot claim EAV numeric traversal.
- **`thesis/10-doc-fusion-ablation.md`**: the attribute channel matches colour, material and size, so its result is a lower bound.
- **`thesis/7-doc-evaluation-framework.md`**: Groundedness is unfair until features text is in the KG, because true spec claims are scored as fabricated.
- **2026-10-07-009 point 3**: hierarchical traversal is vacuous with 33 edges.
- **Coverage statistics**: recompute on the 161k titled products, and note the 85% ghost share of the coverage-bias reference set.
- **Vision correction note** for §4, 2026-09-28-006 point 4 and 2026-10-09-012, following the 2026-10-18-017 precedent.
- **Reframe the grounding claim**: the KG grounds identity, type, price and brand as structure, and grounds features as quoted listing text stored in the KG.

## Decisions needed

| ID | Decision |
|---|---|
| K-1 | Download the raw Amazon Reviews 2023 Electronics metadata again (for the `details` dict and bullet and level boundaries), or work from the CSV only. **Decided (user, 2026-10-18)**: use the raw data. No download is needed: the complete raw files are already in the local Hugging Face cache (`~/.cache/huggingface/hub/datasets--McAuley-Lab--Amazon-Reviews-2023/blobs/`): `meta_Electronics` = blob `5eb4dabd…5d93` (5.2 GB, 1,610,012 lines), reviews `Electronics` = blob `bf11cf9c…8de8e` (22.6 GB, 43,886,944 lines), downloaded 2025-01-30. All 104,306 ghost products and all 161,001 current products have a raw metadata entry (e.g. ghost `B0001A3N58` = Nikon 7218 binoculars, with categories list, details dict and features list). Done 2026-10-18: hard-linked as `datasets/raw/meta_Electronics.jsonl` and `datasets/raw/Electronics.jsonl` (git-ignored, no extra disk); SHA-256 in `datasets/raw/SHA256SUMS` matches the Hugging Face blob names, so the files are intact. The pipeline reads from `datasets/raw/` and records these hashes. It also restores the metadata of the ghost products (K-3) and gives exact category levels (K-7). Open: catalogue and review scope of the re-ingest. |
| K-2 | Approve graph writes (features property, category tree, full-text index, ghost handling): in place, or in a separate database / after a dump. **Decided (user, 2026-10-18)**: in place on the current graph, after an offline `neo4j-admin database dump` (Community 5.14 has no `CREATE DATABASE` and dumps offline only). Writes run after R2a's citable runs are archived and before the R2b freeze. All writes are additive under new names (`p.features`, a new full-text index, the tree under a new label and relationship, not `Category` / `BELONGS_TO_CATEGORY`), so the current code reads the same data and R1/R2a runs stay reproducible. Readers switch over behind a config flag. Each write script is idempotent and has an undo script. A `GraphVersion` stamp is added to `src/evaluation/provenance.py`, whose `graph_snapshot` counts would not detect these writes. Ghost handling belongs to K-3 (a query-time filter needs no write). |
| K-3 | What to do with ghosts: filter at query time, or remove from the graph; and recompute the published coverage figures. **Direction (user, 2026-10-18)**: fix the cause in the pipeline (preprocessing, `batch_ingest.py`, `backfill_embeddings.py`) and re-ingest from the re-downloaded raw data (K-1), so ghosts are filled rather than deleted. See "Follow-up facts on ghosts". **Decided (user, 2026-10-18)**: catalogue scope = today's ~265k products (161k titled + the 104k ghost products, filled from raw metadata); products with no raw metadata entry are left out. The fixed pipeline selects products first, loads reviews only for selected products, and never creates a product from a review, so the rebuilt graph has zero ghosts. The rebuild is a new graph version (amends K-2's additive assumption); v1 stays reproducible via the dump. |
| K-4 | Extractor and budget: gpt-4o-mini Batch API vs a local LLM; gpt-4o for the audit |
| K-5 | Retire the attribute vector channel or replace it with BM25, depending on the R3 arm |
| K-6 | Re-embed products with features text (changes the R1 baseline): as an arm, or not at all |
| K-7 | Move the leaf category rebuild from R3 into R2b, which delays the benchmark freeze by about a week. **Decided (user, 2026-10-18)**: rebuild the tree during the re-ingest (R2b, before the benchmark freeze) from the raw category lists, under new names (K-2). |
| K-8 | Query-time verifier latency budget, or precomputed verdicts for the benchmark categories |
| K-9 | An extraction-only Beauty/Fashion probe as evidence for domain-agnosticism, or keep it as a design property |
| K-10 | Distilled spec tagger for the long tail (extends D-2) |
| K-11 | Review scope of the re-ingest. **Decided (user, 2026-10-18)**: at most the 20 most helpful reviews per product (same cap as the old pipeline), chosen after the split rule (K-12) is applied. Measured 2026-10-18 (read-only, raw `Electronics.jsonl`): the 265,307 in-scope products carry 35,349,187 of the 43,886,944 raw reviews; 2,828,276 are valid/test pairs; 32,520,911 remain, of which only 10,495,892 are train-split pairs (the rest belong to users outside Amazon's 5-core splits). With the cap of 20: 3,388,842 reviews; 265,294 products keep at least 1 review, 185,332 at least 5, 138,021 at least 20. Reviews in no split are kept (K-12), so the capped total is 3,388,842. Size note: ~8-9 GB in Neo4j with text and 384-d embeddings; local MiniLM embedding on the order of 1-2 h; the 2 GB heap may need raising. |
| K-12 | Leakage against the official Amazon 2023 splits (`datasets/Electronics.{train,valid,test}.csv`; train 12,191,484 rows, valid and test 1,641,026 each, 1999-06 to 2023-09, i.e. the same data version as the raw download). **Decided (user, 2026-10-18)**: only (user, product) pairs in the valid or test split are left out. Everything else stays: train-split pairs (10,495,892) and reviews by users outside the 5-core splits (~22.0M, in no split, so no leakage path), so Meta-Phase C baselines and the KG see the same training data. Products stay in the catalogue even if their only reviews are held out. |
