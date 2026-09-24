import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

def get_stats():
    conn = Neo4jConnector()
    conn.connect()
    
    stats = {}
    with conn.session() as session:
        # Node counts
        for label in ["ParentProduct", "Brand", "Category", "Attribute", "Review", "User"]:
            res = session.run(f"MATCH (n:{label}) RETURN count(n) as cnt")
            stats[f"count_{label}"] = res.single()["cnt"]
            
        # Has embedding
        for label in ["ParentProduct", "Brand", "Category", "Attribute"]:
            res = session.run(f"MATCH (n:{label}) WHERE n.embedding IS NOT NULL RETURN count(n) as cnt")
            stats[f"embeddings_{label}"] = res.single()["cnt"]
            
        # Top Users by Review count
        res = session.run("""
            MATCH (u:User)-[:WROTE_REVIEW]->(r:Review)
            RETURN u.user_id as user_id, count(r) as review_count
            ORDER BY review_count DESC
            LIMIT 30
        """)
        stats["top_users"] = [{"user_id": r["user_id"], "count": r["review_count"]} for r in res]
        
        # Bottom Users
        res = session.run("""
            MATCH (u:User)-[:WROTE_REVIEW]->(r:Review)
            RETURN u.user_id as user_id, count(r) as review_count
            ORDER BY review_count ASC
            LIMIT 10
        """)
        stats["bottom_users"] = [{"user_id": r["user_id"], "count": r["review_count"]} for r in res]
        
        # Top Products by Review count
        res = session.run("""
            MATCH (p:ParentProduct)<-[:ABOUT_PRODUCT]-(r:Review)
            RETURN p.parent_asin as asin, count(r) as review_count
            ORDER BY review_count DESC
            LIMIT 30
        """)
        stats["top_products"] = [{"asin": r["asin"], "count": r["review_count"]} for r in res]
        
        # Products with 0 reviews
        res = session.run("""
            MATCH (p:ParentProduct)
            WHERE NOT (p)<-[:ABOUT_PRODUCT]-(:Review)
            RETURN p.parent_asin as asin
            LIMIT 10
        """)
        stats["bottom_products"] = [r["asin"] for r in res]

    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    get_stats()
