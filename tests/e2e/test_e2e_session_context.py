"""
End-to-End Session Context Test Suite.
Verifies the complete integration flow from conversational extraction
through Dialogue State Manager to Recommender Graph Query Adapter.
Uses deterministic mock fixtures without requiring live external OpenAI or Neo4j services.
"""
from typing import Any, Dict
from unittest.mock import MagicMock
import pytest

from tests.e2e.schema_validator import assert_valid_session_context


class MockLLMPreferenceExtractor:
    """Deterministic mock preference extractor returning current_session_context schema."""

    def __init__(self, predefined_responses: Dict[str, Dict[str, Any]]) -> None:
        self.responses = predefined_responses

    def extract_preferences(self, utterance: str) -> Dict[str, Any]:
        for pattern, response in self.responses.items():
            if pattern.lower() in utterance.lower():
                return response
        # Default cold start fallback
        return {
            "current_session_context": {
                "session_intent": "initial_search",
                "situational_context": utterance,
                "extracted_parameters": {"hard_constraints": [], "soft_preferences": []},
                "dialogue_state": {
                    "ready_for_recommendation": False,
                    "missing_critical_attributes": ["category"],
                    "suggested_system_action": "ask_clarification",
                }
            }
        }


class MockGraphSearchTool:
    """Deterministic mock of GraphSearchTool verifying structured filters acceptance."""

    def __init__(self) -> None:
        self.last_query_filters: Dict[str, Any] = {}

    def search(self, query: str, filters: Dict[str, Any]) -> list:
        self.last_query_filters = filters
        # Return mock candidates
        return [
            {"name": "MacBook Air M1", "price": 899, "brand": "Apple", "category": "laptop"},
            {"name": "Dell XPS 13", "price": 999, "brand": "Dell", "category": "laptop"},
        ]


@pytest.mark.e2e
def test_e2e_full_extraction_to_search_pipeline(dialogue_manager_factory, adapter_functions):
    """
    E2E Test: Multi-turn interaction connecting MockLLM -> DialogueManager -> SessionAdapter -> MockGraphSearchTool.
    """
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    legacy_adapter = adapter_functions["session_context_to_legacy_preferences"]
    mock_search = MockGraphSearchTool()

    # Predefined mock LLM outputs for conversation turns
    mock_extractor = MockLLMPreferenceExtractor({
        "college": {
            "current_session_context": {
                "session_intent": "initial_search",
                "situational_context": "User needs lightweight laptop for college.",
                "extracted_parameters": {
                    "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                    "soft_preferences": [
                        {"category": "weight", "value": "lightweight", "polarity": 0.85, "confidence": 0.9, "evidence": "easy carry"}
                    ],
                },
                "dialogue_state": {
                    "ready_for_recommendation": False,
                    "missing_critical_attributes": ["price"],
                    "suggested_system_action": "ask_clarification",
                }
            }
        },
        "budget": {
            "current_session_context": {
                "session_intent": "refining_options",
                "situational_context": "Budget under $1000, no ChromeOS.",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "price", "operator": "less_than", "value": 1000},
                        {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"},
                    ],
                    "soft_preferences": [],
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results",
                }
            }
        },
    })

    session_id = "e2e_pipeline_session_42"

    # --- Turn 1 ---
    user_msg_1 = "I need a lightweight laptop for college."
    raw_extraction_1 = mock_extractor.extract_preferences(user_msg_1)
    assert_valid_session_context(raw_extraction_1)

    ctx_1 = dm.update_turn(session_id, user_msg_1, raw_extraction_1)
    assert ctx_1.session_intent.value == "initial_search"
    assert ctx_1.dialogue_state.ready_for_recommendation is False
    assert ctx_1.dialogue_state.suggested_system_action.value == "ask_clarification"

    # --- Turn 2 ---
    user_msg_2 = "My budget is strictly $1000 and exclude ChromeOS."
    raw_extraction_2 = mock_extractor.extract_preferences(user_msg_2)
    assert_valid_session_context(raw_extraction_2)

    ctx_2 = dm.update_turn(session_id, user_msg_2, raw_extraction_2)
    assert ctx_2.session_intent.value == "refining_options"
    assert ctx_2.dialogue_state.ready_for_recommendation is True
    assert ctx_2.dialogue_state.suggested_system_action.value == "present_results"

    # --- Adapter step ---
    filters = filter_adapter(ctx_2.extracted_parameters.hard_constraints)
    legacy = legacy_adapter(ctx_2)

    assert filters.get("category") == "laptop"
    assert filters.get("price_max") == 1000.0
    assert "lightweight" in legacy["likes"]

    # --- Graph Search invocation ---
    candidates = mock_search.search("laptop", filters)
    assert len(candidates) > 0
    assert mock_search.last_query_filters["price_max"] == 1000.0


@pytest.mark.e2e
def test_e2e_schema_strictness_rejects_legacy_unwrapped_payload():
    """
    E2E Test: Verifies that legacy flat format (without current_session_context)
    is strictly rejected by the schema validation layer.
    """
    legacy_payload = {
        "likes": ["Apple", "lightweight"],
        "dislikes": ["Windows"],
        "constraints": {"price_range": "under 1000"},
        "intent": "recommendation",
        "notes": "Student laptop",
    }
    is_valid, errors = assert_valid_session_context, legacy_payload
    with pytest.raises(AssertionError) as exc_info:
        assert_valid_session_context(legacy_payload)
    assert "current_session_context" in str(exc_info.value)


@pytest.mark.e2e
def test_e2e_dialogue_state_invariants(dialogue_manager_factory):
    """
    E2E Test: Invariant verification that missing_critical_attributes cannot
    coexist with ready_for_recommendation=True in DialogueManager.
    """
    dm = dialogue_manager_factory(critical_attributes=["category", "budget"])
    ctx = dm.get_context("invariant_session")
    assert not (ctx.dialogue_state.ready_for_recommendation and len(ctx.dialogue_state.missing_critical_attributes) > 0)

    # Provide only category
    dm.update_turn("invariant_session", "laptop", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            }
        }
    })
    ctx_updated = dm.get_context("invariant_session")
    assert not (ctx_updated.dialogue_state.ready_for_recommendation and len(ctx_updated.dialogue_state.missing_critical_attributes) > 0)
