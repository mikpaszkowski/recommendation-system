import chainlit as cl
import json
import logging
import sys
import os
from typing import Dict, Any

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.agents.orchestrator import AgentOrchestrator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@cl.on_chat_start
async def start_chat():
    """Initialize the agent orchestrator and store it in the user session."""
    user_id = "test_user_chainlit"  # specific ID for this manual test session
    
    # Initialize the new Agent Orchestrator
    orchestrator = AgentOrchestrator()
    
    cl.user_session.set("orchestrator", orchestrator)
    cl.user_session.set("user_id", user_id)
    
    await cl.Message(
        content="**Autonomous Recommendation Agent**\nI'm ready to chat! I can answer questions, search for equality products, or ask for clarification if needed."
    ).send()

@cl.on_message
async def main(message: cl.Message):
    """Handle incoming user messages."""
    orchestrator: AgentOrchestrator = cl.user_session.get("orchestrator")
    user_id = cl.user_session.get("user_id")

    try:
        # Run the Agent Orchestrator
        async with cl.Step(name="Agent Thinking") as step:
            step.input = message.content
            
            result = await orchestrator.run(
                user_id=user_id,
                user_message=message.content
            )
            
            # Extract action and answer
            action = result.get("action", "UNKNOWN")
            answer = result.get("answer", "I'm sorry, something went wrong.")
            data = result.get("data", {})
            
            step.output = f"Action Taken: {action}\nReasoning/Data: {json.dumps(data, indent=2) if data else 'None'}"

        # If it was a search, show detailed breakdown in Chainlit UI step
        if action == "SEARCH" and data:
            async with cl.Step(name="Graph Search & Critic Evaluation") as search_step:
                items = data.get("items", [])
                raw_candidates = data.get("raw_candidates", [])
                
                details = []
                details.append(f"🔍 **Graph Candidates Retrieved**: {len(raw_candidates)}")
                for i, c in enumerate(raw_candidates):
                    c_title = c.get("title") or c.get("asin") or "Unknown Product"
                    details.append(f"- [{i+1}] {c_title} (${c.get('price')})")
                    reasons = c.get("match_reasons", [])
                    if reasons:
                        details.append(f"  *Match Reasons*: {', '.join(reasons[:2])}")
                
                details.append(f"\n⚖️ **Critic Agent Approved**: {len(items)}")
                if items:
                    for i, it in enumerate(items):
                        it_title = it.get("title") or it.get("asin") or "Unknown Product"
                        details.append(f"- [{i+1}] {it_title} (Fit Score: {it.get('semantic_score', 0)}/100)")
                else:
                    details.append("*(Critic Agent rejected all initial candidates due to unmet constraints/features)*")
                    
                search_step.output = "\n".join(details)

        # Send the final response to the user
        await cl.Message(content=answer).send()

    except Exception as e:
        logger.exception("Error during agent execution")
        await cl.Message(content=f"An error occurred: {str(e)}").send()
