from typing import Dict, Any, List, Optional
import logging

from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
from src.knowledge_graph.graphdb.resolver_service import ResolverService
from src.knowledge_graph.graphdb.vector_search_helper import build_vector_search_query

logger = logging.getLogger(__name__)

class GraphSearchTool:
    """
    Tool for searching the Knowledge Graph using Hybrid Semantic Search.
    Combines Vector Search (for semantic understanding) with Cypher Filtering (for hard constraints).
    """
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

    def search(self, 
               semantic_query: Optional[str] = None, 
               structured_filters: Optional[Dict[str, Any]] = None, 
               limit: int = 5,
               # Legacy/Fallback arguments to avoid breaking existing calls if any
               query: Optional[str] = None,
               preferences: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        """
        # Handle aliases/legacy args
        text = semantic_query or query
        raw_filters = structured_filters or preferences or {}
        filters = dict(raw_filters)
        
        logger.info(f"[GST] Input: text='{text}', raw_filters={raw_filters}")
        
        # Normalize filters before searching
        if self._filters_present(filters):
            logger.info(f"[GST] Normalizing filters...")
            filters = self._normalize_filters(filters)
            logger.info(f"[GST] Normalized filters: {filters}")
        
        if not self.db or not self.embedder:
             return {"status": "error", "message": "Database or Embedder not initialized.", "items": []}

        try:
            # STRATEGY 1: HYBRID (Most common and desired)
            if text and self._filters_present(filters):
                logger.info(f"[GST] Strategy: HYBRID (text + filters)")
                return self._execute_hybrid_search(text, filters, raw_filters, limit)
            
            # STRATEGY 2: VECTOR ONLY (No specific filters)
            if text and not self._filters_present(filters):
                logger.info(f"[GST] Strategy: VECTOR_ONLY (text only, no meaningful filters)")
                return self._execute_vector_search(text, limit)

            # STRATEGY 3: FILTER ONLY (Parametric query)
            if self._filters_present(filters) and not text:
                logger.info(f"[GST] Strategy: FILTER_ONLY (filters only)")
                return self._execute_cypher_search(filters, raw_filters, limit)
            
            return {"status": "error", "message": "No search criteria provided.", "items": []}

        except Exception as e:
            logger.error(f"[GST] Execution error: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "items": []}

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
        return {"status": "success", "items": items, "count": len(items), "strategy": "hybrid_multi_index"}

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
            
        return {"status": "success", "items": items, "count": len(items), "strategy": "vector_only"}

    def _execute_cypher_search(self, filters: Dict[str, Any], raw_filters: Dict[str, Any], limit: int) -> Dict[str, Any]:
        where_clauses, params = self._build_filters(filters, raw_filters)
        where_str = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        cypher = f"""
        MATCH (node:ParentProduct)
        WHERE {where_str}
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, 1.0 as score, elementId(node) as id, node.parent_asin as asin
        LIMIT {limit}
        """
        
        logger.info(f"[GST:Filter] Cypher:\n{cypher}\nParams: {params}")

        with self.db.session() as session:
            result = session.run(cypher, params)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:Filter] Results: {len(items)} items found")
        for i, item in enumerate(items):
            logger.info(f"  [{i+1}] price={item.get('price')} | brand={item.get('brand')} | cat={item.get('category')} | title={str(item.get('title', ''))[:70]}")
            
        return {"status": "success", "items": items, "count": len(items), "strategy": "filter_only"}

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
                where_clauses.append("node.price <= $price_max")
                params["price_max"] = float(value)
            elif key == "price_min":
                where_clauses.append("node.price >= $price_min")
                params["price_min"] = float(value)
            elif key == "excluded_asins" and isinstance(value, list) and value:
                where_clauses.append("NOT node.parent_asin IN $excluded_asins")
                params["excluded_asins"] = value
            elif key == "brand":
                raw_brand = raw_filters.get("brand", value)
                where_clauses.append(
                    "(EXISTS { MATCH (node)-[:HAS_BRAND]->(b:Brand) WHERE b.name = $brand_filter } "
                    "OR toLower(node.title) CONTAINS toLower($raw_brand_filter))"
                )
                params["brand_filter"] = value
                params["raw_brand_filter"] = raw_brand
            elif key == "exclude_brand":
                raw_ex_brand = raw_filters.get("exclude_brand", value)
                where_clauses.append(
                    "NOT (EXISTS { MATCH (node)-[:HAS_BRAND]->(eb:Brand) WHERE eb.name = $exclude_brand } "
                    "OR toLower(node.title) CONTAINS toLower($raw_ex_brand_filter))"
                )
                params["exclude_brand"] = value
                params["raw_ex_brand_filter"] = raw_ex_brand
            elif key == "category":
                raw_cat = raw_filters.get("category", value)
                where_clauses.append(
                    "(EXISTS { MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category) WHERE toLower(c.name) CONTAINS toLower($category_filter) } "
                    "OR toLower(node.title) CONTAINS toLower($raw_category_filter))"
                )
                params["category_filter"] = value
                params["raw_category_filter"] = raw_cat
            # EAV Numeric filters dynamically intercepted with toFloat fallback for string attribute values
            elif key.endswith("_min") and key != "price_min":
                attr_name = key.replace("_min", "")
                where_clauses.append(f"EXISTS {{ MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute) WHERE a.attribute_name = '{attr_name}' AND COALESCE(toFloat(a.attribute_value), toFloat(a.normalized_value)) >= ${key} }}")
                params[key] = float(value)
            elif key.endswith("_max") and key != "price_max":
                attr_name = key.replace("_max", "")
                where_clauses.append(f"EXISTS {{ MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute) WHERE a.attribute_name = '{attr_name}' AND COALESCE(toFloat(a.attribute_value), toFloat(a.normalized_value)) <= ${key} }}")
                params[key] = float(value)
            elif key.endswith("_exact"):
                attr_name = key.replace("_exact", "")
                where_clauses.append(f"EXISTS {{ MATCH (node)-[:HAS_ATTRIBUTE]->(a:Attribute) WHERE a.attribute_name = '{attr_name}' AND COALESCE(toFloat(a.attribute_value), toFloat(a.normalized_value)) = ${key} }}")
                params[key] = float(value)
            else:
                logger.debug(f"Ignoring unhandled filter key: '{key}' = {value}")
            
        return where_clauses, params

    def _normalize_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize filter values to canonical graph node names using ResolverService.
        
        Confidence thresholds:
        - Brand: 0.85 (brand names are precise nouns, require high similarity to avoid Sennheiser -> Senso false positives)
        - Category: 0.80 (higher threshold to avoid bad mappings)
        
        NOTE: If normalization fails or confidence is low, the filter is NO LONGER dropped.
        Instead, it remains as the raw string so that the Cypher title fallback logic 
        (e.g., `OR toLower(node.title) CONTAINS $raw`) can still attempt a textual match.
        """
        BRAND_CONFIDENCE = 0.85
        CATEGORY_CONFIDENCE = 0.80
        
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
