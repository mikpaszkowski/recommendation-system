// 1. Count core nodes ingested in the prototype window
MATCH (u:User)
RETURN count(u) AS user_count;

MATCH (p:Product)
RETURN count(p) AS product_count;

MATCH (r:Review)
RETURN count(r) AS review_count;

// 2. Users who rated a specific product with rating detail
MATCH (u:User)-[rel:RATED]->(p:Product {asin: $asin})
RETURN u.user_id AS user_id, rel.rating AS rating, rel.timestamp_iso AS rated_at
ORDER BY rel.timestamp_iso DESC
LIMIT 25;

// 3. Products in category path containing a given keyword with a target attribute
MATCH (p:Product)-[:BELONGS_TO_CATEGORY]->(c:Category)
WHERE toLower(c.name) CONTAINS toLower($category_keyword)
MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
WHERE a.attribute_name = $attribute_name
RETURN p.asin, p.title, a.attribute_value
LIMIT 50;

// 4. Retrieve recent reviews including sentiment placeholders
MATCH (p:Product {asin: $asin})<-[:REVIEWS]-(r:Review)
RETURN r.review_title, r.rating, r.review_body, r.timestamp_iso
ORDER BY r.timestamp_iso DESC
LIMIT 10;

// 5. Multi-hop: Products often bought with a given ASIN and their price buckets
MATCH (p:Product {asin: $asin})-[:BOUGHT_TOGETHER]->(other:Product)
OPTIONAL MATCH (other)-[:IN_PRICE_RANGE]->(pr:PriceRange)
RETURN other.asin, other.title, pr.label AS price_range
ORDER BY other.title
LIMIT 25;

// 6. Products sharing a key attribute (e.g., brand) for explainable recommendations
MATCH (p:Product {asin: $asin})-[:HAS_ATTRIBUTE]->(a:Attribute)
MATCH (other:Product)-[:HAS_ATTRIBUTE]->(a)
WHERE other.asin <> p.asin
RETURN other.asin, other.title, a.attribute_name, a.attribute_value
LIMIT 25;

// 7. Category hierarchy traversal for UI grouping
MATCH (leaf:Category {name: $leaf_category})-[:SUBCATEGORY_OF*1..5]->(root:Category)
RETURN root.name AS ancestor, size((leaf)-[:SUBCATEGORY_OF*]->(root)) AS depth
ORDER BY depth;

// 8. Reviews mentioning attributes (future NLP) - placeholder to verify structure
MATCH (r:Review)-[m:MENTIONS_ATTRIBUTE]->(a:Attribute)
RETURN r.review_title, a.attribute_name, m.sentiment
ORDER BY m.sentiment DESC
LIMIT 20;

// 9. Variant mapping sanity check
MATCH (child:Product)-[:IS_VARIANT_OF]->(parent:Product)
RETURN parent.asin AS parent_asin, collect(child.asin) AS variants
LIMIT 10;

