# Graph RAG Module

This module provides knowledge graph functionality for the recommendation system using Neo4j.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Neo4j Connection

Create a `.env` file in the project root (copy from `.env.example`):

```bash
cp .env.example .env
```

Edit the `.env` file with your Neo4j credentials:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password_here
NEO4J_DATABASE=neo4j
```

### 3. Install and Run Neo4j

#### Option A: Using Docker Compose (Recommended)

We provide a complete Docker Compose setup with APOC and Graph Data Science plugins:

```bash
cd src/knowledge-graph
docker-compose up -d
```

This will start Neo4j with:

- APOC plugin for utility functions
- Graph Data Science plugin for algorithms
- Persistent volumes for data
- Health checks and auto-restart

**See [DOCKER.md](DOCKER.md) for detailed setup instructions.**

#### Option B: Using Docker (Manual)

```bash
docker run \
    --name neo4j-recommendation \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/your_password_here \
    -v $HOME/neo4j/data:/data \
    neo4j:latest
```

#### Option C: Using Neo4j Desktop

1. Download Neo4j Desktop from https://neo4j.com/download/
2. Create a new database
3. Start the database
4. Update your `.env` file with the connection details

#### Option D: Using Neo4j Aura (Cloud)

1. Sign up at https://neo4j.com/cloud/aura/
2. Create a new database instance
3. Update your `.env` file with the provided connection details

## Usage

### Basic Usage

```python
from graphrag.knowledge_graph.neo4j_connector import Neo4jConnector

# Using context manager (recommended)
with Neo4jConnector() as connector:
    result = connector.execute_query(
        "MATCH (n) RETURN count(n) as count"
    )
    print(f"Total nodes: {result[0]['count']}")
```

### Creating Nodes and Relationships

```python
with Neo4jConnector() as connector:
    # Create a product node
    connector.execute_write_transaction(
        """
        CREATE (p:Product {
            asin: $asin,
            title: $title,
            category: $category
        })
        RETURN p
        """,
        parameters={
            "asin": "B001234567",
            "title": "Sample Product",
            "category": "Electronics"
        }
    )
```

### Querying Data

```python
with Neo4jConnector() as connector:
    # Find products by category
    results = connector.execute_read_transaction(
        """
        MATCH (p:Product)
        WHERE p.category = $category
        RETURN p.asin, p.title
        LIMIT $limit
        """,
        parameters={"category": "Electronics", "limit": 10}
    )

    for product in results:
        print(f"{product['p.title']} - {product['p.asin']}")
```

## Examples

See `graphrag/knowledge_graph/example_usage.py` for comprehensive examples:

```bash
cd graphrag/knowledge_graph
python example_usage.py
```

## Neo4j Connector API

### Class: `Neo4jConnector`

#### Methods

- `connect()` - Establish connection to Neo4j database
- `close()` - Close the database connection
- `is_connected()` - Check if currently connected
- `verify_connection()` - Verify the connection is working
- `execute_query(query, parameters)` - Execute a Cypher query
- `execute_write_transaction(query, parameters)` - Execute a write transaction
- `execute_read_transaction(query, parameters)` - Execute a read transaction
- `get_database_info()` - Get database information
- `clear_database()` - Clear all data (use with caution!)
- `session(**kwargs)` - Get a session context manager

## Knowledge Graph Schema (Planned)

For Amazon Reviews dataset:

```
(Product)
  - asin: String (unique identifier)
  - title: String
  - price: Float
  - category: String
  - brand: String
  - features: List<String>

(Review)
  - review_id: String (unique identifier)
  - rating: Float
  - text: String
  - timestamp: DateTime
  - helpful_vote: Integer

(User)
  - user_id: String (unique identifier)
  - name: String

(Category)
  - name: String (unique identifier)
  - level: Integer

Relationships:
  (Review)-[:REVIEWS]->(Product)
  (User)-[:WROTE]->(Review)
  (Product)-[:IN_CATEGORY]->(Category)
  (Category)-[:SUBCATEGORY_OF]->(Category)
  (Product)-[:SIMILAR_TO]->(Product)
```

## Troubleshooting

### Connection Issues

If you get connection errors:

1. Verify Neo4j is running: `docker ps` or check Neo4j Desktop
2. Check your `.env` file has correct credentials
3. Ensure the port 7687 is not blocked by firewall
4. Try connecting via Neo4j Browser at http://localhost:7474

### Authentication Errors

- Double-check username and password in `.env`
- Default Neo4j credentials are `neo4j/neo4j` (you'll be prompted to change on first login)

### Module Import Errors

Make sure you're running from the project root or have the project in your PYTHONPATH:

```bash
export PYTHONPATH="${PYTHONPATH}:/path/to/recommendation-system"
```

## Next Steps

1. Implement data ingestion pipeline for Amazon Reviews dataset
2. Create graph builder for products, reviews, and users
3. Implement graph-based recommendation algorithms
4. Add graph embeddings for semantic search
