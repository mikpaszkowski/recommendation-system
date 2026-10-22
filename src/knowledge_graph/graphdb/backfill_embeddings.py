"""
Online embedding backfill for the v1 graph (BackfillService).

The text builders delegate to `embedding_templates` (Technical Specification Graph Rebuild FR-032):
blank products (no title, description or features) and blank reviews (no title and body) are never
embedded, and the product fetch orders attributes before `collect` so the top-5 attribute text is
deterministic. Graph v2 embeds through `scripts/graph_ingestion/post_import_v2.py embed`.
"""
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
    from src.knowledge_graph.graphdb.embedding_templates import (
        GENERIC_KEYS,
        attribute_text_v1,
        brand_text_v1,
        category_parent_text_legacy,
        product_text_v1,
        review_text_v1,
    )
except ImportError:
    from neo4j_connector import Neo4jConnector
    from attribute_normalizer import AttributeNormalizer
    from embedding_service import EmbeddingService
    from embedding_templates import (
        GENERIC_KEYS,
        attribute_text_v1,
        brand_text_v1,
        category_parent_text_legacy,
        product_text_v1,
        review_text_v1,
    )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 100

class BackfillService:
    def __init__(self):
        self.connector = Neo4jConnector()
        self.embed_svc = EmbeddingService()
        self.connector.connect()

    def backfill_reviews(self):
        query_fetch = """
        MATCH (r:Review)
        WHERE elementId(r) IN $ids
        RETURN elementId(r) as id, r.review_title as title, r.review_body as body
        """

        def generator(row):
            # None for a blank review (skip-empty); otherwise the v1 text cut at 800 characters
            return review_text_v1(row['title'], row['body'])

        self._process_batch("Review", query_fetch, generator)

    def backfill_all(self):
        self.backfill_attributes()
        self.backfill_brands()
        self.backfill_categories()
        self.backfill_products()
        self.backfill_reviews()

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
        skipped = 0
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
                else:
                    skipped += 1

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

        if skipped:
            logger.info(f"Skipped {skipped} {label} nodes with no embeddable text (skip-empty).")

    def backfill_attributes(self):
        query_fetch = """
        MATCH (a:Attribute)
        WHERE elementId(a) IN $ids
        RETURN elementId(a) as id, a.attribute_name as name, a.attribute_value as val
        """
        
        def generator(row):
            return attribute_text_v1(row['name'] or "", row['val'] or "")

        self._process_batch("Attribute", query_fetch, generator)

    def backfill_brands(self):
        # Assuming Brand nodes have 'name' and optionally 'domain_description'
        # If domain_description is missing, we use a generic placeholder or just the name
        query_fetch = """
        MATCH (b:Brand)
        WHERE elementId(b) IN $ids
        RETURN elementId(b) as id, b.name as name
        """

        def generator(row):
            # Default domain "consumer electronics" since domain_description doesn't exist
            return brand_text_v1(row['name'])

        self._process_batch("Brand", query_fetch, generator)

    def backfill_categories(self):
        query_fetch = """
        MATCH (c:Category)
        WHERE elementId(c) IN $ids
        OPTIONAL MATCH (c)-[:CHILD_OF]->(p:Category)
        RETURN elementId(c) as id, c.name as name, p.name as parent_name
        """

        def generator(row):
            return category_parent_text_legacy(row['name'], row['parent_name'])

        self._process_batch("Category", query_fetch, generator)

    def backfill_products(self):
        # For ParentProduct, we need to aggregate features.
        # This is more complex than a simple row return.
        # We'll do a subquery or just fetch connected attributes.
        
        query_fetch = """
        MATCH (p:ParentProduct)
        WHERE elementId(p) IN $ids
        OPTIONAL MATCH (p)-[:BELONGS_TO_CATEGORY]->(c:Category)
        OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute)
        WITH p, c, a ORDER BY a.attribute_name, a.attribute_value
        WITH p, c, collect(a.attribute_name + ': ' + coalesce(a.attribute_value, a.normalized_value, '')) as features
        RETURN elementId(p) as id, p.title as title, p.description as description, p.features as listing_features,
               c.name as category, features
        """

        def generator(row):
            # None when title, description and listing features are all blank (skip-empty); the v1 text
            # keeps the top 5 attribute pairs, now in a deterministic order
            return product_text_v1(
                row['title'], row['category'], row['features'] or [], row['description'], row['listing_features'],
            )

        self._process_batch("ParentProduct", query_fetch, generator)

if __name__ == "__main__":
    service = BackfillService()
    service.backfill_all()
