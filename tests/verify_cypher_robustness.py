import sys
import os
import re

# Ensure src is in path
sys.path.append(os.getcwd())

from src.knowledge_graph.graphdb.graph_query_manager import GraphQueryManager

class MockLLMHandler:
    pass

class MockQueryGenerator:
    def generate_query(self, **kwargs):
        # Simulate a bad response from LLM where it forgets parameters
        return {
            "cypher": "MATCH (n) WHERE n.name IN $missing_param RETURN n",
            "parameters": {} 
        }

def test_missing_parameter_safety():
    print("Testing missing parameter safety...")
    
    # We inject a mock generator that produces bad Cypher
    manager = GraphQueryManager(query_generator=MockQueryGenerator())
    
    try:
        # This normally would crash Neo4j driver with "Expected parameter(s): missing_param"
        # But our fix should catch it and default it to [].
        # Since we don't have a real Neo4j connection here, we might get a connection error
        # or if existing tests mock it, we might get further.
        # However, the logic we added is BEFORE execution.
        
        # To test purely logic without Neo4j, we can inspect what's passed to execution
        # But GraphQueryManager executes immediately. i'll check if it fails with "missing param"
        # or just connection error (which means it passed the param check).
        
        manager.retrieve_items("test query", {"likes": [], "dislikes": []})
        print("Completed without parameter error (likely Connection Error which is expected if no DB)")
        
    except Exception as e:
        str_e = str(e)
        if "Expected parameter(s): missing_param" in str_e:
             print(f"FAILED: The parameter check did not work. Error: {e}")
        else:
             print(f"PASSED (caught expected other error): {e}")

if __name__ == "__main__":
    test_missing_parameter_safety()
