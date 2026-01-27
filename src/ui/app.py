import chainlit as cl
import json
import logging
from typing import Dict, Any
from langchain_core.messages.utils import get_buffer_string

from src.dialog_manager.preference_agent_flow import PreferenceAgentFlow
from src.llm_interface.response_generator import ResponseGenerator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize singletons (or per-session objects can be initialized in start_chat)
# For now, we'll re-initialize per session to keep it clean.

@cl.on_chat_start
async def start_chat():
    """Initialize the flow and store it in the user session."""
    user_id = "test_user_chainlit"  # specific ID for this manual test session
    
    flow = PreferenceAgentFlow()
    response_generator = ResponseGenerator()
    
    cl.user_session.set("flow", flow)
    cl.user_session.set("response_generator", response_generator)
    cl.user_session.set("user_id", user_id)
    
    await cl.Message(
        content="**Recommendation System Debugger**\nI'm ready to chat! Tell me what kind of movies you like."
    ).send()

@cl.on_message
async def main(message: cl.Message):
    """Handle incoming user messages."""
    flow: PreferenceAgentFlow = cl.user_session.get("flow")
    response_generator: ResponseGenerator = cl.user_session.get("response_generator")
    user_id = cl.user_session.get("user_id")

    # 1. Execute the Phase I Flow
    # Note: flow.run is synchronous, so we run it directly. 
    # If it takes too long, we might need make_async, but for debugging it's fine.
    try:
        async with cl.Step(name="Processing User Input") as processing_step:
            processing_step.input = message.content
            
            # Since flow.run is blocking, we wrap it if needed or just call it.
            # For simplicity in this v1, we just call it.
            result = flow.run(
                user_id=user_id,
                user_message=message.content
            )
            
            processing_step.output = "Flow execution complete."

        # 2. Visualize the outputs as intermediate steps
        
        # Raw Extraction
        if "raw_extraction" in result:
             async with cl.Step(name="Raw Extraction (LLM)") as step:
                 step.input = "Based on conversation history..."
                 step.output = json.dumps(result["raw_extraction"], indent=2)

        # Quantified Preferences
        if "preferences" in result:
            async with cl.Step(name="Quantified Preferences") as step:
                step.output = json.dumps(result["preferences"], indent=2)

        # User Profile
        if "user_profile" in result:
            async with cl.Step(name="Updated User Profile") as step:
                step.output = json.dumps(result["user_profile"], indent=2)

        # Constructed Prompt
        prompt_messages = result.get("prompt_messages", [])
        if prompt_messages:
            # Convert LangChain messages to a readable string format
            prompt_text = get_buffer_string(prompt_messages)
            
            async with cl.Step(name="Constructed Recommender Prompt") as step:
                step.output = prompt_text

        # 3. Generate Final Response
        # We use the NEW ResponseGenerator to actually talk back to the user
        valid_response = False
        if prompt_messages:
            async with cl.Step(name="Generating Response") as step:
                response_text = response_generator.generate_response(prompt_messages)
                step.output = response_text
                valid_response = True
                
            # Send the final message to the chat
            await cl.Message(content=response_text).send()
        
        if not valid_response:
             await cl.Message(content="[System] Flow finished, but no prompt messages were generated to create a response.").send()

    except Exception as e:
        logger.exception("Error during flow execution")
        await cl.Message(content=f"An error occurred: {str(e)}").send()
