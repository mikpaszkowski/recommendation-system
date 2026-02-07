import logging
import os
import sys

# Ensure imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
except ImportError:
    from neo4j_connector import Neo4jConnector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_category_path_dry_run():
    logger.info("Starting Category Path Construction Dry Run...")
    
    # Query to fetch categories and their hierarchical paths
    # We assume 'path' property exists on Category nodes (as ingest script creates it)
    # Or we can traverse relationships. The ingest script says it stores `path` property.
    query = """
    MATCH (c:Category)
    WHERE c.path IS NOT NULL
    RETURN c
    LIMIT 10
    """
    
    with Neo4jConnector() as connector:
        results = connector.execute_read_transaction(query)

    if not results:
        logger.warning("No Category nodes with 'path' property found.")
        return

    for record in results:
        node = record['c']
        name = node.get('name', 'Unknown')
        path_list = node.get('path', [])
        
        # Logic to construct the embedding text
        # " > ".join(path)
        full_context = " > ".join(path_list)
        
        logger.info(f"Category: '{name}'")
        logger.info(f"  -> Path: {path_list}")
        logger.info(f"  -> Embedding String: '{full_context}'")
        
        if len(path_list) < 2:
            logger.info("  (Top level or orphan)")
        elif name != path_list[-1]:
             logger.warning(f"  [MISMATCH] Node name '{name}' != last path element '{path_list[-1]}'")
        
    logger.info("Dry run complete.")

if __name__ == "__main__":
    test_category_path_dry_run()
