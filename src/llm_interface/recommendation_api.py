import logging
from typing import Dict, List, Any, Optional, Union
import json

from src.conversation.abstract_history_manager import AbstractHistoryManager
from src.conversation.history_manager import InMemoryConversationManager
from src.recommendation_engine.base import BaseRecommender
from src.llm_interface.preference_parser import PreferenceParser
from src.llm_interface.prompt_constructor import PromptConstructor
from src.user.abstract_profile_manager import AbstractProfileManager
from src.user.profile_manager import InMemoryUserProfileManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RecommendationAPI:
    """
    API for integrating LLMs with recommendation engines.
    This serves as the bridge between natural language and structured recommendation systems.
    """
    
    def __init__(self, 
                recommender: BaseRecommender,
                preference_parser: Optional[PreferenceParser] = None,
                prompt_constructor: Optional[PromptConstructor] = None,
                profile_manager: Optional[AbstractProfileManager] = None,
                history_manager: Optional[AbstractHistoryManager] = None):
        """
        Initialize the recommendation API.
        
        Args:
            recommender: Recommendation engine instance
            preference_parser: Optional preference parser instance
            prompt_constructor: Optional prompt constructor instance
        """
        self.recommender = recommender
        self.preference_parser = preference_parser or PreferenceParser()
        self.prompt_constructor = prompt_constructor or PromptConstructor()
        self.history_manager = history_manager or InMemoryConversationManager()
        self.profile_manager = profile_manager or InMemoryUserProfileManager()
        
    def process_query(self, 
                     user_id: str,
                     query: str,
                     num_recommendations: int = 5) -> Dict[str, Any]:
        """
        Process a natural language query and return recommendations.
        
        Args:
            user_id: User identifier
            query: Natural language query
            num_recommendations: Number of recommendations to return
            
        Returns:
            Dictionary containing recommendations and prompt for LLM
        """
        # Extract preferences from query
        preferences = self.preference_parser.extract_preferences(query)
        
        # Format preferences for recommender
        formatted_preferences = self.preference_parser.format_for_recommender(preferences)
        
        # Update user preferences in the recommender
        self.recommender.update_user_preferences(user_id, formatted_preferences)
        
        # Update user profile
        self.profile_manager.update_profile(user_id, formatted_preferences)
        
        # Get recommendations
        recommendations = self.recommender.recommend(
            user_id=user_id,
            user_preferences=formatted_preferences,
            num_recommendations=num_recommendations,
            query_text=query
        )
        
        
        # Update conversation history
        self.history_manager.add_turn(user_id, query, None)
        
        # Construct prompt for LLM
        prompt = self.prompt_constructor.construct_recommendation_prompt(
            user_query=query,
            user_profile=self.profile_manager.get_profile(user_id),
            conversation_history=self.history_manager.get_history(user_id),
            retrieved_items=recommendations
        )
        
        return {
            "recommendations": recommendations,
            "prompt": prompt,
            "extracted_preferences": preferences
        }
    
    def get_explanation(self, 
                      user_id: str,
                      item_id: str) -> Dict[str, Any]:
        """
        Get an explanation for why an item was recommended.
        
        Args:
            user_id: User identifier
            item_id: Item identifier
            
        Returns:
            Dictionary containing explanation and prompt for LLM
        """
        # Get explanation from recommender
        explanation = self.recommender.explain(user_id, item_id)
        
        # Find item details
        item_details = None
        if hasattr(self.recommender, 'item_data'):
            item_row = self.recommender.item_data[self.recommender.item_data['product_id'] == item_id]
            if not item_row.empty:
                item_details = item_row.iloc[0].to_dict()
        
        # If item details not found, return basic explanation
        if not item_details:
            return {
                "explanation": explanation,
                "prompt": None
            }
        
        # Construct prompt for LLM
        prompt = self.prompt_constructor.construct_explanation_prompt(
            user_id=user_id,
            item=item_details,
            user_profile=self.profile_manager.get_profile(user_id)
        )
        
        return {
            "explanation": explanation,
            "prompt": prompt,
            "item_details": item_details
        }
    
    def update_conversation(self, 
                          user_id: str,
                          user_message: str,
                          assistant_message: str) -> None:
        """
        Update conversation history with a new turn.
        
        Args:
            user_id: User identifier
            user_message: User message
            assistant_message: Assistant message
        """
        self.history_manager.add_turn(user_id, user_message, assistant_message)
        
        # Extract preferences from user message
        preferences = self.preference_parser.extract_preferences(user_message)
        
        # Format preferences for recommender
        if preferences:
            formatted_preferences = self.preference_parser.format_for_recommender(preferences)
            
            # Update user preferences in the recommender
            self.recommender.update_user_preferences(user_id, formatted_preferences)
            
            # Update user profile
            self.profile_manager.update_profile(user_id, formatted_preferences)