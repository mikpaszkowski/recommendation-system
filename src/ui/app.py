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
        # Note: orchestrator.run is synchronous for now
        async with cl.Step(name="Agent Thinking") as step:
            step.input = message.content
            
            result = await cl.make_async(orchestrator.run)(
                user_id=user_id,
                user_message=message.content
            )
            
            # Extract action and answer
            action = result.get("action", "UNKNOWN")
            answer = result.get("answer", "I'm sorry, something went wrong.")
            data = result.get("data", {})
            
            step.output = f"Action Taken: {action}\nReasoning/Data: {json.dumps(data, indent=2) if data else 'None'}"

        # If it was a search, we might want to show some details in a separate step or just rely on the answer
        if action == "SEARCH" and data:
             async with cl.Step(name="Graph Search Results") as search_step:
                 items = data.get("items", [])
                 search_step.output = f"Found {len(items)} items."

        # Send the final response to the user
        await cl.Message(content=answer).send()

    except Exception as e:
        logger.exception("Error during agent execution")
        await cl.Message(content=f"An error occurred: {str(e)}").send()
