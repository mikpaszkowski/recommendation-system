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
| K-1 | Download the raw Amazon Reviews 2023 Electronics metadata again (for the `details` dict and bullet and level boundaries), or work from the CSV only |
| K-2 | Approve graph writes (features property, category tree, full-text index, ghost handling): in place, or in a separate database / after a dump. **Decided (user, 2026-10-18)**: in place on the current graph, after an offline `neo4j-admin database dump` (Community 5.14 has no `CREATE DATABASE` and dumps offline only). Writes run after R2a's citable runs are archived and before the R2b freeze. All writes are additive under new names (`p.features`, a new full-text index, the tree under a new label and relationship, not `Category` / `BELONGS_TO_CATEGORY`), so the current code reads the same data and R1/R2a runs stay reproducible. Readers switch over behind a config flag. Each write script is idempotent and has an undo script. A `GraphVersion` stamp is added to `src/evaluation/provenance.py`, whose `graph_snapshot` counts would not detect these writes. Ghost handling belongs to K-3 (a query-time filter needs no write). |
| K-3 | What to do with ghosts: filter at query time, or remove from the graph; and recompute the published coverage figures |
| K-4 | Extractor and budget: gpt-4o-mini Batch API vs a local LLM; gpt-4o for the audit |
| K-5 | Retire the attribute vector channel or replace it with BM25, depending on the R3 arm |
| K-6 | Re-embed products with features text (changes the R1 baseline): as an arm, or not at all |
| K-7 | Move the leaf category rebuild from R3 into R2b, which delays the benchmark freeze by about a week |
| K-8 | Query-time verifier latency budget, or precomputed verdicts for the benchmark categories |
| K-9 | An extraction-only Beauty/Fashion probe as evidence for domain-agnosticism, or keep it as a design property |
| K-10 | Distilled spec tagger for the long tail (extends D-2) |
