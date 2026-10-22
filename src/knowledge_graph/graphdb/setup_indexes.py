import logging
import os
import sys
import re
from typing import Dict, List, Optional, Tuple

# Ensure imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
except ImportError:
    from neo4j_connector import Neo4jConnector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Vector index specs: (name, label, property, dimensions, similarity). Module level so the graph v2
# post-import step (scripts/graph_ingestion/post_import_v2.py) can reuse them.
INDEX_SPECS: List[Tuple[str, str, str, int, str]] = [
    ("product_embedding_index", "ParentProduct", "embedding", 384, "cosine"),
    ("brand_embedding_index", "Brand", "embedding", 384, "cosine"),
    ("category_embedding_index", "Category", "embedding", 384, "cosine"),
    ("attribute_embedding_index", "Attribute", "embedding", 384, "cosine"),
    ("review_embedding_index", "Review", "embedding", 384, "cosine"),
]


def setup_indexes(connector: Optional[Neo4jConnector] = None, allow_ddl_fallback: bool = True) -> Dict[str, str]:
    """
    Creates the vector indexes in INDEX_SPECS with the Neo4j 5.14 procedure
    `db.index.vector.createNodeIndex`. If the procedure fails and `allow_ddl_fallback` is True, the
    Neo4j >= 5.15 `CREATE VECTOR INDEX` DDL is tried; callers on 5.14 pass False so no DDL is ever
    sent (D-4). An injected connector is reused (connected only if needed).

    Returns index name -> "exists" | "created" | "created_ddl" | "failed: <error>".
    """
    connector = connector or Neo4jConnector()
    if not connector.is_connected():
        logger.info("Connecting to Neo4j...")
        connector.connect()

    cypher_file = os.path.join(os.path.dirname(__file__), "create_vector_indexes.cypher")
    
    if not os.path.exists(cypher_file):
        logger.error(f"Cypher file not found at {cypher_file}")
        return {name: "failed: create_vector_indexes.cypher missing" for name, *_ in INDEX_SPECS}

    logger.info(f"Reading Cypher script from {cypher_file}...")
    with open(cypher_file, "r") as f:
        content = f.read()

    outcomes: Dict[str, str] = {}
    with connector.session() as session:
        for idx_name, label, prop, dims, sim in INDEX_SPECS:
            try:
                check = session.run("SHOW INDEXES YIELD name WHERE name = $name RETURN count(*) > 0 as exists", name=idx_name).single()
                if check and check["exists"]:
                    logger.info(f"Vector index '{idx_name}' already exists and is active.")
                    outcomes[idx_name] = "exists"
                    continue

                logger.info(f"Creating vector index '{idx_name}' on :{label}({prop})...")
                try:
                    # Neo4j 5.14 procedure syntax. consume() so a procedure error surfaces here and is
                    # attributed to this index, not raised by the next statement or at session close.
                    session.run(
                        "CALL db.index.vector.createNodeIndex($name, $label, $prop, $dims, $sim)",
                        name=idx_name, label=label, prop=prop, dims=dims, sim=sim
                    ).consume()
                    logger.info(f"Successfully created '{idx_name}' via procedure.")
                    outcomes[idx_name] = "created"
                except Exception as proc_error:
                    if not allow_ddl_fallback:
                        raise
                    logger.warning(f"Procedure failed for '{idx_name}' ({proc_error}); trying the >= 5.15 DDL.")
                    # Neo4j >= 5.15 DDL syntax fallback
                    session.run(f"""
                        CREATE VECTOR INDEX {idx_name} IF NOT EXISTS
                        FOR (n:{label}) ON (n.{prop})
                        OPTIONS {{indexConfig: {{`vector.dimensions`: {dims}, `vector.similarity_function`: '{sim}'}}}}
                    """).consume()
                    logger.info(f"Successfully created '{idx_name}' via DDL.")
                    outcomes[idx_name] = "created_ddl"
            except Exception as e:
                logger.error(f"Error checking/creating index '{idx_name}': {e}")
                outcomes[idx_name] = f"failed: {e}"

    logger.info("Index setup complete.")
    return outcomes

if __name__ == "__main__":
    setup_indexes()
