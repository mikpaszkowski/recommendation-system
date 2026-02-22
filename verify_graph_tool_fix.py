
import logging
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.tools.graph_search_tool import GraphSearchTool

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_graph_search_tool():
    print("Initializing GraphSearchTool...")
    tool = GraphSearchTool()
    
    # Test 1: Vector Search (no filters)
    print("\nTest 1: Vector Search")
    try:
        result = tool.search(semantic_query="gaming laptop")
        print(f"Result: {result.get('status')} - Found {len(result.get('items', []))} items")
    except Exception as e:
        print(f"Test 1 Failed: {e}")

    # Test 2: Filter Search (only filters)
    print("\nTest 2: Filter Search")
    try:
        result = tool.search(structured_filters={"brand": "Dell"})
        print(f"Result: {result.get('status')} - Found {len(result.get('items', []))} items")
    except Exception as e:
        print(f"Test 2 Failed: {e}")

    # Test 3: Hybrid Search (both)
    print("\nTest 3: Hybrid Search")
    try:
        result = tool.search(semantic_query="gaming laptop", structured_filters={"brand": "Dell"})
        print(f"Result: {result.get('status')} - Found {len(result.get('items', []))} items")
    except Exception as e:
        print(f"Test 3 Failed: {e}")

if __name__ == "__main__":
    test_graph_search_tool()
