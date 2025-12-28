# Data Pipeline Architecture (Electronics KG Foundation)

This document outlines the ETL strategy for constructing and maintaining the Electronics knowledge graph that backs the conversational recommender. The pipeline is optimised for iterative development: a constrained backfill (2018–2023 data, falling back to 2021–2023 if volume remains high) proves the schema, while the architecture extends to full-scale operation with batch and streaming modes.

## High-Level Architecture

1. **Landing Zone (S3/GCS/Local):** Raw Amazon reviews and metadata JSONL files (`Electronics.jsonl`, `meta_Electronics.jsonl`) stored in object storage. The Workspace uses `/datasets` during development.
2. **Processing Engine:** Apache Spark (batch and structured streaming) performs schema-on-read ingestion, filtering, and transformation.
3. **Feature Services:**
   - **NLP/LLM microservice** (optional during prototype) extracts aspects, sentiment, and opinion phrases from review text.
   - **Price bucketing module** derives `PriceRange` nodes.
4. **Graph Persistence:** Neo4j AuraDB (or self-managed Neo4j) receives nodes and relationships via the Neo4j Python driver and Cypher `UNWIND` batches.
5. **Orchestration:** Apache Airflow or Prefect schedules batch jobs; Kafka Connect/Spark Structured Streaming maintains incremental updates.

```
Raw JSONL (S3) --> Spark Batch ETL --> Curated Parquet (Delta Lake) --> Neo4j Loader
                                    ↘ Kafka Topic (new reviews) → Spark Streaming → Neo4j upsert
```

## Dataset Filtering Strategy

- **Temporal window:** Filter review events by `unixReviewTime` (or `review_date`) to 2018-01-01 through 2023-12-31. Use Spark predicate pushdown for efficient filtering.
- **Fallback control:** If the filtered dataset still exceeds the prototype threshold (configurable, e.g., >2M reviews), tighten the window to 2021-01-01 onward.
- **Metadata alignment:** Ensure `meta_Electronics.jsonl` is restricted to ASINs observed in the filtered reviews to minimise orphan product nodes.

Configuration snippet (YAML referenced by ingestion scripts):

```yaml
filters:
  review_start_date: "2018-01-01"
  review_end_date: "2023-12-31"
  fallback_start_date: "2021-01-01"
  max_reviews: 2000000
```

## Batch ETL (Historical Backfill)

1. **Extract**
   - Read metadata into Spark DataFrames with schema inference tuned for nested fields (`categories`, `details`).
   - Read reviews into Spark, apply temporal filter, and drop records with missing `asin` or `user_id`.
2. **Transform**
   - **Product model:** Select core product attributes, normalise price (`price` → float), add `ingest_batch_id` and `ingested_at`.
   - **Category hierarchy:** Explode `categories` (list of lists) so each level becomes a `Category` node. Generate deterministic `category_id` (hash of full path).
   - **Attributes:** Flatten `details`, `feature_bullets`, and `brand` into `Attribute` nodes. Use `attribute_id = hash(attribute_name + attribute_value)`.
   - **Reviews:** Generate `review_id = sha256(user_id + asin + unixReviewTime + reviewText)`. Retain `review_body`, `summary`, `rating`, `verified`.
   - **Price ranges:** Bin prices using configurable buckets (e.g., `[0,50)`, `[50,150)`, `[150,400)`, `[400, inf)`).
   - **Co-purchase sets:** For each product with `bought_together`, create `CoPurchaseSet` node (`set_id = hash(asin + sorted_list)`) and pairwise `BOUGHT_TOGETHER` edges.
   - **Review aspects (optional):** Call NLP service (batch UDF or external microservice) to extract aspects and sentiment, emit `Mentions` relationships.
3. **Load**
   - Export transformed entities as partitioned Parquet/CSV staging tables (`s3://.../kg/products/`, `.../reviews/`, etc.).
   - Use Python Neo4j driver in `sample_ingest.py` (prototype) or `neo4j-admin database import` (full backfill) to load nodes/relationships in chunks (e.g., 10k records per transaction).
   - Maintain idempotency with `MERGE` on unique identifiers and `SET` for properties.

## Streaming / Incremental Updates

1. **Source Events:** E-commerce platform publishes `new_review`, `product_update`, `price_update` events to Kafka topics (`crs.reviews`, `crs.catalog`).
2. **Spark/Flink Structured Streaming**
   - Deserialize JSON payloads; enforce schema.
   - Apply same temporal window (reject out-of-range data during pilot).
   - Enrich with derived fields (price bucket, aspect extraction via async calls).
3. **Upsert Logic**
   - Leverage Neo4j transactional batches (`session.write_transaction`) with `MERGE`.
   - Use APOC `apoc.merge.node`/`relationship` for flexible property setting.
4. **Dead-letter and Monitoring**
   - Route failed records to `crs.dlq` topic with reason codes.
   - Emit metrics (prometheus exporters) for throughput, lag, error rates.

## Transform Mapping Summary

| Target          | Source Fields                             | Transform Notes                                                                          |
| --------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| `User`          | `reviewerID`, counts aggregated per batch | Derive `review_count`, `verified_purchase_count`, `helpful_votes_given` (sum `helpful`). |
| `Variant`       | Review ASINs                              | Create from reviews; link to parents when `asin != parent_asin`.                         |
| `ParentProduct` | `parent_asin` from metadata               | Create parent nodes; attach price/brand/categories/attributes from metadata.             |
| `Brand`         | `brand`                                   | Normalise brand names and hash to `brand_id`; link via `HAS_BRAND`.                      |
| `Review`        | Review record                             | Generate deterministic id; clip text to max length for ingestion; attach `source_file`.  |
| `Attribute`     | `details`, `feature`, NLP outputs         | Standardise keys (snake_case), normalise values (unit conversion).                       |
| `Category`      | `categories` array                        | Deduplicate via hash of full path; capture `level`, `path`.                              |
| `PriceRange`    | Parent price                              | Precompute ranges; maintain dimension table versioning.                                  |
| `CoPurchaseSet` | `bought_together` list                    | Keep original `source_asin` and computed quality metrics (support = list length).        |
| `OpinionPhrase` | NLP pipeline                              | Optional; store canonical aspect mapping and sentiment for reuse.                        |

Renamed edge `ABOUT_PRODUCT` (formerly `REVIEWS`) links reviews to variants when available, otherwise directly to `ParentProduct`. Variants link to parents via `IS_VARIANT_OF`. Brands and categories attach at the parent level (with optional propagation); price ranges also attach to parents.

## Operational Considerations

- **Job Scheduling:** Nightly batch for historical rebuild; hourly micro-batch for streaming ingestion during pilot.
- **Idempotency:** Use `ingest_batch_id` to re-run batches safely; maintain watermark timestamps for streaming.
- **Data Quality Rules:** Enforce non-null `asin`, `user_id`, positive `price`, category path consistency. Invalid rows routed to quarantine storage.
- **Testing:** Use the Electronics subset filtered to 2018–2023 to validate schema and performance before scaling.
- **Security:** Store Neo4j credentials in Secrets Manager; TLS-enabled AuraDB connection strings; restrict Kafka topics with ACLs.
- **Observability:** Airflow DAG-level SLAs, Spark structured streaming checkpoints, Neo4j query logs for slow-query analysis.

## Prototype Execution Path (Developer Workstation)

1. Set local `.env` with Neo4j connection details.
2. Run `python src/knowledge-graph/graphdb/graph-builder/sample_ingest.py --start-date 2018-01-01 --end-date 2023-12-31 --limit 100000`.
3. Script loads:
   - Constraints from `constraints.cypher`.
   - Filtered subset of metadata and reviews.
   - Derived nodes/relationships limited to Electronics category.
4. Inspect ingest metrics logged to console; adjust `--limit` or `--start-date` to enforce fallback strategy.
5. Execute validation queries from `validation.cypher` to confirm data integrity.

This architecture balances immediate prototype needs with a clear upgrade path to production-scale ingestion, streaming freshness, and ML/LLM integration.
