from abc import ABC, abstractmethod
from typing import Dict, Any

class AbstractProfileManager(ABC):
    @abstractmethod
    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Get user profile."""
        pass
    
    @abstractmethod
    def update_profile(self, user_id: str, preferences: Dict[str, Any]) -> None:
        """Update user profile."""
        pass
    
    @abstractmethod
    def update_interaction_history(self, user_id: str, item: Dict[str, Any]) -> None:
        """Update user interaction history."""