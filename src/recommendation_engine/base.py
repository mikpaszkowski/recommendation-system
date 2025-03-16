from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple

class BaseRecommender(ABC):
    """
    Abstract base class for recommendation engines.
    All recommendation models should implement this interface.
    """
    
    @abstractmethod
    def recommend(self, 
                 user_id: Optional[str] = None, 
                 item_features: Optional[Dict[str, Any]] = None,
                 user_preferences: Optional[Dict[str, Any]] = None,
                 num_recommendations: int = 5,
                 **kwargs) -> List[Dict[str, Any]]:
        """
        Generate recommendations based on user ID, item features, or user preferences.
        
        Args:
            user_id: Optional user identifier for collaborative filtering
            item_features: Optional dictionary of item features for content-based filtering
            user_preferences: Optional dictionary of user preferences
            num_recommendations: Number of recommendations to return
            **kwargs: Additional model-specific parameters
            
        Returns:
            List of dictionaries containing recommended items with their metadata
        """
        pass
    
    @abstractmethod
    def explain(self, 
               user_id: Optional[str] = None,
               item_id: str = None,
               **kwargs) -> str:
        """
        Generate an explanation for why an item was recommended to a user.
        
        Args:
            user_id: Optional user identifier
            item_id: Item identifier to explain
            **kwargs: Additional model-specific parameters
            
        Returns:
            String explanation of why the item was recommended
        """
        pass
    
    @abstractmethod
    def update_user_preferences(self,
                              user_id: str,
                              preferences: Dict[str, Any]) -> None:
        """
        Update user preferences based on conversation.
        
        Args:
            user_id: User identifier
            preferences: Dictionary of user preferences to update
        """
        pass 