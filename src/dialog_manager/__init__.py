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
    CATALOG_SAFE_ATTRIBUTES,
    CATALOG_SAFE_FILTER_KEYS,
    extract_demoted_soft_preferences,
    extract_semantic_query,
    generate_attribute_unit_variations,
    hard_constraints_to_structured_filters,
    legacy_preferences_to_session_context,
    session_context_to_dialogue_action,
    session_context_to_legacy_preferences,
    session_context_to_soft_preferences,
    session_context_to_structured_filters,
    session_context_to_user_persona,
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
    "CATALOG_SAFE_ATTRIBUTES",
    "CATALOG_SAFE_FILTER_KEYS",
    "extract_demoted_soft_preferences",
    "extract_semantic_query",
    "generate_attribute_unit_variations",
    "hard_constraints_to_structured_filters",
    "legacy_preferences_to_session_context",
    "session_context_to_dialogue_action",
    "session_context_to_legacy_preferences",
    "session_context_to_soft_preferences",
    "session_context_to_structured_filters",
    "session_context_to_user_persona",
]

try:
    from src.dialog_manager.preference_agent_flow import PreferenceAgentFlow
    __all__.append("PreferenceAgentFlow")
except ImportError:
    pass
