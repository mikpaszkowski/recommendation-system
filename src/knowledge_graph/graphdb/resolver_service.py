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

logger = logging.getLogger(__name__)

class ResolverService:
    def __init__(self):
        self.connector = Neo4jConnector()
        self.connector.connect()
        self.embed_svc = EmbeddingService()
        self.min_score = 0.7  # Cosine similarity threshold

    def resolve_attribute(self, text: str, k: int = 3) -> List[Dict]:
        """
        Resolve a user attribute query (e.g. "pulse reader") to graph attributes.
        """
        if not text:
            return []
            
        embedding = self.embed_svc.embed_query(text)
        
        # Cypher for vector search
        query = """
        CALL db.index.vector.queryNodes('attribute_embedding_index', $k, $embedding)
        YIELD node, score
        WHERE score >= $min_score
        RETURN node.attribute_name as name, node.attribute_value as value, node.normalized_value as norm, score
        """
        
        with self.connector.session() as session:
            result = session.run(query, {
                "k": k, 
                "embedding": embedding,
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
        
        query = """
        CALL db.index.vector.queryNodes('category_embedding_index', $k, $embedding)
        YIELD node, score
        WHERE score >= $min_score
        RETURN node.name as name, node.path as path, score
        """
        
        with self.connector.session() as session:
            result = session.run(query, {
                "k": k, 
                "embedding": embedding,
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
