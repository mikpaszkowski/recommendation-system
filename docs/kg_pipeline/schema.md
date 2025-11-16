# Knowledge Graph Schema (Electronics CRS Foundation)

This document captures the extensible Neo4j schema that underpins the conversational recommendation system. The design emphasises explicit entities and relationships extracted from the Amazon Reviews 2023 dataset while leaving dedicated attachment points for future commonsense knowledge, embeddings, and LLM alignment layers.

## Core Node Labels

| Label                        | Key Properties (type)                                                                                                                                                                                                                                                           | Description & Semantics                                                                                                                                                            | Primary Source                               |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| `User`                       | `user_id` (string, **unique**); `review_count` (int); `verified_purchase_count` (int); `helpful_votes_given` (int); `account_age_years` (float, optional)                                                                                                                       | Represents an Amazon reviewer. Stores lightweight behavioural aggregates to support cold-start mitigation and personalization.                                                     | `Electronics.jsonl` (reviews)                |
| `Product`                    | `asin` (string, **unique**); `parent_asin` (string, nullable); `title` (string); `brand` (string); `price` (float); `currency` (string); `image_url` (string, optional); `avg_rating` (float, derived); `review_count` (int, derived); `ingested_at` (datetime)                 | Catalog entry for an item. `parent_asin` captures variant grouping; `brand` retained for explicit filtering and to seed attribute connections.                                     | `meta_Electronics.jsonl`                     |
| `Review`                     | `review_id` (string, **unique**); `rating` (float); `review_title` (string); `review_body` (string); `verified_purchase` (boolean); `helpful_votes` (int); `timestamp` (datetime); `source_file` (string)                                                                       | Event node capturing a single user opinion. Acts as the anchor for textual context, implicit preference extraction, and modality alignment.                                        | `Electronics.jsonl`                          |
| `Attribute`                  | `attribute_id` (string, **unique**); `attribute_name` (string); `attribute_value` (string); `normalized_value` (string); `value_type` (enum: `exact`, `range`, `boolean`, `categorical`); `source` (enum: `metadata`, `details`, `feature_bullet`, `nlp`); `confidence` (float) | Normalised facet (e.g., `Brand:Apple`, `Screen Size:6.1 Inches`). Aggregates heterogeneous attribute sources into a reusable dimension suitable for explicit and implicit signals. | Derived in transform step                    |
| `Category`                   | `category_id` (string, **unique**); `name` (string); `level` (int); `path` (list\<string\>)                                                                                                                                                                                     | Nodes for each unique category segment. `level` enables hierarchical ordering; `path` preserves the full Amazon taxonomy chain.                                                    | `meta_Electronics.jsonl`                     |
| `PriceRange`                 | `range_id` (string, **unique**); `label` (string); `lower_bound` (float); `upper_bound` (float\|null); `currency` (string)                                                                                                                                                      | Bucketed price ranges derived during transform for faster filtering and reasoning (“$0–$50”, “$50–$150”, …).                                                                       | Derived in transform step                    |
| `CoPurchaseSet`              | `set_id` (string, **unique**); `source_asin` (string); `size` (int); `support` (int); `confidence` (float)                                                                                                                                                                      | Represents a hyper-edge grouping of products frequently purchased together. Preserves the co-purchase context beyond pairwise edges.                                               | `meta_Electronics.jsonl` (`bought_together`) |
| `OpinionPhrase`              | `phrase_id` (string, **unique**); `text` (string); `canonical_aspect` (string, optional); `sentiment_hint` (float, optional); `extraction_version` (string)                                                                                                                     | Placeholder for aspect/opinion phrases extracted by NLP/LLM modules. Enables future commonsense relation ingestion (e.g., `USED_FOR`, `CAPABLE_OF`).                               | Future NLP pipeline                          |
| `CommonsenseEntity` (future) | `entity_id` (string, **unique**); `entity_type` (enum: `Audience`, `Function`, `Context`, …); `label` (string); `source` (string)                                                                                                                                               | Reserved label for ingesting external commonsense concepts while keeping the foundational schema stable.                                                                           | Future LLM reasoning                         |

> **Note:** While `Brand` and similar single-dimension attributes can be modelled as dedicated nodes, treating them uniformly within `Attribute` simplifies ingestion and future embedding generation.

## Relationship Types

| Type                  | Start → End                                 | Properties                                                                                                  | Description & Usage                                                                                               |
| --------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `WROTE`               | `User` → `Review`                           | `created_at` (datetime); `ingest_batch_id` (string)                                                         | Connects a user to authored reviews.                                                                              |
| `REVIEWS`             | `Review` → `Product`                        | `aspect_quality` (map\<string,float\>, optional)                                                            | Links review event to the target product. `aspect_quality` can store per-aspect sentiment scores when available.  |
| `RATED`               | `User` → `Product`                          | `rating` (float); `review_id` (string); `timestamp` (datetime); `verified_purchase` (boolean)               | Shortcut edge mirroring core rating info for fast collaborative traversals.                                       |
| `HAS_ATTRIBUTE`       | `Product` → `Attribute`                     | `value_origin` (enum); `raw_value` (string); `confidence` (float); `last_seen` (datetime)                   | Explicit product facets derived from metadata/details/features.                                                   |
| `MENTIONS_ATTRIBUTE`  | `Review` → `Attribute`                      | `sentiment` (float); `magnitude` (float); `extraction_method` (string); `extracted_at` (datetime)           | Implicit facet opinions sourced from review text NLP.                                                             |
| `BELONGS_TO_CATEGORY` | `Product` → `Category`                      | `primary` (boolean); `source` (string)                                                                      | Assigns product to each category level observed.                                                                  |
| `SUBCATEGORY_OF`      | `Category` → `Category`                     | `depth` (int)                                                                                               | Encodes the taxonomy hierarchy, enabling traversal and roll-ups.                                                  |
| `IN_PRICE_RANGE`      | `Product` → `PriceRange`                    | `bucket_version` (string); `bucketed_at` (datetime)                                                         | Connects products to the active pricing bucket.                                                                   |
| `BOUGHT_TOGETHER`     | `Product` → `Product`                       | `support` (int); `confidence` (float); `lift` (float, optional); `last_seen` (datetime)                     | Pairwise co-purchase edges derived directly from metadata. Direction reflects Amazon’s source → target semantics. |
| `MEMBER_OF_SET`       | `Product` → `CoPurchaseSet`                 | `position` (int, optional)                                                                                  | Provides a lossless representation of multi-product `bought_together` lists.                                      |
| `HAS_ROOT`            | `CoPurchaseSet` → `Product`                 |                                                                                                             | Identifies the originating product for the set (usually the product whose metadata produced the bundle).          |
| `IS_VARIANT_OF`       | `Product` → `Product`                       | `variant_dimension` (string, optional)                                                                      | Links variant ASINs to their `parent_asin`.                                                                       |
| `PRICE_CHANGED`       | `Product` → `Review`                        | `price_at_review` (float)                                                                                   | Stores historical price snapshots aligned with reviews (optional, supports temporal analytics).                   |
| `DERIVES_OPINION`     | `Review` → `OpinionPhrase`                  | `sentiment` (float); `confidence` (float)                                                                   | Associates free-form opinion phrases with reviews.                                                                |
| `RELATES_TO` (future) | `Product`/`Attribute` → `CommonsenseEntity` | `relationship` (enum: `USED_FOR`, `CAPABLE_OF`, `SUITABLE_FOR`, …); `confidence` (float); `source` (string) | Entry point for commonsense triples generated by LLM extraction.                                                  |
| `SUPPORTS` (future)   | `OpinionPhrase` → `CommonsenseEntity`       | `alignment_score` (float)                                                                                   | Bridges textual evidence to commonsense nodes for explainability.                                                 |

## Constraints & Indexing Strategy

Create the following constraints/indices before ingestion:

```cypher
// Uniqueness (auto-indexed)
CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE;
CREATE CONSTRAINT asin_unique IF NOT EXISTS FOR (p:Product) REQUIRE p.asin IS UNIQUE;
CREATE CONSTRAINT review_id_unique IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE;
CREATE CONSTRAINT attribute_id_unique IF NOT EXISTS FOR (a:Attribute) REQUIRE a.attribute_id IS UNIQUE;
CREATE CONSTRAINT category_id_unique IF NOT EXISTS FOR (c:Category) REQUIRE c.category_id IS UNIQUE;
CREATE CONSTRAINT price_range_id_unique IF NOT EXISTS FOR (pr:PriceRange) REQUIRE pr.range_id IS UNIQUE;
CREATE CONSTRAINT copurchase_set_id_unique IF NOT EXISTS FOR (cs:CoPurchaseSet) REQUIRE cs.set_id IS UNIQUE;

// Range / lookup indexes
CREATE INDEX product_price_idx IF NOT EXISTS FOR (p:Product) ON (p.price);
CREATE INDEX product_brand_idx IF NOT EXISTS FOR (p:Product) ON (p.brand);
CREATE INDEX review_timestamp_idx IF NOT EXISTS FOR (r:Review) ON (r.timestamp);
CREATE INDEX attribute_name_idx IF NOT EXISTS FOR (a:Attribute) ON (a.attribute_name);
CREATE INDEX category_name_idx IF NOT EXISTS FOR (c:Category) ON (c.name);
```

Additional full-text indexes (configured separately) should cover `Review.review_body`, `Product.title`, and `OpinionPhrase.text` to support conversational retrieval scenarios.

## Versioning & Governance Metadata

- All nodes and relationships carry `ingest_batch_id` (string) to track the Spark job partition and facilitate upserts.
- `ingested_at` (datetime) is recorded on nodes to support incremental refresh detection.
- `source_system` (enum) distinguishes batch backfill (`spark_batch`) from streaming updates (`kafka_stream`).

## Future-Ready Extensions

- **Commonsense enrichment:** The reserved `CommonsenseEntity` label and `RELATES_TO` edges allow direct ingestion of LLM-derived triples without schema refactoring.
- **Embedding alignment:** Rich, typed neighbourhoods (Users ⇄ Reviews ⇄ Products ⇄ Attributes ⇄ Categories) enable heterogeneous GNN training. `Review` nodes maintain both structural and textual context, required for Mutual Information Maximisation (MIM) alignment with LLM embeddings.
- **Temporal reasoning:** `timestamp` properties on `Review`, `RATED`, and `BOUGHT_TOGETHER` relationships support time-aware recommendations and dataset filtering (e.g., 2018–2023 subset).
- **Explainability:** Explicit representation of attributes, co-purchase sets, and opinion phrases allows GraphRAG pipelines to surface multi-hop explanations tailored to dialogue context.
