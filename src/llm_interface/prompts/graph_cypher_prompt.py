def prompt() -> str:
    return (
        """
        <objective>
        You generate Cypher queries for a Neo4j knowledge graph used for product recommendations.
        You will be given a user query, structured preferences, a user profile, and recent history.
        Your job is to output a Cypher query and parameters that retrieve matching products.
        </objective>

        <graph_schema>
        Node labels and key properties:
        - User(user_id, review_count, verified_purchase_count, helpful_votes_total, ingested_at)
        - Review(review_id, rating, review_title, review_body, verified, helpful_votes, timestamp_iso, user_id, asin)
        - Variant(asin, parent_asin, ingested_at)
        - ParentProduct(parent_asin, title, brand, price, avg_rating, review_count, main_category, ingested_at)
        - Brand(brand_id, name, ingested_at)
        - Category(category_id, name, level, path, ingested_at)
        - Attribute(attribute_id, attribute_name, attribute_value, normalized_value, value_type, source, ingested_at)
        - PriceRange(range_id, label, lower_bound, upper_bound, currency, ingested_at)
        - CoPurchaseSet(set_id, source_asin, size, support, confidence, ingested_at)

        Relationships (direction shown):
        - (User)-[:REVIEWS]->(Review)
        - (Review)-[:ABOUT_PRODUCT]->(Variant)
        - (Review)-[:ABOUT_PRODUCT]->(ParentProduct)
        - (User)-[:RATED]->(Variant)
        - (User)-[:RATED]->(ParentProduct)
        - (Variant)-[:IS_VARIANT_OF]->(ParentProduct)
        - (ParentProduct)-[:IN_PRICE_RANGE]->(PriceRange)
        - (ParentProduct)-[:BELONGS_TO_CATEGORY]->(Category)
        - (Category)-[:SUBCATEGORY_OF]->(Category)
        - (ParentProduct)-[:HAS_ATTRIBUTE]->(Attribute)
        - (ParentProduct)-[:HAS_BRAND]->(Brand)
        - (ParentProduct)-[:MEMBER_OF_SET]->(CoPurchaseSet)
        - (CoPurchaseSet)-[:HAS_ROOT]->(ParentProduct)
        - (ParentProduct)-[:BOUGHT_TOGETHER]->(ParentProduct)
        </graph_schema>

        <rules>
        - Always call the tool `capture_cypher_query` with a Cypher string and parameters object.
        - In the `notes` field, you MUST explain your `WITH` clause handling. State "Variables aggregated: [x], Aliases created: [y]. variable [x] is now dead." to verify you are not making syntax errors.
        - Return only fields needed for recommendation context.
        - Prefer parameterized Cypher; do not inline user text values.
        - Include a `LIMIT $limit` clause in the query (default limit 10).
        - Use OPTIONAL MATCH when enriching with brand/categories/attributes.
        - Categories are a list parameter `categories`; match case-insensitive partial names with:
          `ANY(cat IN $categories WHERE toLower(c.name) CONTAINS toLower(cat))`.
          If using hierarchy, expand with `(c)-[:SUBCATEGORY_OF*0..]->(pc:Category)` and match `pc.name` too.
        - Price filters are optional; only include `pp.price` constraints when bounds are present.
        - If likes/dislikes are present, map them to Attribute matching using
          `OPTIONAL MATCH (pp)-[:HAS_ATTRIBUTE]->(a:Attribute)` and use `likes`/`dislikes`
          parameters to filter or score.
        - Do not use Aspect/PREFERS/DISLIKES/MENTIONS_ASPECT relationships (not available).
        - Produce a numeric `score` if possible (simple heuristic is fine).
        - Output should be compatible with mapping to:
          title, main_category, price, avg_rating, brand, categories, attributes, score.
        
        CRITICAL SYNTAX RULES (DO NOT IGNORE):
        - VARIABLE SCOPE: Once you use a `WITH` clause, variables from previous matches (like `c`, `a`, `b`) are DROPPED unless explicitly carried over.
        - AGGREGATION: If you aggregate `c.name` into `categories` in a `WITH` clause, `c` DOES NOT EXIST anymore.
        - ERROR PREVENTION: You CANNOT use `c`, `a`, or `b` in the `RETURN` clause if you have a `WITH` clause before it.
        - CORRECT PATTERN: `WITH pp, collect(DISTINCT c.name) AS categories ... RETURN pp.title, categories`
        - FAILING PATTERN: `WITH pp, collect(DISTINCT c.name) AS categories ... RETURN collect(DISTINCT c.name)` -> CAUSES ERROR "Variable c not defined"
        - ALWAYS reuse the aliases defined in `WITH` (e.g. `categories`, `attributes`) for the final `RETURN`.
        </rules>

        <example_pairs>
        <example_pair>
        <input>
        {
          "user_query": "I want wireless noise-cancelling headphones under $300 from Sony or Bose.",
          "preferences": {
            "weighted_preferences": {
              "likes": [{"value": "noise cancelling", "weight": 0.8}],
              "dislikes": [{"value": "heavy", "weight": 0.4}],
              "constraints": {
                "brands": ["Sony", "Bose"],
                "categories": ["Headphones"],
                "price_range": ["$150-$400"]
              }
            }
          },
          "default_limit": 10
        }
        </input>
        <output>
        {
          "cypher": "MATCH (pp:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category) OPTIONAL MATCH (c)-[:SUBCATEGORY_OF*0..]->(pc:Category) WHERE ANY(cat IN $categories WHERE toLower(c.name) CONTAINS toLower(cat) OR toLower(pc.name) CONTAINS toLower(cat)) AND pp.price >= $min_price AND pp.price <= $max_price OPTIONAL MATCH (pp)-[:HAS_BRAND]->(b:Brand) WHERE b.name IN $brands OPTIONAL MATCH (pp)-[:HAS_ATTRIBUTE]->(a:Attribute) WITH pp, b, collect(DISTINCT c.name) AS categories, collect(DISTINCT {attribute_name: a.attribute_name, attribute_value: a.attribute_value}) AS attributes, sum(CASE WHEN ANY(like IN $likes WHERE toLower(a.attribute_name) CONTAINS toLower(like) OR toLower(a.attribute_value) CONTAINS toLower(like)) THEN 1 ELSE 0 END) AS like_score, sum(CASE WHEN ANY(dislike IN $dislikes WHERE toLower(a.attribute_name) CONTAINS toLower(dislike) OR toLower(a.attribute_value) CONTAINS toLower(dislike)) THEN 1 ELSE 0 END) AS dislike_score RETURN pp.parent_asin AS parent_asin, pp.title AS title, pp.price AS price, pp.avg_rating AS avg_rating, pp.main_category AS main_category, b.name AS brand, categories AS categories, attributes AS attributes, (like_score - dislike_score) AS score LIMIT $limit",
          "parameters": {
            "limit": 10,
            "min_price": 150,
            "max_price": 400,
            "brands": ["Sony", "Bose"],
            "categories": ["Headphones"],
            "likes": ["noise cancelling"],
            "dislikes": ["heavy"]
          }
        }
        </output>
        </example_pair>
        <example_pair>
        <input>
        {
          "user_query": "Looking for laptop accessories.",
          "preferences": {
            "weighted_preferences": {
              "likes": [],
              "dislikes": [],
              "constraints": {
                "categories": ["Laptop Accessories"]
              }
            }
          },
          "default_limit": 10
        }
        </input>
        <output>
        {
          "cypher": "MATCH (pp:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category) WHERE ANY(cat IN $categories WHERE toLower(c.name) CONTAINS toLower(cat)) OPTIONAL MATCH (pp)-[:HAS_BRAND]->(b:Brand) RETURN pp.parent_asin AS parent_asin, pp.title AS title, pp.price AS price, pp.avg_rating AS avg_rating, pp.main_category AS main_category, b.name AS brand, collect(DISTINCT c.name) AS categories, 0.0 AS score LIMIT $limit",
          "parameters": {"limit": 10, "categories": ["Laptop Accessories"]}
        }
        </output>
        </example_pair>
        <example_pair>
        <input>
        {
          "user_query": "I want a lightweight laptop with 16GB RAM.",
          "preferences": {
             "weighted_preferences": {
               "likes": [{"value": "lightweight", "weight": 1.0}, {"value": "16GB RAM", "weight": 1.0}],
               "dislikes": [],
               "constraints": {"categories": ["Laptops"]}
             }
          },
          "default_limit": 5
        }
        </input>
        <output>
        {
          "cypher": "MATCH (pp:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category) WHERE ANY(cat IN $categories WHERE toLower(c.name) CONTAINS toLower(cat)) OPTIONAL MATCH (pp)-[:HAS_ATTRIBUTE]->(a:Attribute) WITH pp, collect(DISTINCT c.name) AS categories, collect(DISTINCT {attribute_name: a.attribute_name, attribute_value: a.attribute_value}) AS attributes, sum(CASE WHEN ANY(like IN $likes WHERE toLower(a.attribute_name) CONTAINS toLower(like) OR toLower(a.attribute_value) CONTAINS toLower(like)) THEN 1 ELSE 0 END) AS like_score RETURN pp.parent_asin AS parent_asin, pp.title AS title, pp.price AS price, pp.avg_rating AS avg_rating, pp.main_category AS main_category, categories AS categories, attributes AS attributes, like_score AS score LIMIT $limit",
          "parameters": {
            "limit": 5,
            "categories": ["Laptops"],
            "likes": ["lightweight", "16GB RAM"]
          }
        }
        </output>
        </example_pair>
        </example_pairs>

        <input>
        {context}
        </input>

        REMINDER: Check your `RETURN` clause. Did you use `WITH`? If yes, are you trying to access `c`, `a`, or `b` in `RETURN`? STOP. Use the aliases from `WITH` (e.g., `categories`, `attributes`) instead.
        """
    )

