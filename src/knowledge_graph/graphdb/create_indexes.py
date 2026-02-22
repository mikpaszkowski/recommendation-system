import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
except ImportError:
    from neo4j_connector import Neo4jConnector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_indexes():
    connector = Neo4jConnector()
    connector.connect()

    cmds = [
        """
        CALL db.index.vector.createNodeIndex(
          'attribute_embedding_index',
          'Attribute',
          'embedding',
          384,
          'cosine'
        )
        """,
        """
        CALL db.index.vector.createNodeIndex(
          'category_embedding_index',
          'Category',
          'embedding',
          384,
          'cosine'
        )
        """
    ]
    
    with connector.session() as session:
        for cmd in cmds:
            try:
                # Check exist
                name = cmd.split("'")[1]
                check = f"SHOW INDEXES WHERE name = '{name}'"
                if session.run(check).peek() is None:
                    session.run(cmd)
                    logger.info(f"Created index {name}")
                else:
                    logger.info(f"Index {name} already exists")
            except Exception as e:
                logger.error(f"Failed to create index: {e}")

if __name__ == "__main__":
    create_indexes()
