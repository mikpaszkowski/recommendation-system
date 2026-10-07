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

    INDEX_SPECS = [
        ("product_embedding_index", "ParentProduct", "embedding", 384, "cosine"),
        ("brand_embedding_index", "Brand", "embedding", 384, "cosine"),
        ("category_embedding_index", "Category", "embedding", 384, "cosine"),
        ("attribute_embedding_index", "Attribute", "embedding", 384, "cosine"),
        ("review_embedding_index", "Review", "embedding", 384, "cosine"),
    ]

    with connector.session() as session:
        for idx_name, label, prop, dims, sim in INDEX_SPECS:
            try:
                check = session.run("SHOW INDEXES YIELD name WHERE name = $name RETURN count(*) > 0 as exists", name=idx_name).single()
                if check and check["exists"]:
                    logger.info(f"Vector index '{idx_name}' already exists and is active.")
                    continue

                logger.info(f"Creating vector index '{idx_name}' on :{label}({prop})...")
                try:
                    # Neo4j 5.14 procedure syntax
                    session.run(
                        "CALL db.index.vector.createNodeIndex($name, $label, $prop, $dims, $sim)",
                        name=idx_name, label=label, prop=prop, dims=dims, sim=sim
                    )
                    logger.info(f"Successfully created '{idx_name}' via procedure.")
                except Exception:
                    # Neo4j >= 5.15 DDL syntax fallback
                    session.run(f"""
                        CREATE VECTOR INDEX {idx_name} IF NOT EXISTS
                        FOR (n:{label}) ON (n.{prop})
                        OPTIONS {{indexConfig: {{`vector.dimensions`: {dims}, `vector.similarity_function`: '{sim}'}}}}
                    """)
                    logger.info(f"Successfully created '{idx_name}' via DDL.")
            except Exception as e:
                logger.error(f"Error checking/creating index '{idx_name}': {e}")

    logger.info("Index setup complete.")

if __name__ == "__main__":
    setup_indexes()
