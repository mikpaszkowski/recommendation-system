// Core uniqueness constraints
CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE;
CREATE CONSTRAINT variant_asin_unique IF NOT EXISTS FOR (v:Variant) REQUIRE v.asin IS UNIQUE;
CREATE CONSTRAINT parent_asin_unique IF NOT EXISTS FOR (pp:ParentProduct) REQUIRE pp.parent_asin IS UNIQUE;
CREATE CONSTRAINT brand_id_unique IF NOT EXISTS FOR (b:Brand) REQUIRE b.brand_id IS UNIQUE;
CREATE CONSTRAINT review_id_unique IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE;
CREATE CONSTRAINT attribute_id_unique IF NOT EXISTS FOR (a:Attribute) REQUIRE a.attribute_id IS UNIQUE;
CREATE CONSTRAINT category_id_unique IF NOT EXISTS FOR (c:Category) REQUIRE c.category_id IS UNIQUE;
CREATE CONSTRAINT price_range_id_unique IF NOT EXISTS FOR (pr:PriceRange) REQUIRE pr.range_id IS UNIQUE;
CREATE CONSTRAINT copurchase_set_id_unique IF NOT EXISTS FOR (cs:CoPurchaseSet) REQUIRE cs.set_id IS UNIQUE;
CREATE CONSTRAINT aspect_name_unique IF NOT EXISTS FOR (a:Aspect) REQUIRE a.name IS UNIQUE;

// Frequently queried indexes
CREATE INDEX parent_price_idx IF NOT EXISTS FOR (pp:ParentProduct) ON (pp.price);
CREATE INDEX brand_name_idx IF NOT EXISTS FOR (b:Brand) ON (b.name);
CREATE INDEX review_timestamp_idx IF NOT EXISTS FOR (r:Review) ON (r.timestamp);
CREATE INDEX attribute_name_idx IF NOT EXISTS FOR (a:Attribute) ON (a.attribute_name);
CREATE INDEX category_name_idx IF NOT EXISTS FOR (c:Category) ON (c.name);
CREATE INDEX aspect_name_idx IF NOT EXISTS FOR (a:Aspect) ON (a.name);

