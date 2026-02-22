from typing import List, Optional, Dict, Any, TypedDict, Annotated
from langchain_core.messages import BaseMessage
import operator

class ConversationState(TypedDict):
    """
    Represents the state of the conversation in the Multi-Agent System.
    """
    # The full history of messages in the conversation
    messages: Annotated[List[BaseMessage], operator.add]
    
    # The next action determined by the router
    # Values: "SEARCH", "CLARIFY", "ANSWER", "UPDATE_PROFILE", "READ_PROFILE", "CRITIQUE"
    next_step: Optional[str]
    
    # Persistent filters/preferences for the current conversation
    active_filters: Dict[str, Any]
    
    # Temporary context or metadata to pass between steps
    # e.g., raw search results from the tool before the critic sees them
    current_context: Optional[Dict[str, Any]]

    # The user's profile context (optional, can be fetched on demand)
    user_profile: Optional[Dict[str, Any]]
