import logging
import os
import sys
from tqdm import tqdm

# Ensure imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
    from src.knowledge_graph.graphdb.embedding_templates import category_text_v1
except ImportError:
    from neo4j_connector import Neo4jConnector
    from embedding_service import EmbeddingService
    from embedding_templates import category_text_v1

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 100

# Sample titles are taken from titled products in a fixed order (review_count DESC, parent_asin ASC)
# so re-embedding identical data gives identical texts (Technical Specification Graph Rebuild FR-033).
CATEGORY_FETCH_QUERY = """
        MATCH (c:Category)
        WHERE elementId(c) IN $ids
        OPTIONAL MATCH (p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c)
        WHERE p.title IS NOT NULL AND trim(p.title) <> ''
        WITH c, p ORDER BY coalesce(p.review_count, 0) DESC, p.parent_asin ASC
        WITH c, collect(p.title)[..5] AS sample_products
        RETURN elementId(c) as id, c.path as path, c.name as name, sample_products
        """

def backfill_category_embeddings():
    logger.info("Starting Category Embedding Backfill...")
    connector = Neo4jConnector()
    embed_svc = EmbeddingService()

    # Ensure connected
    connector.connect()
    
    # 1. Fetch all category IDs
    query_ids = "MATCH (c:Category) RETURN elementId(c) as id"
    with connector.session() as session:
        result = session.run(query_ids)
        all_ids = [record["id"] for record in result]
    
    total = len(all_ids)
    logger.info(f"Found {total} categories to process.")

    # 2. Batch Process
    for i in tqdm(range(0, total, BATCH_SIZE), desc="Embedding Categories"):
        batch_ids = all_ids[i:i+BATCH_SIZE]
        
        query_fetch = CATEGORY_FETCH_QUERY
        
        with connector.session() as session:
            rows = list(session.run(query_fetch, ids=batch_ids))
        
        texts_to_embed = []
        update_data = [] # {id, embedding} map

        # Prepare texts
        temp_rows = []
        for row in rows:
            cat_id = row['id']
            # "Category: Subwoofers. Context: Car Audio, Electronics. Related items: JBL Bass, Pioneer..."
            full_text = category_text_v1(row['name'] or "", row['path'] or [], row['sample_products'] or [])
            
            texts_to_embed.append(full_text)
            temp_rows.append(cat_id)

        if not texts_to_embed:
            continue

        # Embed
        try:
            embeddings = embed_svc.embed_documents(texts_to_embed)
        except Exception as e:
            logger.error(f"Failed to embed batch {i}: {e}")
            continue

        # Prepare updates
        for j, cat_id in enumerate(temp_rows):
            update_data.append({
                "id": cat_id,
                "embedding": embeddings[j]
            })

        # Write
        query_update = """
        UNWIND $updates AS row
        MATCH (c:Category)
        WHERE elementId(c) = row.id
        SET c.embedding = row.embedding
        """
        
        with connector.session() as session:
            session.run(query_update, updates=update_data)

    logger.info("Category embeddings generation complete.")

    # 3. Create Index (if not already existing)
    logger.info("Ensuring Vector Index 'category_embedding_index' exists...")
    check_query = "SHOW INDEXES YIELD name WHERE name = 'category_embedding_index' RETURN count(*) > 0 as exists"
    with connector.session() as session:
        try:
            res = session.run(check_query).single()
            if res and res["exists"]:
                logger.info("Vector index 'category_embedding_index' already exists and is active.")
            else:
                # In Neo4j 5.14 Community, use db.index.vector.createNodeIndex procedure
                try:
                    session.run("CALL db.index.vector.createNodeIndex('category_embedding_index', 'Category', 'embedding', 384, 'cosine')")
                    logger.info("Created category_embedding_index successfully via procedure.")
                except Exception:
                    # Fallback for newer Neo4j versions (>= 5.15)
                    session.run("""
                    CREATE VECTOR INDEX category_embedding_index IF NOT EXISTS
                    FOR (n:Category) ON (n.embedding)
                    OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}
                    """)
                    logger.info("Created category_embedding_index successfully via DDL.")
        except Exception as e:
            logger.warning(f"Note on vector index check/creation: {e}")

if __name__ == "__main__":
    backfill_category_embeddings()
