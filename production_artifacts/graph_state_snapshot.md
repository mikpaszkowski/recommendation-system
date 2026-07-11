# Knowledge Graph & Embedding State Report

**Date**: 2026-07-11
**Purpose**: Document the current state of the Neo4j Knowledge Graph and embedding pipeline before the curated subset rebuild.

---

## 1. How the Graph Was Built

### Source Data
The existing graph was built **entirely from Amazon Electronics data**. Two raw JSONL files were used by `sample_ingest.py`:
- `datasets/Electronics.jsonl` — raw Amazon reviews
- `datasets/meta_Electronics.jsonl` — raw Amazon product metadata

These have since been pre-processed into CSVs:
- `datasets/processed_data/processed_reviews.csv` — **1,630,273 rows**, columns: `user_id, asin, rating, helpful_votes, verified_purchase, title, text, parent_asin, sort_timestamp`
- `datasets/processed_data/combined_product_data.csv` — **9,271 rows**, columns: `asin, title, main_category, average_rating, price, review_count, combined_text`
- `datasets/processed_data/processed_metadata.csv` — **161,031 rows**, columns: `asin, title, main_category, average_rating, rating_number, price, store, parent_asin, description_text, features_text, categories_text, metadata_text, detail_brand, detail_material, detail_color, detail_style, detail_size`

### Ingestion Script
**Script**: `src/knowledge_graph/graphdb/graph-builder/sample_ingest.py` (43KB, 1,000+ lines)
- Loads constraints from `constraints.cypher`
- Applies temporal filtering (recent window from raw JSONL timestamps)
- Derives node types: `:ParentProduct`, `:Variant`, `:Brand`, `:Category`, `:Attribute`, `:Review`, `:User`, `:PriceRange`, `:CoPurchaseSet`
- Builds relationships: `[:HAS_BRAND]`, `[:BELONGS_TO_CATEGORY]`, `[:HAS_ATTRIBUTE]`, `[:WROTE]`, `[:ABOUT_PRODUCT]`, `[:IN_PRICE_RANGE]`
- Uses batch upserts via Cypher `MERGE`

**Schema** (`constraints.cypher`): Uniqueness constraints on `user_id`, `asin`, `parent_asin`, `brand_id`, `review_id`, `attribute_id`, `category_id`, `range_id`. Also includes `:Aspect` node type (from `aspect_pipeline.py`).

> ✅ **REDIAL-compatible**: The schema already includes `CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE` — `:User` nodes exist in the schema and are ready for REDIAL extension.

### Embedding Pipeline
**Script**: `src/knowledge_graph/graphdb/backfill_embeddings.py`
**Model**: `sentence-transformers/all-MiniLM-L6-v2` (via `EmbeddingService`) → **384-dimensional vectors**
**Batch size**: 100 nodes per batch

**What was embedded (text template per node type)**:

| Node Label | Text Template Used |
|---|---|
| `Attribute` | `"{name}: {normalized_value}"` (generic keys like `bullet_point` → value only) |
| `Brand` | `"Brand: {name}. Domain: {domain_description or 'consumer electronics'}"` |
| `Category` | `"Category: {name}. Parent: {parent_name or 'Root'}"` |
| `ParentProduct` | `"Product: {title}. Category: {category}. Features: {top_5_features}. Description: {description}"` |

**Not embedded**: `:Review`, `:User`, `:Variant`, `:PriceRange`, `:CoPurchaseSet` nodes — no embedding property set.

---

## 2. Live Graph State (Must Be Verified)

> ⚠️ **The following node counts are UNKNOWN until the introspection queries below are run against the live Neo4j instance.** The graph was built from a filtered subset of the full Amazon dataset — exact counts depend on the temporal filter parameters used during ingestion.

**Run these queries against the current Neo4j database to complete this section:**

```cypher
-- Node counts
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;

-- Embedding coverage
MATCH (n:ParentProduct)
RETURN count(n) AS total_products,
       count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded_products,
       count(CASE WHEN n.embedding IS NULL THEN 1 END) AS missing_embeddings;

MATCH (n:Brand)
RETURN count(n) AS total_brands,
       count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded_brands;

MATCH (n:Category)
RETURN count(n) AS total_categories,
       count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded_categories;

MATCH (n:Attribute)
RETURN count(n) AS total_attributes,
       count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded_attributes;

-- Vector index status
SHOW INDEXES WHERE type = 'VECTOR';

-- Relationship counts
MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY count(r) DESC;

-- Sample embedding dimensionality check
MATCH (p:ParentProduct) WHERE p.embedding IS NOT NULL
RETURN p.title, size(p.embedding) AS dims LIMIT 3;
```

**Record actual results here after running:**

| Label | Total Nodes | Embedded | Missing |
|---|---|---|---|
| ParentProduct | *(run query)* | *(run query)* | *(run query)* |
| Brand | *(run query)* | *(run query)* | *(run query)* |
| Category | *(run query)* | *(run query)* | *(run query)* |
| Attribute | *(run query)* | *(run query)* | *(run query)* |

---

## 3. Known Issues with Existing Graph

| Issue | Details | Fix |
|---|---|---|
| Wrong dataset foundation | Built from Amazon-only data; no REDIAL items | Rebuild with curated subset (F3) |
| Deprecated vector index API | `db.index.vector.queryNodes()` deprecated in Neo4j 2026.04 | GAP-003: migrate to Cypher 25 `VECTOR SEARCH` |
| Deprecated index creation | `db.index.vector.createNodeIndex()` used in setup scripts | GAP-003: migrate to `CREATE VECTOR INDEX` DDL |
| Embedding model adequacy | `all-MiniLM-L6-v2` is adequate for structural nodes but not SOTA for semantic chunks | Watch for upgrade to `BGE-M3` in Meta-Phase A |
| No `:Chunk` nodes | GraphRAG layer not built — no lexical chunking of product descriptions | F3 / Meta-Phase A |

---

## 4. Dataset Analysis Results (2026-07-11)

**Full Amazon Electronics dataset statistics:**

| Metric | Count |
|---|---|
| Total reviews | 1,630,273 |
| Unique users | 471,471 |
| Unique products (in reviews) | 123,720 |
| Products in catalog (combined_product_data.csv) | 9,271 |
| Products with 0 reviews in catalog | 0 |
| Products with 1–2 reviews | 97 |

**User activity distribution:**

| Review count | Number of users |
|---|---|
| Exactly 1 review | 169,062 (35.8%) |
| 2–5 reviews | 234,445 (49.7%) |
| 6–10 reviews | 44,212 (9.4%) |
| 11–50 reviews | 22,974 (4.9%) |
| 51+ reviews | 778 (0.16%) |

**Top reviewer**: `AHMNA5UK3V66O2V3DZSBJA4FYMOA` — 532 reviews across 528 distinct products.

**Most reviewed product**: `B094V7S7D7` — 519 reviews from 475 unique users.

---

## 5. Curated Subset Plan

See `production_artifacts/Implementation_Plan.md` sections F2.1–F2.4 for the full selected user and product lists.

**Summary:**
- 20 active users (147–532 reviews each)
- 5 cold-start users (1 review each)
- 20 well-reviewed products (292–519 reviews each)
- 5 low-review products (1–2 reviews each)
- Target graph size: ~25 `:User`, ~25 `:ParentProduct`, ~N `:Review`, M `:Brand`, K `:Category`, L `:Attribute` nodes
- Target database: `kg_curated` (separate from existing database)
