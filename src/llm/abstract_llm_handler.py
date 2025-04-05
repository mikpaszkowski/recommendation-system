"""Interface definition for LLM handlers."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from langchain.schema import BaseMessage

class LLMHandlerInterface(ABC):
    """Interface for LLM handlers."""
    
    @abstractmethod
    def query(self, messages: List[BaseMessage]) -> str:
        """
        Submit a list of LangChain messages to the LLM.
        
        Args:
            messages: List of LangChain message objects
            
        Returns:
            Response from the LLM as a string
        """
        pass 