import logging
import os
import sys
import re
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

BRAND_CONFIDENCE = 0.85
CATEGORY_CONFIDENCE = 0.70  # Lowered to 0.70 to reliably resolve plurals and inflections
CATEGORY_MARGIN = 0.05      # Minimum margin between top-1 and runner-up candidate

class ResolverService:
    BRAND_CONFIDENCE = BRAND_CONFIDENCE
    CATEGORY_CONFIDENCE = CATEGORY_CONFIDENCE
    CATEGORY_MARGIN = CATEGORY_MARGIN

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
        Tier 2: Substring Match (CONTAINS) or Word-Boundary Regex (for Category)
        Tier 3: Vector Semantic Search
        """
        text = text.strip()
        if not text:
            return []

        # Ensure return properties are formatted correctly for Cypher
        ret_clause = ", ".join([f"node.{p} AS {p}" for p in return_props])
        
        with self.connector.session() as session:
            # Tier 1: Exact Match
            order_clause = "ORDER BY COALESCE(node.product_count, 0) DESC" if node_label == "Taxon" else ""
            t1_query = f"""
            MATCH (node:{node_label})
            WHERE toLower(node.{property_name}) = toLower($text)
            RETURN {ret_clause}, 1.0 AS score
            {order_clause}
            LIMIT {k}
            """
            result = session.run(t1_query, {"text": text})
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 1 (Exact) match found for '{text}' as {node_label}")
                return matches
            
            # Tier 2: Substring / Word-Boundary Regex Match
            if node_label in ("Category", "Taxon"):
                # Whole-token / word-boundary regex matching to prevent cross-domain contamination
                # (e.g. 'phone' matching 'Headphones')
                text_clean = text.lower().strip()
                if text_clean in ("smartphone", "smartphones", "smart phone", "smart phones", "cellphone", "cellphones", "cell phone", "cell phones", "mobile phone", "mobile phones"):
                    pattern = "(?i).*(^|[^a-z])(smart|cell|mobile)?( )?phone(s)?([^a-z]|$).*"
                else:
                    pattern = f"(?i).*(^|[^a-z]){re.escape(text)}(s)?([^a-z]|$).*"
                t2_query = f"""
                MATCH (node:{node_label})
                WHERE node.{property_name} =~ $pattern
                RETURN {ret_clause}, 0.85 AS score
                {order_clause}
                LIMIT {k}
                """
                result = session.run(t2_query, {"pattern": pattern})
            else:
                t2_query = f"""
                MATCH (node:{node_label})
                WHERE toLower(node.{property_name}) CONTAINS toLower($text)
                RETURN {ret_clause}, 0.85 AS score
                {order_clause}
                LIMIT {k}
                """
                result = session.run(t2_query, {"text": text})
            matches = [dict(record) for record in result]
            if matches:
                logger.info(f"[Resolver] Tier 2 (Substring/Regex) match found for '{text}' as {node_label}")
                return matches

        # Tier 3: Vector Search (Fallback)
        logger.info(f"[Resolver] Tiers 1 & 2 failed for '{text}'. Falling back to Tier 3 (Vector Semantic Search).")
        if node_label == "Taxon":
            matches = self._resolve_taxon_vector(text, k=k)
            if matches:
                logger.info(f"[Resolver] Tier 3 (Taxon Vector) match found for '{text}' with score {matches[0].get('score', 0):.3f}")
            return matches

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

    def _ensure_taxon_cache(self):
        """Loads and embeds all Taxon nodes into memory for fast Tier 3 fallback."""
        if getattr(self, "_taxon_cache", None) is not None:
            return
        self._taxon_cache = []
        self._taxon_embeddings = None
        try:
            with self.connector.session() as session:
                records = session.run(
                    "MATCH (t:Taxon) "
                    "RETURN t.name AS name, t.path AS path, t.product_count AS product_count, "
                    "t.depth AS depth, t.taxon_id AS taxon_id "
                    "ORDER BY COALESCE(t.product_count, 0) DESC"
                ).data()
            if not records:
                return
            self._taxon_cache = records
            names = [r.get("name") or "" for r in records]
            if hasattr(self.embed_svc, "embed_documents"):
                import numpy as np
                raw_embs = self.embed_svc.embed_documents(names)
                embs = np.array(raw_embs, dtype=np.float32)
                norms = np.linalg.norm(embs, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                self._taxon_embeddings = embs / norms
        except Exception as e:
            logger.warning(f"[Resolver] Could not initialize Taxon vector cache: {e}")

    def _resolve_taxon_vector(self, text: str, k: int = 3) -> List[Dict]:
        """In-memory cosine similarity search over cached Taxon embeddings."""
        self._ensure_taxon_cache()
        if not self._taxon_cache or self._taxon_embeddings is None:
            return []
        try:
            import numpy as np
            q_emb = self.embed_svc.embed_query(text)
            if not q_emb:
                return []
            q_vec = np.array(q_emb, dtype=np.float32)
            q_norm = np.linalg.norm(q_vec)
            if q_norm > 0:
                q_vec /= q_norm
            sims = np.dot(self._taxon_embeddings, q_vec)
            top_indices = np.argsort(-sims)[:k]
            matches = []
            for idx in top_indices:
                score = float(sims[idx])
                if score >= self.min_score:
                    item = dict(self._taxon_cache[idx])
                    item["score"] = score
                    matches.append(item)
            return matches
        except Exception as e:
            logger.error(f"[Resolver] Taxon vector search failed for '{text}': {e}")
            return []

    def resolve_brand(self, text: str, k: int = 1) -> List[Dict]:
        return self._execute_waterfall(text, "Brand", "name", "brand_embedding_index", k, ["name"])

    def resolve_attribute(self, text: str, k: int = 3) -> List[Dict]:
        # Attributes use attribute_name for lexical mapping, and have value/norm values to return
        # Since waterfall expects a primary property to match against, we use attribute_name.
        return self._execute_waterfall(text, "Attribute", "attribute_name", "attribute_embedding_index", k, ["attribute_name AS name", "attribute_value AS value", "normalized_value AS norm"])

    def resolve_taxon(self, text: str, k: int = 3) -> List[Dict]:
        return self._execute_waterfall(
            text, "Taxon", "name", "", k, ["name", "path", "product_count", "depth", "taxon_id"]
        )

    def resolve_category(self, text: str, k: int = 3) -> List[Dict]:
        return self.resolve_taxon(text, k=k)

    def validate_category_candidates(
        self,
        matches: List[Dict],
        min_confidence: float = CATEGORY_CONFIDENCE,
        min_margin: float = CATEGORY_MARGIN,
    ) -> Optional[Dict]:
        """
        Validates that the top category candidate meets min_confidence (0.70)
        and min_margin (>= 0.05) against cross-domain runner-ups.
        Returns the top candidate if valid, None if ambiguous or below confidence.
        """
        if not matches or matches[0].get("score", 0.0) < min_confidence:
            return None
        if matches[0].get("score", 0.0) < 0.85 and len(matches) > 1:
            top = matches[0]
            top_name = top.get("name", "").lower()
            top_path = [p.lower() for p in (top.get("path") or [])]
            for runner_up in matches[1:]:
                ru_name = runner_up.get("name", "").lower()
                ru_path = [p.lower() for p in (runner_up.get("path") or [])]
                if top_name in ru_name or ru_name in top_name or ru_name in top_path or top_name in ru_path:
                    continue
                if top.get("score", 0.0) - runner_up.get("score", 0.0) < min_margin:
                    return None
                break
        return matches[0]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    resolver = ResolverService()
    print("Testing Waterfall Resolver...")
    print(f"Brand 'asus': {resolver.resolve_brand('asus')}")
    print(f"Category 'monitor': {resolver.resolve_category('monitor')}")
    print(f"Attribute 'refresh': {resolver.resolve_attribute('refresh')}")
