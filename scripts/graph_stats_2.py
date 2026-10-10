import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

def get_stats():
    conn = Neo4jConnector()
    conn.connect()
    
    with conn.session() as session:
        # Check review properties
        res = session.run("MATCH (r:Review) RETURN keys(r) AS keys LIMIT 1")
        print("Review keys:", res.single()["keys"])
        
        # Who writes it? Maybe Review node has user_id property
        res = session.run("""
            MATCH (r:Review)
            RETURN r.user_id as user_id, count(r) as review_count
            ORDER BY review_count DESC
            LIMIT 30
        """)
        top_users = [{"user_id": r["user_id"], "count": r["review_count"]} for r in res]
        print("Top 5 users by review count (using r.user_id):")
        for u in top_users[:5]:
            print(f"  {u['user_id']}: {u['count']}")

if __name__ == "__main__":
    get_stats()
