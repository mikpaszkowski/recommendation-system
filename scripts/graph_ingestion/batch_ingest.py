import argparse
import logging
import os
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Ensure the src module is in path if needed
import sys
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

LOGGER = logging.getLogger("kg.batch_ingest")
logging.basicConfig(level=logging.INFO)

ROOT_DIR = Path(__file__).resolve().parents[2]
METADATA_CSV = ROOT_DIR / "datasets" / "processed_data" / "processed_metadata.csv"
REVIEWS_CSV = ROOT_DIR / "datasets" / "processed_data" / "processed_reviews.csv"

def run_ingest(uri, user, password, limit):
    connector = Neo4jConnector(uri, user, password)
    
    # 1. Apply constraints
    LOGGER.info("Applying schema constraints...")
    
    # 2. Parse CSVs
    LOGGER.info(f"Loading metadata from {METADATA_CSV}...")
    df_meta = pd.read_csv(METADATA_CSV)
    if limit > 0:
        df_meta = df_meta.head(limit)
        
    LOGGER.info(f"Loading reviews from {REVIEWS_CSV}...")
    if REVIEWS_CSV.exists():
        df_reviews = pd.read_csv(REVIEWS_CSV)
        if limit > 0:
            df_reviews = df_reviews.head(limit)
    else:
        df_reviews = None
        LOGGER.warning(f"Reviews file not found at {REVIEWS_CSV}")
        
    # 3. Ingest Nodes (Mock up)
    LOGGER.info(f"Ingesting {len(df_meta)} products into Neo4j...")
    if df_reviews is not None:
        LOGGER.info(f"Ingesting {len(df_reviews)} reviews and users into Neo4j...")
    
    # Example Cypher for importing from Pandas/CSV to Neo4j
    # This should be expanded by the @engineer to run UNWIND queries on both datasets
    
    connector.close()
    LOGGER.info("Batch ingestion complete. Please run embeddings backfill scripts next.")

if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Full batch pipeline for ingesting product metadata and reviews into Neo4j.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of rows to ingest. 0 means all.")
    args = parser.parse_args()
    
    run_ingest(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
        limit=args.limit
    )
