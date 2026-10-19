# Research Report: Graph v2 Data-Foundation Rebuild (K-3 Ghost Fix)

**Date**: 2026-10-18
**Requested by**: `/implement` Phase 1. Fix the ingest pipeline that created 104k empty "ghost" products, and rebuild the Neo4j graph from the raw Amazon Reviews 2023 Electronics files (K-1, K-3, K-7, K-11, K-12 settled; K-2 amended).
**Status**: Approved 2026-10-19 (Gate #1, G-1 … G-12; G-11 brand case duplicates reported only, G-12 Variant/PriceRange removed from `graph_cypher_prompt.py`). Recorded in the Vision Report as 2026-10-19-018 … 021.
**Inputs**: `_bmad-output/brainstorming/brainstorm-kg-attribute-problems-2026-10-18/brainstorm-intent.md`, `production_artifacts/Vision_Report.md`, `production_artifacts/Implementation_Plan.md`, `production_artifacts/action_items/Retrieval_Score_Redesign_Roadmap.md`, `production_artifacts/action_items/Live_Graph_Audit_2026-10-10.md`, and the code cited below.
**Note**: Saved as a separate file because `production_artifacts/Research_Report.md` holds the active R2 report.

## Executive Summary

Rebuild the graph in three stages.
1. A Python transform reads `datasets/raw/*.jsonl` and writes validated, de-duplicated CSV files plus a lineage file.
2. `neo4j-admin database import full` loads them into a fresh store. Community Edition supports this offline. It builds nodes only from node files, and a relationship that points to a missing product fails the import, so ghosts cannot be created by construction.
3. Online steps then add constraints, embeddings, vector and full-text indexes, a `GraphVersion` node and a validation gate.

V2 keeps every v1 label, relationship and embedding template that the current code reads. That way the v1 → v2 baseline change measures the data fix only. The category tree, the full `details` dict and the `features` bullets go in under new names that no current reader uses.

This research found five new facts:
- The v1 preprocessing read the wrong review field names, so every v1 review has `helpful_votes = 0` and `sort_timestamp = 0`.
- Neo4j 5.14 has no `CREATE VECTOR INDEX` DDL (it arrived in 5.15).
- The raw category lists make the K-7 tree a deterministic step with no LLM.
- The S1 "cold" stratum of decision 2026-10-18-014 nearly vanishes on v2: only 13 of 265,307 products have zero reviews.
- R2a's citable runs are not archived yet (`evaluations_archive/` holds only the three non-citable R1 legacy runs), so the K-2 start gate is not met today.

## Problem Statement

The live v1 graph holds 265,307 `ParentProduct` nodes. 104,281 of them (39%) are ghosts: they carry only `parent_asin` and an embedding of the blank template. The ghosts have three causes:
- **Independent sampling.** `process_and_save_data` sampled metadata and reviews separately (`src/utils/AmazonDataProcessor.py:1041-1042`).
- **Products created from reviews.** The review step merges products: `scripts/graph_ingestion/batch_ingest.py:219` runs `MERGE (p:ParentProduct …)`.
- **Blank texts embedded.** `src/knowledge_graph/graphdb/backfill_embeddings.py:172-178` never checks for empty text.

Ghosts pass the `price IS NULL` filter (`src/tools/graph_search_tool.py:678`). They are 85% of the review-embedded reference set and distort every coverage figure. Because the KG is the grounding layer (Vision §4), a product with no data cannot be grounded or explained. The fix is a rebuild with a data contract, not a query-time filter.

## Research Findings

### New facts verified during this research (read-only)

| # | Fact | Evidence | Consequence |
|---|---|---|---|
| N-1 | All 1,630,273 rows of `datasets/processed_data/processed_reviews.csv` have `helpful_votes = 0` and `sort_timestamp = 0` | Count by regex over the CSV; re-checked by the orchestrator. `AmazonDataProcessor.process_reviews_file` reads `helpful_votes` and `sort_timestamp` (lines 304, 309), but the raw fields are `helpful_vote` and `timestamp` (unix ms) [10] | The v1 "20 most helpful" cap (`_filter_reviews`, lines 363-371) actually sorted by `verified_purchase` only, per child `asin` and not per parent, with pandas' default unstable sort. AI-03's plan to backfill timestamps from this CSV cannot work. V2 takes both fields from raw. |
| N-2 | v1 `review_id = md5(user_id-asin-sort_timestamp)` with the timestamp always 0 | `batch_ingest.py:194-195` | Repeat reviews of the same child ASIN by the same user collapse into one node. This is consistent with 1,630,273 CSV rows becoming 1,629,426 `Review` nodes (847 fewer); the cause is likely but not verified. V2 uses the real timestamp. |
| N-3 | The v1 preprocessing defaults drop items with fewer than 5 reviews and users with fewer than 2, within the sampled slice | `process_and_save_data` defaults, lines 1008-1010. The March 2025 call parameters were not recorded. | v1 reviews were not a uniform sample. V2 applies only K-11 and K-12. |
| N-4 | `CREATE VECTOR INDEX` arrived in Neo4j 5.15; 5.14 needs `db.index.vector.createNodeIndex` | [8] | `src/knowledge_graph/graphdb/create_vector_indexes.cypher` and `create_indexes.py` (DDL) fail on 5.14. `setup_indexes.py` (procedure first, DDL fallback) works. 5.14 also has no vector quantization (quantization requires the vector-2.0 provider, 5.18+). |
| N-5 | 265,294 of 265,307 v2 products keep at least 1 review (from the brief's measurement) | Brief | The 53% "cold" share behind stratum S1 in 2026-10-18-014 was a sampling artefact. S1 as defined ("no reviews") has about 13 candidates on v2. |
| N-6 | Raw `categories` is a list of levels | Raw meta [10] | The K-7 tree needs no word-trie and no GPT-4o pass. That pass was only needed for the space-joined CSV paths. |
| N-7 | Two text builders depend on `collect()` order, which is not deterministic | `backfill_embeddings.py:168-176` (top-5 attributes), `backfill_category_embeddings.py:45` (sample titles) | Re-embedding identical data is not reproducible bit for bit. Fix with explicit ordering. |
| N-8 | `docker-compose.yml` sets `dbms_transaction_timeout=60s`, heap 2G and pagecache 1G | `src/knowledge_graph/docker-compose.yml:17-28` | Large write batches and index builds must stay under 60 s per transaction, or the timeout must be raised during the build. |
| N-9 | Docker Desktop VM has 8 GB of memory on a 16 GB Mac | `docker info`, `sysctl hw.memsize` (checked by the orchestrator) | Constrains G-5 and G-7 (see Q4, Q6). |

### Literature and documentation review

- **Neo4j Operations Manual 5: `neo4j-admin database import`** [1][2]. Full import is available in Community; incremental import is Enterprise only. It needs an offline target database that is empty or does not exist, and `--overwrite-destination` deletes any existing files. Array types are declared as `float[]` and `string[]`, with `--array-delimiter`. By default `--skip-bad-relationships` and `--skip-duplicate-nodes` are false, `--bad-tolerance` is 1000 and the report goes to `--report-file`. Creating indexes during import (`--schema`) is Enterprise only and 5.24+, so Community must create indexes after the import. *Applicability*: this fits a one-shot, versioned rebuild of the only user database (`neo4j`).
- **Neo4j Docker operations** [3]. Import runs as `docker run --rm --volume=<data>:/data --volume=<csv>:/import neo4j:<ver> neo4j-admin database import full …`. *Applicability*: run it in a throw-away container from the same `neo4j:5.14.0` image against a stopped volume.
- **Offline dump** [4]. "On Community Edition, the command can be run only on an offline Neo4j DBMS." This confirms K-2's procedure.
- **Memory configuration** [5]. Page cache ≈ 1.2 × (data + native indexes). For new deployments, import a fraction of the data, measure, and extrapolate. Set initial heap equal to max heap. Reserve memory for the OS. `neo4j-admin server memory-recommendation` gives starting values.
- **Vector index memory** [6]. Lucene vector index files live in the OS filesystem cache, not the Neo4j page cache. Without quantization (the 5.14 case), allow about 100% of the index size. Size ≈ 1.1 × (4 B × dims + 8 B × M) per vector, with M = 16 by default.
- **Full-text indexes** [7]. `CREATE FULLTEXT INDEX … ON EACH [n.a, n.b]` indexes STRING and LIST<STRING> properties. The analyzer is configurable (`fulltext.analyzer: 'english'`); the default is `standard-no-stop-words`. *Applicability*: `p.features` can stay a list, which keeps bullet boundaries for RS-12 span quoting. Smoke-test LIST<STRING> indexing on 5.14 before relying on it.
- **Amazon Reviews 2023** (Hou et al., 2024) [9][10][11]:
  - Metadata fields include `main_category`, `categories` ("hierarchical categories"), `details`, `features` (bullets), `description`, `store` and `price`.
  - Reviews carry `helpful_vote`, `timestamp` (unix ms) and `verified_purchase`.
  - The 5-core, leave-last-out splits give each user's last item to test and the one before to valid.
  - *Applicability*: confirms the field names behind N-1, the exact category levels (N-6) and the K-12 exclusion unit (user, parent_asin).
- **all-MiniLM-L6-v2** [12][13]. Input beyond 256 word pieces is truncated, and the model was trained on 128 tokens. sbert.net lists about 14k sentences/s on a V100 GPU; a laptop is far slower, so measure. *Applicability*: field order in the template decides what survives truncation, which matters for K-6.
- **W3C SKOS** [14]. Concepts with `prefLabel`/`altLabel` and `broader`/`narrower` relations. *Applicability*: naming for the tree (`BROADER`) and the later RS-24 type vocabulary.
- **Data validation practice** [15][16][17][18]:
  - Breck et al. (SysML 2019, TFX Data Validation): a schema for the data, checks for anomalies before data is used, and data treated like code.
  - Schelter et al. (Deequ, 2018): declarative "unit tests for data" (completeness, uniqueness, referential checks).
  - Great Expectations: expectation suites with a stored validation result.
  - Gebru et al. (Datasheets for Datasets): document how a dataset was built.
  - *Applicability*: a check suite with hard gates and a lineage file that records source hashes and per-step drop counts. These are plain Python and Cypher checks; no new framework dependency is needed.

### Q1: Load method

| Criterion | A. `neo4j-admin database import full` | B. Batched Cypher `UNWIND` via driver (v1 way) | C. `apoc.periodic.iterate` + `apoc.load.json` |
|---|---|---|---|
| Community 5.14 | Yes, offline, into `neo4j` [1] | Yes, online | Yes (APOC installed) |
| Speed (about 7M nodes, about 7.5M relationships) | Fastest; writes store files directly, no transactions or tx logs. Expect minutes; confirm with a pilot. | Slowest; MERGE plus constraint lookups per row, about 0.5–3 h, plus tx logs | Middle; but scans 22.6 GB JSONL inside the container |
| Ghost safety | Structural: nodes come only from node files. A relationship to a missing ID is "bad" and aborts with `--bad-tolerance=0`. | Depends on discipline: one `MERGE` in the wrong place recreates ghosts (the v1 bug) | Same risk as B |
| Idempotency | The whole build is idempotent: `--overwrite-destination` gives the same store from the same CSVs | Per batch via MERGE and checkpoints (`.ingest_checkpoint.json`); resume state is a failure source | Per batch |
| Reproducibility | Graph = f(CSVs); hash the CSVs | Graph = f(CSVs, run history, checkpoint state) | Selection rules (top-20 by helpfulness, split exclusion) are awkward to express and test in Cypher |
| Clearing v1 | Not needed; overwrite or fresh volume | Needs `DETACH DELETE` of about 9 GB in batches, or a new volume | Same as B |
| Constraints and indexes | Created after import (Community) | Before load | Before load |
| Embeddings | Possible as `float[]` in CSV, but about 13 GB of text for 3.39M review vectors. Better written online after import. | Online | Online |
| Fit with existing code | New import wrapper. `backfill_embeddings.py` and `setup_indexes.py` are reused online. | Reuses `batch_ingest.py` | New |

**Recommendation: A**, in three stages:
1. **Transform** (pure Python, unit-testable without Neo4j): read `datasets/raw/meta_Electronics.jsonl` and `Electronics.jsonl`, the frozen catalogue ID list and `datasets/Electronics.{valid,test}.csv`. Write node and relationship CSVs plus `lineage.json`.
   - Selection runs in two streaming passes: (1) selection keys per product with a bounded heap of 20, then (2) extraction of the selected lines.
   - Memory is roughly 1–1.5 GB: the valid/test pair set (2.83M) plus about 5.3M heap entries.
   - Use `--multiline-fields=true` for review text, and an `--array-delimiter` character that never occurs in the data (e.g. U+001F) because bullets contain `;`.
2. **Import**: stop `neo4j-recommendation` and run `neo4j-admin database import full --overwrite-destination --bad-tolerance=0 --report-file=… neo4j` in a `docker run --rm` container of `neo4j:5.14.0`.
3. **Post-import online steps**: constraints and range indexes; embeddings; vector indexes (procedure form, N-4); the full-text index; the `GraphVersion` node; the validation gate.

Also fix the v1 scripts so they cannot recreate ghosts if anyone reuses them:
- In `batch_ingest.py:219`, replace `MERGE` with `MATCH`.
- In `backfill_embeddings.py`, skip empty content (Q4).

**Volume strategy.** In addition to the K-2 dump, import into a new named volume (e.g. `knowledge-graph_neo4j_data_v2`) and keep the v1 volume untouched. Switching the volume in `docker-compose.yml`, for example through an external volume name from `.env`, is an instant rollback and lets R1/R2a be re-run on v1 without restoring the dump. Disk budget: 89 GB free; v1 ≈ 7 GB; v2 ≤ 21 GB (Q6); import CSVs ≈ 5–6 GB; dump ≈ 3–5 GB.

### Q2: V2 schema and comparability with v1 code

Recommendation: yes. Keep the v1 contract that current readers depend on, and add the tree under new names.

| Element | v1 | v2 | Reader |
|---|---|---|---|
| `ParentProduct` | parent_asin, title, price, avg_rating, review_count, description, embedding | Same names and semantics. New: `features` (LIST<STRING>), `details_json` (raw dict, `sort_keys`), `details_text` (flattened `Key: value` lines for scalar values; optional), `category_path` (LIST<STRING>), `store` | `graph_search_tool.py`, `kecr_tool.py` |
| `Category` + `BELONGS_TO_CATEGORY` | `main_category` (71 nodes; 34 legacy nodes have `level`; 33 legacy `SUBCATEGORY_OF` edges) | `main_category` only. No `level` and no `SUBCATEGORY_OF`. The node count will change because filled ghosts add `main_category` values. | `graph_search_tool.py:724` (`*0..3` still matches the leaf itself), `kecr_tool.py:210,235`, `resolver_service.py:123`, `provenance.py:183` |
| `Brand` + `HAS_BRAND` | `coalesce(store, details.Brand)`, exact-name MERGE | Same rule | Brand filter, KECR |
| `Attribute` + `HAS_ATTRIBUTE` | Material, Color, Style, Size; no `numeric_value` on the live graph | Same 4 keys from raw `details`. `numeric_value` is not written (Q3). | Attribute channel, KECR, CS@K |
| `Review` + `ABOUT_PRODUCT`, `User` + `WROTE` | review_id, review_title, review_body, rating, verified | Same, plus `timestamp` (ms), `helpful_vote`, `asin` (child), `in_train_split` (bool) | Review channel, `fetch_product_attributes`, KECR (AI-03 becomes feasible) |
| Legacy `Variant`/`Product`/`PriceRange`, `REVIEWS` (4,847) | Present | Dropped. No reader in `src/tools` or `src/agents`; KECR's `REVIEWS` path already yields nothing, because rating is not on the edge. | — |
| **New tree** | — | `(:Taxon {taxon_id, name, path, depth, product_count})`, `(:Taxon)-[:BROADER]->(:Taxon)` (child → parent, SKOS `broader` [14]), `(:ParentProduct)-[:IN_TAXON]->(:Taxon)` | R2b benchmark generator (offline). RS-24 in R3. |
| New index | — | `product_fulltext_index` on title, description, features (and `details_text`), `english` analyzer | Nobody yet (RS-12, RS-03 BM25 arm) |

Tree rules:
- **Identity** is the full path: `taxon_id` is the levels joined with " > ", case kept. Duplicate leaf names in different branches ("Accessories", "Cables") are therefore separate nodes. `name` is not unique. Add a uniqueness constraint on `taxon_id` only.
- **Assignment**: each product gets one `IN_TAXON` edge to the deepest level of its own path. That level may be an inner node of the tree, because Amazon lists some items at intermediate levels. Ancestors are reached through `BROADER*`.
- **Empty category lists**: no `IN_TAXON` edge. Report the count per `main_category`.
- **Roots**: several roots are allowed (e.g. "Electronics", and whatever roots the filled ghosts bring).
- **No runtime flag now.** No runtime reader uses the tree before RS-24 (R3). Add a `GRAPH_TAXONOMY` flag when a reader switches; a flag without a reader is dead configuration.
- **No `Taxon` embeddings now.** They are cheap, but nothing reads them until RS-24.

### Q3: Attributes in v2

- **`HAS_ATTRIBUTE`**: keep exactly the 4 v1 keys from raw `details` (`Material`, `Color`, `Style`, `Size`), with case-sensitive key match, scalar string values only and the v1 node key `(attribute_name, attribute_value)`. Brand stays a `Brand` node. This keeps the attribute channel and KECR comparable with v1. It also drops the v1 vocabulary chaos (`color` vs `Color`, `best_sellers_rank`, `feature`), which came from the legacy build and `decompose_attributes.py`.
- **No `numeric_value`.** `parse_numeric_attribute` (`batch_ingest.py:24`) on colour, style or size strings gives nonsense (e.g. "Black 2" becomes 2.0). Typed numerics belong to RS-11 (`HAS_SPEC`), and the correction note (§8) withdraws the numeric EAV claim.
- **Raw `details` and `features` are stored as product properties, not nodes.**
  - `p.details_json` keeps the whole dict for RS-11 seeding and the `STR` evidence tier.
  - `p.features` keeps the bullets as a list for RS-12 span quoting.
  - `p.details_text` is optional and feeds the full-text index.
  - Properties create no hub nodes and no new vector index. RS-11 later writes `HAS_SPEC` edges with quoted spans from these properties.
- **Full `details` dict as `Attribute` nodes: rejected.** It would recreate value hubs ("Color: Black" shared by about 21k products), change the attribute channel (confounding the v1/v2 comparison), and duplicate RS-11 work.

### Q4: Embeddings

**Product template (K-6).** Re-embed all products with the **v1 template**: `"Product: {title}. Category: {main_category}. Features: {up to 5 'Name: value' attributes}. Description: {description}"`. Order the attributes by `attribute_name` (N-7) and record template ID `product_v1`.

K-6 does **not** need to be decided now. Embeddings are written online after the import, so a features-based variant can be added later as `p.embedding_feat` with its own vector index. That takes about 10–20 minutes of compute and no rebuild, and runs as an R3 arm (it pairs with RS-08 query versions).

Deciding K-6 now would change two things in one step (data and representation), and the v1 → v2 delta would no longer isolate the ghost fix. One caution for the later arm: MiniLM truncates at 256 word pieces [12], so features placed before the description push the description out. The arm needs its own field order and length budget.

**Skip-empty rule.** Content means the title, features and description, stripped. Template scaffolding does not count.
- **Product**: if all three are empty, write no embedding and record the product in the validation report. A pre-flight count of raw empty titles decides whether "zero untitled" can be a hard gate.
- **Review**: if title and text are both empty, skip it. Keep v1's 800-character cut (`backfill_embeddings.py:41-43`) for comparability.
- **Brand, Category, Attribute**: v1 templates, with deterministic sample-title order for categories.

**Review-embedding scope:**

| Option | Vectors | Product coverage | Disk (store + index) | OS file cache needed [6] | Local compute (estimate, measure on 10k) | RS-02 evidence |
|---|---|---|---|---|---|---|
| None | 0 | 0% | — | — | — | RS-02 decided by default without evidence; review channel gone |
| Top-5 most helpful per product | ≈ 1.1M (to measure) | ≈ 100% of reviewed products | ≈ 4 GB | ≈ 2 GB | ≈ 10–60 min | Fair test: coverage is uniform across products |
| All within the K-11 cap | 3,388,842 | ≈ 100% | ≈ 12 GB | ≈ 6.2 GB | ≈ 0.5–3 h | Fair test, full evidence |

**Recommendation**:
- **All 3.39M** if Docker Desktop can give the Neo4j VM at least about 20 GB.
- **Otherwise top-5** (the same ordering as the K-11 cap).
- *Orchestrator note (N-9)*: the Docker VM has 8 GB on a 16 GB Mac, so the 20 GB condition cannot be met on this machine. That points to top-5.

Either option removes the coverage confound that conditioned the RS-02 rule ("conditional on 4.7% coverage", 2026-10-18-015 point 4). "None" pre-empts an open decision. Writing 3.39M vectors over Bolt creates about 5 GB of transaction logs, so set a retention policy for the build.

### Q5: Data contract and validation

**Lineage file.** Write `graph_versions/v2/lineage.json` (git-tracked; small) with:
- source paths and SHA-256 from `datasets/raw/SHA256SUMS`;
- SHA-256 of `Electronics.{train,valid,test}.csv`;
- the frozen catalogue ID list (`graph_versions/v2/catalogue_asins.txt.gz`, about 1.5 MB, exported from v1 before the dump) and its hash;
- the git commit, parameters (cap 20, tie-break, exclusion rule, templates, model), columns read and dropped per file, and output CSV hashes;
- per-step row counts with drop reasons: JSON error, not in catalogue, valid/test pair, beyond cap, empty text.

This follows the Breck et al. and Datasheets practice [15][18].

**Hard gates.** The build fails, and `GraphVersion` is not written, if any of these fails:
- the count of `ParentProduct` equals the catalogue size (265,307), and none was created outside the metadata file;
- untitled products = 0, or equal to the pre-flight raw count that the user accepted;
- every `Review` has exactly one `ABOUT_PRODUCT` and one `WROTE` (also enforced by the import);
- no review's (user_id, parent_asin) is in valid ∪ test, and no product has more than 20 reviews;
- the review count equals the lineage count (expected 3,388,842);
- uniqueness constraints exist on `parent_asin`, `review_id`, `user_id`, `Brand.name`, `Category.name`, `Taxon.taxon_id`;
- no embedding equals the blank-template embedding, and no embedded product has empty content;
- all vector and full-text indexes are `ONLINE` at 100% population, with node counts equal to the embedded counts.

**Report-only checks**, written to `graph_versions/v2/validation_report.json`:
- per-field coverage per `main_category` and per top-level `Taxon`: title, price, brand, features, description, number of `details` keys, at least 1 and at least 5 reviews;
- the taxon depth distribution and products without a taxon;
- groups of identical embeddings with different texts;
- brand names that differ only in case;
- the 90 ISBN-like products, flagged and kept per K-3.

**`GraphVersion` node.** One node: `{version: 'v2', built_at, lineage_sha256, source_meta_sha256, source_reviews_sha256, splits_sha256, catalogue_sha256, code_commit, embedding_model, template_ids, review_embedding_scope, neo4j_version, validation_passed}`.

**`src/evaluation/provenance.py`.**
- `collect_runtime_provenance` reads the node into `graph_snapshot.graph_version`.
- It adds `products_untitled` and `reviews_embedded` to the counts. Today's `products`, `categories` and `reviews` counts cannot detect property-level changes.
- `evaluate_citable` adds the reason `graph_version_unknown` when the node is missing. Archived v1 runs keep their own citability; any run against a graph without a stamp cannot be cited.

### Q6: Neo4j sizing

These are estimates. Confirm them with a 5% pilot import, as the Neo4j docs advise for new deployments [5].

| Component | Basis | Estimate |
|---|---|---|
| Reviews, users, relationships, text (3.39M reviews) | Scaled from v1 (4.9 GB store for 1.63M reviews, plus product data) | 4–7 GB |
| Product properties (title, description, features, details) | 265k × 2–4 KB | 0.5–1 GB |
| Product embeddings (store + vector index) | 265k × 1.7 KB + 265k × 1.83 KB [6] | ≈ 0.95 GB |
| Brand, Category, Attribute embeddings | ≈ 120k vectors | ≈ 0.4 GB |
| Review embeddings: none / top-5 / all | 1.7 KB store + 1.83 KB index per vector | 0 / ≈ 4 GB / ≈ 12 GB |
| **Total on disk** | | **≈ 6–9 / 10–13 / 17–21 GB** |

The memory budget has to fit inside the Docker Desktop VM limit. Set initial heap equal to max heap [5].

| Docker VM memory | Heap | Page cache | Left for OS cache (vector indexes) | Review scope that fits |
|---|---|---|---|---|
| 8 GB (this machine, N-9) | 2G | 2G | ≈ 3 GB | Top-5 (slower) |
| 12–16 GB | 3–4G | 3–4G | ≥ 5 GB | Top-5 comfortably; all works but review search will read from SSD |
| ≥ 20–24 GB | 4G | 6–8G | ≥ 8 GB | All |

During the build:
- Use a 4G heap for index population and large write batches.
- Raise `dbms.transaction.timeout` above 60 s, or keep batches under it (N-8).
- Run the import with `HEAP_SIZE=2G` and the default `--max-off-heap-memory` [1].

### Q7: Consequences and order of work

**What must be re-run or recomputed on v2:**
- **Retrieval baseline.** Re-run all R1 arms (`rrf3`, `rrf2`, `wrrf3`, `cc3`, `sum_legacy`) on legacy-21 at the same commit as the archived R2a v1 run, with r = 3. The only difference is then the graph. 104k ghosts become real competitors, often in the same categories, so the direction of the HR/MRR change cannot be predicted.
- **`live_eval_dataset.json`.** All 21 targets are titled v1 products, so they exist on v2 with the same price, brand and category. Their review sets change. Run `validate_benchmark_graph_grounding()` as a gate.
- **RS-02.** Collect the evidence on the v2 tuning split. The 4.7% condition in 2026-10-18-015 no longer applies.
- **R2b.** Generate and freeze the benchmark on v2 only, after the tree exists (K-7). S1 needs redefinition (N-5): see Decisions needed.

**Figures that change** (correction note, §8):
- "47% have reviews" (roadmap; actually 12% of titled products in v1);
- review-embedding coverage of 4.7% / 2.2% and the 5,715 reference set (`thesis/10-doc-fusion-ablation.md:55`, roadmap R1-7);
- "53% cold" (2026-10-18-014 context);
- "71 live categories";
- the counts in 2026-10-05-001 (12,909 complete products, 72,538 users);
- all R1 hit-rate, MRR and NDCG numbers, which remain valid only as v1 evidence.

**Unblocked by v2:**
- AI-03 (KECR timestamps; review rating and `verified` are already on the node);
- AI-06 (order reviews by `helpful_vote`);
- RS-12 and RS-03 (BM25 over `features`).

**Order of work:**
1. **Pre-flight** (read-only): in-scope raw coverage (empty title, empty categories, null or unparseable price, `details` keys); the Docker VM memory limit; the top-5 count; embedding throughput on 10k texts.
2. **R2a citable runs on v1 archived.** This is the K-2 gate and is not met yet: `evaluations_archive/` holds only the three legacy R1 runs.
3. **Export the catalogue ID list** (265,307) and its hash from v1, and commit it.
4. **Stop the container and dump**: `neo4j-admin database dump neo4j --to-path=…` [4]. Record the SHA-256. Keep the v1 volume.
5. **Pipeline fix**: transform script with unit tests (selection, exclusion, cap and tie-break, skip-empty, tree builder); `batch_ingest.py` MERGE → MATCH; skip-empty guard in `backfill_embeddings.py`.
6. **5% pilot import** into a scratch volume. Measure size and time, then run the checks.
7. **Full import** into the new v2 volume.
8. **Post-import**: constraints, embeddings, vector indexes (procedure form), full-text index.
9. **Validation gate**, then the `GraphVersion` node, then the `provenance.py` update.
10. **v2 baseline re-run** (r = 3) and archive.
11. **R2b benchmark** on v2, then freeze.

### Q8: Decision Log drafts

These are drafts to append after approval. Numbering and date are set when written; the standard Decision Log heading prefix is added at write time.

---
**[2026-10-18-018]: Graph v2: Rebuild of the Knowledge Graph from the Raw Amazon Reviews 2023 Electronics Files**

**Context**: 104,281 of the 265,307 v1 products are ghosts: no title, price or category, and an embedding of the blank template, identical across ghosts. Three causes:
- metadata and reviews were sampled independently (`AmazonDataProcessor.process_and_save_data`);
- `batch_ingest.py` created products from reviews (`MERGE`);
- `backfill_embeddings.py` embedded empty texts.

Research report: `production_artifacts/Research_Report_Graph_Rebuild.md`.

**Decision**:
1. **Source**: `datasets/raw/meta_Electronics.jsonl` and `Electronics.jsonl` (SHA-256 in `datasets/raw/SHA256SUMS`) and the official splits `datasets/Electronics.{train,valid,test}.csv`. No download.
2. **Catalogue**: the 265,307 v1 `parent_asin`s, frozen as a hashed ID list, filled from raw metadata. Products are created only from metadata, never from a review. Zero ghosts.
3. **Reviews**:
   - (user, parent_asin) pairs in valid or test are excluded; train-split and no-split reviews are kept;
   - then at most 20 per product, ordered by `helpful_vote` descending with a fixed tie-break;
   - `timestamp` and `helpful_vote` are stored.
4. **Schema**:
   - v1 labels and relationships keep their v1 semantics (`Category` = `main_category`; `HAS_BRAND` from `coalesce(store, details.Brand)`; `HAS_ATTRIBUTE` for Material, Color, Style and Size; no `numeric_value`).
   - The category tree is built from the raw category lists as `Taxon` / `BROADER` / `IN_TAXON`.
   - Listing text is stored as `p.features` and `p.details_json`.
   - A full-text index covers title, description and features.
5. **Load**: transform to CSV with a lineage file, then `neo4j-admin database import full` into a new volume (Neo4j 5.14 Community), then online embeddings with the v1 templates (deterministic order, empty texts skipped), vector indexes, the full-text index and a `GraphVersion` node.
6. **Validation gate** (zero ghosts, referential integrity, split exclusion, cap, no blank embeddings, indexes online). Evaluation manifests record `GraphVersion`; a run without it is not citable.
7. **Neo4j stays 5.14** for this release (D-4 is separate).

**Rationale**: The KG can only ground what it contains. A rebuild that is a pure function of hashed inputs is reproducible, and the importer enforces referential integrity structurally. Keeping v1 semantics isolates the data fix from representation changes (K-6 is deferred to an R3 arm). Data-validation practice: Breck et al., SysML 2019; Schelter et al., 2018.

**Impact on vision**: Strengthens §4 (KG as grounding, Amazon-only) and §5 (reproducible evaluation). All retrieval figures are re-baselined on v2. No model training.

**Approved by**: User (date, `/implement` Gate #1)

---
**[2026-10-18-019]: Amendment: Graph Writes Are a Versioned Rebuild, Not Additive In-Place Writes (K-2)**

**Context**: K-2 (brainstorm, 2026-10-18) approved additive, in-place writes under new names after an offline dump, so that R1/R2a stay reproducible on the same graph. K-3 then chose to fill ghosts by re-ingesting.

**Decision**:
- The graph is rebuilt as version v2 (2026-10-18-018); no additive in-place writes.
- v1 stays reproducible through the offline dump (hash recorded) and the retained v1 Docker volume.
- The K-2 order is kept: the rebuild starts only after R2a's citable runs on v1 are archived.
- New names are kept for new structures (`Taxon`, `p.features`, the full-text index), so v1-era code reads v2 with v1 semantics.

**Rationale**: Filling 104k products changes existing nodes, so additive writes cannot deliver K-3.

**Impact on vision**: None. It clarifies how graph versions are managed.

**Approved by**: User (date)

---
**[2026-10-18-020]: Amendment of Implementation Plan C1: Official Amazon 2023 Splits; KG Holds Train and No-Split Reviews**

**Context**: C1 planned an 80/20 or leave-one-out split of the curated subset, with the KG populated from train only. The official 5-core, leave-last-out splits exist locally (train 12,191,484; valid and test 1,641,026 each). About 22.0M in-scope reviews belong to users outside the 5-core splits.

**Decision**:
- C1 uses the official Amazon 2023 splits.
- Valid and test (user, parent_asin) pairs never enter the KG.
- Train-split and no-split reviews are both kept (K-12), and both are available to the Meta-Phase C baselines, so the KG and the baselines see the same training data.
- Products stay in the catalogue even when all their reviews are held out.

**Rationale**: No-split reviews have no leakage path to the official test items. Standard splits make the baseline comparison citable (Hou et al., 2024).

**Impact on vision**: Implements §4 "exact same dataset splits".

**Approved by**: User (date)

---
**[2026-10-18-021]: Correction Note: Claims Invalidated by the Ghost-Product Finding (Graph v1)**

**Context**: The ghost finding (2026-10-18) and the graph v2 research report checked earlier claims against the v1 graph and pipeline. This follows the 2026-10-18-017 precedent.

**Decision**: The following are recorded as v1 artefacts or as not holding:
1. **Coverage figures**: "47% of products have reviews" (12% of titled products in v1); review-embedding coverage of 4.7% / 2.2% (85% of the 5,715 review-embedded products are ghosts); "53% cold products" (2026-10-18-014 context); the 2026-10-05-001 counts (12,909 complete products, 72,538 users with ≥ 3 reviews); "71 live categories". All are recomputed on v2.
2. **R1 results** (2026-10-17-013, `eval_2026-10-17_1846` and `_1937`) were measured on a candidate pool containing 104,281 identical-embedding ghosts. They are valid as v1 evidence only and are re-baselined on v2.
3. **2026-10-07-009 point 3** (hierarchical traversal) ran over 33 legacy `SUBCATEGORY_OF` edges and was effectively inactive. It is superseded by the v2 `Taxon` tree.
4. **2026-09-28-006 point 4 (EAV numeric schema) and 2026-10-09-012 point 2 (numeric parsing)**: `numeric_value` exists on no `Attribute` node, attributes hold only Material, Color, Style and Size, and numeric attribute filters never ran on live data.
5. **Vision §4**: "rich structural … nodes" did not hold for v1. 39% of products had no metadata, `features` text was not loaded, and reviews are whole-review nodes, not chunks.
6. **v1 preprocessing** read `helpful_votes` and `sort_timestamp`, but the raw fields are `helpful_vote` and `timestamp`, so both are 0 in all 1,630,273 v1 reviews. The v1 "20 most helpful" cap was not helpfulness-based, and the AI-03 plan to backfill timestamps from `processed_reviews.csv` cannot work.

**Rationale**: The Decision Log must describe the system that produced the thesis results.

**Impact on vision**: None on the vision. It removes unsupported claims.

**Approved by**: User (date)

---

### Codebase impact assessment

- **New**:
  - transform script (e.g. `scripts/graph_ingestion/build_graph_v2.py`) and an import wrapper;
  - post-import setup script (constraints, vector indexes through `setup_indexes.py`'s procedure path, full-text index, `GraphVersion`);
  - validation script (e.g. `scripts/graph_ingestion/validate_graph.py`);
  - `graph_versions/v2/` (lineage, catalogue list, validation report);
  - tests for selection, exclusion, cap and tie-break, the tree builder, skip-empty and the checks.
- **Changed**:
  - `scripts/graph_ingestion/batch_ingest.py` (MERGE → MATCH in the review step);
  - `src/knowledge_graph/graphdb/backfill_embeddings.py` (skip-empty, deterministic attribute order, template ID);
  - `src/knowledge_graph/graphdb/backfill_category_embeddings.py` (ordered sample titles);
  - `src/evaluation/provenance.py` (`GraphVersion`, untitled and embedded counts, `graph_version_unknown`);
  - `src/knowledge_graph/docker-compose.yml` (volume name from env, memory settings).
- **Unchanged**: `graph_search_tool.py`, `kecr_tool.py`, `resolver_service.py`, the orchestrator and the Critic. V1 semantics are kept.
- **Scope**: M–L. About 2–4 days of engineering plus about 0.5 day of pipeline wall-clock time.

## Guardian Assessment

| Guardian question | Answer |
|---|---|
| Aligns with the phase structure? | Yes. This is Foundation-level work, a corrected F3, and must precede the R2b freeze (K-7). Meta-Phases A, B and C are unchanged. |
| Integrates with the existing Neo4j KG? | Yes. Same database, same edition and version (5.14 Community), same labels and index names for every current reader. |
| Unnecessary complexity? | No, with two deliberate omissions: no runtime taxonomy flag and no `Taxon` embeddings until RS-24 has a reader, and no Great Expectations or new framework (plain checks). `details_text` is optional. |
| Incremental? | Yes. Pilot at 5% first. The K-6 arm, RS-11 `HAS_SPEC` and RS-24 are added later without a rebuild. |
| Conflicts with existing components? | `create_vector_indexes.cypher` and `create_indexes.py` use DDL that fails on 5.14 (N-4). `.claude/rules/python-conventions.md` requires Cypher 25 `VECTOR SEARCH`, which 5.14 cannot run (D-4, unchanged). |
| Cost vs value? | High value. It removes a confound under every retrieval figure and unblocks AI-03, AI-06, RS-12 and RS-03. Moderate cost. |

**Vision alignment.**
- *Amazon-only rule*: satisfied. Same dataset, same version, official splits.
- *No-training rule*: satisfied. Pre-trained MiniLM only; no LLM is needed in the rebuild (N-6). The user's relaxed stance on small trained models is not touched.
- *KG as grounding*: strengthened. Every product has a title and listing text in the KG.
- *Zero-mock (2026-10-05-001)*: kept; v2 is live data.

**Deviations and frictions:**
- Implementation Plan F2/F3 (curated 25-product story) is stale; propose an "F4: Graph v2" item, subject to user approval.
- Stratum S1 in 2026-10-18-014 needs an amendment (N-5).
- The 5.14 vector-index DDL gap (N-4).

**Risks.**
- **Memory**: the Docker VM limit may force the top-5 review scope.
- **Pre-flight surprises**: raw empty titles or empty category lists among the 265k may make "zero untitled" a measured count rather than zero.
- **Shifting results**: all retrieval figures move, so thesis chapters 3, 7 and 10 need re-runs.
- **Import pitfalls**: multiline text and array delimiters in CSV. Mitigated by the pilot and `--bad-tolerance=0`.

## Recommendation

**Recommended approach**: transform → `neo4j-admin database import full` into a new volume → online embeddings, indexes and validation → `GraphVersion` → v2 baseline → R2b. Keep the v1 schema and templates, and add the tree and listing text under new names.

**Why**: Of the three load methods, only this one makes ghosts structurally impossible and makes the graph a hashable function of its inputs. It also keeps the v1 → v2 delta attributable to the data fix.

**What not to do:**
- No Cypher `MERGE`-based full re-ingest (the bug class that caused the ghosts).
- No `apoc.load.json` over 22.6 GB inside the container.
- No full `details` dict as `Attribute` nodes (hubs, broken comparability).
- No features-based product template in v2 (K-6 stays an R3 arm).
- No Neo4j upgrade in the same release.
- No GPT pass for the tree.
- No query-time ghost filter as the fix (K-3 settled).

## Decisions needed

| ID | Open choice | Recommendation |
|---|---|---|
| G-1 | Load method | `neo4j-admin database import full` plus online post-steps (Q1) |
| G-2 | Where v2 lives | New Docker volume next to the retained v1 volume, plus the K-2 dump |
| G-3 | Attribute scope | v1's 4 keys as `HAS_ATTRIBUTE`. Full `details` as `p.details_json`, bullets as `p.features`. `numeric_value` not written. |
| G-4 | Product embedding template (K-6) | v1 template now (deterministic order, skip-empty). K-6 deferred to an R3 arm, added later as `p.embedding_feat` with no rebuild. |
| G-5 | Review-embedding scope | All 3,388,842 if the Docker VM can have at least about 20 GB; otherwise top-5 per product (≈ 1.1M). Not "none". On this machine (8 GB VM, 16 GB Mac; N-9): top-5. |
| G-6 | Tie-break inside "20 most helpful" (most reviews have 0 votes, so the tie-break picks most of the sample) | `helpful_vote` DESC, `verified_purchase` DESC, `timestamp` DESC, `review_id` ASC |
| G-7 | Heap and page cache | Build: heap 4G (initial = max), transaction timeout raised. Runtime: per the memory-tier table in Q6. Needs the machine's RAM and Docker VM limit (N-9). |
| G-8 | Citability rule | A run without a `GraphVersion` node is not citable |
| G-9 | S1 "cold" stratum (2026-10-18-014) on v2, for the R2b spec | Redefine S1 as review-sparse (1–2 reviews in graph). Simulate true cold start by masking reviews at query time. Record as an amendment of 014. |
| G-10 | Neo4j version for v2 | Stay on 5.14. Handle D-4 (upgrade) separately, after the v2 baseline. |

## Sources

1. Neo4j Operations Manual 5, "neo4j-admin database import": https://neo4j.com/docs/operations-manual/5/tools/neo4j-admin/neo4j-admin-import/
2. Neo4j Operations Manual, "Full import": https://neo4j.com/docs/operations-manual/current/import/full-import/
3. Neo4j Operations Manual 5, "Docker operations": https://neo4j.com/docs/operations-manual/5/docker/operations/
4. Neo4j Operations Manual 5, "Back up an offline database" (dump): https://neo4j.com/docs/operations-manual/5/backup-restore/offline-backup/
5. Neo4j Operations Manual 5, "Memory configuration": https://neo4j.com/docs/operations-manual/5/performance/memory-configuration/
6. Neo4j Operations Manual, "Vector index memory configuration": https://neo4j.com/docs/operations-manual/current/performance/vector-index-memory-configuration/
7. Neo4j Cypher Manual 5, "Full-text indexes": https://neo4j.com/docs/cypher-manual/5/indexes/semantic-indexes/full-text-indexes/
8. Neo4j Cypher Manual 5, "Additions, deprecations, removals, and compatibility" (`CREATE VECTOR INDEX` in 5.15): https://neo4j.com/docs/cypher-manual/5/deprecations-additions-removals-compatibility/
9. Hou, Li, He, Yan, Chen, McAuley (2024), "Bridging Language and Items for Retrieval and Recommendation", arXiv:2403.03952: https://arxiv.org/abs/2403.03952
10. Amazon Reviews 2023, dataset documentation: https://amazon-reviews-2023.github.io/
11. Amazon Reviews 2023, "5-core and splits": https://amazon-reviews-2023.github.io/data_processing/5core.html
12. sentence-transformers/all-MiniLM-L6-v2 model card: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
13. SBERT, "Pretrained Models": https://sbert.net/docs/pretrained_models.html
14. W3C, "SKOS Simple Knowledge Organization System Reference": https://www.w3.org/TR/skos-reference/
15. Breck, Polyzotis, Roy, Whang, Zinkevich (2019), "Data Validation for Machine Learning", SysML: https://research.google/pubs/data-validation-for-machine-learning/
16. Schelter et al. (2018), "Deequ: Data Quality Validation for Machine Learning Pipelines": https://cdn.amazon.science/9f/b6/15099d504c54bec20ec6a6c2eb3d/deequ-data-quality-validation-for-machine-learning-pipelines.pdf
17. Great Expectations documentation: https://docs.greatexpectations.io/
18. Gebru et al. (2018/2021), "Datasheets for Datasets", arXiv:1803.09010: https://arxiv.org/abs/1803.09010

**Code and data referenced**:
- Ingest and preprocessing: `scripts/graph_ingestion/batch_ingest.py`, `src/utils/AmazonDataProcessor.py`
- Embedding and index scripts: `src/knowledge_graph/graphdb/backfill_embeddings.py`, `src/knowledge_graph/graphdb/backfill_category_embeddings.py`, `src/knowledge_graph/graphdb/setup_indexes.py`, `src/knowledge_graph/graphdb/create_vector_indexes.cypher`
- Readers and provenance: `src/evaluation/provenance.py`, `src/tools/graph_search_tool.py`, `src/tools/kecr_tool.py`, `src/knowledge_graph/graphdb/resolver_service.py`
- Infrastructure and data: `src/knowledge_graph/docker-compose.yml`, `datasets/processed_data/processed_reviews.csv`, `evaluations_archive/`
