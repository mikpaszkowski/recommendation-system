import logging
import json
import os
import sys
import argparse
from typing import List, Dict, Optional, Any
from tqdm import tqdm

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


# Configure logging - default to handling by class
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GENERIC_KEYS = {"feature", "bullet_point", "product_feature", "about_this_item"}

class AttributeDecomposer:
    def __init__(self, dry_run: bool = True, use_local_llm: bool = False, debug: bool = False):
        self.dry_run = dry_run
        self.debug = debug
        self.connector = Neo4jConnector()
        
        # Adjust log level based on debug flag
        if self.debug:
            logger.setLevel(logging.DEBUG)
        else:
            # Silence info logs from this module, only show warnings/errors
            # Tqdm will handle progress
            logger.setLevel(logging.WARNING)
        
        # Suppress Neo4j driver warnings about missing property keys (expected)
        import warnings
        warnings.filterwarnings("ignore", message=".*processed_for_decomposition.*")
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

        if use_local_llm:
            try:
                self.llm_handler = SimpleLLMHandler(
                    provider="ollama",
                    model_name="llama3.1"
                )
                if self.debug: logger.debug("Using Local LLM (Ollama)")
            except Exception as e:
                logger.error(f"Failed to init Ollama: {e}")
                sys.exit(1)
        else:
            self.llm_handler = SimpleLLMHandler(model_name="gpt-4o-mini")
            if self.debug: logger.debug("Using OpenAI LLM")

    def run(self, limit: int = 50):
        if not self.debug:
            print(f"Starting Attribute Decomposition (Dry Run: {self.dry_run}, Limit: {limit})...")
            # Silence other loggers if not debug
            logging.getLogger().setLevel(logging.WARNING)
        else:
            logger.info(f"Starting Attribute Decomposition (Dry Run: {self.dry_run}, Limit: {limit})...")

        batch_size = 10
        total_processed = 0
        
        # Progress bar configuration
        pbar = None
        if not self.debug:
            pbar = tqdm(total=limit, desc="Decomposing", unit="attr", file=sys.stdout)

        try:
            while total_processed < limit:
                # Dynamically adjust batch size
                current_batch_limit = min(batch_size, limit - total_processed)
                if current_batch_limit <= 0:
                    break
                
                # If dry_run, skip processed items (as they aren't marked in DB)
                # If execute, skip 0 (as processed items are filtered out by WHERE clause)
                current_skip = total_processed if self.dry_run else 0
                    
                candidates = self._find_candidates(current_batch_limit, skip=current_skip)
                
                if not candidates:
                    if self.debug: logger.info("No more candidates found matching criteria.")
                    break
                
                if self.debug:
                    logger.debug(f"Fetched batch of {len(candidates)} candidates.")

                for record in candidates:
                    try:
                        self._process_single_candidate(record)
                    except Exception as e:
                        logger.error(f"Error processing candidate: {e}")
                    
                    if pbar:
                        pbar.update(1)
                
                total_processed += len(candidates)
                
        except KeyboardInterrupt:
            if not self.debug: print("\nInterrupted by user.")
        finally:
            if pbar: pbar.close()
            self.connector.close()
            if not self.debug:
                print(f"\nCompleted. Total processed: {total_processed}")

    def _find_candidates(self, limit: int, skip: int = 0) -> List[Dict]:
        query = """
        MATCH (p:ParentProduct)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WHERE toLower(a.attribute_name) IN $generic_keys
        AND size(a.attribute_value) > 50
        AND a.source <> 'derived'
        AND (a.processed_for_decomposition IS NULL OR a.processed_for_decomposition = false)
        RETURN p.parent_asin as parent_asin, a, elementId(a) as attr_id
        SKIP $skip
        LIMIT $limit
        """
        params = {"generic_keys": list(GENERIC_KEYS), "limit": limit, "skip": skip}
        
        if not self.connector.is_connected():
            self.connector.connect()

        with self.connector.session() as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def _process_single_candidate(self, record: Dict):
        attr_node = record['a']
        parent_asin = record['parent_asin']
        attr_id = record['attr_id']
        text = attr_node['attribute_value']
        
        if self.debug:
            logger.debug(f"Processing ({parent_asin}): {text[:50]}...")
        
        # Extract features
        extracted = self._extract_features(text)
        
        # Create derived attributes (if any) AND mark original as processed
        self._create_derived_and_mark(parent_asin, attr_id, extracted)

    def _extract_features(self, text: str) -> List[Dict[str, str]]:
        prompt = [
            {"role": "system", "content": "You are a precise data extraction assistant that outputs ONLY valid JSON. No markdown, no explanations."},
            {"role": "user", "content": f"""
            Extract specific, atomic product features from the following text.
            Return a purely JSON list of objects with 'key' and 'value'.
            
            Example format:
            [
                {{"key": "Connectivity", "value": "Bluetooth 5.0"}}, 
                {{"key": "Battery", "value": "20 hours"}}
            ]
            
            Text to process:
            "{text}"
            """}
        ]
        
        try:
            response = self.llm_handler.submit_raw(prompt)
            clean_resp = response.strip()
            
            if "```" in clean_resp:
                clean_resp = clean_resp.replace("```json", "").replace("```", "")
            
            start_idx = clean_resp.find("[")
            end_idx = clean_resp.rfind("]")
            
            if start_idx != -1 and end_idx != -1:
                 clean_resp = clean_resp[start_idx:end_idx+1]
            else:
                if self.debug: logger.warning(f"No JSON array found in response.")
                return []

            data = json.loads(clean_resp)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            if self.debug: logger.warning(f"JSON Decode Error for text: {text[:20]}...")
        except Exception as e:
            logger.error(f"LLM Extraction failed: {e}")
        return []

    def _create_derived_and_mark(self, parent_asin: str, original_attr_id: str, features: List[Dict]):
        if self.debug and features:
            logger.debug(f"  Extracted {len(features)} attributes.")
            
        if self.dry_run:
            if self.debug:
                for f in features:
                    norm = AttributeNormalizer.normalize(f['value'], f['key'])
                    logger.debug(f"    [DRY RUN] - {f['key']}: {f['value']} -> {norm}")
            return

        if not self.connector.is_connected():
            self.connector.connect()

        with self.connector.session() as session:
            # 1. Create new attributes if any
            if features:
                create_query = """
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
                for f in features:
                    key = f['key'].lower().strip()
                    val = f['value']
                    norm = AttributeNormalizer.normalize(val, key)
                    session.run(create_query, {
                        "parent_asin": parent_asin,
                        "key": key,
                        "value": val,
                        "norm_value": norm
                    })
            
            # 2. Mark original as processed (ALWAYS, even if 0 features extracted, to avoid loop)
            mark_query = """
            MATCH (a:Attribute)
            WHERE elementId(a) = $attr_id
            SET a.processed_for_decomposition = true
            """
            session.run(mark_query, {"attr_id": original_attr_id})
            if self.debug: logger.debug(f"  Marked attribute {original_attr_id} as processed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True, help="Don't write to DB (default)")
    parser.add_argument("--execute", action="store_false", dest="dry_run", help="Write changes to DB")
    parser.add_argument("--local", action="store_true", help="Use local Ollama (Llama 3.1) instead of OpenAI")
    parser.add_argument("--debug", action="store_true", help="Show detailed logs instead of progress bar")
    parser.add_argument("--limit", type=int, default=10, help="Max attributes to process")
    args = parser.parse_args()
    
    decomposer = AttributeDecomposer(
        dry_run=args.dry_run, 
        use_local_llm=args.local,
        debug=args.debug
    )
    decomposer.run(limit=args.limit)
