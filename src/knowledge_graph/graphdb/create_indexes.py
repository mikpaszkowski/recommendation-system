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
        CREATE VECTOR INDEX attribute_embedding_index IF NOT EXISTS
        FOR (n:Attribute) ON (n.embedding)
        OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}
        """,
        """
        CREATE VECTOR INDEX category_embedding_index IF NOT EXISTS
        FOR (n:Category) ON (n.embedding)
        OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}
        """
    ]
    
    with connector.session() as session:
        for cmd in cmds:
            try:
                session.run(cmd)
                logger.info("Index created or already exists")
            except Exception as e:
                logger.error(f"Failed to create index: {e}")

if __name__ == "__main__":
    create_indexes()
