# Neo4j Docker Setup Guide

This guide explains how to run Neo4j using Docker Compose for the recommendation system knowledge graph.

## Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose)
- At least 4GB of available RAM
- Ports 7474 and 7687 available

## Quick Start

### 1. Start Neo4j

From the `src/knowledge-graph` directory:

```bash
docker-compose up -d
```

This will:

- Pull the Neo4j 5.14.0 image (if not already downloaded)
- Start Neo4j with APOC and Graph Data Science plugins
- Expose ports 7474 (HTTP) and 7687 (Bolt)
- Create persistent volumes for data, logs, and imports

### 2. Verify Neo4j is Running

Check the container status:

```bash
docker-compose ps
```

You should see:

```
NAME                      STATUS              PORTS
neo4j-recommendation      Up (healthy)        0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

View logs:

```bash
docker-compose logs -f neo4j
```

Wait for the message: `Remote interface available at http://localhost:7474/`

### 3. Access Neo4j Browser

Open your web browser and navigate to:

```
http://localhost:7474
```

Login with:

- **Username**: `neo4j`
- **Password**: `test123` (or the password you set in docker-compose.yml)

### 4. Test the Connection

Run the test script from the project root:

```bash
cd /Users/mikolajpaszkowski/recommendation-system
python -m src.knowledge-graph.graphdb.test_connector
```

## Configuration

### Environment Variables

The docker-compose.yml file uses environment variables for configuration. You can customize these by:

1. Creating a `.env` file in the `src/knowledge-graph` directory:

```bash
# Neo4j Authentication
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_secure_password_here
```

2. Or by modifying the `docker-compose.yml` file directly.

### Memory Settings

The default memory settings are:

- **Heap Initial Size**: 512MB
- **Heap Max Size**: 2GB
- **Page Cache Size**: 1GB

To adjust these for your system, edit the environment variables in `docker-compose.yml`:

```yaml
environment:
  - NEO4J_server_memory_heap_initial__size=512m
  - NEO4J_server_memory_heap_max__size=2G
  - NEO4J_server_memory_pagecache_size=1G
```

**Recommendations**:

- For small datasets (< 1M nodes): Use defaults
- For medium datasets (1M-10M nodes): 4GB heap, 2GB page cache
- For large datasets (> 10M nodes): 8GB+ heap, 4GB+ page cache

### Plugins

The setup includes two essential plugins:

1. **APOC (Awesome Procedures on Cypher)**: Utility functions and procedures
2. **Graph Data Science (GDS)**: Graph algorithms for recommendations

These are automatically installed and configured.

## Common Operations

### Stop Neo4j

```bash
docker-compose stop
```

### Start Neo4j (after stopping)

```bash
docker-compose start
```

### Restart Neo4j

```bash
docker-compose restart
```

### Stop and Remove Container (keeps data)

```bash
docker-compose down
```

### Stop and Remove Everything (including data)

⚠️ **Warning**: This will delete all your graph data!

```bash
docker-compose down -v
```

### View Logs

```bash
# Follow logs in real-time
docker-compose logs -f neo4j

# View last 100 lines
docker-compose logs --tail=100 neo4j
```

### Access Neo4j Shell

```bash
docker-compose exec neo4j cypher-shell -u neo4j -p test123
```

## Data Import

### Using the Import Directory

The docker-compose setup mounts a volume at `/var/lib/neo4j/import` for bulk data loading.

1. Copy your data files to the import volume:

```bash
# Find the volume location
docker volume inspect knowledge-graph_neo4j_import

# Copy files (example)
docker cp your_data.csv neo4j-recommendation:/var/lib/neo4j/import/
```

2. Load data using Cypher:

```cypher
LOAD CSV WITH HEADERS FROM 'file:///your_data.csv' AS row
CREATE (p:Product {asin: row.asin, title: row.title})
```

### Using Python Scripts

You can also load data using the Neo4j connector:

```python
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

with Neo4jConnector() as connector:
    # Your data loading logic here
    pass
```

## Troubleshooting

### Container Won't Start

**Check if ports are in use:**

```bash
# Check port 7474
lsof -i :7474

# Check port 7687
lsof -i :7687
```

If ports are in use, either:

- Stop the conflicting service
- Change the ports in docker-compose.yml:

```yaml
ports:
  - "17474:7474" # Use port 17474 instead
  - "17687:7687" # Use port 17687 instead
```

### Out of Memory Errors

If you see `OutOfMemoryError` in the logs:

1. Increase heap size in docker-compose.yml
2. Ensure Docker has enough memory allocated (Docker Desktop → Settings → Resources)
3. Close other memory-intensive applications

### Connection Refused

If you get "Connection refused" errors:

1. Wait 30-60 seconds for Neo4j to fully start
2. Check logs: `docker-compose logs neo4j`
3. Verify the container is healthy: `docker-compose ps`
4. Ensure firewall isn't blocking ports 7474/7687

### Authentication Failed

If authentication fails:

1. Check the password in docker-compose.yml matches your `.env` file
2. Try resetting by removing the container and volume:

```bash
docker-compose down -v
docker-compose up -d
```

### Plugin Not Found

If APOC or GDS procedures aren't available:

1. Check logs for plugin loading errors
2. Verify plugins are enabled in docker-compose.yml
3. Restart the container: `docker-compose restart`

## Performance Tuning

### For Development

The default settings are optimized for development:

- Fast startup
- Moderate memory usage
- All features enabled

### For Production

For production use, consider:

1. **Increase memory allocation**:

   - Heap: 50-75% of available RAM
   - Page cache: 25-50% of available RAM

2. **Enable authentication** (already enabled by default)

3. **Use persistent volumes** (already configured)

4. **Set up backups**:

```bash
# Backup
docker-compose exec neo4j neo4j-admin database dump neo4j --to-path=/backups

# Restore
docker-compose exec neo4j neo4j-admin database load neo4j --from-path=/backups
```

5. **Monitor performance**:

```cypher
// In Neo4j Browser
:sysinfo
CALL dbms.queryJmx("org.neo4j:*")
```

## Volumes

The setup creates four persistent volumes:

1. **neo4j_data**: Database files (nodes, relationships, indexes)
2. **neo4j_logs**: Log files
3. **neo4j_import**: Import directory for bulk loading
4. **neo4j_plugins**: Plugin files

### Backup Volumes

```bash
# List volumes
docker volume ls | grep neo4j

# Backup data volume
docker run --rm -v knowledge-graph_neo4j_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/neo4j-backup.tar.gz -C /data .

# Restore data volume
docker run --rm -v knowledge-graph_neo4j_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/neo4j-backup.tar.gz -C /data
```

## Network

The setup creates a custom bridge network `recommendation-network`. This allows:

- Isolated network for Neo4j
- Easy integration with other services (Kafka, Spark, etc.)
- Service discovery by container name

To add other services to the same network, add to their docker-compose.yml:

```yaml
networks:
  - recommendation-network

networks:
  recommendation-network:
    external: true
    name: knowledge-graph_recommendation-network
```

## Security Considerations

### Development

The current setup is optimized for development:

- Default password is simple (`test123`)
- All connections allowed (`0.0.0.0`)
- Debug logging enabled

### Production

For production deployments:

1. **Use strong passwords**:

   ```yaml
   - NEO4J_AUTH=neo4j/${STRONG_PASSWORD}
   ```

2. **Restrict network access**:

   ```yaml
   - NEO4J_dbms_connector_bolt_listen__address=127.0.0.1:7687
   ```

3. **Enable SSL/TLS**:

   ```yaml
   - NEO4J_dbms_connector_bolt_tls_level=REQUIRED
   ```

4. **Use secrets management** (Docker Swarm/Kubernetes)

5. **Regular backups**

6. **Monitor access logs**

## Resources

- [Neo4j Docker Documentation](https://neo4j.com/docs/operations-manual/current/docker/)
- [Neo4j Configuration Reference](https://neo4j.com/docs/operations-manual/current/configuration/)
- [APOC Documentation](https://neo4j.com/labs/apoc/)
- [Graph Data Science Documentation](https://neo4j.com/docs/graph-data-science/current/)

## Next Steps

1. ✅ Start Neo4j with Docker Compose
2. ✅ Verify connection
3. 📝 Load your Amazon Reviews dataset
4. 📝 Create graph schema and indexes
5. 📝 Implement recommendation queries
6. 📝 Integrate with your application

See [QUICKSTART.md](QUICKSTART.md) for more details on using the Neo4j connector.
