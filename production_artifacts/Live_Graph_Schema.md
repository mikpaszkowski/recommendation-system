# Live Neo4j Graph DB Snapshot

> **AUTO-GENERATED**: Ground truth of the currently running Neo4j database.

**Database:** Neo4j Kernel 5.14.0 (community)

## Node Counts
- **User**: 30
- **Review**: 4847
- **Product**: 25
- **PriceRange**: 3
- **Category**: 34
- **Attribute**: 22738
- **Variant**: 31
- **ParentProduct**: 30
- **Brand**: 13

## Indexes
- **asin_unique** (RANGE): `:Product(asin)`
- **aspect_name_unique** (RANGE): `:Aspect(name)`
- **attribute_embedding_index** (VECTOR): `:Attribute(embedding)`
- **attribute_id_unique** (RANGE): `:Attribute(attribute_id)`
- **attribute_name_idx** (RANGE): `:Attribute(attribute_name)`
- **brand_embedding_index** (VECTOR): `:Brand(embedding)`
- **brand_id_unique** (RANGE): `:Brand(brand_id)`
- **brand_name_idx** (RANGE): `:Brand(name)`
- **category_embedding_index** (VECTOR): `:Category(embedding)`
- **category_id_unique** (RANGE): `:Category(category_id)`
- **category_name_idx** (RANGE): `:Category(name)`
- **copurchase_set_id_unique** (RANGE): `:CoPurchaseSet(set_id)`
- **index_343aff4e** (LOOKUP): `:*(*)`
- **index_f7700477** (LOOKUP): `:*(*)`
- **parent_asin_unique** (RANGE): `:ParentProduct(parent_asin)`
- **parent_price_idx** (RANGE): `:ParentProduct(price)`
- **price_range_id_unique** (RANGE): `:PriceRange(range_id)`
- **product_brand_idx** (RANGE): `:Product(brand)`
- **product_embedding_index** (VECTOR): `:ParentProduct(embedding)`
- **product_price_idx** (RANGE): `:Product(price)`
- **review_embedding_index** (VECTOR): `:Review(embedding)`
- **review_id_unique** (RANGE): `:Review(review_id)`
- **review_timestamp_idx** (RANGE): `:Review(timestamp)`
- **user_id_unique** (RANGE): `:User(user_id)`
- **variant_asin_unique** (RANGE): `:Variant(asin)`

## Constraints
- **asin_unique** (UNIQUENESS): `:Product(asin)`
- **aspect_name_unique** (UNIQUENESS): `:Aspect(name)`
- **attribute_id_unique** (UNIQUENESS): `:Attribute(attribute_id)`
- **brand_id_unique** (UNIQUENESS): `:Brand(brand_id)`
- **category_id_unique** (UNIQUENESS): `:Category(category_id)`
- **copurchase_set_id_unique** (UNIQUENESS): `:CoPurchaseSet(set_id)`
- **parent_asin_unique** (UNIQUENESS): `:ParentProduct(parent_asin)`
- **price_range_id_unique** (UNIQUENESS): `:PriceRange(range_id)`
- **review_id_unique** (UNIQUENESS): `:Review(review_id)`
- **user_id_unique** (UNIQUENESS): `:User(user_id)`
- **variant_asin_unique** (UNIQUENESS): `:Variant(asin)`

## Node Properties

### :Product
- `asin`: String
- `price`: Double
- `review_count`: Long
- `ingested_at`: String
- `parent_asin`: String
- `ingest_batch_id`: String
- `avg_rating`: Double
- `title`: String
- `recent_review_count`: Long
- `main_category`: String

### :Review
- `user_id`: String
- `asin`: String
- `review_id`: String
- `timestamp_iso`: LocalDateTime
- `rating`: Double
- `verified`: Boolean
- `review_body`: String
- `ingest_batch_id`: String
- `helpful_votes`: Long
- `review_title`: String
- `embedding`: DoubleArray

### :Attribute
- `attribute_id`: String
- `attribute_name`: String
- `ingested_at`: String
- `attribute_value`: String
- `value_type`: String
- `normalized_value`: String
- `embedding`: DoubleArray
- `source`: String

### :Category
- `category_id`: String
- `name`: String
- `ingested_at`: String
- `path`: StringArray
- `level`: Long
- `embedding`: DoubleArray

### :PriceRange
- `range_id`: String
- `ingested_at`: String
- `label`: String
- `upper_bound`: Double
- `lower_bound`: Double
- `currency`: String

### :ParentProduct
- `price`: Double
- `review_count`: Long
- `ingested_at`: String
- `avg_rating`: Double
- `parent_asin`: String
- `ingest_batch_id`: String
- `title`: String
- `embedding`: DoubleArray

### :Brand
- `name`: String
- `ingested_at`: String
- `embedding`: DoubleArray
- `brand_id`: String

### :Variant
- `asin`: String
- `ingested_at`: String
- `parent_asin`: String

### :User
- `user_id`: String
- `review_count`: Long
- `helpful_votes_total`: Long
- `verified_purchase_count`: Long
- `ingested_at`: String

## Relationships & Properties
- `[::WROTE]`
- `[::REVIEWS]`
- `[::RATED]` has property `review_id` (String)
- `[::RATED]` has property `timestamp_iso` (String)
- `[::RATED]` has property `rating` (Double)
- `[::RATED]` has property `verified` (Boolean)
- `[::IN_PRICE_RANGE]`
- `[::BELONGS_TO_CATEGORY]` has property `primary` (Boolean)
- `[::SUBCATEGORY_OF]` has property `depth` (Long)
- `[::HAS_ATTRIBUTE]` has property `raw_value` (String)
- `[::HAS_ATTRIBUTE]` has property `confidence` (Double)
- `[::HAS_ATTRIBUTE]` has property `value_origin` (String)
- `[::ABOUT_PRODUCT]`
- `[::HAS_BRAND]` has property `confidence` (Double)
- `[::HAS_BRAND]` has property `source` (String)
- `[::IS_VARIANT_OF]`
