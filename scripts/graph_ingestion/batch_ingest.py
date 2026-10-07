import argparse
import logging
import os
import json
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Ensure the src module is in path if needed
import sys
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

LOGGER = logging.getLogger("kg.batch_ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ROOT_DIR = Path(__file__).resolve().parents[2]
METADATA_CSV = ROOT_DIR / "datasets" / "processed_data" / "processed_metadata.csv"
REVIEWS_CSV = ROOT_DIR / "datasets" / "processed_data" / "processed_reviews.csv"
CHECKPOINT_FILE = Path(__file__).resolve().parent / ".ingest_checkpoint.json"

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    return {"metadata_index": 0, "reviews_index": 0}

def save_checkpoint(state):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(state, f)

def run_ingest(limit, batch_size):
    connector = Neo4jConnector()
    connector.connect()
    checkpoint = load_checkpoint()
    
    # 1. Apply constraints
    LOGGER.info("Applying schema constraints...")
    constraints_queries = [
        "CREATE CONSTRAINT product_id IF NOT EXISTS FOR (p:ParentProduct) REQUIRE p.parent_asin IS UNIQUE",
        "CREATE CONSTRAINT brand_id IF NOT EXISTS FOR (b:Brand) REQUIRE b.name IS UNIQUE",
        "CREATE CONSTRAINT category_id IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT review_id IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE",
        "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE"
    ]
    with connector.session() as session:
        for cq in constraints_queries:
            try:
                session.run(cq)
            except Exception as e:
                if "IndexAlreadyExists" in str(e):
                    LOGGER.warning(f"Constraint/Index already exists, skipping: {cq.split('FOR')[1].split('REQUIRE')[0].strip()}")
                else:
                    LOGGER.error(f"Error applying constraint: {e}")
    
    # 2. Process Metadata in batches
    LOGGER.info(f"Loading metadata from {METADATA_CSV}...")
    meta_start = checkpoint["metadata_index"]
    
    # We use chunksize to process in batches and not load everything into memory
    meta_chunks = pd.read_csv(METADATA_CSV, chunksize=batch_size, skiprows=range(1, meta_start + 1))
    
    current_meta_row = meta_start
    for chunk in meta_chunks:
        if limit > 0 and current_meta_row >= limit:
            break
            
        LOGGER.info(f"Ingesting metadata batch: rows {current_meta_row} to {current_meta_row + len(chunk)}...")
        # Execute UNWIND Cypher query for this metadata chunk
        # Convert chunk to list of dicts, replacing NaNs with None
        records = chunk.where(pd.notnull(chunk), None).to_dict("records")
        
        meta_query = """
        UNWIND $batch AS row
        MERGE (p:ParentProduct {parent_asin: coalesce(row.parent_asin, row.asin)})
        SET p.title = row.title,
            p.price = toFloat(row.price),
            p.avg_rating = toFloat(row.average_rating),
            p.review_count = toInteger(row.rating_number),
            p.description = row.description_text
        
        // Brand logic
        WITH p, row, coalesce(row.store, row.detail_brand) AS brand_name
        CALL {
            WITH p, brand_name
            WITH p, brand_name WHERE brand_name IS NOT NULL AND brand_name <> ''
            MERGE (b:Brand {name: brand_name})
            MERGE (p)-[:HAS_BRAND]->(b)
        }
        
        // Category logic
        WITH p, row
        CALL {
            WITH p, row
            WITH p, row WHERE row.main_category IS NOT NULL AND row.main_category <> ''
            MERGE (c:Category {name: row.main_category})
            MERGE (p)-[:BELONGS_TO_CATEGORY]->(c)
        }
        
        // Attributes logic
        WITH p, row
        UNWIND [
            {name: "Material", val: row.detail_material},
            {name: "Color", val: row.detail_color},
            {name: "Style", val: row.detail_style},
            {name: "Size", val: row.detail_size}
        ] AS attr
        CALL {
            WITH p, attr
            WITH p, attr WHERE attr.val IS NOT NULL AND attr.val <> ''
            MERGE (a:Attribute {attribute_name: attr.name, attribute_value: attr.val})
            MERGE (p)-[:HAS_ATTRIBUTE]->(a)
        }
        """
        
        with connector.session() as session:
            session.run(meta_query, batch=records)
        
        current_meta_row += len(chunk)
        checkpoint["metadata_index"] = current_meta_row
        save_checkpoint(checkpoint)
        LOGGER.info(f"Checkpoint saved: metadata_index = {current_meta_row}")
        
    # 3. Process Reviews in batches
    if REVIEWS_CSV.exists():
        LOGGER.info(f"Loading reviews from {REVIEWS_CSV}...")
        rev_start = checkpoint["reviews_index"]
        rev_chunks = pd.read_csv(REVIEWS_CSV, chunksize=batch_size, skiprows=range(1, rev_start + 1))
        
        current_rev_row = rev_start
        for chunk in rev_chunks:
            if limit > 0 and current_rev_row >= limit:
                break
                
            LOGGER.info(f"Ingesting reviews batch: rows {current_rev_row} to {current_rev_row + len(chunk)}...")
            # Execute UNWIND Cypher query for this reviews chunk
            records = chunk.where(pd.notnull(chunk), None).to_dict("records")
            
            # Since review_id might not exist in CSV, we create one via user_id + asin
            # Or we can just let Cypher create it or hash it in Python
            import hashlib
            for r in records:
                # Basic hash to simulate review_id if not present
                raw_str = f"{r.get('user_id', '')}-{r.get('asin', '')}-{r.get('sort_timestamp', '')}"
                r["review_id"] = hashlib.md5(raw_str.encode("utf-8")).hexdigest()
                
            rev_query = """
            UNWIND $batch AS row
            MERGE (r:Review {review_id: row.review_id})
            SET r.review_title = row.title,
                r.review_body = row.text,
                r.rating = toFloat(row.rating),
                r.verified = row.verified_purchase
            
            // Connect to User
            WITH r, row
            CALL {
                WITH r, row
                WITH r, row WHERE row.user_id IS NOT NULL
                MERGE (u:User {user_id: row.user_id})
                MERGE (u)-[:WROTE]->(r)
            }
            
            // Connect to ParentProduct
            WITH r, row
            CALL {
                WITH r, row
                WITH r, row WHERE coalesce(row.parent_asin, row.asin) IS NOT NULL
                MERGE (p:ParentProduct {parent_asin: coalesce(row.parent_asin, row.asin)})
                MERGE (r)-[:ABOUT_PRODUCT]->(p)
            }
            """
            
            with connector.session() as session:
                session.run(rev_query, batch=records)
            
            current_rev_row += len(chunk)
            checkpoint["reviews_index"] = current_rev_row
            save_checkpoint(checkpoint)
            LOGGER.info(f"Checkpoint saved: reviews_index = {current_rev_row}")
    else:
        LOGGER.warning(f"Reviews file not found at {REVIEWS_CSV}")
        
    connector.close()
    LOGGER.info("Batch ingestion complete. Please run embeddings backfill scripts next.")

if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Full batch pipeline for ingesting product metadata and reviews into Neo4j.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of rows to ingest. 0 means all.")
    parser.add_argument("--batch-size", type=int, default=10000, help="Number of rows per batch chunk. Default is 10000.")
    args = parser.parse_args()
    
    run_ingest(
        limit=args.limit,
        batch_size=args.batch_size
    )
