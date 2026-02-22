
import logging
import sys
import json
from src.agents.orchestrator import AgentOrchestrator

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("src.agents.orchestrator")
logger.setLevel(logging.INFO)

def run_test():
    print("=== Starting Context Persistence Verification ===")
    
    # Use a unique user_id for this test run
    user_id = "verify_user_001"
    
    # Initialize Orchestrator
    orchestrator = AgentOrchestrator()
    
    # --- Turn 1 ---
    print("\n[TURN 1] User: 'I need a performant gaming laptop'")
    response1 = orchestrator.run(user_id, "I need a performant gaming laptop")
    
    # Check Active Filters in State (we can't access state directly from run() return unless we exposed it, 
    # but we can look at the logs or infer from the search result/data if we added it to response)
    # Actually, the orchestrator logs "Updated Active Filters". We will rely on that or modify run to return state for test?
    # Modifying run to return state is intrusive. 
    # However, `response_payload['data']['structured_filters']` should reflect the active filters used in search.
    
    filters_1 = response1.get("data", {}).get("structured_filters", {})
    print(f"Active Filters after Turn 1: {json.dumps(filters_1, indent=2)}")
    
    # --- Turn 2 ---
    print("\n[TURN 2] User: 'My budget is under 2000 USD'")
    response2 = orchestrator.run(user_id, "My budget is under 2000 USD")
    
    filters_2 = response2.get("data", {}).get("structured_filters", {})
    print(f"Active Filters after Turn 2: {json.dumps(filters_2, indent=2)}")
    
    # --- Turn 3 ---
    print("\n[TURN 3] User: 'Actually, make it 2500 max'")
    response3 = orchestrator.run(user_id, "Actually, make it 2500 max")
    
    filters_3 = response3.get("data", {}).get("structured_filters", {})
    print(f"Active Filters after Turn 3: {json.dumps(filters_3, indent=2)}")

if __name__ == "__main__":
    run_test()
