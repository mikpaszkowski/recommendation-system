from typing import Dict, Any, List, Optional
import logging

from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
from src.knowledge_graph.graphdb.resolver_service import ResolverService

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
        filters = structured_filters or preferences
        
        logger.info(f"[GST] Input: text='{text}', raw_filters={filters}")
        
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
                return self._execute_hybrid_search(text, filters, limit)
            
            # STRATEGY 2: VECTOR ONLY (No specific filters)
            if text and not self._filters_present(filters):
                logger.info(f"[GST] Strategy: VECTOR_ONLY (text only, no meaningful filters)")
                return self._execute_vector_search(text, limit)

            # STRATEGY 3: FILTER ONLY (Parametric query)
            if self._filters_present(filters) and not text:
                logger.info(f"[GST] Strategy: FILTER_ONLY (filters only)")
                return self._execute_cypher_search(filters, limit)
            
            return {"status": "error", "message": "No search criteria provided.", "items": []}

        except Exception as e:
            logger.error(f"[GST] Execution error: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "items": []}

    def _execute_hybrid_search(self, text: str, filters: Dict[str, Any], limit: int) -> Dict[str, Any]:
        # 1. Embed query
        query_vector = self.embedder.embed_query(text)
        logger.info(f"[GST:Hybrid] Embedded query (dim={len(query_vector)})")

        # 2. Build WHERE clauses
        where_clauses, params = self._build_filters(filters)
        params["vector"] = query_vector
        
        where_str = " AND ".join(where_clauses) if where_clauses else ""
        logger.info(f"[GST:Hybrid] WHERE clauses: {where_str or '(none)'}")
        logger.info(f"[GST:Hybrid] Params (excl. vector): { {k:v for k,v in params.items() if k != 'vector'} }")

        # 3. Hybrid Query: vector search first, then apply filters
        cypher = f"""
        CALL db.index.vector.queryNodes('product_embedding_index', {limit * 30}, $vector)
        YIELD node, score
        {"WHERE " + where_str if where_str else ""}
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, score, elementId(node) as id, node.parent_asin as asin
        ORDER BY score DESC
        LIMIT {limit}
        """
        
        logger.info(f"[GST:Hybrid] Cypher:\n{cypher}")

        with self.db.session() as session:
            result = session.run(cypher, params)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:Hybrid] Results: {len(items)} items found")
        for i, item in enumerate(items):
            logger.info(f"  [{i+1}] score={item.get('score', 0):.4f} | price={item.get('price')} | brand={item.get('brand')} | cat={item.get('category')} | title={str(item.get('title', ''))[:70]}")
        if not items:
            logger.warning(f"[GST:Hybrid] 0 results! Vector index queried {limit*30} candidates but all were filtered out.")
            
        return {"status": "success", "items": items, "count": len(items), "strategy": "hybrid"}

    def _execute_vector_search(self, text: str, limit: int) -> Dict[str, Any]:
        query_vector = self.embedder.embed_query(text)
        logger.info(f"[GST:Vector] Embedded query (dim={len(query_vector)}), searching top {limit}")
        
        cypher = f"""
        CALL db.index.vector.queryNodes('product_embedding_index', {limit}, $vector)
        YIELD node, score
        OPTIONAL MATCH (node)-[:HAS_BRAND]->(b:Brand)
        OPTIONAL MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category)
        RETURN node.title as title, node.price as price, b.name as brand, 
               collect(DISTINCT c.name) as category, score, elementId(node) as id, node.parent_asin as asin
        ORDER BY score DESC
        LIMIT {limit}
        """

        with self.db.session() as session:
            result = session.run(cypher, vector=query_vector)
            items = [dict(record) for record in result]
        
        logger.info(f"[GST:Vector] Results: {len(items)} items found")
        for i, item in enumerate(items):
            logger.info(f"  [{i+1}] score={item.get('score', 0):.4f} | price={item.get('price')} | brand={item.get('brand')} | cat={item.get('category')} | title={str(item.get('title', ''))[:70]}")
            
        return {"status": "success", "items": items, "count": len(items), "strategy": "vector_only"}

    def _execute_cypher_search(self, filters: Dict[str, Any], limit: int) -> Dict[str, Any]:
        where_clauses, params = self._build_filters(filters)
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

    def _build_filters(self, filters: Dict[str, Any]):
        """Build WHERE clauses for filters. Uses EXISTS subqueries for relationship-based filters."""
        where_clauses = []
        params = {}
        
        for key, value in filters.items():
            if value is None or value == "":
                continue
            
            if key == "price_max":
                where_clauses.append("node.price <= $price_max")
                params["price_max"] = float(value)
            elif key == "price_min":
                where_clauses.append("node.price >= $price_min")
                params["price_min"] = float(value)
            elif key == "brand":
                where_clauses.append(
                    "EXISTS { MATCH (node)-[:HAS_BRAND]->(b:Brand) WHERE b.name = $brand_filter }"
                )
                params["brand_filter"] = value
            elif key == "exclude_brand":
                where_clauses.append(
                    "NOT EXISTS { MATCH (node)-[:HAS_BRAND]->(eb:Brand) WHERE eb.name = $exclude_brand }"
                )
                params["exclude_brand"] = value
            elif key == "category":
                where_clauses.append(
                    "EXISTS { MATCH (node)-[:BELONGS_TO_CATEGORY]->(c:Category) WHERE toLower(c.name) CONTAINS toLower($category_filter) }"
                )
                params["category_filter"] = value
            else:
                logger.debug(f"Ignoring unhandled filter key: '{key}' = {value}")
            
        return where_clauses, params

    def _normalize_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize filter values to canonical graph node names using ResolverService.
        
        Confidence thresholds:
        - Brand: 0.6 (brand names are precise, easier to match)
        - Category: 0.75 (higher threshold; low-confidence categories are dropped
          to avoid filtering out relevant vector search results)
        """
        BRAND_CONFIDENCE = 0.6
        CATEGORY_CONFIDENCE = 0.75
        
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
                    logger.warning(f"[GST] ✗ Brand '{normalized['brand']}' best match '{matches[0]['name']}' score={matches[0]['score']:.3f} < {BRAND_CONFIDENCE}. Dropping filter.")
                    normalized["brand"] = None
                else:
                    logger.warning(f"[GST] ✗ No brand match for '{normalized['brand']}'. Dropping filter.")
                    normalized["brand"] = None
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
                    logger.warning(f"[GST] ✗ Low confidence for exclude_brand. Dropping filter.")
                    normalized["exclude_brand"] = None
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
                    logger.warning(f"[GST] ✗ Category '{normalized['category']}' best match '{matches[0]['name']}' score={matches[0]['score']:.3f} < {CATEGORY_CONFIDENCE}. Dropping filter (vector search will handle semantics).")
                    candidates = [(m['name'], round(m['score'], 3)) for m in matches]
                    logger.info(f"[GST]   Top candidates: {candidates}")
                    normalized["category"] = None
                else:
                    logger.warning(f"[GST] ✗ No category match for '{normalized['category']}'. Dropping filter.")
                    normalized["category"] = None
            except Exception as e:
                logger.warning(f"[GST] Category normalization failed: {e}")

        return normalized

    def _filters_present(self, filters: Optional[Dict[str, Any]]) -> bool:
        """Check if any meaningful (non-None) filters exist."""
        if not filters:
            return False
        return any(v is not None for v in filters.values())
