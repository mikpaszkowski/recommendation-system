import logging
import os
import sys
from tqdm import tqdm

# Ensure imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    from src.knowledge_graph.graphdb.embedding_service import EmbeddingService
except ImportError:
    from neo4j_connector import Neo4jConnector
    from embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 100

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
        
        query_fetch = """
        MATCH (c:Category)
        WHERE elementId(c) IN $ids
        OPTIONAL MATCH (p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c)
        WITH c, collect(p.title)[..5] as sample_products
        RETURN elementId(c) as id, c.path as path, c.name as name, sample_products
        """
        
        with connector.session() as session:
            rows = list(session.run(query_fetch, ids=batch_ids))
        
        texts_to_embed = []
        update_data = [] # {id, embedding} map

        # Prepare texts
        temp_rows = []
        for row in rows:
            cat_id = row['id']
            name = row['name'] or ""
            path_list = row['path'] or []
            products = row['sample_products'] or []
            
            # 1. Leaf Name (Priority)
            leaf_part = f"Category: {name}"
            
            # 2. Hierarchy Context (Parents)
            # path usually includes self at the end, so take everything except the last
            if len(path_list) > 1:
                parents = path_list[:-1]
                # Reverse order? "Parent, Grandparent" vs "Grandparent, Parent"
                # MiniLM handles natural language well. "Context: Parent, Grandparent" is fine.
                context_str = ", ".join(parents)
                context_part = f"Context: {context_str}"
            else:
                context_part = "Context: Root Category"

            # 3. Product Augmentation
            if products:
                # Clean product titles (sometimes they are super long) -> take first 10 words maybe?
                # or just join them. 5 products can be long. Let's truncate title to 10 words.
                clean_prods = []
                for p in products:
                    if p:
                        clean_prods.append(" ".join(p.split()[:10]))
                
                prod_str = ", ".join(clean_prods)
                product_part = f"Related items: {prod_str}"
            else:
                product_part = "Related items: None"

            # Combine: "Category: Subwoofers. Context: Car Audio, Electronics. Related items: JBL Bass, Pioneer..."
            full_text = f"{leaf_part}. {context_part}. {product_part}."
            
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

    # 3. Create Index
    logger.info("Creating Vector Index 'category_embedding_index'...")
    # Try Cypher syntax first, fall back to procedure if fails (handled by try/except usually but let's use the procedure which is 5.11+ compatible)
    # Actually, CREATE INDEX is standard. CREATE VECTOR INDEX is 5.15+.
    # Let's try the db.index.vector.createNodeIndex procedure which works on 5.11+
    
    index_query = """
    CALL db.index.vector.createNodeIndex(
      'category_embedding_index',
      'Category',
      'embedding',
      384,
      'cosine'
    )
    """
    try:
        with connector.session() as session:
            # Check if index exists first to avoid error
            check = "SHOW INDEXES WHERE name = 'category_embedding_index'"
            if session.run(check).peek() is None:
                session.run(index_query)
                logger.info("Index created successfully.")
            else:
                logger.info("Index already exists.")
    except Exception as e:
        logger.error(f"Failed to create index: {e}")

if __name__ == "__main__":
    backfill_category_embeddings()
