from typing import List, Optional, Dict, Any, TypedDict, Annotated
from langchain_core.messages import BaseMessage
import operator

class _ConversationStateOptional(TypedDict, total=False):
    """Per-turn routing scratch space (R2a); absent or None unless the router step sets it."""

    # Search parameters produced by category recovery (RS-23), reused by the SEARCH branch
    search_params: Optional[Dict[str, Any]]

    # How the turn's product category was resolved (copied into eval_trace)
    category_resolution: Optional[Dict[str, Any]]

    # Why the turn ended as CLARIFY (None on SEARCH); one of orchestrator.CLARIFY_REASONS
    clarify_reason: Optional[str]


class ConversationState(_ConversationStateOptional):
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
