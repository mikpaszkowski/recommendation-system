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

class BackfillService:
    def __init__(self):
        self.connector = Neo4jConnector()
        self.embed_svc = EmbeddingService()
        self.connector.connect()

    def backfill_all(self):
        self.backfill_attributes()
        self.backfill_brands()
        self.backfill_categories()
        self.backfill_products()

    def _process_batch(self, label, fetch_query, text_generator):
        logger.info(f"Processing {label}...")
        
        # 1. Fetch IDs
        query_ids = f"MATCH (n:{label}) WHERE n.embedding IS NULL RETURN elementId(n) as id"
        with self.connector.session() as session:
            result = session.run(query_ids)
            all_ids = [record["id"] for record in result]
        
        total = len(all_ids)
        logger.info(f"Found {total} {label} nodes needing embeddings.")
        
        if total == 0:
            return

        # 2. Process in batches
        for i in tqdm(range(0, total, BATCH_SIZE), desc=f"Embedding {label}"):
            batch_ids = all_ids[i:i+BATCH_SIZE]
            
            with self.connector.session() as session:
                rows = list(session.run(fetch_query, ids=batch_ids))
            
            texts_to_embed = []
            valid_ids = []

            for row in rows:
                text = text_generator(row)
                if text:
                    texts_to_embed.append(text)
                    valid_ids.append(row['id'])

            if not texts_to_embed:
                continue

            # Generate Embeddings
            try:
                embeddings = self.embed_svc.embed_documents(texts_to_embed)
            except Exception as e:
                logger.error(f"Failed to embed batch {i}: {e}")
                continue

            # Write Back
            update_data = [{"id": valid_ids[j], "embedding": embeddings[j]} for j in range(len(valid_ids))]

            query_update = f"""
            UNWIND $updates AS row
            MATCH (n:{label})
            WHERE elementId(n) = row.id
            SET n.embedding = row.embedding
            """
            
            with self.connector.session() as session:
                session.run(query_update, updates=update_data)

    def backfill_attributes(self):
        query_fetch = """
        MATCH (a:Attribute)
        WHERE elementId(a) IN $ids
        RETURN elementId(a) as id, a.attribute_name as name, a.attribute_value as val
        """
        
        def generator(row):
            name = row['name'] or ""
            raw_val = row['val'] or ""
            norm_val = AttributeNormalizer.normalize(raw_val, name)
            clean_name = name.lower().strip()
            
            if clean_name in GENERIC_KEYS:
                return norm_val
            return f"{name}: {norm_val}"

        self._process_batch("Attribute", query_fetch, generator)

    def backfill_brands(self):
        # Assuming Brand nodes have 'name' and optionally 'domain_description'
        # If domain_description is missing, we use a generic placeholder or just the name
        query_fetch = """
        MATCH (b:Brand)
        WHERE elementId(b) IN $ids
        RETURN elementId(b) as id, b.name as name, b.domain_description as domain
        """

        def generator(row):
            name = row['name']
            domain = row['domain'] or "consumer electronics" # Default fallback
            return f"Brand: {name}. Domain: {domain}"

        self._process_batch("Brand", query_fetch, generator)

    def backfill_categories(self):
        query_fetch = """
        MATCH (c:Category)
        WHERE elementId(c) IN $ids
        OPTIONAL MATCH (c)-[:CHILD_OF]->(p:Category)
        RETURN elementId(c) as id, c.name as name, p.name as parent_name
        """

        def generator(row):
            name = row['name']
            parent = row['parent_name'] or "Root"
            return f"Category: {name}. Parent: {parent}"

        self._process_batch("Category", query_fetch, generator)

    def backfill_products(self):
        # For ParentProduct, we need to aggregate features.
        # This is more complex than a simple row return.
        # We'll do a subquery or just fetch connected attributes.
        
        query_fetch = """
        MATCH (p:ParentProduct)
        WHERE elementId(p) IN $ids
        OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, c, collect(a.attribute_name + ': ' + a.normalized_value) as features
        RETURN elementId(p) as id, p.title as title, p.description as description, c.name as category, features
        """

        def generator(row):
            title = row['title'] or ""
            category = row['category'] or "Unknown"
            description = row['description'] or ""
            features = ", ".join(row['features'][:5]) # Limit features to top 5 to avoid token limit issues
            
            return f"Product: {title}. Category: {category}. Features: {features}. Description: {description}"

        self._process_batch("ParentProduct", query_fetch, generator)

if __name__ == "__main__":
    service = BackfillService()
    service.backfill_all()
