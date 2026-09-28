import logging
import os
import sys
from typing import List, Dict, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
except ImportError:
    from neo4j_connector import Neo4jConnector
    from embedding_service import EmbeddingService
from src.knowledge_graph.graphdb.vector_search_helper import build_vector_search_query

logger = logging.getLogger(__name__)

class ResolverService:
    def __init__(self, connector=None, embed_svc=None, min_score: float = 0.55):
        self.connector = connector or Neo4jConnector()
        if not connector:
            self.connector.connect()
        self.embed_svc = embed_svc or EmbeddingService()
        self.min_score = min_score

    def _execute_waterfall(self, text: str, node_label: str, property_name: str, index_name: str, k: int, return_props: List[str]) -> List[Dict]:
        """
        Executes a 3-tier waterfall resolution strategy.
        Tier 1: Exact Match (case-insensitive)
        Tier 2: Substring Match (CONTAINS)
        Tier 3: Vector Semantic Search
        """
        text = text.strip()
        if not text:
            return []

        # Ensure return properties are formatted correctly for Cypher
        ret_clause = ", ".join([f"node.{p} AS {p}" for p in return_props])
        
        with self.connector.session() as session:
            # Tier 1: Exact Match
            t1_query = f"""
            MATCH (node:{node_label})
            WHERE toLower(node.{property_name}) = toLower($text)
            RETURN {ret_clause}, 1.0 AS score LIMIT {k}
            """
            result = session.run(t1_query, {"text": text})
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 1 (Exact) match found for '{text}' as {node_label}")
                return matches
            
            # Tier 2: Substring Match
            t2_query = f"""
            MATCH (node:{node_label})
            WHERE toLower(node.{property_name}) CONTAINS toLower($text)
            RETURN {ret_clause}, 0.85 AS score LIMIT {k}
            """
            result = session.run(t2_query, {"text": text})
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 2 (Substring) match found for '{text}' as {node_label}")
                return matches

        # Tier 3: Vector Search (Fallback)
        logger.info(f"[Resolver] Tiers 1 & 2 failed for '{text}'. Falling back to Tier 3 (Vector Semantic Search).")
        try:
            embedding = self.embed_svc.embed_query(text)
        except Exception as e:
            logger.error(f"[Resolver] Failed to generate embedding for '{text}': {e}")
            return []

        t3_query = build_vector_search_query(
            index_name=index_name,
            k=k,
            where_clause="score >= $min_score",
            return_clause=f"RETURN {ret_clause}, score"
        )
        
        with self.connector.session() as session:
            result = session.run(t3_query, {
                "k": k,
                "vector": embedding,
                "min_score": self.min_score
            })
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 3 (Vector) match found for '{text}' as {node_label} with score {matches[0].get('score', 0):.3f}")
            return matches

    def resolve_brand(self, text: str, k: int = 1) -> List[Dict]:
        return self._execute_waterfall(text, "Brand", "name", "brand_embedding_index", k, ["name"])

    def resolve_attribute(self, text: str, k: int = 3) -> List[Dict]:
        # Attributes use attribute_name for lexical mapping, and have value/norm values to return
        # Since waterfall expects a primary property to match against, we use attribute_name.
        return self._execute_waterfall(text, "Attribute", "attribute_name", "attribute_embedding_index", k, ["attribute_name AS name", "attribute_value AS value", "normalized_value AS norm"])

    def resolve_category(self, text: str, k: int = 3) -> List[Dict]:
        return self._execute_waterfall(text, "Category", "name", "category_embedding_index", k, ["name", "path"])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    resolver = ResolverService()
    print("Testing Waterfall Resolver...")
    print(f"Brand 'asus': {resolver.resolve_brand('asus')}")
    print(f"Category 'monitor': {resolver.resolve_category('monitor')}")
    print(f"Attribute 'refresh': {resolver.resolve_attribute('refresh')}")
