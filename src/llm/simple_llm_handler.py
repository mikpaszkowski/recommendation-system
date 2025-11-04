import json
from langchain_community.chat_models import ChatOpenAI
from langchain.schema import BaseMessage, HumanMessage, SystemMessage, AIMessage
from typing import Dict, Any, Optional, List, Union
import os
import logging

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
            # Use invoke() instead of direct call
            response = self.llm.invoke(messages)
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
        
    def extract_preferences(self, user_query: str) -> Dict:
        """
        Extract structured preferences from a user query using the LLM.
        
        Args:
            user_query: Natural language query from user
            
        Returns:
            Dictionary containing extracted preferences in standardized format
        """
        try:
            # System prompt to structure the output
            system_prompt = """Extract product preferences from the user query and return them in this JSON format:
            {
                "category": string or null,  # High level category like "Electronics", "Clothing" etc
                "product_type": string or null,  # Specific product type like "Laptop", "Headphones" etc
                "constraints": {
                    "maxPrice": number or null,
                    "minPrice": number or null
                },
                "use_case": string or null,  # The intended use or purpose
                "attributes": {  # Key product attributes/features
                    "key1": {
                        "value": string,
                        "importance": "must-have" | "nice-to-have" | "flexible"
                    }
                }
            }
            
            Extract only what is explicitly mentioned or clearly implied. Use null for missing values.
            """
            
            # Format messages
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_query)
            ]
            
            # Get structured response
            response = self.query(messages)
            
            # Parse JSON response
            preferences = json.loads(response)
            
            # Validate basic structure
            required_keys = ['category', 'product_type', 'constraints', 'use_case', 'attributes']
            for key in required_keys:
                if key not in preferences:
                    preferences[key] = None
                    
            if 'constraints' in preferences and preferences['constraints']:
                if 'maxPrice' not in preferences['constraints']:
                    preferences['constraints']['maxPrice'] = None
                if 'minPrice' not in preferences['constraints']:
                    preferences['constraints']['minPrice'] = None
            
            return preferences
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing LLM response as JSON: {str(e)}")
            return {
                "category": None,
                "product_type": None, 
                "constraints": {"maxPrice": None, "minPrice": None},
                "use_case": None,
                "attributes": {}
            }
            
        except Exception as e:
            logger.error(f"Error extracting preferences: {str(e)}")
            return {
                "category": None,
                "product_type": None,
                "constraints": {"maxPrice": None, "minPrice": None}, 
                "use_case": None,
                "attributes": {}
            }