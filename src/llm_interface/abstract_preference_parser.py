from abc import ABC, abstractmethod
from typing import Dict, Any

class PreferenceParserInterface(ABC):
    @abstractmethod
    def extract_preferences(self, text: str) -> Dict[str, Any]:
        """Extract structured preferences from natural language text."""
        pass
    
    @abstractmethod
    def format_for_recommender(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Format extracted preferences for the recommendation engine."""
        pass