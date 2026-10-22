# Knowledge Graph State Report

**Date**: 2026-10-20
**Live graph**: **v2**, built, validated (18/18 hard gates) and stamped on 2026-10-20 (`(:GraphVersion {version: 'v2', validation_passed: true})`, stamped 2026-10-20T08:20:05Z).
**Neo4j**: 5.14.0 Community, Docker container `neo4j-recommendation`, data volume `kg_neo4j_data_v2`.

This file replaces the July 2026 curated-subset report (stale since 2026-10-10, AI-13). The machine-readable records are authoritative; this file is a readable summary of them:

| Record | Path |
|---|---|
| Build lineage (sources, parameters, counts, output hashes) | `graph_versions/v2/lineage.json` |
| Validation (18 hard gates, report-only R-01 … R-08) | `graph_versions/v2/validation_report.json` |
| Embedding run | `graph_versions/v2/embedding_report.json` |
| Checkpoint approvals CP-1 … CP-9 | `graph_versions/v2/RUNBOOK_LOG.md` |
| v1 freeze (counts, dump record) | `graph_versions/v1/snapshot.json`, `graph_versions/v1/DUMP.json` |
| v1 vs v2 retrieval baseline | `graph_versions/v2/baseline_comparison.json` |
| Design and schema | `production_artifacts/Technical_Specification_Graph_Rebuild.md` §5.1, Vision 2026-10-19-018 … 021 |

---

## 1. Graph v2

### 1.1 How it was built

- **Source**: raw Amazon Reviews 2023 Electronics files (`datasets/raw/meta_Electronics.jsonl`, 1,610,012 lines; `datasets/raw/Electronics.jsonl`, 43,886,944 lines), SHA-256 verified against `datasets/raw/SHA256SUMS`.
- **Catalogue**: the 265,307 `parent_asin`s of v1, frozen read-only on 2026-10-19 (`graph_versions/v2/catalogue_asins.txt.gz`, content SHA-256 `76d882ab…f528`). Every one of them is found in the raw metadata, so v2 has no ghost products.
- **Transform**: `scripts/graph_ingestion/build_graph_v2.py --require-clean` at clean commit `75c5c0a` (10.5 min, peak RSS 4.2 GB, 2.9 GB of CSV).
- **Review rules**: at most 20 reviews per product (`review_cap`, rank key `helpful_vote DESC, verified_purchase DESC, timestamp DESC, review_id ASC`); reviews whose `(user_id, parent_asin)` pair is in the validation or test split (`Electronics.valid.csv` ∪ `Electronics.test.csv`) are excluded; duplicate review IDs collapsed (60,521). The top 5 non-blank reviews per product by `cap_rank` get an embedding.
- **Import**: `import_graph_v2.py import` with `neo4j-admin` offline import, 94 s, empty import report (0 bad rows), store 4.0 GB before post-import.
- **Post-import**: `post_import_v2.py all` (~2.6 h, run detached): constraints, embeddings on MPS at encode batch 32 with no out-of-memory event, 5 vector indexes, full-text index. Embedding model `sentence-transformers/all-MiniLM-L6-v2` (384-dim, cosine).
- **Code commits**: build `75c5c0a`, stamp `0a32604` (post-import fixes `8b10a35`, `0a32604`).

### 1.2 Node counts

| Label | Count | Embedded | Notes |
|---|---|---|---|
| `ParentProduct` | 265,307 | 265,303 | 4 skipped by the `title_description` content rule; 8 untitled products |
| `Review` | 3,382,248 | 1,081,137 | embedding only where `embed_rank` is set (top 5 non-blank per product) |
| `User` | 2,594,661 | n/a | |
| `Brand` | 49,663 | 49,663 | 925 case-variant groups (for example `ASUS` / `Asus`) are kept as separate nodes |
| `Attribute` | 36,187 | 36,187 | keys `Material`, `Color`, `Style`, `Size` |
| `Taxon` | 1,183 | not embedded | 3 roots, max depth 7 |
| `Category` | 38 | 38 | Amazon `main_category` values |
| `GraphVersion` | 1 | n/a | stamp node, see §1.6 |

All embeddings have 384 dimensions (gate H-10: embedded = report = eligible per label, 0 wrong dimensions).

### 1.3 Relationship counts

| Type | Count |
|---|---|
| `ABOUT_PRODUCT` (`Review` → `ParentProduct`) | 3,382,248 |
| `WROTE` (`User` → `Review`) | 3,382,248 |
| `HAS_BRAND` | 264,274 |
| `BELONGS_TO_CATEGORY` | 261,664 |
| `IN_TAXON` (`ParentProduct` → deepest `Taxon`) | 248,053 |
| `HAS_ATTRIBUTE` | 190,043 |
| `BROADER` (`Taxon` → parent `Taxon`) | 1,180 |

No `Variant`, `Product`, `PriceRange`, `Aspect`, `CoPurchaseSet` nodes and no `RATED`, `REVIEWS`, `SUBCATEGORY_OF`, `IN_PRICE_RANGE`, `IS_VARIANT_OF` relationships (gate H-16: no legacy schema).

### 1.4 Indexes and constraints

Neo4j 5.14 has no `CREATE VECTOR INDEX` DDL (needs 5.15) and no Cypher 25 `VECTOR SEARCH`. The vector indexes are therefore created with the procedure `db.index.vector.createNodeIndex`, and queries use `db.index.vector.queryNodes` (pending decision D-4).

| Index | Kind | Target |
|---|---|---|
| `product_embedding_index` | vector, 384, cosine | `ParentProduct.embedding` |
| `review_embedding_index` | vector, 384, cosine | `Review.embedding` |
| `brand_embedding_index` | vector, 384, cosine | `Brand.embedding` |
| `attribute_embedding_index` | vector, 384, cosine | `Attribute.embedding` |
| `category_embedding_index` | vector, 384, cosine | `Category.embedding` |
| `product_fulltext_index` | full-text (`english`) | `ParentProduct` `[title, description, features, details_text]` |

Uniqueness constraints (all ONLINE, H-12): `product_id` (`parent_asin`), `review_id`, `user_id`, `brand_id` (`Brand.name`), `category_id` (`Category.name`), `taxon_id`, `attribute_key` (`attribute_name`, `attribute_value`), `graph_version_id`. All 16 indexes reported by gate H-12 (the 8 constraint-backing indexes, 6 named vector / full-text indexes above counted as 6, and 2 auto-named indexes) are ONLINE at 100%.

The full-text index was first built with a `features_text` fallback; the fallback was dropped, `features_text` removed from 215,032 products, and the index rebuilt over the four fields (RUNBOOK_LOG, R-9). A phrase smoke test finds a features-only phrase at rank 1 (gate H-13).

### 1.5 Coverage figures (report-only, `validation_report.json`)

| Measure | v2 |
|---|---|
| Untitled products | 8 (0.003%; v1: 104,281 = 39.3%) |
| Products with at least one review | 265,294 of 265,307 |
| Products with at least one embedded review | 99.995% (v1: 2.15%) |
| Reviews embedded | 1,081,137 of 3,382,248 (32.0%) |
| Products without a price | 151,262 (57.0%) |
| Products without a category path | 17,254 |
| Products with `IN_TAXON` | 248,053 (93.5%); the rest have no category path |
| Products without brand | 1,033 |
| Taxonomy depth distribution (R-03) | depth 1: 3, 2: 192, 3: 203, 4: 344, 5: 337, 6: 98, 7: 6 |
| Products assigned to an inner (non-leaf) taxon | 22,684 |

Per-`main_category` completeness (title, price, brand, features, description, details, reviews) is in `validation_report.json` section `report_only.R-01`; per-taxon-level completeness in `R-02`. The largest `main_category` groups are Computers (73,206 products), All Electronics (70,430), Camera & Photo (33,743), Cell Phones & Accessories (25,796) and Home Audio & Theater (19,478).

### 1.6 `GraphVersion` node

Properties (spec §5.6): `version` (`v2`), `built_at`, hashes of lineage / validation report / embedding report / build parameters / sources / splits / catalogue, `code_commit` (`75c5c0a`), `stamp_commit` (`0a32604`), `embedding_model`, `template_ids`, `review_embedding_scope` (`top5_nonblank_by_cap_rank`), `review_cap` (20), `fulltext_fields`, `neo4j_version` (5.14.0), `product_count`, `review_count`, `user_count`, `taxon_count`, `validation_passed` (true). Evaluation manifests read it as the `graph_version` field (`src/evaluation/provenance.py`); the three v2 baseline runs are `graph_version` v2 and citable.

### 1.7 Runtime profile

Compose runs without build overrides: heap 2 GiB, page cache 2 GiB, transaction timeout 1 min (`.env`: `NEO4J_DATA_VOLUME=kg_neo4j_data_v2`). Rollback to v1: see `scripts/graph_ingestion/README.md`, "Rollback".

### 1.8 Known limits of v2

| Limit | Detail |
|---|---|
| Review sample, not full history | at most 20 reviews per product; reviews of the validation and test splits are excluded by design |
| Review embeddings cover a third of reviews | 32.0% of kept reviews; the top 5 per product |
| Sparse price | 57.0% of products have no price (price filters cannot use them; unknown is never scored as a mismatch, P-2) |
| Brand case duplicates | 925 groups of brand names differing only in case are separate `Brand` nodes (resolution is case-insensitive in `GraphSearchTool`) |
| Review timestamps are populated | `Review.timestamp` (ms) and `helpful_vote` exist now, unlike v1; KECR historical paths (AI-03) still need a rewrite for the v2 schema |
| Vector API | procedure form on Neo4j 5.14; upgrade is D-4 |
| Embedding model | `all-MiniLM-L6-v2` (384-dim); `BGE-M3` for chunk nodes is only an upgrade path |

---

## 2. Graph v1 (retired 2026-10-20, dated record)

The v1 graph (full Electronics ingest by `batch_ingest.py`) was frozen on 2026-10-19 (`graph_versions/v1/snapshot.json`, Neo4j 5.14.0) and replaced by v2. It is kept for rollback and as the reference of the archived v1 evaluation runs (`evaluations_archive/eval_2026-10-18_2340`, `_2349`, `_2358`).

- **Container and volume**: container `neo4j-recommendation-v1` (stopped; the former `neo4j-recommendation`), volume `knowledge-graph_neo4j_data` (never written by the v2 build).
- **Dump**: `~/neo4j-backups/kg_v1_20261019_2234/neo4j.dump`, 2,717,863,893 bytes, SHA-256 `51db8128…c0026f` (`graph_versions/v1/DUMP.json`; restore test not run).
- **Why it was replaced**: 104,281 of its 265,307 products were ghosts without title, price or category (Vision 2026-10-19-021); review embeddings reached 2.15% of products; reviews had no timestamps; legacy structures (`Variant`, `PriceRange`, `Product`, `RATED`, `REVIEWS`) were curated-build leftovers.

v1 vs v2 counts (R-08, `validation_report.json`):

| Item | v1 | v2 |
|---|---|---|
| `ParentProduct` | 265,307 | 265,307 |
| `Review` | 1,629,426 | 3,382,248 |
| `User` | 471,474 | 2,594,661 |
| `Brand` | 40,998 | 49,663 |
| `Attribute` | 47,335 | 36,187 |
| `Category` | 71 | 38 |
| `Taxon` | none | 1,183 |
| `Variant` / `PriceRange` / `Product` | 31 / 3 / 25 | none |
| `ABOUT_PRODUCT` | 1,634,273 | 3,382,248 |
| `WROTE` | 1,624,586 | 3,382,248 |
| `HAS_BRAND` | 160,135 | 264,274 |
| `BELONGS_TO_CATEGORY` | 159,475 | 261,664 |
| `HAS_ATTRIBUTE` | 111,015 | 190,043 |
| `SUBCATEGORY_OF` / `IN_TAXON` / `BROADER` | 33 / none / none | none / 248,053 / 1,180 |
| Untitled share of products | 39.3% | 0.003% |
| Products with an embedded review | 2.15% | 99.995% |

v1 also had `IN_PRICE_RANGE` 38, `IS_VARIANT_OF` 6, `RATED` 16 and `REVIEWS` 4,847 (all absent in v2), 76,814 embedded reviews on 5,715 products, and v1 detail is in `production_artifacts/action_items/Live_Graph_Audit_2026-10-10.md`.

The earlier history (a 30-product curated graph in July 2026, the curated-subset plan of Implementation Plan F2/F3, and the Amazon dataset analysis of 2026-07-11) is in the git history of this file and in `production_artifacts/Implementation_Plan.md` F2/F3.
