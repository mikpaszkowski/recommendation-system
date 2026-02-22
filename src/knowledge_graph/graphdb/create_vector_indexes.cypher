// 1. Index for Products (Crucial for recommendation)
CALL db.index.vector.createNodeIndex('product_embedding_index', 'ParentProduct', 'embedding', 384, 'cosine');

// 2. Index for Brands (For grounding/disambiguation)
CALL db.index.vector.createNodeIndex('brand_embedding_index', 'Brand', 'embedding', 384, 'cosine');

// 3. Index for Categories
CALL db.index.vector.createNodeIndex('category_embedding_index', 'Category', 'embedding', 384, 'cosine');
