import logging
import os
import sys
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from src.knowledge_graph.graphdb.graph_query_manager import GraphQueryManager
    from src.knowledge_graph.graphdb.resolver_service import ResolverService
except ImportError:
    from graph_query_manager import GraphQueryManager
    from resolver_service import ResolverService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MockGenerator:
    def generate_query(self, **kwargs):
        return {"cypher": "MATCH (n) RETURN n", "parameters": {}}

def test_retrieval():
    logger.info("=== Starting Retrieval Test ===")
    
    # Initialize Manager with Mock Generator to avoid importing broken ExternalLLMCypherGenerator
    manager = GraphQueryManager(enabled=True, query_generator=MockGenerator())
    
    test_cases = [
        {
            "query": "I want a watch with a pulse reader",
            "preferences": {
                "weighted_preferences": {
                    "likes": [{"value": "pulse reader", "weight": 1.0}], # ambiguous term
                    "constraints": {"categories": ["Watches"]}
                }
            }
        },
        {
            "query": "Looking for car bass speakers",
            "preferences": {
                "weighted_preferences": {
                    "likes": [],
                    "constraints": {"categories": ["car bass speakers"]} # ambiguous category
                }
            }
        }
    ]

    for i, case in enumerate(test_cases):
        logger.info(f"\n--- Test Case {i+1} ---")
        logger.info(f"Query: {case['query']}")
        logger.info(f"Input Prefernces: {json.dumps(case['preferences'], indent=2)}")
        
        # 1. Test Grounding Logic directly
        grounded = manager._ground_preferences(case['preferences'])
        logger.info(f"Grounded Preferences: {json.dumps(grounded, indent=2)}")
        
        # Check specific fields
        grounded_ctx = grounded.get("grounded_context", {})
        resolved_attrs = grounded_ctx.get("resolved_attributes", [])
        resolved_cats = grounded_ctx.get("resolved_categories", [])
        
        if resolved_attrs:
            logger.info(f"✅ Resolved Attributes: {resolved_attrs}")
        if resolved_cats:
            logger.info(f"✅ Resolved Categories: {resolved_cats}")

if __name__ == "__main__":
    test_retrieval()
