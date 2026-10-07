import os
import matplotlib.pyplot as plt
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

def analyze():
    conn = Neo4jConnector()
    conn.connect()
    
    cat_query = """
    MATCH (p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c:Category) 
    RETURN c.name as category, count(p) as count 
    ORDER BY count DESC LIMIT 15
    """
    cat_results = conn.execute_query(cat_query)
    
    print("Top Categories from Graph:")
    for r in cat_results:
        print(f"{r['category']}: {r['count']}")
        
    keywords = ["notebook", "laptop", "keyboard", "headphone", "cable", "mouse", "watch", "monitor", "speaker", "camera", "tablet", "phone", "case", "charger", "adapter"]
    
    type_counts = {}
    for kw in keywords:
        kw_query = f"""
        MATCH (p:ParentProduct)
        WHERE toLower(p.title) CONTAINS '{kw}'
        RETURN count(p) as count
        """
        res = conn.execute_query(kw_query)
        type_counts[kw] = res[0]['count']
        
    sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
    
    print("\nSpecific Product Types (Derived from Title):")
    for k, v in sorted_types:
        print(f"{k.capitalize()}: {v}")
        
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    
    labels_cat = [r['category'] for r in cat_results]
    vals_cat = [r['count'] for r in cat_results]
    ax1.barh(labels_cat[::-1], vals_cat[::-1], color='skyblue')
    ax1.set_title('Top 15 Categories (Neo4j Category Node)')
    ax1.set_xlabel('Product Count')
    
    labels_kw = [k.capitalize() for k, v in sorted_types]
    vals_kw = [v for k, v in sorted_types]
    ax2.barh(labels_kw[::-1], vals_kw[::-1], color='lightgreen')
    ax2.set_title('Specific Product Types (Title Keyword Match)')
    ax2.set_xlabel('Product Count')
    
    plt.tight_layout()
    
    plot_path = "/Users/mikolajpaszkowski/.gemini/antigravity/brain/2b1ec273-504b-45ae-9508-8bc020364d6f/scratch/product_distribution.png"
    plt.savefig(plot_path)
    print(f"\nPlot saved to {plot_path}")
    
if __name__ == "__main__":
    analyze()
