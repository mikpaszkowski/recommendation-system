from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

class AbstractHistoryManager(ABC):
    @abstractmethod
    def get_history(self, user_id: str) -> List[Dict[str, str]]:
        """Get conversation history for a user."""
        pass
    
    @abstractmethod
    def add_turn(self, user_id: str, user_message: str, assistant_message: Optional[str] = None) -> None:
        """Add a conversation turn to the history."""
        pass