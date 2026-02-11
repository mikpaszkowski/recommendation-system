
import logging
import os
import sys
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.knowledge_graph.graphdb.external_llm_cypher_generator import ExternalLLMCypherGenerator
from src.llm.simple_llm_handler import SimpleLLMHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_fix():
    logger.info("=== Testing Cypher Generation Fix ===")
    
    # Initialize Generator
    try:
        # Check if API key is available
        if not os.getenv("OPENAI_API_KEY"):
            logger.warning("OPENAI_API_KEY not found. Please set it to run this test.")
            return

        llm_handler = SimpleLLMHandler()
        generator = ExternalLLMCypherGenerator(llm_handler=llm_handler)
    except Exception as e:
        logger.error(f"Failed to initialize generator: {e}")
        return

    # User Query that caused the error
    user_query = "I am looking for headphones up to 100$ that are waterproof and can be used under water"
    
    # Preferences structure as seen in logs
    preferences = {
        "weighted_preferences": {
            "likes": [
                {"value": "waterproof"}, 
                {"value": "can be used under water"}
            ],
            "dislikes": [],
            "constraints": {
                "price_range": "up to $100", # String format as per log? Logs said: constraints={'price_range': 'up to $100'} which is odd for 'constraints'. Usually it's a list or dict. 
                                            # Wait, the prompt example shows constraints.price_range as ["< 100"].
                                            # The log said: constraints={'price_range': 'up to $100'}. 
                                            # The parser might have put it that way. The generator needs to handle it.
                "categories": ["Headphones"] # Implicit from query
            }
        },
        "intent": "recommendation",
        "notes": "User is looking for waterproof headphones up to $100 that can be used under water"
    }
    
    # Run generation
    try:
        result = generator.generate_query(
            user_query=user_query,
            preferences=preferences
        )
        
        cypher = result.get("cypher", "")
        parameters = result.get("parameters", {})
        
        logger.info("\nGenerated Cypher:")
        logger.info(cypher)
        logger.info("\nParameters:")
        logger.info(json.dumps(parameters, indent=2))
        
        # Simple validation check
        if "WHERE" in cypher:
            # Check for pattern expression variable introduction in WHERE
            # e.g. WHERE ... (p)-[:HAS]->(a) ... AND a.prop ...
            import re
            # Only a heuristic check
            if re.search(r"WHERE.*\(.*-[^>]*>.*\((\w+)[^)]*\).*\b\1\.", cypher, re.DOTALL):
                logger.warning("⚠️ POTENTIAL SYNTAX ERROR: Variable introduced in WHERE clause pattern might be used improperly.")
            else:
                logger.info("✅ Cypher looks safer (no obvious pattern variable reuse in WHERE).")
                
    except Exception as e:
        logger.error(f"Error during generation: {e}")

if __name__ == "__main__":
    test_fix()
