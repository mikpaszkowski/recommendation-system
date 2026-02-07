import logging
import json
import os
import sys
from typing import List, Dict

# Ensure imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    from src.knowledge_graph.graphdb.attribute_normalizer import AttributeNormalizer
    from src.llm.simple_llm_handler import SimpleLLMHandler
except ImportError:
    from neo4j_connector import Neo4jConnector
    from attribute_normalizer import AttributeNormalizer
    # Adjust path if running from subdir
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
    from src.llm.simple_llm_handler import SimpleLLMHandler


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GENERIC_KEYS = {"feature", "bullet_point", "product_feature", "about_this_item"}

class AttributeDecomposer:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.connector = Neo4jConnector()
        self.llm_handler = SimpleLLMHandler(model_name="gpt-4o-mini")

    def run(self, limit: int = 50):
        logger.info(f"Starting Attribute Decomposition (Dry Run: {self.dry_run})...")
        
        # 1. Find candidates
        candidates = self._find_candidates(limit)
        logger.info(f"Found {len(candidates)} candidate attributes to decompose.")

        for record in candidates:
            attr_node = record['a']
            parent_asin = record['parent_asin']
            text = attr_node['attribute_value']
            
            logger.info(f"Processing ({parent_asin}): {text[:50]}...")
            
            # 2. Extract
            extracted = self._extract_features(text)
            if not extracted:
                continue

            # 3. Create new nodes
            self._create_derived_attributes(parent_asin, extracted)
        
        self.connector.close()

    def _find_candidates(self, limit: int) -> List[Dict]:
        query = """
        MATCH (p:ParentProduct)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WHERE toLower(a.attribute_name) IN $generic_keys
        AND size(a.attribute_value) > 50
        AND a.source <> 'derived'
        RETURN p.parent_asin as parent_asin, a
        LIMIT $limit
        """
        params = {"generic_keys": list(GENERIC_KEYS), "limit": limit}
        
        # Ensure connection
        if not self.connector.is_connected():
            self.connector.connect()

        with self.connector.session() as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _extract_features(self, text: str) -> List[Dict[str, str]]:
        prompt = [
            {"role": "system", "content": "You are a precise data extraction assistant."},
            {"role": "user", "content": f"""
            Extract specific, atomic product features from the following text.
            Return ONLY a JSON list of objects with 'key' and 'value'.
            Example: [{{"key": "Connectivity", "value": "Bluetooth 5.0"}}, {{"key": "Battery", "value": "20 hours"}}]
            
            Text: "{text}"
            """}
        ]
        
        try:
            response = self.llm_handler.submit_raw(prompt)
            # Naive cleanup
            clean_resp = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_resp)
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.error(f"LLM Extraction failed: {e}")
        return []

    def _create_derived_attributes(self, parent_asin: str, features: List[Dict]):
        if self.dry_run:
            logger.info(f"  [DRY RUN] Would create {len(features)} derived attributes:")
            for f in features:
                norm = AttributeNormalizer.normalize(f['value'], f['key'])
                logger.info(f"    - {f['key']}: {f['value']} -> Normalized: {norm}")
            return

        # Write to DB
        query = """
        MATCH (p:ParentProduct {parent_asin: $parent_asin})
        MERGE (a:Attribute {
            attribute_id: apoc.util.md5([$key, $norm_value]), 
            attribute_name: $key,
            attribute_value: $value,
            normalized_value: $norm_value,
            source: 'derived'
        })
        MERGE (p)-[:HAS_ATTRIBUTE]->(a)
        """
        
        if not self.connector.is_connected():
            self.connector.connect()

        with self.connector.session() as session:
            for f in features:
                key = f['key'].lower().strip()
                val = f['value']
                norm = AttributeNormalizer.normalize(val, key)
                
                session.run(query, {
                    "parent_asin": parent_asin,
                    "key": key,
                    "value": val,
                    "norm_value": norm
                })
        logger.info(f"  Saved {len(features)} derived attributes.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_false", dest="dry_run")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    
    decomposer = AttributeDecomposer(dry_run=args.dry_run)
    decomposer.run(limit=args.limit)
