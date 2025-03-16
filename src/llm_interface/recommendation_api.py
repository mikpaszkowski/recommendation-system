from typing import Dict, List, Any, Optional, Union
import json

from src.recommendation_engine.base import BaseRecommender
from src.llm_interface.preference_parser import PreferenceParser
from src.llm_interface.prompt_constructor import PromptConstructor

class RecommendationAPI:
    """
    API for integrating LLMs with recommendation engines.
    This serves as the bridge between natural language and structured recommendation systems.
    """
    
    def __init__(self, 
                recommender: BaseRecommender,
                preference_parser: Optional[PreferenceParser] = None,
                prompt_constructor: Optional[PromptConstructor] = None):
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
        
        # Store conversation history
        self.conversation_history = {}
        
        # Store user profiles
        self.user_profiles = {}
        
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
        self._update_user_profile(user_id, formatted_preferences)
        
        # Get recommendations
        recommendations = self.recommender.recommend(
            user_id=user_id,
            user_preferences=formatted_preferences,
            num_recommendations=num_recommendations
        )
        
        
        # Update conversation history
        self._update_conversation_history(user_id, query, None)
        
        # Construct prompt for LLM
        prompt = self.prompt_constructor.construct_recommendation_prompt(
            user_query=query,
            user_profile=self.user_profiles.get(user_id),
            conversation_history=self.conversation_history.get(user_id),
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
            user_profile=self.user_profiles.get(user_id)
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
        self._update_conversation_history(user_id, user_message, assistant_message)
        
        # Extract preferences from user message
        preferences = self.preference_parser.extract_preferences(user_message)
        
        # Format preferences for recommender
        if preferences:
            formatted_preferences = self.preference_parser.format_for_recommender(preferences)
            
            # Update user preferences in the recommender
            self.recommender.update_user_preferences(user_id, formatted_preferences)
            
            # Update user profile
            self._update_user_profile(user_id, formatted_preferences)
    
    def _update_conversation_history(self, 
                                   user_id: str,
                                   user_message: str,
                                   assistant_message: Optional[str]) -> None:
        """
        Update conversation history for a user.
        
        Args:
            user_id: User identifier
            user_message: User message
            assistant_message: Optional assistant message
        """
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
        
        # Add new turn
        turn = {"user": user_message}
        if assistant_message:
            turn["assistant"] = assistant_message
            
        self.conversation_history[user_id].append(turn)
        
        # Limit history size
        if len(self.conversation_history[user_id]) > 10:
            self.conversation_history[user_id] = self.conversation_history[user_id][-10:]
    
    def _update_user_profile(self, 
                           user_id: str,
                           preferences: Dict[str, Any]) -> None:
        """
        Update user profile with new preferences.
        
        Args:
            user_id: User identifier
            preferences: Dictionary of preferences
        """
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                "preferences": {},
                "history": []
            }
        
        # Update preferences
        for key, value in preferences.items():
            self.user_profiles[user_id]["preferences"][key] = value
    
    def update_interaction_history(self, 
                                 user_id: str,
                                 item: Dict[str, Any]) -> None:
        """
        Update user's interaction history with an item.
        
        Args:
            user_id: User identifier
            item: Item that the user interacted with
        """
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                "preferences": {},
                "history": []
            }
        
        # Add item to history
        self.user_profiles[user_id]["history"].insert(0, item)
        
        # Limit history size
        if len(self.user_profiles[user_id]["history"]) > 20:
            self.user_profiles[user_id]["history"] = self.user_profiles[user_id]["history"][:20] 