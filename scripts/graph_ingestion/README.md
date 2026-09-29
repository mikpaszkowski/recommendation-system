# Graph Ingestion Pipeline Instructions

This guide outlines the steps required to populate the Neo4j Knowledge Graph with the full catalog of products from the flattened datasets (`datasets/processed_data/processed_metadata.csv and processed_reviews.csv`).

## Prerequisites

1. Ensure the `.env` file is properly configured with your Neo4j credentials:
   ```env
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=password
   OPENAI_API_KEY=your_key_here  # For embeddings backfill
   ```
2. Ensure the Neo4j docker container is running.

## 1. Run the Batch Ingestion Script

We have consolidated the ingestion logic into a dedicated script directory: `scripts/graph_ingestion/`.
Run the new batch ingestion script to load the nodes and edges from the processed CSV.

```bash
python scripts/graph_ingestion/batch_ingest.py
```
*(You can pass `--limit 1000` for a test run).*

## 2. Apply Neo4j Constraints and Setup Vector Indexes

Next, setup the constraints and vector indexes required for search (Cypher 25 VECTOR indexes).

```bash
python src/knowledge_graph/graphdb/setup_indexes.py
```

## 3. Backfill Embeddings (Required for GraphSearchTool)

The full product catalog will be missing OpenAI embeddings for vector search upon initial ingestion. You must run the backfill scripts to generate them.

### Generate Product, Attribute, and Review Embeddings
```bash
python src/knowledge_graph/graphdb/backfill_embeddings.py
```

### Generate Category Embeddings
```bash
python src/knowledge_graph/graphdb/backfill_category_embeddings.py
```

## 4. Test the Database

Finally, test the end-to-end graph query:
```bash
python scripts/run_a1_flow.py "small keyboard under 30$ with usb-c"
```
