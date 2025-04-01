from typing import Dict, List, Any, Optional
import logging
from src.llm_interface.recommendation_api import RecommendationAPI
from src.llm.simple_llm_handler import SimpleLLMHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimpleDialogManager:
    """
    A simple dialog manager that handles conversation flow between user input,
    recommendation API, and LLM response generation.
    """
    
    def __init__(self, recommendation_api: RecommendationAPI, llm_handler: SimpleLLMHandler):
        """
        Initialize the dialog manager.
        
        Args:
            recommendation_api: Instance of RecommendationAPI for processing queries
            llm_handler: Instance of SimpleLLMHandler for generating responses
        """
        self.recommendation_api = recommendation_api
        self.llm_handler = llm_handler
        logger.info("SimpleDialogManager initialized")
        
    def manage(self, user_query: str, user_id: str, num_recommendations: int = 5) -> str:
        """
        Manage the dialog flow from user query to response.
        
        Args:
            user_query: The user's input query
            user_id: User identifier
            num_recommendations: Number of recommendations to retrieve
            
        Returns:
            Generated response to be displayed to the user
        """
        try:
            logger.info(f"Processing query for user {user_id}: {user_query}")
            
            # Step 1: Process the query through the recommendation API
            api_result = self.recommendation_api.process_query(
                user_id=user_id,
                query=user_query,
                num_recommendations=num_recommendations
            )
            
            logger.info(f"Retrieved {len(api_result['recommendations'])} recommendations")
            
            # Step 2: Get the prompt prepared by the recommendation API
            prompt = api_result['prompt']
            
            # Step 3: Send the prompt to the LLM for response generation
            llm_response = self.llm_handler.query(prompt)
            
            # Step 4: Return the generated response
            return llm_response
            
        except Exception as e:
            logger.error(f"Error in dialog management: {str(e)}")
            return f"I'm sorry, I encountered an error while processing your request: {str(e)}"