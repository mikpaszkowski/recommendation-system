"""
Shared fixtures and setup for E2E tests.
Derived strictly from ORIGINAL_REQUEST.md and PROJECT.md.
"""
from typing import Any, Dict
import pytest

from tests.e2e.schema_validator import (
    SESSION_CONTEXT_JSON_SCHEMA,
    validate_session_context_schema,
    assert_valid_session_context,
)

# Attempt to load canonical implementations from src; fall back to reference models
try:
    from src.dialog_manager.session_schema import (
        CurrentSessionContextWrapper,
        SessionContext,
        ExtractedParameters,
        HardConstraint,
        SoftPreference,
        DialogueState,
        SessionIntent,
        ConstraintOperator,
        SuggestedSystemAction,
    )
    SRC_SCHEMA_AVAILABLE = True
except ImportError:
    from tests.e2e.reference_impl import (
        CurrentSessionContextWrapper,
        SessionContext,
        ExtractedParameters,
        HardConstraint,
        SoftPreference,
        DialogueState,
        SessionIntent,
        ConstraintOperator,
        SuggestedSystemAction,
    )
    SRC_SCHEMA_AVAILABLE = False

try:
    from src.dialog_manager.session_adapter import (
        hard_constraints_to_structured_filters,
        session_context_to_legacy_preferences,
    )
    SRC_ADAPTER_AVAILABLE = True
except ImportError:
    from tests.e2e.reference_impl import (
        hard_constraints_to_structured_filters,
        session_context_to_legacy_preferences,
    )
    SRC_ADAPTER_AVAILABLE = False

try:
    from src.dialog_manager.dialogue_manager import DialogueManager
    SRC_DIALOGUE_MANAGER_AVAILABLE = True
except ImportError:
    from tests.e2e.reference_impl import DialogueManager
    SRC_DIALOGUE_MANAGER_AVAILABLE = False


@pytest.fixture
def canonical_sample_payload() -> Dict[str, Any]:
    """
    Authoritative complete example from ORIGINAL_REQUEST.md lines 46-88.
    """
    return {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "User is looking for a lightweight laptop for college with a good battery life.",
            "extracted_parameters": {
                "hard_constraints": [
                    {
                        "attribute": "price",
                        "operator": "less_than",
                        "value": 1000,
                    },
                    {
                        "attribute": "operating_system",
                        "operator": "exclude",
                        "value": "ChromeOS",
                    },
                ],
                "soft_preferences": [
                    {
                        "category": "weight",
                        "value": "lightweight",
                        "polarity": 0.8,
                        "confidence": 0.9,
                        "evidence": "User mentioned wanting something easy to carry around campus.",
                    },
                    {
                        "category": "brand",
                        "value": "Apple",
                        "polarity": 0.4,
                        "confidence": 0.6,
                        "evidence": "User asked if MacBooks ever go on sale in this price range.",
                    },
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": ["screen_size"],
                "suggested_system_action": "ask_clarification",
            },
        }
    }


@pytest.fixture
def minimal_valid_payload() -> Dict[str, Any]:
    """
    Minimal valid payload conforming strictly to the schema.
    """
    return {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "",
            "extracted_parameters": {
                "hard_constraints": [],
                "soft_preferences": [],
            },
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": [],
                "suggested_system_action": "ask_clarification",
            },
        }
    }


@pytest.fixture
def schema_classes():
    """Provides schema model classes."""
    return {
        "CurrentSessionContextWrapper": CurrentSessionContextWrapper,
        "SessionContext": SessionContext,
        "ExtractedParameters": ExtractedParameters,
        "HardConstraint": HardConstraint,
        "SoftPreference": SoftPreference,
        "DialogueState": DialogueState,
        "SessionIntent": SessionIntent,
        "ConstraintOperator": ConstraintOperator,
        "SuggestedSystemAction": SuggestedSystemAction,
        "is_src_implementation": SRC_SCHEMA_AVAILABLE,
    }


@pytest.fixture
def adapter_functions():
    """Provides adapter functions."""
    return {
        "hard_constraints_to_structured_filters": hard_constraints_to_structured_filters,
        "session_context_to_legacy_preferences": session_context_to_legacy_preferences,
        "is_src_implementation": SRC_ADAPTER_AVAILABLE,
    }


@pytest.fixture
def dialogue_manager_factory():
    """Factory fixture returning a fresh DialogueManager instance."""
    def _create(critical_attributes=None):
        return DialogueManager(critical_attributes=critical_attributes)
    return _create
