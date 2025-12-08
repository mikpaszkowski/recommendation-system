// 1. Count core nodes ingested in the prototype window
MATCH (u:User)
RETURN count(u) AS user_count;

MATCH (v:Variant)
RETURN count(v) AS variant_count;

MATCH (pp:ParentProduct)
RETURN count(pp) AS parent_count;

MATCH (r:Review)
RETURN count(r) AS review_count;

MATCH (a:Aspect)
RETURN count(a) AS aspect_count;

// 2. Users who rated a specific product with rating detail
MATCH (u:User)-[rel:RATED]->(v:Variant {asin: $asin})
RETURN u.user_id AS user_id, rel.rating AS rating, rel.timestamp_iso AS rated_at
ORDER BY rel.timestamp_iso DESC
LIMIT 25;

// 3. Products in category path containing a given keyword with a target attribute
MATCH (pp:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category)
WHERE toLower(c.name) CONTAINS toLower($category_keyword)
MATCH (pp)-[:HAS_ATTRIBUTE]->(a:Attribute)
WHERE a.attribute_name = $attribute_name
RETURN pp.parent_asin, a.attribute_value
LIMIT 50;

// 4. Retrieve recent reviews including sentiment placeholders
MATCH (p:Variant {asin: $asin})<-[:ABOUT_PRODUCT]-(r:Review)
RETURN r.review_title, r.rating, r.review_body, r.timestamp_iso
ORDER BY r.timestamp_iso DESC
LIMIT 10;

// 5. Multi-hop: Products often bought with a given ASIN and their price buckets
MATCH (pp:ParentProduct {parent_asin: $parent_asin})-[:BOUGHT_TOGETHER]->(other:ParentProduct)
OPTIONAL MATCH (other)-[:IN_PRICE_RANGE]->(pr:PriceRange)
RETURN other.parent_asin AS parent_asin, pr.label AS price_range
ORDER BY other.title
LIMIT 25;

// 6. Products sharing a brand for explainable recommendations
MATCH (pp:ParentProduct {parent_asin: $parent_asin})-[:HAS_BRAND]->(b:Brand)
MATCH (other:ParentProduct)-[:HAS_BRAND]->(b)
WHERE other.parent_asin <> pp.parent_asin
RETURN other.parent_asin, b.name AS brand
LIMIT 25;

// 7. Category hierarchy traversal for UI grouping
MATCH (leaf:Category {name: $leaf_category})-[:SUBCATEGORY_OF*1..5]->(root:Category)
RETURN root.name AS ancestor, size((leaf)-[:SUBCATEGORY_OF*]->(root)) AS depth
ORDER BY depth;

// 8. Reviews mentioning aspects with sentiment distribution
MATCH (r:Review)-[m:MENTIONS_ASPECT]->(a:Aspect)
RETURN m.sentiment AS sentiment, count(*) AS count
ORDER BY count DESC;

// 9. Variant mapping sanity check
MATCH (child:Variant)-[:IS_VARIANT_OF]->(parent:ParentProduct)
RETURN parent.parent_asin AS parent_asin, collect(child.asin) AS variants
LIMIT 10;

// 10. Brand linkage for parent products (if present)
MATCH (pp:ParentProduct)-[:HAS_BRAND]->(b:Brand)
RETURN pp.parent_asin AS parent_asin, b.name AS brand
LIMIT 10;

// 11. User-level preferences derived from aspect aggregation
MATCH (u:User)-[p:PREFERS]->(a:Aspect)
RETURN u.user_id AS user_id, a.name AS aspect, p.preference_score AS score, p.support AS mentions
ORDER BY score DESC, mentions DESC
LIMIT 20;

// 12. User-level dislikes derived from aspect aggregation
MATCH (u:User)-[p:DISLIKES]->(a:Aspect)
RETURN u.user_id AS user_id, a.name AS aspect, p.preference_score AS score, p.support AS mentions
ORDER BY score DESC, mentions DESC
LIMIT 20;

