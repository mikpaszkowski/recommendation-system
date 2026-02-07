import logging
import os
import sys
from tqdm import tqdm

# Ensure imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    from src.knowledge_graph.graphdb.attribute_normalizer import AttributeNormalizer
    from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
except ImportError:
    from neo4j_connector import Neo4jConnector
    from attribute_normalizer import AttributeNormalizer
    from embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GENERIC_KEYS = {"feature", "bullet_point", "product_feature", "about_this_item"}
BATCH_SIZE = 100

def backfill_attribute_embeddings():
    logger.info("Starting Attribute Embedding Backfill...")
    connector = Neo4jConnector()
    embed_svc = EmbeddingService()

    logger.info("Connecting to Neo4j...")
    connector.connect()

    # 1. Fetch all attributes
    query_count = "MATCH (a:Attribute) RETURN count(a) as cnt"
    with connector.session() as session:
        count = session.run(query_count).single()["cnt"]
    
    logger.info(f"Found {count} attributes to process.")

    # 2. Iterate in batches
    # We use skip/limit or ID based pagination. Using ID-based is safer but skip/limit is easier for this scale if not mutating the sort order.
    # Actually, let's fetch IDs first to be robust.
    query_ids = "MATCH (a:Attribute) RETURN elementId(a) as id"
    with connector.session() as session:
        # This might be large, but for <1M nodes it's fine.
        result = session.run(query_ids)
        all_ids = [record["id"] for record in result]

    total = len(all_ids)
    
    # Process in batches
    for i in tqdm(range(0, total, BATCH_SIZE), desc="Embedding Attributes"):
        batch_ids = all_ids[i:i+BATCH_SIZE]
        
        # Fetch batch data
        query_fetch = """
        MATCH (a:Attribute)
        WHERE elementId(a) IN $ids
        RETURN elementId(a) as id, a.attribute_name as name, a.attribute_value as val, a.normalized_value as norm
        """
        
        texts_to_embed = []
        node_updates = []

        with connector.session() as session:
            rows = list(session.run(query_fetch, ids=batch_ids))
        
        for row in rows:
            attr_id = row['id']
            name = row['name'] or ""
            raw_val = row['val'] or ""
            # normalizing just for the embedding text quality
            norm_val = AttributeNormalizer.normalize(raw_val, name)
            
            # Smart String Construction
            clean_name = name.lower().strip()
            if clean_name in GENERIC_KEYS:
                # Use only value
                text = norm_val
            else:
                # Use "Name: Value"
                text = f"{name}: {norm_val}"
            
            texts_to_embed.append(text)
            node_updates.append({"id": attr_id, "text": text})

        # Generate Embeddings (Batch)
        try:
            embeddings = embed_svc.embed_documents(texts_to_embed)
        except Exception as e:
            logger.error(f"Failed to embed batch {i}: {e}")
            continue

        # Write Back (Batch)
        # Note: We can pass list of dicts {id, embedding}
        update_data = []
        for j, node_info in enumerate(node_updates):
            update_data.append({
                "id": node_info["id"],
                "embedding": embeddings[j]
            })

        query_update = """
        UNWIND $updates AS row
        MATCH (a:Attribute)
        WHERE elementId(a) = row.id
        SET a.embedding = row.embedding
        """
        
        with connector.session() as session:
            session.run(query_update, updates=update_data)

    logger.info("Embedding generation complete.")

    # 3. Create Index
    logger.info("Creating Vector Index 'attribute_embedding_index'...")
    index_query = """
    CALL db.index.vector.createNodeIndex(
      'attribute_embedding_index',
      'Attribute',
      'embedding',
      384,
      'cosine'
    )
    """
    try:
        with connector.session() as session:
            # Check if index exists first
            check = "SHOW INDEXES WHERE name = 'attribute_embedding_index'"
            if session.run(check).peek() is None:
                session.run(index_query)
                logger.info("Index created successfully.")
            else:
                logger.info("Index already exists.")
    except Exception as e:
        logger.error(f"Failed to create index: {e}")

if __name__ == "__main__":
    backfill_attribute_embeddings()
