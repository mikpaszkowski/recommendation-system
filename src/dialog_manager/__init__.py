"""Dialogue Manager module exports."""

from src.dialog_manager.session_schema import (
    CurrentSessionContext,
    CurrentSessionContextWrapper,
    SessionContext,
    ExtractedParameters,
    HardConstraint,
    SoftPreference,
    DialogueState,
    SessionIntent,
    ConstraintOperator,
    HardConstraintOperator,
    SuggestedSystemAction,
)
from src.dialog_manager.session_adapter import (
    hard_constraints_to_structured_filters,
    session_context_to_structured_filters,
    session_context_to_legacy_preferences,
    session_context_to_user_persona,
    session_context_to_dialogue_action,
    legacy_preferences_to_session_context,
    extract_semantic_query,
)
from src.dialog_manager.dialogue_manager import DialogueManager

__all__ = [
    "DialogueManager",
    "CurrentSessionContext",
    "CurrentSessionContextWrapper",
    "SessionContext",
    "ExtractedParameters",
    "HardConstraint",
    "SoftPreference",
    "DialogueState",
    "SessionIntent",
    "ConstraintOperator",
    "HardConstraintOperator",
    "SuggestedSystemAction",
    "hard_constraints_to_structured_filters",
    "session_context_to_structured_filters",
    "session_context_to_legacy_preferences",
    "session_context_to_user_persona",
    "session_context_to_dialogue_action",
    "legacy_preferences_to_session_context",
    "extract_semantic_query",
]

try:
    from src.dialog_manager.preference_agent_flow import PreferenceAgentFlow
    __all__.append("PreferenceAgentFlow")
except ImportError:
    pass
