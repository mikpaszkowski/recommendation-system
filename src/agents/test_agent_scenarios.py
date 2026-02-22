import logging
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.agents.orchestrator import AgentOrchestrator

# Configure logging to show only INFO
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("src.agents.orchestrator")
logger.setLevel(logging.INFO)

def run_scenario(name: str, message: str, orchestrator: AgentOrchestrator):
    print(f"\n--- SCENARIO: {name} ---")
    print(f"User: {message}")
    
    result = orchestrator.run("test_user", message)
    
    action = result.get("action")
    answer = result.get("answer")
    data = result.get("data")
    
    print(f"ACTION: {action}")
    print(f"ANSWER: {answer}")
    if data and "count" in data:
        print(f"DATA: Found {data['count']} items")
    elif data:
        print(f"DATA: {data}")

def main():
    print("Initializing AgentOrchestrator...")
    orchestrator = AgentOrchestrator()
    
    # 1. Chit-chat
    run_scenario("A (Chit-chat)", "Hi, how are you?", orchestrator)
    
    # 2. Clarification
    run_scenario("B (Ambiguous)", "I want to buy a laptop", orchestrator)
    
    # 3. Search
    run_scenario("C (Specific)", "I am looking for a cheap Dell laptop for gaming under $1000", orchestrator)

    # 4. Profile Update (Optional check)
    run_scenario("D (Profile Update)", "I really hate red color", orchestrator)

if __name__ == "__main__":
    main()
