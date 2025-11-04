# Neo4j Connector Quick Start Guide

This guide will help you get started with the Neo4j connector for your recommendation system.

## Prerequisites

- Python 3.8+
- Docker (recommended) or Neo4j Desktop
- pip or conda for package management

## Step 1: Install Dependencies

From the project root:

```bash
pip install -r requirements.txt
```

This will install:

- `neo4j>=5.14.0` - Official Neo4j Python driver
- `python-dotenv>=1.0.0` - Environment variable management

## Step 2: Start Neo4j Database

### Using Docker (Easiest)

```bash
docker run \
    --name neo4j-recommendation \
    -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/test123 \
    -d \
    neo4j:latest
```

Wait a few seconds for Neo4j to start, then verify it's running:

```bash
docker ps
```

You should see the `neo4j-recommendation` container running.

Access Neo4j Browser at: http://localhost:7474

### Using Neo4j Desktop

1. Download from https://neo4j.com/download/
2. Install and open Neo4j Desktop
3. Create a new project
4. Add a local DBMS
5. Set password and start the database

## Step 3: Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Copy the example file
cp .env.example .env

# Edit with your favorite editor
nano .env  # or vim, code, etc.
```

Update the `.env` file with your credentials:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=test123
NEO4J_DATABASE=neo4j
```

**Note:** If you used the Docker command above, the password is `test123`. Otherwise, use the password you set.

## Step 4: Test the Connection

Run the test script:

```bash
cd /Users/mikolajpaszkowski/recommendation-system
python graphrag/knowledge_graph/test_connector.py
```

Expected output:

```
✓ Connection established
✓ Connection verified
✓ Database info retrieved: Neo4j Kernel
✓ Query executed: Connection test successful!
✓ Database contains 0 nodes

============================================================
All tests passed! Neo4j connector is working correctly.
============================================================
```

## Step 5: Try the Examples

Run the example script to see various usage patterns:

```bash
python graphrag/knowledge_graph/example_usage.py
```

## Usage in Your Code

### Basic Example

```python
from graphrag.knowledge_graph.neo4j_connector import Neo4jConnector

# Use context manager for automatic cleanup
with Neo4jConnector() as connector:
    # Execute a simple query
    result = connector.execute_query(
        "MATCH (n) RETURN count(n) as count"
    )
    print(f"Nodes in database: {result[0]['count']}")
```

### Creating Data

```python
from graphrag.knowledge_graph.neo4j_connector import Neo4jConnector

with Neo4jConnector() as connector:
    # Create a product node
    connector.execute_write_transaction(
        """
        CREATE (p:Product {
            asin: $asin,
            title: $title,
            category: $category,
            price: $price
        })
        RETURN p
        """,
        parameters={
            "asin": "B001234567",
            "title": "Wireless Headphones",
            "category": "Electronics",
            "price": 79.99
        }
    )
    print("Product created!")
```

### Querying Data

```python
from graphrag.knowledge_graph.neo4j_connector import Neo4jConnector

with Neo4jConnector() as connector:
    # Find products in a category
    results = connector.execute_read_transaction(
        """
        MATCH (p:Product)
        WHERE p.category = $category
        RETURN p.asin, p.title, p.price
        ORDER BY p.price DESC
        LIMIT $limit
        """,
        parameters={"category": "Electronics", "limit": 10}
    )

    for product in results:
        print(f"{product['p.title']}: ${product['p.price']}")
```

## Common Issues and Solutions

### Issue: "Missing required environment variables"

**Solution:** Make sure you've created a `.env` file in the project root with all required variables.

### Issue: "ServiceUnavailable" or "Failed to connect"

**Solutions:**

1. Check if Neo4j is running: `docker ps`
2. Restart Neo4j: `docker restart neo4j-recommendation`
3. Check if port 7687 is accessible: `telnet localhost 7687`
4. Verify firewall isn't blocking the port

### Issue: "AuthError" or "Authentication failed"

**Solutions:**

1. Double-check username and password in `.env`
2. Default Neo4j credentials are `neo4j/neo4j` (first-time setup requires password change)
3. If using Docker, ensure `NEO4J_AUTH` matches your `.env` password

### Issue: "ModuleNotFoundError: No module named 'neo4j'"

**Solution:** Install dependencies: `pip install -r requirements.txt`

### Issue: "ModuleNotFoundError: No module named 'graphrag'"

**Solution:** Run from project root or add to PYTHONPATH:

```bash
export PYTHONPATH="${PYTHONPATH}:/Users/mikolajpaszkowski/recommendation-system"
```

## Next Steps

Now that you have the connector working, you can:

1. **Build the Knowledge Graph**: Create nodes and relationships from your Amazon Reviews dataset
2. **Implement Graph Queries**: Write Cypher queries for recommendations
3. **Add Graph Algorithms**: Use Neo4j's graph algorithms for similarity and centrality
4. **Integrate with RAG**: Use the graph for context-aware recommendations

## Useful Neo4j Commands

### Clear all data (use with caution!)

```python
with Neo4jConnector() as connector:
    connector.clear_database()
```

### View database statistics

```cypher
// In Neo4j Browser (http://localhost:7474)
CALL db.stats.retrieve('GRAPH COUNTS')
```

### Create indexes for better performance

```cypher
// Create index on Product ASIN
CREATE INDEX product_asin IF NOT EXISTS FOR (p:Product) ON (p.asin)

// Create index on Review ID
CREATE INDEX review_id IF NOT EXISTS FOR (r:Review) ON (r.review_id)
```

## Resources

- [Neo4j Documentation](https://neo4j.com/docs/)
- [Cypher Query Language](https://neo4j.com/docs/cypher-manual/current/)
- [Neo4j Python Driver](https://neo4j.com/docs/python-manual/current/)
- [Graph Data Science Library](https://neo4j.com/docs/graph-data-science/current/)

## Support

If you encounter issues:

1. Check the logs: `docker logs neo4j-recommendation`
2. Verify your `.env` configuration
3. Ensure Neo4j is running and accessible
4. Review the examples in `example_usage.py`
