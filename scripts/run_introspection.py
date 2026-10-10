import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

try:
    from knowledge_graph.graphdb.neo4j_connector import Neo4jConnector
    conn = Neo4jConnector()
    conn.connect()
    
    queries = {
        "node_counts": "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;",
        "embedding_parent_product": "MATCH (n:ParentProduct) RETURN count(n) AS total, count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;",
        "embedding_brand": "MATCH (n:Brand) RETURN count(n) AS total, count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;",
        "embedding_category": "MATCH (n:Category) RETURN count(n) AS total, count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;",
        "embedding_attribute": "MATCH (n:Attribute) RETURN count(n) AS total, count(CASE WHEN n.embedding IS NOT NULL THEN 1 END) AS embedded;",
        "indexes": "SHOW INDEXES WHERE type = 'VECTOR';",
        "relationships": "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS count ORDER BY count DESC;",
        "sample": "MATCH (p:ParentProduct) RETURN p LIMIT 1;"
    }
    
    with conn.session() as session:
        for name, query in queries.items():
            print(f"--- {name} ---")
            res = session.run(query)
            for record in res:
                print(dict(record))
            print()

except Exception as e:
    print(f"Error: {e}")
