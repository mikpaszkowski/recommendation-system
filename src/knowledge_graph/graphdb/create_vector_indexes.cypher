// Vector indexes in the Neo4j 5.14 procedure form (Vision D-4: the live graph runs Neo4j 5.14, which has
// no vector-index DDL statement; that arrived in 5.15). Graph v2 creates these through
// setup_indexes.py / post_import_v2.py vector-indexes (Technical Specification Graph Rebuild FR-024, FR-034).
// The procedure fails if an index of the same name already exists.

// 1. Index for Products
CALL db.index.vector.createNodeIndex('product_embedding_index', 'ParentProduct', 'embedding', 384, 'cosine');

// 2. Index for Brands
CALL db.index.vector.createNodeIndex('brand_embedding_index', 'Brand', 'embedding', 384, 'cosine');

// 3. Index for Categories
CALL db.index.vector.createNodeIndex('category_embedding_index', 'Category', 'embedding', 384, 'cosine');

// 4. Index for Attributes
CALL db.index.vector.createNodeIndex('attribute_embedding_index', 'Attribute', 'embedding', 384, 'cosine');

// 5. Index for Reviews
CALL db.index.vector.createNodeIndex('review_embedding_index', 'Review', 'embedding', 384, 'cosine');
