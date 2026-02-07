import logging
import os
import sys
from typing import Dict, Any

# Ensure we can import from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    from src.knowledge_graph.graphdb.attribute_normalizer import AttributeNormalizer
except ImportError:
    # Fallback for different path structures
    from neo4j_connector import Neo4jConnector
    from attribute_normalizer import AttributeNormalizer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_normalization_dry_run():
    logger.info("Starting Attribute Normalization Dry Run...")
    
    query = """
    MATCH (a:Attribute)
    WHERE a.normalized_value IS NOT NULL
    RETURN a
    LIMIT 10
    """
    
    with Neo4jConnector() as connector:
        results = connector.execute_read_transaction(query)
    
    if not results:
        logger.warning("No Attribute nodes found to test.")
        return

    logger.info(f"Fetched {len(results)} attributes. Checking normalization logic...")
    
    for record in results:
        node = record['a']
        props = dict(node.items()) if hasattr(node, "items") else {}
        
        raw_val = props.get('attribute_value', '')
        current_norm = props.get('normalized_value', '')
        attr_name = props.get('attribute_name', '')
        
        # Run our new Pydantic logic
        new_norm = AttributeNormalizer.normalize(raw_val, attr_name)
        
        # Compare
        if new_norm != current_norm and new_norm != raw_val:
            logger.info(f"--- Attribute: {attr_name} ---")
            logger.info(f"Original:   '{raw_val}'")
            logger.info(f"Current DB: '{current_norm}'")
            logger.info(f"PROPOSED:   '{new_norm}'")
            if new_norm != current_norm:
                logger.info(">>> CHANGE DETECTED <<<")
            else:
                logger.info("(No change vs current DB)")
        else:
            logger.debug(f"Skipping '{attr_name}': '{raw_val}' -> '{new_norm}' (Stable)")

    logger.info("Dry run complete.")

if __name__ == "__main__":
    test_normalization_dry_run()
