"""
Unit and integration test suite for LLMPreferenceParser (Milestone 2).
Verifies:
1. Tool definition schema conformance to CurrentSessionContextWrapper.
2. Parser extraction with mock LLM handler emitting valid current_session_context.
3. Parsing fallback and error handling for malformed or partial completions.
4. format_for_recommender() compatibility with both canonical and legacy consumers.
5. Realistic multi-turn conversation extraction sequences covering all 5 session intents.

Executes 100% offline, deterministically, with no external OpenAI or Neo4j dependencies.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from src.dialog_manager.session_adapter import (
    hard_constraints_to_structured_filters,
    legacy_preferences_to_session_context,
    session_context_to_legacy_preferences,
)
from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContextWrapper,
    DialogueState,
    ExtractedParameters,
    HardConstraint,
    SessionContext,
    SessionIntent,
    SoftPreference,
    SuggestedSystemAction,
)
from src.llm.abstract_llm_handler import LLMHandlerInterface
from src.llm_interface.preference_parser import LLMPreferenceParser
from src.personalization.preference_quantifier import PreferenceQuantifier
from tests.e2e.schema_validator import assert_valid_session_context


# ============================================================================
# Deterministic Mock LLM Fixture & Harness
# ============================================================================

class MockLLMHandler(LLMHandlerInterface):
    """
    Deterministic mock LLM handler adhering to LLMHandlerInterface.
    Wraps a MagicMock(spec=ChatOpenAI) to satisfy LLMPreferenceParser
    initialization and enables preprogrammed response dispatching.
    """

    def __init__(
        self,
        responses: Optional[Dict[str, Any]] = None,
        default_response: Optional[Any] = None,
    ) -> None:
        self.responses: Dict[str, Any] = responses or {}
        self.default_response: Optional[Any] = default_response
        self.invoked_messages: List[Any] = []

        # Create mock ChatOpenAI instance supporting bind_tools
        self.llm = MagicMock(spec=ChatOpenAI)
        self.bound_mock = MagicMock()
        self.llm.bind_tools.return_value = self.bound_mock
        self.bound_mock.invoke.side_effect = self._handle_invoke

    def _handle_invoke(self, messages: Any) -> Any:
        self.invoked_messages.append(messages)

        # Extract human message text to match configured responses
        query_text = ""
        if isinstance(messages, list):
            for m in messages:
                if isinstance(m, tuple) and len(m) == 2 and m[0] == "human":
                    query_text = str(m[1])
                elif hasattr(m, "content") and getattr(m, "type", "") in ("human", "user"):
                    query_text = str(m.content)

        # Check keyword matches in query_text
        for pattern, response in self.responses.items():
            if pattern.lower() in query_text.lower():
                return self._to_ai_message(response)

        if self.default_response is not None:
            return self._to_ai_message(self.default_response)

        # Fallback default empty tool call
        empty_payload = CurrentSessionContextWrapper.create_empty().to_dict()
        return AIMessage(
            content="",
            tool_calls=[{
                "id": "call_default_empty",
                "name": "capture_preferences",
                "args": empty_payload,
            }],
        )

    def _to_ai_message(self, response: Any) -> Any:
        if isinstance(response, AIMessage):
            return response
        if isinstance(response, Exception):
            raise response
        if isinstance(response, dict):
            # Check if dict represents tool call wrapper or direct payload
            if "name" in response and "args" in response:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "id": response.get("id", "call_mock_1"),
                        "name": response["name"],
                        "args": response["args"],
                    }],
                )
            # Default to wrapping under capture_preferences tool call
            return AIMessage(
                content="",
                tool_calls=[{
                    "id": "call_mock_1",
                    "name": "capture_preferences",
                    "args": response,
                }],
            )
        if isinstance(response, str):
            return AIMessage(content=response)
        return AIMessage(content=str(response))

    def query(self, messages: List[Any]) -> str:
        return ""

    async def aquery(self, messages: List[Any]) -> str:
        return ""


@pytest.fixture
def canonical_session_payload() -> Dict[str, Any]:
    """Authoritative sample payload from ORIGINAL_REQUEST.md lines 46-88."""
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


# ============================================================================
# Suite 1: Tool Definition Schema Conformance to CurrentSessionContextWrapper
# ============================================================================

class TestCapturePreferencesToolSchema:
    """Verifies that the capture tool conforms strictly to the schema specification."""

    def test_tool_name_and_description(self):
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)
        tool = parser.capture_preferences_tool

        assert tool.name == "capture_preferences"
        assert len(tool.description) > 0

    def test_tool_args_schema_is_current_session_context_wrapper(self):
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)
        tool = parser.capture_preferences_tool

        schema = tool.get_input_schema().model_json_schema()
        assert "current_session_context" in schema.get("properties", {})
        assert schema.get("required") == ["current_session_context"] or "current_session_context" in schema.get("properties", {})

    def test_tool_json_schema_defs_conformance(self):
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)
        tool = parser.capture_preferences_tool

        schema = tool.get_input_schema().model_json_schema()
        defs = schema.get("$defs", {})

        # Ensure all key domain models are represented in schema definitions
        for expected_def in (
            "SessionIntent",
            "ConstraintOperator",
            "SuggestedSystemAction",
            "HardConstraint",
            "SoftPreference",
            "ExtractedParameters",
            "DialogueState",
            "SessionContext",
        ):
            assert expected_def in defs, f"Missing {expected_def} in tool schema $defs"

        # Verify SessionIntent enum values
        intent_enum = defs["SessionIntent"].get("enum", [])
        assert set(intent_enum) == {
            "initial_search",
            "exploring_domain",
            "refining_options",
            "comparing_items",
            "finalizing_choice",
        }

        # Verify ConstraintOperator enum values
        operator_enum = defs["ConstraintOperator"].get("enum", [])
        assert set(operator_enum) == {
            "include",
            "exclude",
            "greater_than",
            "less_than",
            "equal",
        }

    def test_tool_direct_invocation_valid_payload(self, canonical_session_payload):
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)
        tool = parser.capture_preferences_tool

        # Calling tool directly with valid wrapper payload
        result = tool.invoke(canonical_session_payload)
        assert result is not None
        # Must contain session context data
        if isinstance(result, dict):
            assert "current_session_context" in result or "session_intent" in result


# ============================================================================
# Suite 2: Parser Extraction with Mock LLM Emitting Valid current_session_context
# ============================================================================

class TestLLMPreferenceParserExtraction:
    """Verifies extraction output when mock LLM emits structured tool calls."""

    def test_extract_preferences_canonical_tool_call(self, canonical_session_payload):
        handler = MockLLMHandler(default_response=canonical_session_payload)
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("I need a lightweight laptop for college under $1000")

        # Must strictly have root wrapper
        assert "current_session_context" in result
        ctx = result["current_session_context"]

        # Validate schema fields
        assert ctx["session_intent"] == "refining_options"
        assert "lightweight" in ctx["situational_context"]

        # Hard constraints
        hard_constraints = ctx["extracted_parameters"]["hard_constraints"]
        assert len(hard_constraints) == 2
        price_constraint = next(c for c in hard_constraints if c["attribute"] == "price")
        assert price_constraint["operator"] == "less_than"
        assert price_constraint["value"] == 1000

        # Soft preferences
        soft_prefs = ctx["extracted_parameters"]["soft_preferences"]
        assert len(soft_prefs) == 2
        weight_pref = next(p for p in soft_prefs if p["category"] == "weight")
        assert weight_pref["polarity"] == 0.8
        assert weight_pref["confidence"] == 0.9

        # Dialogue state
        assert ctx["dialogue_state"]["ready_for_recommendation"] is False
        assert ctx["dialogue_state"]["missing_critical_attributes"] == ["screen_size"]
        assert ctx["dialogue_state"]["suggested_system_action"] == "ask_clarification"

        # Validate via Pydantic model
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert wrapper.session_intent == SessionIntent.REFINING_OPTIONS

        # Validate via Draft-7 JSON schema validator
        assert_valid_session_context(result)

    def test_extract_preferences_auto_wrap_unwrapped_args(self, canonical_session_payload):
        """Verifies auto-wrap recovery when LLM omits the root 'current_session_context' key."""
        unwrapped_args = canonical_session_payload["current_session_context"]
        handler = MockLLMHandler(default_response=unwrapped_args)
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Looking for college laptop")
        assert "current_session_context" in result
        assert result["current_session_context"]["session_intent"] == "refining_options"
        assert_valid_session_context(result)

    def test_extract_preferences_string_numeric_coercion(self):
        """Verifies string currency / formatted number handling."""
        payload_with_string_numbers = {
            "current_session_context": {
                "session_intent": "initial_search",
                "situational_context": "Budget laptop",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "price", "operator": "less_than", "value": "$1,000"},
                    ],
                    "soft_preferences": [],
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results",
                },
            }
        }
        handler = MockLLMHandler(default_response=payload_with_string_numbers)
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Laptop under $1,000")
        assert "current_session_context" in result
        hc = result["current_session_context"]["extracted_parameters"]["hard_constraints"][0]
        assert hc["value"] == 1000 or hc["value"] == 1000.0
        assert_valid_session_context(result)

    def test_extract_preferences_prompt_invoked_correctly(self):
        """Verifies that user message content is included in LLM invocation messages."""
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)

        user_query = "Looking for high-end gaming laptops under $2000"
        parser.extract_preferences(user_query)

        assert len(handler.invoked_messages) == 1
        invoked = handler.invoked_messages[0]
        # Inspect human message
        human_text = ""
        for m in invoked:
            if isinstance(m, tuple) and m[0] == "human":
                human_text = m[1]
            elif getattr(m, "type", "") in ("human", "user"):
                human_text = getattr(m, "content", "")

        assert user_query in human_text

    def test_extract_preferences_legacy_format_adaptation(self):
        """Verifies that legacy dict output from LLM is adapted to valid current_session_context."""
        legacy_response = {
            "likes": ["MacBook", "Retina display"],
            "dislikes": ["ChromeOS"],
            "constraints": {"price_max": 1200, "brand": "Apple"},
            "intent": "recommendation",
            "notes": "User seeking MacBook under 1200",
        }
        handler = MockLLMHandler(default_response=legacy_response)
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Looking for MacBook")
        assert "current_session_context" in result
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert isinstance(wrapper.session_intent, SessionIntent)
        assert_valid_session_context(result)


# ============================================================================
# Suite 3: Parsing Fallback & Error Handling for Malformed or Partial Completions
# ============================================================================

class TestLLMPreferenceParserFallback:
    """Verifies that LLMPreferenceParser never crashes and falls back cleanly."""

    def test_fallback_on_malformed_json_content(self):
        """Malformed JSON string returned by LLM."""
        handler = MockLLMHandler(default_response=AIMessage(content='{"current_session_context": {invalid_json:'))
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Sample query")
        assert "current_session_context" in result
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert wrapper.session_intent == SessionIntent.INITIAL_SEARCH
        assert isinstance(wrapper.hard_constraints, list)
        assert_valid_session_context(result)

    def test_fallback_on_plain_text_completion(self):
        """LLM returns conversational text with no tool call."""
        handler = MockLLMHandler(default_response=AIMessage(content="I can help you search for laptops. What brand?"))
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Hello")
        assert "current_session_context" in result
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert wrapper.session_intent == SessionIntent.INITIAL_SEARCH
        assert_valid_session_context(result)

    def test_fallback_on_schema_validation_error(self):
        """Tool call with invalid enum value."""
        invalid_enum_payload = {
            "current_session_context": {
                "session_intent": "unsupported_nonexistent_phase",
                "situational_context": "Invalid intent test",
                "extracted_parameters": {"hard_constraints": [], "soft_preferences": []},
                "dialogue_state": {
                    "ready_for_recommendation": False,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "ask_clarification",
                },
            }
        }
        handler = MockLLMHandler(default_response=invalid_enum_payload)
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Sample query")
        assert "current_session_context" in result
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert isinstance(wrapper.session_intent, SessionIntent)
        assert_valid_session_context(result)

    def test_fallback_on_unrecognized_tool_name(self):
        """LLM calls a different tool than capture_preferences."""
        different_tool_call = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_different_tool",
                "name": "search_google",
                "args": {"query": "lightweight laptops"},
            }],
        )
        handler = MockLLMHandler(default_response=different_tool_call)
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Sample query")
        assert "current_session_context" in result
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert wrapper.session_intent == SessionIntent.INITIAL_SEARCH
        assert_valid_session_context(result)

    def test_fallback_on_llm_invocation_exception(self):
        """Underlying LLM throws network / timeout exception."""
        handler = MockLLMHandler(default_response=RuntimeError("OpenAI connection timeout"))
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("Sample query")
        assert "current_session_context" in result
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert wrapper.session_intent == SessionIntent.INITIAL_SEARCH
        assert_valid_session_context(result)

    def test_fallback_on_empty_string_completion(self):
        """Empty string completion."""
        handler = MockLLMHandler(default_response=AIMessage(content=""))
        parser = LLMPreferenceParser(llm_handler=handler)

        result = parser.extract_preferences("")
        assert "current_session_context" in result
        wrapper = CurrentSessionContextWrapper.model_validate(result)
        assert wrapper.session_intent == SessionIntent.INITIAL_SEARCH
        assert_valid_session_context(result)


# ============================================================================
# Suite 4: format_for_recommender() Compatibility
# ============================================================================

class TestFormatForRecommenderCompatibility:
    """Verifies that format_for_recommender produces both canonical and legacy outputs."""

    def test_format_for_recommender_canonical_session_context(self, canonical_session_payload):
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)

        formatted = parser.format_for_recommender(canonical_session_payload)

        # 1. Canonical structure preserved
        assert "current_session_context" in formatted
        assert formatted["current_session_context"]["session_intent"] == "refining_options"

        # 2. Legacy keys populated correctly
        assert "likes" in formatted
        assert "dislikes" in formatted
        assert "constraints" in formatted
        assert "intent" in formatted
        assert "notes" in formatted
        assert "weighted_preferences" in formatted

        # Check values
        assert "lightweight" in formatted["likes"]
        assert "Apple" in formatted["likes"]
        assert formatted["constraints"]["price_max"] == 1000.0
        assert formatted["constraints"]["exclude_operating_system"] == "ChromeOS"
        assert formatted["intent"] == "refining_options"
        assert "college" in formatted["notes"].lower()

        # Check weighted_preferences
        wp = formatted["weighted_preferences"]
        assert "likes" in wp
        assert len(wp["likes"]) == 2
        lightweight_wp = next(w for w in wp["likes"] if w["value"] == "lightweight")
        assert lightweight_wp["weight"] == 0.72  # 0.8 * 0.9 = 0.72
        assert lightweight_wp["confidence"] == 0.9

    def test_format_for_recommender_legacy_input_backward_compatibility(self):
        """Verifies that legacy input dicts are transformed gracefully without errors."""
        legacy_input = {
            "likes": ["MacBook", "Retina display"],
            "dislikes": ["heavy"],
            "constraints": {"price_max": 1500, "brand": "Apple"},
            "intent": "recommendation",
            "notes": "Student seeking Apple laptop",
        }
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)

        formatted = parser.format_for_recommender(legacy_input)

        assert "current_session_context" in formatted
        assert formatted["likes"] == ["MacBook", "Retina display"]
        assert formatted["dislikes"] == ["heavy"]
        assert formatted["constraints"]["price_max"] == 1500.0
        assert formatted["constraints"]["brand"] == "Apple"

    def test_format_for_recommender_empty_dict(self):
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)

        formatted = parser.format_for_recommender({})
        assert "current_session_context" in formatted
        assert formatted["likes"] == []
        assert formatted["dislikes"] == []
        assert formatted["constraints"] == {}
        assert isinstance(formatted["intent"], str)
        assert isinstance(formatted["notes"], str)
        assert "weighted_preferences" in formatted

    def test_format_for_recommender_pydantic_model_input(self, canonical_session_payload):
        """Verifies that passing a Pydantic CurrentSessionContextWrapper directly works."""
        wrapper = CurrentSessionContextWrapper.model_validate(canonical_session_payload)
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)

        formatted = parser.format_for_recommender(wrapper)
        assert "current_session_context" in formatted
        assert "lightweight" in formatted["likes"]
        assert formatted["constraints"]["price_max"] == 1000.0

    def test_format_for_recommender_with_preference_quantifier(self, canonical_session_payload):
        """Verifies that format_for_recommender integrates with downstream PreferenceQuantifier."""
        handler = MockLLMHandler()
        parser = LLMPreferenceParser(llm_handler=handler)
        quantifier = PreferenceQuantifier()

        formatted = parser.format_for_recommender(canonical_session_payload)
        quantified = quantifier.quantify(formatted)

        assert "weighted_preferences" in quantified
        assert len(quantified["weighted_preferences"]["likes"]) == 2
        assert quantified["intent"] == "refining_options"


# ============================================================================
# Suite 5: Multi-Turn Conversation Extraction Scenarios
# ============================================================================

class TestMultiTurnConversationExtraction:
    """Verifies realistic multi-turn conversation extraction flows across all 5 session intents."""

    def test_multiturn_college_laptop_scenario(self):
        """
        Scenario: College Student Budget Laptop Search (4-turn flow).
        - Turn 1: Initial search (lightweight, college).
        - Turn 2: Hard budget $1000, OS exclude ChromeOS.
        - Turn 3: Brand Apple preference.
        - Turn 4: Finalizing on MacBook Air M1 under $900.
        """
        turn_responses = {
            "college": {
                "current_session_context": {
                    "session_intent": "initial_search",
                    "situational_context": "Starting college computer science; needs lightweight laptop.",
                    "extracted_parameters": {
                        "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                        "soft_preferences": [
                            {"category": "weight", "value": "lightweight", "polarity": 0.85, "confidence": 0.9, "evidence": "easy carry"},
                        ],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": False,
                        "missing_critical_attributes": ["price"],
                        "suggested_system_action": "ask_clarification",
                    },
                }
            },
            "chromeos": {
                "current_session_context": {
                    "session_intent": "refining_options",
                    "situational_context": "Setting hard $1000 budget and excluding ChromeOS.",
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
                    },
                }
            },
            "macbook": {
                "current_session_context": {
                    "session_intent": "refining_options",
                    "situational_context": "Inquiring about Apple MacBooks in price range.",
                    "extracted_parameters": {
                        "hard_constraints": [],
                        "soft_preferences": [
                            {"category": "brand", "value": "Apple", "polarity": 0.6, "confidence": 0.7, "evidence": "asking if MacBooks go on sale"}
                        ],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    },
                }
            },
            "m1": {
                "current_session_context": {
                    "session_intent": "finalizing_choice",
                    "situational_context": "Deciding on MacBook Air M1 under $900.",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "model", "operator": "include", "value": "MacBook Air M1"},
                            {"attribute": "price", "operator": "less_than", "value": 900},
                        ],
                        "soft_preferences": [],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    },
                }
            },
        }

        handler = MockLLMHandler(responses=turn_responses)
        parser = LLMPreferenceParser(llm_handler=handler)

        # Turn 1
        t1 = parser.extract_preferences("I need a lightweight laptop for college.")
        assert t1["current_session_context"]["session_intent"] == "initial_search"
        assert t1["current_session_context"]["dialogue_state"]["ready_for_recommendation"] is False
        assert_valid_session_context(t1)

        # Turn 2
        t2 = parser.extract_preferences("My budget is under $1000 and exclude ChromeOS.")
        assert t2["current_session_context"]["session_intent"] == "refining_options"
        assert t2["current_session_context"]["dialogue_state"]["ready_for_recommendation"] is True
        assert_valid_session_context(t2)

        # Turn 3
        t3 = parser.extract_preferences("Are there any Apple MacBook options?")
        assert t3["current_session_context"]["session_intent"] == "refining_options"
        assert_valid_session_context(t3)

        # Turn 4
        t4 = parser.extract_preferences("I'll take the M1 under $900.")
        assert t4["current_session_context"]["session_intent"] == "finalizing_choice"
        assert_valid_session_context(t4)

        # Adapter translation verification on final turn
        formatted = parser.format_for_recommender(t4)
        assert formatted["constraints"]["price_max"] == 900.0

    def test_multiturn_gaming_rig_scenario(self):
        """
        Scenario: Gaming Rig Search.
        - Turn 1: Exploring domain for 4K ray tracing desktop PC.
        - Turn 2: Setting hard limits ($2500, RTX 4080, exclude refurbished).
        """
        responses = {
            "4k": {
                "current_session_context": {
                    "session_intent": "exploring_domain",
                    "situational_context": "User looking for desktop PC for 4K ray tracing.",
                    "extracted_parameters": {
                        "hard_constraints": [{"attribute": "category", "operator": "include", "value": "desktop PC"}],
                        "soft_preferences": [
                            {"category": "feature", "value": "ray tracing", "polarity": 0.95, "confidence": 0.9, "evidence": "4K gaming"}
                        ],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": False,
                        "missing_critical_attributes": ["price"],
                        "suggested_system_action": "ask_clarification",
                    },
                }
            },
            "2500": {
                "current_session_context": {
                    "session_intent": "refining_options",
                    "situational_context": "Budget $2500 max, RTX 4080, no refurbished.",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "price", "operator": "less_than", "value": 2500},
                            {"attribute": "gpu", "operator": "include", "value": "RTX 4080"},
                            {"attribute": "condition", "operator": "exclude", "value": "refurbished"},
                        ],
                        "soft_preferences": [],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    },
                }
            },
        }

        handler = MockLLMHandler(responses=responses)
        parser = LLMPreferenceParser(llm_handler=handler)

        t1 = parser.extract_preferences("What can I get for 4K ray tracing?")
        assert t1["current_session_context"]["session_intent"] == "exploring_domain"
        assert_valid_session_context(t1)

        t2 = parser.extract_preferences("My budget is 2500 max, RTX 4080, no refurbished.")
        assert t2["current_session_context"]["session_intent"] == "refining_options"
        assert t2["current_session_context"]["dialogue_state"]["ready_for_recommendation"] is True
        assert_valid_session_context(t2)

        formatted = parser.format_for_recommender(t2)
        assert formatted["constraints"]["price_max"] == 2500.0
        assert formatted["constraints"]["gpu"] == "RTX 4080"

    def test_multiturn_head_to_head_comparison_scenario(self):
        """
        Scenario: Head-to-Head ANC Headphones Comparison.
        - Turn 1: Comparing Sony WH-1000XM5 vs Bose QC Ultra.
        - Turn 2: Prioritizing ANC and compact travel case.
        - Turn 3: Final purchase selection of Bose.
        """
        responses = {
            "compare": {
                "current_session_context": {
                    "session_intent": "comparing_items",
                    "situational_context": "Comparing Sony WH-1000XM5 vs Bose QuietComfort Ultra for frequent flights.",
                    "extracted_parameters": {
                        "hard_constraints": [{"attribute": "category", "operator": "include", "value": "headphones"}],
                        "soft_preferences": [
                            {"category": "brand", "value": "Sony", "polarity": 0.5, "confidence": 0.8, "evidence": "evaluating XM5"},
                            {"category": "brand", "value": "Bose", "polarity": 0.5, "confidence": 0.8, "evidence": "evaluating QC Ultra"},
                        ],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    },
                }
            },
            "anc": {
                "current_session_context": {
                    "session_intent": "refining_options",
                    "situational_context": "Focusing on ANC quality and compact travel case.",
                    "extracted_parameters": {
                        "hard_constraints": [{"attribute": "category", "operator": "include", "value": "headphones"}],
                        "soft_preferences": [
                            {"category": "noise_cancellation", "value": "ANC", "polarity": 1.0, "confidence": 1.0, "evidence": "top priority"},
                            {"category": "portability", "value": "bulky case", "polarity": -0.85, "confidence": 0.9, "evidence": "hate bulky cases"},
                        ],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    },
                }
            },
            "bose": {
                "current_session_context": {
                    "session_intent": "finalizing_choice",
                    "situational_context": "Purchasing Bose QuietComfort Ultra.",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "brand", "operator": "include", "value": "Bose"},
                            {"attribute": "model", "operator": "equal", "value": "QuietComfort Ultra"},
                        ],
                        "soft_preferences": [],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    },
                }
            },
        }

        handler = MockLLMHandler(responses=responses)
        parser = LLMPreferenceParser(llm_handler=handler)

        t1 = parser.extract_preferences("Can you compare the Sony WH-1000XM5 and Bose QC Ultra?")
        assert t1["current_session_context"]["session_intent"] == "comparing_items"
        assert_valid_session_context(t1)

        t2 = parser.extract_preferences("ANC is my top priority and I want something that folds up compact.")
        assert t2["current_session_context"]["session_intent"] == "refining_options"
        assert_valid_session_context(t2)

        t3 = parser.extract_preferences("I'll get the Bose QC Ultra, where is it in stock?")
        assert t3["current_session_context"]["session_intent"] == "finalizing_choice"
        assert_valid_session_context(t3)
