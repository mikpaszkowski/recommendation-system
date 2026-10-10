import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

def prune_database():
    conn = Neo4jConnector()
    conn.connect()
    
    subset_path = os.path.join(os.path.dirname(__file__), "../datasets/curated/subset_selection.json")
    with open(subset_path, "r") as f:
        data = json.load(f)
        
    target_users = data["users"]
    target_asins = data["products"]
    
    print(f"Pruning database to keep {len(target_users)} users and {len(target_asins)} products...")
    
    with conn.session() as session:
        # 1. Delete all ParentProducts NOT in target_asins
        print("Deleting unselected products...")
        session.run("""
            MATCH (p:ParentProduct)
            WHERE NOT p.parent_asin IN $asins
            CALL {
                WITH p
                DETACH DELETE p
            } IN TRANSACTIONS OF 5000 ROWS
        """, {"asins": target_asins})
        
        # 2. Delete all Users NOT in target_users
        print("Deleting unselected users...")
        session.run("""
            MATCH (u:User)
            WHERE NOT u.user_id IN $users
            CALL {
                WITH u
                DETACH DELETE u
            } IN TRANSACTIONS OF 5000 ROWS
        """, {"users": target_users})
        
        # 3. Delete orphaned reviews
        print("Deleting orphaned reviews...")
        session.run("""
            MATCH (r:Review)
            WHERE NOT (r)-[:ABOUT_PRODUCT]->(:ParentProduct)
            CALL {
                WITH r
                DETACH DELETE r
            } IN TRANSACTIONS OF 5000 ROWS
        """)
        
        # 4. Delete orphaned Brands
        print("Deleting orphaned Brands...")
        session.run("""
            MATCH (b:Brand)
            WHERE NOT (b)<-[:HAS_BRAND]-(:ParentProduct)
            CALL {
                WITH b
                DETACH DELETE b
            } IN TRANSACTIONS OF 5000 ROWS
        """)
        
        # 5. Delete orphaned Categories
        print("Deleting orphaned Categories...")
        session.run("""
            MATCH (c:Category)
            WHERE NOT (c)<-[:BELONGS_TO_CATEGORY]-(:ParentProduct)
            CALL {
                WITH c
                DETACH DELETE c
            } IN TRANSACTIONS OF 5000 ROWS
        """)
        
        # 6. Delete orphaned Attributes
        print("Deleting orphaned Attributes...")
        session.run("""
            MATCH (a:Attribute)
            WHERE NOT (a)--()
            CALL {
                WITH a
                DELETE a
            } IN TRANSACTIONS OF 50000 ROWS
        """, timeout=300.0)

        # 7. Delete orphaned Products (child products)
        print("Deleting unselected Products...")
        session.run("""
            MATCH (p:Product)
            WHERE NOT p.asin IN $asins AND NOT p.parent_asin IN $asins
            CALL {
                WITH p
                DETACH DELETE p
            } IN TRANSACTIONS OF 50000 ROWS
        """, {"asins": target_asins}, timeout=300.0)

        # 8. Delete orphaned Variants
        print("Deleting unselected Variants...")
        session.run("""
            MATCH (v:Variant)
            WHERE NOT v.asin IN $asins AND NOT v.parent_asin IN $asins
            CALL {
                WITH v
                DETACH DELETE v
            } IN TRANSACTIONS OF 50000 ROWS
        """, {"asins": target_asins}, timeout=300.0)
        
        # 9. Delete orphaned PriceRanges
        print("Deleting orphaned PriceRanges...")
        session.run("""
            MATCH (pr:PriceRange)
            WHERE NOT (pr)--()
            CALL {
                WITH pr
                DELETE pr
            } IN TRANSACTIONS OF 50000 ROWS
        """)
        
    print("Database successfully pruned in-place!")

if __name__ == "__main__":
    prune_database()
