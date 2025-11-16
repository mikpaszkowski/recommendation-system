// Core uniqueness constraints
CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE;
CREATE CONSTRAINT asin_unique IF NOT EXISTS FOR (p:Product) REQUIRE p.asin IS UNIQUE;
CREATE CONSTRAINT review_id_unique IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE;
CREATE CONSTRAINT attribute_id_unique IF NOT EXISTS FOR (a:Attribute) REQUIRE a.attribute_id IS UNIQUE;
CREATE CONSTRAINT category_id_unique IF NOT EXISTS FOR (c:Category) REQUIRE c.category_id IS UNIQUE;
CREATE CONSTRAINT price_range_id_unique IF NOT EXISTS FOR (pr:PriceRange) REQUIRE pr.range_id IS UNIQUE;
CREATE CONSTRAINT copurchase_set_id_unique IF NOT EXISTS FOR (cs:CoPurchaseSet) REQUIRE cs.set_id IS UNIQUE;

// Frequently queried indexes
CREATE INDEX product_price_idx IF NOT EXISTS FOR (p:Product) ON (p.price);
CREATE INDEX product_brand_idx IF NOT EXISTS FOR (p:Product) ON (p.brand);
CREATE INDEX review_timestamp_idx IF NOT EXISTS FOR (r:Review) ON (r.timestamp);
CREATE INDEX attribute_name_idx IF NOT EXISTS FOR (a:Attribute) ON (a.attribute_name);
CREATE INDEX category_name_idx IF NOT EXISTS FOR (c:Category) ON (c.name);

