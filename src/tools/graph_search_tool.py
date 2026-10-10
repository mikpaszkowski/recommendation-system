import logging
import re
from typing import Dict, Any, List, Optional

from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
from src.knowledge_graph.graphdb.resolver_service import ResolverService
from src.knowledge_graph.graphdb.vector_search_helper import build_vector_search_query

logger = logging.getLogger(__name__)

BRAND_CONFIDENCE = 0.85
CATEGORY_CONFIDENCE = 0.70
CATEGORY_MARGIN = 0.05

class GraphSearchTool:
    """
    Tool for searching the Knowledge Graph using Hybrid Semantic Search.
    Combines Vector Search (for semantic understanding) with Cypher Filtering (for hard constraints).
    """
    BRAND_CONFIDENCE = BRAND_CONFIDENCE
    CATEGORY_CONFIDENCE = CATEGORY_CONFIDENCE
    CATEGORY_MARGIN = CATEGORY_MARGIN
    def __init__(self, db_connector: Optional[Neo4jConnector] = None, embedding_service: Optional[EmbeddingService] = None, resolver: Optional[ResolverService] = None):
        try:
            self.db = db_connector or Neo4jConnector()
            # Ensure connection is open if not passed in
            if not db_connector:
                 self.db.connect()
        except Exception as e:
            logger.error(f"Failed to initialize Neo4jConnector: {e}")
            self.db = None

        try:
            self.embedder = embedding_service or EmbeddingService()
        except Exception as e:
            logger.error(f"Failed to initialize EmbeddingService: {e}")
            self.embedder = None

        try:
            self.resolver = resolver or ResolverService(connector=self.db, embed_svc=self.embedder)
        except Exception as e:
            logger.warning(f"Failed to initialize ResolverService: {e}. Filter normalization disabled.")
            self.resolver = None

    @staticmethod
    def _clean_params_for_metadata(params: Dict[str, Any]) -> Dict[str, Any]:
        """Summarizes high-dimensional embedding vectors for telemetry metadata."""
        cleaned = {}
        for k, v in params.items():
            is_vector_like = isinstance(v, (list, tuple)) or (
                hasattr(v, "__len__") and (hasattr(v, "shape") or hasattr(v, "tolist"))
            )
            if is_vector_like:
                try:
                    dim = len(v)
                    if dim > 50:
                        cleaned[k] = f"<vector dim={dim}>"
                        continue
                except Exception:
                    pass
            cleaned[k] = v
        return cleaned

    def search(self, 
               semantic_query: Optional[str] = "", 
               structured_filters: Optional[Dict[str, Any]] = None, 
               limit: int = 5,
               # Legacy/Fallback arguments to avoid breaking existing calls if any
               query: Optional[str] = None,
               preferences: Optional[Dict[str, Any]] = None,
               soft_preferences: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Executes a search using one of three strategies:
        1. Hybrid (Semantic + Filters) - PREFERRED
        2. Vector Only (Semantic)
        3. Filter Only (Cypher)
        
        Args:
            semantic_query: User's intent for vector search (e.g. "powerful gaming laptop").
            structured_filters: Hard constraints (e.g. {"price_max": 2000, "brand": "Asus"}).
            limit: Number of results to return.
            query: Alias for semantic_query (legacy support).
            preferences: Alias for structured_filters (legacy support).
            soft_preferences: List of flexible desires for additive scoring.
        """
        # Handle aliases/legacy args
        text = semantic_query or query
        raw_filters = structured_filters or preferences or {}
        filters = dict(raw_filters)
        soft_preferences = soft_preferences or []
        
        logger.info(f"[GST] Input: text='{text}', raw_filters={raw_filters}")
        
        # Normalize filters before searching
        if self._filters_present(filters):
            logger.info(f"[GST] Normalizing filters...")
            filters = self._normalize_filters(filters)
            logger.info(f"[GST] Normalized filters: {filters}")
        
        if not self.db or not self.embedder:
             return {"status": "error", "message": "Database or Embedder not initialized.", "items": [], "metadata": {"cypher": "", "params": {}}}

        try:
            result = {"status": "error", "items": []}
            # STRATEGY 1: HYBRID (Most common and desired)
            if text and self._filters_present(filters):
                logger.info(f"[GST] Strategy: HYBRID (text + filters)")
                result = self._execute_hybrid_search(text, filters, raw_filters, limit)
                
                # MACS Progressive Relaxation
                relaxed_constraints = []
                if result.get("count", 0) < 3:
                    logger.warning(f"[GST] MACS Triggered: Candidate yield {result.get('count', 0)} < 3. Initiating relaxation cascade.")
                    
                    # Pass 1: Widen Budget
                    relaxed = False
                    if "price_max" in filters:
                        filters["price_max"] = filters["price_max"] * 1.15
                        relaxed_constraints.append("Widened budget ceiling by 15%")
                        relaxed = True
                    if "price_min" in filters:
                        filters["price_min"] = filters["price_min"] * 0.85
                        relaxed_constraints.append("Lowered budget floor by 15%")
                        relaxed = True
                        
                    if relaxed:
                        result = self._execute_hybrid_search(text, filters, raw_filters, limit)
                    
                    # Pass 2: Drop Category constraint if still failing
                    if result.get("count", 0) < 3 and "category" in filters:
                        logger.warning(f"[GST] MACS Triggered: Yield still < 3. Dropping category constraint.")
                        del filters["category"]
                        relaxed_constraints.append("Dropped explicit category constraint (relying purely on vector search)")
                        result = self._execute_hybrid_search(text, filters, raw_filters, limit)
                
                if relaxed_constraints:
                    result["relaxed_constraints"] = relaxed_constraints
                    
            # STRATEGY 2: VECTOR ONLY (No specific filters)
            elif text and not self._filters_present(filters):
                logger.info(f"[GST] Strategy: VECTOR_ONLY (text only, no meaningful filters)")
                result = self._execute_vector_search(text, limit)

            # STRATEGY 3: FILTER ONLY (Parametric query)
            elif self._filters_present(filters) and not text:
                logger.info(f"[GST] Strategy: FILTER_ONLY (filters only)")
                result = self._execute_cypher_search(filters, raw_filters, limit)
            else:
                return {"status": "error", "message": "No search criteria provided.", "items": [], "metadata": {"cypher": "", "params": {}}}
                
            # ADDITIVE SCORING (Pillar 1/2)
            if soft_preferences and result.get("items"):
                logger.info(f"[GST] Applying Additive Scoring for {len(soft_preferences)} soft preferences.")
                for item in result["items"]:
                    title_lower = (item.get("title") or "").lower()
                    brand_lower = (item.get("brand") or "").lower()
                    reasons_str = " ".join(item.get("match_reasons") or []).lower()
                    
                    base_score = item.get("score", 0.0)
                    bonus = 0.0
                    for sp in soft_preferences:
                        val = str(sp.get("value", "")).lower()
                        cat = str(sp.get("category", "")).lower()
                        polarity = float(sp.get("polarity", 0.5))
                        
                        # Add heuristic bonus if value appears in title, brand or match reasons
                        if val:
                            if val.isdigit() and len(val) <= 2:
                                # For short bare digits (e.g. 1, 2, 8), require whole word boundary
                                # to prevent false positives on years (2021) or model numbers (Inspiron 15, S20)
                                if re.search(r"\b" + re.escape(val) + r"\b", title_lower):
                                    bonus += (polarity * 0.2)
                            elif (val in title_lower or (val in brand_lower and cat == 'brand') or val in reasons_str):
                                bonus += (polarity * 0.2)
                            
                    item["score"] = base_score + bonus
                
                # Re-sort after additive scoring
                result["items"] = sorted(result["items"], key=lambda x: x.get("score", 0), reverse=True)
                
            return result

        except Exception as e:
            logger.error(f"[GST] Execution error: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "items": [], "metadata": {"cypher": "", "params": {}}}

    def _execute_hybrid_search(self, text: str, filters: Dict[str, Any], raw_filters: Dict[str, Any], limit: int) -> Dict[str, Any]:
        query_vector = self.embedder.embed_query(text)
        logger.info(f"[GST:Hybrid] Embedded query (dim={len(query_vector)})")

        where_clauses, params = self._build_filters(filters, raw_filters)
        params["vector"] = query_vector
        params["k"] = limit * 30
        
        where_str = " AND ".join(where_clauses) if where_clauses else "1=1"
        logger.info(f"[GST:Hybrid] WHERE clauses: {where_str}")

        # GAP-003 Compliance: Use central helper to generate the vector search fragments
        prod_vector = build_vector_search_query(
            "product_embedding_index", 
            "$k", 
            yield_alias="node", 
            score_alias="score", 
            return_clause="RETURN node AS p, score, 'Product Title Match' AS match_reason"
        )
        
        attr_vector = build_vector_search_query(
            "attribute_embedding_index", 
            "$k", 
            yield_alias="node", 
            score_alias="score", 
            return_clause="MATCH (p:ParentProduct)-[:HAS_ATTRIBUTE]->(node)\nRETURN p, score * 0.8 AS score, 'Attribute Match: ' + node.attribute_name + '=' + coalesce(node.attribute_value, node.normalized_value, '') AS match_reason"
        )
        
        rev_vector = build_vector_search_query(
            "review_embedding_index", 
            "$k", 
            yield_alias="node", 
            score_alias="score", 
            return_clause="MATCH (node)-[:ABOUT_PRODUCT]->(p:ParentProduct)\nRETURN p, score * 0.9 AS score, 'Review Match: ' + coalesce(node.review_title, '') AS match_reason"
        )

        cypher = f"""
        CALL {{
            WITH $vector AS vector
            {prod_vector.replace('$vector', 'vector')}
            
            UNION
            
            WITH $vector AS vector
            {attr_vector.replace('$vector', 'vector')}
            
            UNION
            
            WITH $vector AS vector
            {rev_vector.replace('$vector', 'vector')}
        }}
        WITH p AS node, sum(score) AS total_score, collect(match_reason) AS match_reasons
        WHERE {where_str}
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, total_score as score, elementId(node) as id, node.parent_asin as asin,
               match_reasons
        ORDER BY score DESC
        LIMIT $limit
        """
        params["limit"] = limit
        
        logger.info("[GST:Hybrid] Cypher:\n" + cypher)

        with self.db.session() as session:
            result = session.run(cypher, params)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:Hybrid] Results: {len(items)} items found")
        clean_params = self._clean_params_for_metadata(params)
        return {
            "status": "success",
            "items": items,
            "count": len(items),
            "strategy": "hybrid_multi_index",
            "metadata": {"cypher": cypher, "params": clean_params},
        }

    def _execute_vector_search(self, text: str, limit: int) -> Dict[str, Any]:
        query_vector = self.embedder.embed_query(text)
        logger.info(f"[GST:Vector] Embedded query (dim={len(query_vector)}), searching top {limit}")
        
        prod_vector = build_vector_search_query(
            "product_embedding_index", "$k", yield_alias="node", score_alias="score", 
            return_clause="RETURN node AS p, score, 'Product Title Match' AS match_reason"
        )
        attr_vector = build_vector_search_query(
            "attribute_embedding_index", "$k", yield_alias="node", score_alias="score", 
            return_clause="MATCH (p:ParentProduct)-[:HAS_ATTRIBUTE]->(node)\nRETURN p, score * 0.8 AS score, 'Attribute Match: ' + node.attribute_name + '=' + coalesce(node.attribute_value, node.normalized_value, '') AS match_reason"
        )
        rev_vector = build_vector_search_query(
            "review_embedding_index", "$k", yield_alias="node", score_alias="score", 
            return_clause="MATCH (node)-[:ABOUT_PRODUCT]->(p:ParentProduct)\nRETURN p, score * 0.9 AS score, 'Review Match: ' + coalesce(node.review_title, '') AS match_reason"
        )

        cypher = f"""
        CALL {{
            WITH $vector AS vector
            {prod_vector.replace('$vector', 'vector')}
            UNION
            WITH $vector AS vector
            {attr_vector.replace('$vector', 'vector')}
            UNION
            WITH $vector AS vector
            {rev_vector.replace('$vector', 'vector')}
        }}
        WITH p AS node, sum(score) AS total_score, collect(match_reason) AS match_reasons
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, total_score as score, elementId(node) as id, node.parent_asin as asin,
               match_reasons
        ORDER BY score DESC
        LIMIT $limit
        """
        
        params = {"vector": query_vector, "k": limit * 30, "limit": limit}

        with self.db.session() as session:
            result = session.run(cypher, params)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:Vector] Results: {len(items)} items found")
        for i, item in enumerate(items):
            logger.info(f"  [{i+1}] score={item.get('score', 0):.4f} | reasons={item.get('match_reasons', [])} | title={str(item.get('title', ''))[:50]}")
            
        clean_params = self._clean_params_for_metadata(params)
        return {
            "status": "success",
            "items": items,
            "count": len(items),
            "strategy": "vector_only",
            "metadata": {"cypher": cypher, "params": clean_params},
        }

    def _execute_cypher_search(self, filters: Dict[str, Any], raw_filters: Dict[str, Any], limit: int) -> Dict[str, Any]:
        where_clauses, params = self._build_filters(filters, raw_filters)
        where_str = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        cypher = f"""
        MATCH (node:ParentProduct)
        WHERE {where_str}
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        WITH node, b, c,
             coalesce(node.rating, node.avg_rating, 0.0) AS raw_rating,
             coalesce(node.rating_count, node.review_count, 0) AS raw_count,
             coalesce(node.price, 999999.0) AS sort_price
        WITH node, b, c, sort_price,
             ((10.0 * 4.0 + (toFloat(raw_count) * raw_rating)) / (10.0 + toFloat(raw_count))) AS bayes_rating,
             log(1.0 + CASE WHEN toFloat(raw_count) > 500.0 THEN 500.0 ELSE toFloat(raw_count) END) AS volume_factor
        WITH node, b, c, sort_price,
             (bayes_rating * volume_factor) AS relevance_score
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, relevance_score as score, elementId(node) as id, node.parent_asin as asin
        ORDER BY score DESC, coalesce(price, 999999.0) ASC
        LIMIT {limit}
        """
        
        logger.info(f"[GST:Filter] Cypher:\n{cypher}\nParams: {params}")

        with self.db.session() as session:
            result = session.run(cypher, params)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:Filter] Results: {len(items)} items found")
        for i, item in enumerate(items):
            logger.info(f"  [{i+1}] price={item.get('price')} | brand={item.get('brand')} | cat={item.get('category')} | title={str(item.get('title', ''))[:70]}")
            
        clean_params = self._clean_params_for_metadata(params)
        return {
            "status": "success",
            "items": items,
            "count": len(items),
            "strategy": "filter_only",
            "metadata": {"cypher": cypher, "params": clean_params},
        }

    def fetch_product_attributes(self, asins: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetches unstructured attributes (e.g. pros/cons, opinions, reviews) for given products.
        Returns a dictionary mapping ASIN to a list of attributes and recent reviews.
        """
        if not self.db or not asins:
            return {}

        # Query attributes
        cypher_attr = """
        MATCH (p:ParentProduct)-[r:HAS_ATTRIBUTE]->(a:Attribute)
        WHERE p.parent_asin IN $asins
        RETURN p.parent_asin AS asin, a.attribute_name AS name, a.attribute_value AS value, a.source AS source
        """
        
        # Query reviews (recent helpful ones)
        cypher_rev = """
        MATCH (r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct)
        WHERE p.parent_asin IN $asins
        RETURN p.parent_asin AS asin, r.review_title AS name, r.review_body AS value, 'user_review' AS source
        ORDER BY r.helpful_votes DESC, r.timestamp_iso DESC
        LIMIT 20
        """
        
        logger.info(f"[GST:Attributes] Fetching attributes and reviews for {len(asins)} products...")
        
        result_map = {asin: [] for asin in asins}
        
        try:
            with self.db.session() as session:
                # 1. Fetch Attributes
                result_attr = session.run(cypher_attr, asins=asins)
                for record in result_attr:
                    asin = record["asin"]
                    if asin in result_map:
                        result_map[asin].append({
                            "name": record["name"],
                            "value": str(record["value"])[:200], # truncate to avoid huge context per attr
                            "source": record["source"]
                        })
                        
                # 2. Fetch Reviews
                result_rev = session.run(cypher_rev, asins=asins)
                for record in result_rev:
                    asin = record["asin"]
                    # Optionally limit reviews per product to avoid context window explosion
                    if asin in result_map and sum(1 for a in result_map[asin] if a["source"] == 'user_review') < 5:
                        result_map[asin].append({
                            "name": f"Review: {record['name']}",
                            "value": str(record["value"])[:300], # truncate long reviews
                            "source": record["source"]
                        })
                        
            logger.info(f"[GST:Attributes] Fetched attributes and reviews for {len(result_map)} products.")
            return result_map
        except Exception as e:
            logger.error(f"[GST:Attributes] Error fetching attributes/reviews: {e}", exc_info=True)
            return {}

    def _build_filters(self, filters: Dict[str, Any], raw_filters: Dict[str, Any] = None):
        """Build WHERE clauses for filters. Uses EXISTS subqueries for relationship-based filters."""
        logger.debug(f"[GST] Building filters for payload: {filters}")
        where_clauses = []
        params = {}
        raw_filters = raw_filters or {}
        
        for key, value in filters.items():
            if value is None or value == "":
                logger.debug(f"[GST] Skipping empty filter key: {key}")
                continue
            
            if key == "price_max":
                where_clauses.append("(node.price IS NULL OR node.price <= $price_max)")
                params["price_max"] = float(value)
            elif key == "price_min":
                where_clauses.append("(node.price IS NULL OR node.price >= $price_min)")
                params["price_min"] = float(value)
            elif key == "excluded_asins" and isinstance(value, list) and value:
                where_clauses.append("NOT node.parent_asin IN $excluded_asins")
                params["excluded_asins"] = value
            elif key == "brand":
                raw_brand = raw_filters.get("brand", value)
                where_clauses.append(
                    "(EXISTS { MATCH (node)-[:HAS_BRAND]->(b:Brand) "
                    "WHERE toLower(b.name) = toLower($brand_filter) "
                    "   OR toLower(b.name) CONTAINS toLower($brand_filter) "
                    "   OR toLower($brand_filter) CONTAINS toLower(b.name) } "
                    "OR toLower(node.title) CONTAINS toLower($raw_brand_filter))"
                )
                params["brand_filter"] = value
                params["raw_brand_filter"] = raw_brand
            elif key == "exclude_brand":
                raw_ex_brand = raw_filters.get("exclude_brand", value)
                where_clauses.append(
                    "NOT (EXISTS { MATCH (node)-[:HAS_BRAND]->(eb:Brand) "
                    "WHERE toLower(eb.name) = toLower($exclude_brand) "
                    "   OR toLower(eb.name) CONTAINS toLower($exclude_brand) "
                    "   OR toLower($exclude_brand) CONTAINS toLower(eb.name) } "
                    "OR toLower(node.title) CONTAINS toLower($raw_ex_brand_filter))"
                )
                params["exclude_brand"] = value
                params["raw_ex_brand_filter"] = raw_ex_brand
            elif key == "category":
                raw_cat = raw_filters.get("category", value)
                tokens = [t.strip().lower() for t in raw_cat.split() if len(t.strip()) > 2]

                # Construct conjunction of token matches to handle intervening modifiers in product titles
                if len(tokens) > 1:
                    escaped_tokens = [t.replace("'", "\\'") for t in tokens]
                    token_clauses = " AND ".join([f"toLower(node.title) CONTAINS '{et}'" for et in escaped_tokens])
                    title_condition = f"({token_clauses})"
                else:
                    escaped_raw = re.escape(raw_cat).replace("'", "\\'")
                    title_condition = f"toLower(node.title) =~ '(?i).*(^|[^a-z]){escaped_raw}(s)?([^a-z]|$).*'"

                where_clauses.append(f"""
                (
                    EXISTS {{
                        MATCH (node)-[:BELONGS_TO_CATEGORY]->(leaf:Category)-[:SUBCATEGORY_OF*0..3]->(c:Category)
                        WHERE c.name =~ ('(?i).*(^|[^a-z])' + $category_filter + '(s)?([^a-z]|$).*')
                           OR leaf.name =~ ('(?i).*(^|[^a-z])' + $category_filter + '(s)?([^a-z]|$).*')
                    }}
                    OR {title_condition}
                )
                """)
                params["category_filter"] = value
                params["raw_category_filter"] = raw_cat
            # EAV Numeric filters dynamically intercepted with toFloat fallback for string attribute values
            elif key.endswith("_min") and key != "price_min":
                attr_name = key.replace("_min", "")
                where_clauses.append(f"""
                EXISTS {{
                    MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute)
                    WHERE a.attribute_name = '{attr_name}'
                      AND COALESCE(
                          a.numeric_value,
                          toFloat(split(replace(replace(a.attribute_value, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                          toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
                              a.attribute_value,
                              'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
                      ) >= ${key}
                }}
                """)
                params[key] = float(value)
            elif key.endswith("_max") and key != "price_max":
                attr_name = key.replace("_max", "")
                where_clauses.append(f"""
                EXISTS {{
                    MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute)
                    WHERE a.attribute_name = '{attr_name}'
                      AND COALESCE(
                          a.numeric_value,
                          toFloat(split(replace(replace(a.attribute_value, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                          toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
                              a.attribute_value,
                              'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
                      ) <= ${key}
                }}
                """)
                params[key] = float(value)
            elif key.endswith("_exact"):
                attr_name = key.replace("_exact", "")
                where_clauses.append(f"""
                EXISTS {{
                    MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute)
                    WHERE a.attribute_name = '{attr_name}'
                      AND COALESCE(
                          a.numeric_value,
                          toFloat(split(replace(replace(a.attribute_value, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                          toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
                              a.attribute_value,
                              'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
                      ) = ${key}
                }}
                """)
                params[key] = float(value)
            else:
                logger.debug(f"Ignoring unhandled filter key: '{key}' = {value}")
            
        return where_clauses, params

    def _normalize_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize filter values to canonical graph node names using ResolverService.
        
        Confidence thresholds:
        - Brand: 0.85 (brand names are precise nouns, require high similarity to avoid Sennheiser -> Senso false positives)
        - Category: 0.70 (recalibrated with candidate margin check >= 0.05 to reliably resolve plurals and inflections while blocking cross-domain drift)
        
        NOTE: If normalization fails or confidence is low, the filter is NO LONGER dropped.
        Instead, it remains as the raw string so that the Cypher title fallback logic 
        (e.g., `OR toLower(node.title) CONTAINS $raw`) can still attempt a textual match.
        """
        BRAND_CONFIDENCE = getattr(self, "BRAND_CONFIDENCE", 0.85)
        CATEGORY_CONFIDENCE = getattr(self, "CATEGORY_CONFIDENCE", 0.70)
        CATEGORY_MARGIN = getattr(self, "CATEGORY_MARGIN", 0.05)
        
        if not self.resolver:
            logger.warning("[GST] ResolverService not available. Skipping normalization.")
            return filters
        
        normalized = dict(filters)

        # Normalize brand
        if "brand" in normalized and normalized["brand"]:
            try:
                matches = self.resolver.resolve_brand(normalized["brand"], k=1)
                if matches and matches[0]["score"] >= BRAND_CONFIDENCE:
                    logger.info(f"[GST] ✓ Normalized brand '{normalized['brand']}' → '{matches[0]['name']}' (score: {matches[0]['score']:.3f})")
                    normalized["brand"] = matches[0]["name"]
                elif matches:
                    logger.warning(f"[GST] ✗ Brand '{normalized['brand']}' best match '{matches[0]['name']}' score={matches[0]['score']:.3f} < {BRAND_CONFIDENCE}. Keeping raw value for title fallback.")
                else:
                    logger.warning(f"[GST] ✗ No brand match for '{normalized['brand']}'. Keeping raw value for title fallback.")
            except Exception as e:
                logger.warning(f"[GST] Brand normalization failed: {e}")

        # Normalize exclude_brand
        if "exclude_brand" in normalized and normalized["exclude_brand"]:
            try:
                matches = self.resolver.resolve_brand(normalized["exclude_brand"], k=1)
                if matches and matches[0]["score"] >= BRAND_CONFIDENCE:
                    logger.info(f"[GST] ✓ Normalized exclude_brand '{normalized['exclude_brand']}' → '{matches[0]['name']}'")
                    normalized["exclude_brand"] = matches[0]["name"]
                else:
                    logger.warning(f"[GST] ✗ Low confidence for exclude_brand. Keeping raw value for title fallback.")
            except Exception as e:
                logger.warning(f"[GST] Exclude brand normalization failed: {e}")

        # Normalize category
        if "category" in normalized and normalized["category"]:
            try:
                matches = self.resolver.resolve_category(normalized["category"], k=3)
                if matches and matches[0]["score"] >= CATEGORY_CONFIDENCE:
                    # Check candidate margin against runner-up candidates to prevent cross-domain drift
                    has_margin = True
                    if matches[0]["score"] < 0.85 and len(matches) > 1:
                        top = matches[0]
                        top_name = top.get("name", "").lower()
                        top_path = [p.lower() for p in (top.get("path") or [])]

                        # Find the first runner-up candidate that is a true cross-domain competitor.
                        # Candidates that contain the top candidate's name or share taxonomy lineage
                        # belong to the same taxonomic branch and are not cross-domain competitors.
                        comp_candidate = None
                        for runner_up in matches[1:]:
                            ru_name = runner_up.get("name", "").lower()
                            ru_path = [p.lower() for p in (runner_up.get("path") or [])]
                            if top_name in ru_name or ru_name in top_name or ru_name in top_path or top_name in ru_path:
                                continue
                            comp_candidate = runner_up
                            break

                        if comp_candidate is not None:
                            margin = top["score"] - comp_candidate["score"]
                            if margin < CATEGORY_MARGIN:
                                has_margin = False
                                logger.warning(
                                    f"[GST] ✗ Category '{normalized['category']}' failed margin check: "
                                    f"top match '{top['name']}' ({top['score']:.3f}) vs "
                                    f"runner-up '{comp_candidate['name']}' ({comp_candidate['score']:.3f}), "
                                    f"diff={margin:.3f} < {CATEGORY_MARGIN}. Keeping raw value for title fallback."
                                )
                        elif len(matches) > 1 and not (top_name in matches[1].get("name", "").lower() or matches[1].get("name", "").lower() in top_name):
                            margin = top["score"] - matches[1]["score"]
                            if margin < CATEGORY_MARGIN:
                                has_margin = False
                                logger.warning(
                                    f"[GST] ✗ Category '{normalized['category']}' failed margin check: "
                                    f"top match '{top['name']}' ({top['score']:.3f}) vs "
                                    f"runner-up '{matches[1]['name']}' ({matches[1]['score']:.3f}), "
                                    f"diff={margin:.3f} < {CATEGORY_MARGIN}. Keeping raw value for title fallback."
                                )

                    if has_margin:
                        logger.info(f"[GST] ✓ Normalized category '{normalized['category']}' → '{matches[0]['name']}' (score: {matches[0]['score']:.3f})")
                        normalized["category"] = matches[0]["name"]
                elif matches:
                    logger.warning(f"[GST] ✗ Category '{normalized['category']}' best match '{matches[0]['name']}' score={matches[0]['score']:.3f} < {CATEGORY_CONFIDENCE}. Keeping raw value for title fallback.")
                    candidates = [(m['name'], round(m['score'], 3)) for m in matches]
                    logger.info(f"[GST]   Top candidates: {candidates}")
                else:
                    logger.warning(f"[GST] ✗ No category match for '{normalized['category']}'. Keeping raw value for title fallback.")
            except Exception as e:
                logger.warning(f"[GST] Category normalization failed: {e}")

        return normalized

    def _filters_present(self, filters: Optional[Dict[str, Any]]) -> bool:
        """Check if any meaningful (non-None) filters exist."""
        if not filters:
            return False
        return any(v is not None for v in filters.values())
