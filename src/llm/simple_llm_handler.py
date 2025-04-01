from langchain_community.chat_models import ChatOpenAI
from langchain.schema import BaseMessage, HumanMessage, SystemMessage, AIMessage
from typing import Dict, Any, Optional, List, Union
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleLLMHandler:
    """
    A simple class to handle interactions with LLMs.
    This class only handles submitting messages to the LLM and returning responses,
    with no template formatting functionality.
    """
    
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gpt-3.5-turbo"):
        """
        Initialize the LLM handler.
        
        Args:
            api_key: OpenAI API key. If None, will try to get from environment
            model_name: Name of the model to use
        """
        # Set up API key
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key must be provided or set in OPENAI_API_KEY environment variable")
            
        # Initialize LangChain chat model
        self.llm = ChatOpenAI(
            openai_api_key=self.api_key,
            model_name=model_name,
            temperature=0.7
        )
        
        logger.info(f"Initialized SimpleLLMHandler with model: {model_name}")
    
    def query(self, messages: List[BaseMessage]) -> str:
        """
        Submit a list of LangChain messages to the LLM.
        
        Args:
            messages: List of LangChain message objects
            
        Returns:
            Response from the LLM as a string
        """
        try:
            # Get response from LLM
            response = self.llm(messages)
            return response.content
            
        except Exception as e:
            logger.error(f"Error querying LLM: {str(e)}")
            return f"Error: {str(e)}"
    
    def submit_raw(self, messages: List[Dict[str, str]]) -> str:
        """
        Submit a list of raw message dictionaries to the LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            
        Returns:
            Response from the LLM as a string
        """
        try:
            # Convert to LangChain message objects
            langchain_messages = []
            for message in messages:
                role = message.get('role', '').lower()
                content = message.get('content', '')
                
                if role == 'system':
                    langchain_messages.append(SystemMessage(content=content))
                elif role == 'user' or role == 'human':
                    langchain_messages.append(HumanMessage(content=content))
                elif role == 'assistant' or role == 'ai':
                    langchain_messages.append(AIMessage(content=content))
            
            # Get response
            return self.submit(langchain_messages)
            
        except Exception as e:
            logger.error(f"Error querying LLM with raw messages: {str(e)}")
            return f"Error: {str(e)}" 