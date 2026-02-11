from typing import Dict, Any, Optional
import logging

from src.user.profile_manager import InMemoryUserProfileManager
from src.llm_interface.preference_parser import LLMPreferenceParser
from src.personalization.preference_quantifier import PreferenceQuantifier

logger = logging.getLogger(__name__)

class ProfileTool:
    """
    Tool for managing user profile (reading and updating preferences).
    Wraps ProfileManager, PreferenceParser, and Quantifier.
    """
    def __init__(self, 
                 profile_manager: Optional[InMemoryUserProfileManager] = None,
                 parser: Optional[LLMPreferenceParser] = None,
                 quantifier: Optional[PreferenceQuantifier] = None):
        self.profile_manager = profile_manager or InMemoryUserProfileManager()
        self.parser = parser or LLMPreferenceParser()
        self.quantifier = quantifier or PreferenceQuantifier()

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Reads the full user profile."""
        return self.profile_manager.get_profile(user_id)

    def update_preferences_from_conversation(self, user_id: str, conversation_text: str) -> Dict[str, Any]:
        """
        Extracts preferences from text, quantifies them, and updates the profile.
        Returns the new weighted preferences.
        """
        logger.info(f"ProfileTool: Extracting preferences for user {user_id}")
        
        # 1. Extract
        extracted = self.parser.extract_preferences(conversation_text)
        
        # 2. Normalize/Format
        # Note: PreferenceParser.format_for_recommender usually takes extraction results
        normalized = self.parser.format_for_recommender(extracted)
        
        # 3. Quantify
        weighted_prefs = self.quantifier.quantify(normalized)
        
        # 4. Update Profile
        # We need to merge these with existing profile preferences
        # For simplicity, we implement a basic update here. 
        # Ideally, ProfileManager should handle smart merging.
        self.profile_manager.update_profile(user_id, {"preferences": weighted_prefs})
        
        return weighted_prefs

    def save_item_interaction(self, user_id: str, item: Dict[str, Any]):
        """Saves an interaction (e.g. user viewed/liked an item)."""
        self.profile_manager.update_interaction_history(user_id, item)
