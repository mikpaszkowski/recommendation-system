import json
import os
import logging
from typing import Dict, Any, Optional, List, Union

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI

from src.llm.abstract_llm_handler import LLMHandlerInterface

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleLLMHandler(LLMHandlerInterface):
    """
    A simple class to handle interactions with LLMs.
    This class only handles submitting messages to the LLM and returning responses,
    with no template formatting functionality.
    """
    
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gpt-4o-mini", provider: str = "openai"):
        """
        Initialize the LLM handler.
        
        Args:
            api_key: OpenAI API key. If None, will try to get from environment (only for openai)
            model_name: Name of the model to use (default: gpt-4o-mini, or llama3.1 for ollama)
            provider: 'openai' or 'ollama'
        """
        self.provider = provider
        
        if self.provider == "openai":
            # Set up API key
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                raise ValueError("OpenAI API key must be provided or set in OPENAI_API_KEY environment variable")
                
            # Initialize LangChain chat model
            self.llm = ChatOpenAI(
                openai_api_key=self.api_key,
                model_name=model_name,
                temperature=0
            )
            logger.info(f"Initialized SimpleLLMHandler (OpenAI) with model: {model_name}")
            
        elif self.provider == "ollama":
            # Use ChatOpenAI with Ollama's OpenAI-compatible endpoint
            # Default for ollama if user passed an OpenAI default
            if model_name.startswith("gpt-"):
                model_name = "llama3.1"
                
            self.llm = ChatOpenAI(
                openai_api_key="ollama", # Key is required but ignored by Ollama
                openai_api_base="http://localhost:11434/v1", # Standard Ollama endpoint
                model_name=model_name,
                temperature=0
            )
            logger.info(f"Initialized SimpleLLMHandler (Ollama via OpenAI API) with model: {model_name}")
        
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    def query(self, messages: List[BaseMessage]) -> str:
        """
        Submit a list of LangChain messages to the LLM.
        
        Args:
            messages: List of LangChain message objects
            
        Returns:
            Response from the LLM as a string
        """
        try:
            # Use invoke() instead of direct call
            response = self.llm.invoke(messages)
            result = response.content
            
            # Ollama sometimes returns parsed JSON if format="json" is used, 
            # or just raw text. For generic Usage, raw text is expected.
            return result if isinstance(result, str) else str(result)
            
        except Exception as e:
            logger.error(f"Error querying LLM: {str(e)}")
            return f"Error: {str(e)}"

    async def aquery(self, messages: List[BaseMessage]) -> str:
        """
        Submit a list of LangChain messages to the LLM asynchronously.
        
        Args:
            messages: List of LangChain message objects
            
        Returns:
            Response from the LLM as a string
        """
        try:
            response = await self.llm.ainvoke(messages)
            result = response.content
            return result if isinstance(result, str) else str(result)
            
        except Exception as e:
            logger.error(f"Error asynchronously querying LLM: {str(e)}")
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
            return self.query(langchain_messages)
            
        except Exception as e:
            logger.error(f"Error querying LLM with raw messages: {str(e)}")
            return f"Error: {str(e)}" 