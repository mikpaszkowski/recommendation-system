import logging
from typing import Dict, List, Optional, Any

from src.llm.abstract_llm_handler import LLMHandlerInterface
from src.llm.simple_llm_handler import SimpleLLMHandler
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

class ResponseGenerator:
    """
    Generates a natural language response based on constructed prompts and retrieved items.
    """

    def __init__(
        self,
        llm_handler: Optional[LLMHandlerInterface] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.llm_handler = llm_handler or SimpleLLMHandler()
        
        # Initialize the model similar to other agents
        model = getattr(self.llm_handler, "llm", self.llm_handler)
        if isinstance(model, ChatOpenAI):
            self.llm = model
        else:
            self.llm = ChatOpenAI(model=model, temperature=0.7) # Slightly higher temp for creative responses

    def generate_response(self, prompt_messages: List[Dict[str, str]]) -> str:
        """
        Calls the LLM with the constructed messages and returns the content string.
        
        Args:
            prompt_messages: List of dicts with 'role' and 'content' keys.
            
        Returns:
            The generated response string.
        """
        try:
            self.logger.info("Generating response from LLM...")
            
            # Convert dict messages to LangChain message objects
            lc_messages = []
            for msg in prompt_messages:
                # Handle dictionary input
                if isinstance(msg, dict):
                    role = msg.get("role")
                    content = msg.get("content", "")
                    
                    if role == "system":
                        lc_messages.append(SystemMessage(content=content))
                    elif role == "user":
                        lc_messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        lc_messages.append(AIMessage(content=content))
                    else:
                        self.logger.warning(f"Unknown role '{role}', treating as user message.")
                        lc_messages.append(HumanMessage(content=content))
                # Handle existing LangChain message objects
                elif hasattr(msg, "content"):
                    lc_messages.append(msg)
                else:
                    self.logger.warning(f"Skipping invalid message format: {type(msg)}")

            response = self.llm.invoke(lc_messages)
            return str(response.content)

        except Exception as e:
            self.logger.error(f"Error generating response: {e}")
            return "I apologize, but I encountered an error while generating the response."
