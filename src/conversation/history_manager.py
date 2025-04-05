"""Conversation history management implementation."""

from typing import Dict, List, Any, Optional
import logging

from src.conversation.abstract_history_manager import AbstractHistoryManager

logger = logging.getLogger(__name__)

class InMemoryConversationManager(AbstractHistoryManager):
    """In-memory implementation of conversation history management."""
    
    def __init__(self):
        """Initialize with empty conversations dictionary."""
        self.conversations = {}
    
    def get_history(self, user_id: str) -> List[Dict[str, str]]:
        """
        Get conversation history for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of conversation turns
        """
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        return self.conversations[user_id]
    
    def add_turn(self, user_id: str, user_message: str, assistant_message: Optional[str] = None) -> None:
        """
        Add a conversation turn to the history.
        
        Args:
            user_id: User identifier
            user_message: User message
            assistant_message: Optional assistant message
        """
        if user_id not in self.conversations:
            self.conversations[user_id] = []
            
        turn = {"user": user_message}
        if assistant_message:
            turn["assistant"] = assistant_message
            
        self.conversations[user_id].append(turn)
        
        # Limit history size
        if len(self.conversations[user_id]) > 10:
            self.conversations[user_id] = self.conversations[user_id][-10:]
            
        logger.debug(f"Added conversation turn for user {user_id}") 