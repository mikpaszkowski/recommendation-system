import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

def extract_subset():
    conn = Neo4jConnector()
    conn.connect()
    
    with conn.session() as session:
        # Top 25 users
        res = session.run("""
            MATCH (r:Review)
            RETURN r.user_id as user_id, count(r) as review_count
            ORDER BY review_count DESC
            LIMIT 25
        """)
        top_users = [r["user_id"] for r in res]
        
        # 5 Bottom users (1 review)
        res = session.run("""
            MATCH (r:Review)
            RETURN r.user_id as user_id, count(r) as review_count
            ORDER BY review_count ASC
            LIMIT 5
        """)
        bottom_users = [r["user_id"] for r in res]
        
        # Top 25 products
        res = session.run("""
            MATCH (p:ParentProduct)<-[:ABOUT_PRODUCT]-(r:Review)
            RETURN p.parent_asin as asin, count(r) as review_count
            ORDER BY review_count DESC
            LIMIT 25
        """)
        top_products = [r["asin"] for r in res]
        
        # 5 Products with 0 reviews
        res = session.run("""
            MATCH (p:ParentProduct)
            WHERE NOT (p)<-[:ABOUT_PRODUCT]-(:Review)
            RETURN p.parent_asin as asin
            LIMIT 5
        """)
        bottom_products = [r["asin"] for r in res]

    os.makedirs(os.path.join(os.path.dirname(__file__), "../datasets/curated"), exist_ok=True)
    
    with open(os.path.join(os.path.dirname(__file__), "../datasets/curated/subset_selection.json"), "w") as f:
        json.dump({
            "users": top_users + bottom_users,
            "products": top_products + bottom_products
        }, f, indent=2)
        
    print(f"Extracted {len(top_users + bottom_users)} users and {len(top_products + bottom_products)} products.")

if __name__ == "__main__":
    extract_subset()
