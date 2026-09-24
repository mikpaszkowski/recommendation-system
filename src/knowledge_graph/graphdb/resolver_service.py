import logging
import os
import sys
from typing import List, Dict, Optional, Tuple

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

    def resolve_brand(self, text: str, k: int = 1) -> List[Dict]:
        """
        Resolve a user brand query (e.g. "asus") to canonical Brand node name.
        """
        if not text:
            return []

        embedding = self.embed_svc.embed_query(text)

        query = build_vector_search_query(
            index_name='brand_embedding_index',
            k=k, # k is embedded directly into query string by helper
            where_clause="score >= $min_score",
            return_clause="RETURN node.name as name, score"
        )

        with self.connector.session() as session:
            result = session.run(query, {
                "k": k,
                "vector": embedding,
                "min_score": self.min_score
            })

            matches = []
            for record in result:
                matches.append({
                    "name": record["name"],
                    "score": record["score"]
                })

            return matches

    def resolve_attribute(self, text: str, k: int = 3) -> List[Dict]:
        """
        Resolve a user attribute query (e.g. "pulse reader") to graph attributes.
        """
        if not text:
            return []
            
        embedding = self.embed_svc.embed_query(text)
        
        # Cypher for vector search
        query = build_vector_search_query(
            index_name='attribute_embedding_index',
            k=k,
            where_clause="score >= $min_score",
            return_clause="RETURN node.attribute_name as name, node.attribute_value as value, node.normalized_value as norm, score"
        )
        
        with self.connector.session() as session:
            result = session.run(query, {
                "k": k, 
                "vector": embedding,
                "min_score": self.min_score
            })
            
            matches = []
            for record in result:
                matches.append({
                    "name": record["name"],
                    "value": record["value"],
                    "normalized_value": record["norm"],
                    "score": record["score"]
                })
            
            return matches

    def resolve_category(self, text: str, k: int = 3) -> List[Dict]:
        """
        Resolve a user category query (e.g. "Video") to graph categories.
        """
        if not text:
            return []

        embedding = self.embed_svc.embed_query(text)
        
        query = build_vector_search_query(
            index_name='category_embedding_index',
            k=k,
            where_clause="score >= $min_score",
            return_clause="RETURN node.name as name, node.path as path, score"
        )
        
        with self.connector.session() as session:
            result = session.run(query, {
                "k": k, 
                "vector": embedding,
                "min_score": self.min_score
            })
            
            matches = []
            for record in result:
                matches.append({
                    "name": record["name"],
                    "path": record["path"],
                    "score": record["score"]
                })
            
            return matches

if __name__ == "__main__":
    # Test stub
    logging.basicConfig(level=logging.INFO)
    resolver = ResolverService()
    print("Testing Resolver (expects indexes to exist)...")
    try:
        attrs = resolver.resolve_attribute("pulse reader")
        print(f"Attributes: {attrs}")
        cats = resolver.resolve_category("PC components")
        print(f"Categories: {cats}")
    except Exception as e:
        print(f"Error (maybe index missing): {e}")
