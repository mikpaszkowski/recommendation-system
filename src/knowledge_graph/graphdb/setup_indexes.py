import logging
import os
import sys
import re

# Ensure imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
except ImportError:
    from neo4j_connector import Neo4jConnector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_indexes():
    connector = Neo4jConnector()
    logger.info("Connecting to Neo4j...")
    connector.connect()

    cypher_file = os.path.join(os.path.dirname(__file__), "create_vector_indexes.cypher")
    
    if not os.path.exists(cypher_file):
        logger.error(f"Cypher file not found at {cypher_file}")
        return

    logger.info(f"Reading Cypher script from {cypher_file}...")
    with open(cypher_file, "r") as f:
        content = f.read()

    # robust parsing: find all CALL ... ;
    # We use regex to extract the full command ending with ;
    # This ignores comments because . matches anything but newline (usually) 
    # but we want to capture multiline commands if needed.
    # Actually, simplistic splitting by ; is fine if we strip comments *beforehand*.
    
    # 1. Remove single line comments
    lines = content.split('\n')
    cleaned_lines = [line for line in lines if not line.strip().startswith("//")]
    cleaned_content = "\n".join(cleaned_lines)
    
    # 2. Split by semicolon
    commands = [cmd.strip() for cmd in cleaned_content.split(";") if cmd.strip()]
    
    logger.info(f"Found {len(commands)} commands to execute.")

    with connector.session() as session:
        for i, cmd in enumerate(commands):
            logger.info(f"Executing command {i+1}/{len(commands)}...")
            try:
                # Basic check if index exists to simulate IF NOT EXISTS behavior for procedures
                match = re.search(r"createNodeIndex\('([^']+)'", cmd)
                if match:
                    idx_name = match.group(1)
                    check = f"SHOW INDEXES WHERE name = '{idx_name}'"
                    if session.run(check).peek() is not None:
                        logger.info(f"Index '{idx_name}' already exists. Skipping.")
                        continue
                
                session.run(cmd)
                logger.info("Success.")
            except Exception as e:
                if "already exists" in str(e):
                    logger.info("Index already exists (caught exception).")
                else:
                    logger.error(f"Error executing command: {e}")

    logger.info("Index setup complete.")

if __name__ == "__main__":
    setup_indexes()
