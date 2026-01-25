from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

class PromptConstructorInterface(ABC):
    @abstractmethod
    def construct_recommendation_prompt(self, 
                                      user_query: str,
                                      user_profile: Optional[Dict[str, Any]] = None,
                                      conversation_history: Optional[List[Dict[str, str]]] = None,
                                      retrieved_items: Optional[List[Dict[str, Any]]] = None,
                                      preferences: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Construct a prompt for generating recommendations."""
        pass
    
    @abstractmethod
    def construct_explanation_prompt(self,
                                   user_id: str,
                                   item: Dict[str, Any],
                                   user_profile: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Construct a prompt for generating an explanation."""
        pass