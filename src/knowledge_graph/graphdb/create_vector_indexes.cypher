// 1. Index for Products
CREATE VECTOR INDEX product_embedding_index IF NOT EXISTS
  FOR (n:ParentProduct) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

// 2. Index for Brands
CREATE VECTOR INDEX brand_embedding_index IF NOT EXISTS
  FOR (n:Brand) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

// 3. Index for Categories
CREATE VECTOR INDEX category_embedding_index IF NOT EXISTS
  FOR (n:Category) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

// 4. Index for Attributes
CREATE VECTOR INDEX attribute_embedding_index IF NOT EXISTS
  FOR (n:Attribute) ON (n.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
