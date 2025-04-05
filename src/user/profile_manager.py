"""User profile management implementation."""

from typing import Dict, List, Any, Optional
import logging

from src.user.abstract_profile_manager import AbstractProfileManager

logger = logging.getLogger(__name__)

class InMemoryUserProfileManager(AbstractProfileManager):
    """
    In-memory implementation of user profile management.

    It is responsible for managing user's preferences and interaction history.
    The main point of this class is to abstract the storage of the data and provide
    a simple interface to query these information and update it as well along the converstation.

    """
    
    def __init__(self):
        """Initialize with empty profiles dictionary."""
        self.profiles = {}
    
    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """
        Get a user's profile data.
        
        Args:
            user_id: User identifier
            
        Returns:
            User profile dictionary
        """
        if user_id not in self.profiles:
            self.profiles[user_id] = {
                "preferences": {},
                "history": []
            }
        return self.profiles[user_id]
    
    def update_profile(self, user_id: str, preferences: Dict[str, Any]) -> None:
        """
        Update a user's profile with new preferences.
        
        Args:
            user_id: User identifier
            preferences: Dictionary of preferences to update
        """
        profile = self.get_profile(user_id)
        for key, value in preferences.items():
            profile["preferences"][key] = value
        
        logger.debug(f"Updated profile for user {user_id} with preferences: {preferences}")
    
    def update_interaction_history(self, user_id: str, item: Dict[str, Any]) -> None:
        """
        Update a user's interaction history.
        
        Args:
            user_id: User identifier
            item: Item to add to history
        """
        profile = self.get_profile(user_id)
        profile["history"].insert(0, item)
        
        # Limit history size
        if len(profile["history"]) > 20:
            profile["history"] = profile["history"][:20]
            
        logger.debug(f"Updated interaction history for user {user_id}") 