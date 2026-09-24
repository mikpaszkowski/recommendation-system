import sys
import os
from collections import defaultdict

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

def investigate():
    conn = Neo4jConnector()
    conn.connect()
    
    with conn.session() as session:
        # Get all node counts by label
        res = session.run("""
            MATCH (n)
            RETURN labels(n) as labels, count(n) as cnt
        """)
        
        print("Nodes by label:")
        for r in res:
            print(f"{r['labels']}: {r['cnt']}")
            
if __name__ == "__main__":
    investigate()
