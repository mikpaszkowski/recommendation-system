"""Simple test script for Neo4j connector."""

import sys
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graphrag.knowledge_graph.neo4j_connector import Neo4jConnector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_connection():
    """Test basic connection to Neo4j."""
    logger.info("Testing Neo4j connection...")
    
    try:
        with Neo4jConnector() as connector:
            # Test 1: Verify connection
            logger.info("✓ Connection established")
            
            # Test 2: Verify connectivity
            if connector.verify_connection():
                logger.info("✓ Connection verified")
            else:
                logger.error("✗ Connection verification failed")
                return False
            
            # Test 3: Get database info
            db_info = connector.get_database_info()
            if db_info:
                logger.info(f"✓ Database info retrieved: {db_info.get('name', 'Unknown')}")
            
            # Test 4: Execute simple query
            result = connector.execute_query(
                "RETURN 'Connection test successful!' as message, "
                "datetime() as timestamp"
            )
            if result:
                logger.info(f"✓ Query executed: {result[0]['message']}")
            
            # Test 5: Count nodes
            result = connector.execute_query("MATCH (n) RETURN count(n) as count")
            node_count = result[0]['count']
            logger.info(f"✓ Database contains {node_count} nodes")
            
            logger.info("\n" + "="*60)
            logger.info("All tests passed! Neo4j connector is working correctly.")
            logger.info("="*60)
            return True
            
    except ValueError as e:
        logger.error(f"✗ Configuration error: {e}")
        logger.info("\nPlease ensure you have:")
        logger.info("1. Created a .env file in the project root")
        logger.info("2. Set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD")
        return False
    except Exception as e:
        logger.error(f"✗ Connection test failed: {e}")
        logger.info("\nPlease ensure:")
        logger.info("1. Neo4j is running (try: docker ps)")
        logger.info("2. Your .env file has correct credentials")
        logger.info("3. The Neo4j port (7687) is accessible")
        return False


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)

