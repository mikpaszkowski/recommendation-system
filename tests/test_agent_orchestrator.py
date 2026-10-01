"""
tests/test_agent_orchestrator.py

Comprehensive test suite for AgentOrchestrator integration with DialogueManager
and SessionContext (Milestone 4).

Verifies:
1. Instantiation with default and injected DialogueManager and PreferenceParser.
2. Multi-turn preference accumulation and synchronization with active_filters.
3. Guardrail switching: SEARCH -> CLARIFY when critical attributes are missing.
4. Router fallback: uses session_context_to_dialogue_action on JSON parse errors.
5. Clarification prompt enrichment with missing critical attributes.
6. CriticAgent persona propagation via session_context_to_user_persona.
7. Session ID vs User ID separation.
8. Output dictionary includes canonical session_context.
9. Convenience accessors: get_session_context() and reset_session().
"""


from __future__ import annotations
from unittest.mock import MagicMock


import asyncio
import json
from typing import Any, Dict, List, Optional
import pytest

from src.agents.orchestrator import AgentOrchestrator
from src.dialog_manager.dialogue_manager import DialogueManager
from src.dialog_manager.session_schema import (
    CurrentSessionContextWrapper,
    SessionContext,
    SessionIntent,
    SuggestedSystemAction,
)
from src.dialog_manager.session_adapter import session_context_to_structured_filters
from src.conversation.history_manager import InMemoryHistoryManager
from src.user.profile_manager import InMemoryUserProfileManager
from src.tools.profile_tool import ProfileTool
from tests.e2e.schema_validator import assert_valid_session_context


# ==============================================================================
# Test Doubles (Mocks)
# ==============================================================================

class MockLLMHandler:
    """Configurable mock LLM handler returning queued or pattern-matched responses."""

    def __init__(self, default_response: str = '{"action": "ANSWER", "reasoning": "Default response"}'):
        self.default_response = default_response
        self.router_responses: List[str] = []
        self.search_param_responses: List[str] = []
        self.recorded_queries: List[Any] = []

    async def aquery(self, messages: Any) -> str:
        prompt_str = ""
        if isinstance(messages, list):
            prompt_str = " ".join([getattr(m, "content", str(m)) for m in messages])
        else:
            prompt_str = str(messages)
            
        self.recorded_queries.append(prompt_str)

        # 1. Check if router prompt
        if "Classify the user's intent into ONE action" in prompt_str or "AVAILABLE ACTIONS" in prompt_str:
            if self.router_responses:
                return self.router_responses.pop(0)
            return json.dumps({"action": "SEARCH", "reasoning": "Searching for items"})

        # 2. Check if search parameter generator prompt
        if "YOUR GOAL: Help the user find the perfect product" in prompt_str or "structured_filters" in prompt_str:
            if self.search_param_responses:
                return self.search_param_responses.pop(0)
            return json.dumps({
                "thought": "Extract search parameters",
                "structured_filters": {},
                "semantic_query": "laptop"
            })

        # 3. Check if clarify prompt
        if "clarifying question" in prompt_str.lower():
            return "Could you specify what product category or budget you are looking for?"

        # 4. Final recommendation or chit-chat answer
        return "Here is my response based on your request."


class MockGraphSearchTool:
    """Mock GraphSearchTool capturing search arguments and returning candidate items."""

    def __init__(self):
        self.search_calls: List[Dict[str, Any]] = []

    def search(self, semantic_query: Optional[str] = None, structured_filters: Optional[Dict[str, Any]] = None, limit: int = 5) -> Dict[str, Any]:
        self.search_calls.append({
            "semantic_query": semantic_query,
            "structured_filters": dict(structured_filters) if structured_filters else {},
            "limit": limit
        })
        return {
            "strategy": "hybrid",
            "count": 1,
            "items": [
                {
                    "asin": "B00TEST123",
                    "title": "Apple MacBook Air M1",
                    "price": 899.0,
                    "score": 0.96
                }
            ]
        }

    def fetch_product_attributes(self, asins: List[str]) -> Dict[str, Any]:
        return {asin: {"brand": "Apple", "category": "laptop"} for asin in asins}


class MockCriticAgent:
    """Mock CriticAgent capturing evaluated profiles."""

    def __init__(self):
        self.eval_calls: List[Dict[str, Any]] = []

    async def evaluate_candidates(self, profile: Dict[str, Any], candidates: List[Dict[str, Any]], attributes_map: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.eval_calls.append({
            "profile": profile,
            "candidates": candidates,
            "attributes_map": attributes_map
        })
        return candidates


class MockPreferenceParser:
    """Mock PreferenceParser returning canned extractions conforming to canonical schema."""

    def __init__(self):
        self.extractions: Dict[str, Dict[str, Any]] = {}

    def set_extraction(self, user_message: str, extraction: Dict[str, Any]) -> None:
        self.extractions[user_message] = extraction

    def extract_preferences(self, user_message: str) -> Dict[str, Any]:
        if user_message in self.extractions:
            return self.extractions[user_message]

        # Default fallback extraction
        return {
            "current_session_context": {
                "session_intent": "initial_search",
                "situational_context": f"Request: {user_message}",
                "extracted_parameters": {
                    "hard_constraints": [],
                    "soft_preferences": []
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results"
                }
            }
        }


# ==============================================================================
# Tests
# ==============================================================================

class TestAgentOrchestratorInitialization:
    """Test suite for AgentOrchestrator constructors and default configurations."""

    def test_default_instantiation(self):
        """Verifies default constructor wires DialogueManager and LLMPreferenceParser."""
        orchestrator = AgentOrchestrator()
        assert orchestrator.dialogue_manager is not None
        assert isinstance(orchestrator.dialogue_manager, DialogueManager)
        assert orchestrator.preference_parser is not None

    def test_custom_dependency_injection(self):
        """Verifies injecting custom DialogueManager and PreferenceParser."""
        custom_dm = DialogueManager(critical_attributes=["category", "price", "brand"])
        custom_parser = MockPreferenceParser()
        orchestrator = AgentOrchestrator(
            dialogue_manager=custom_dm,
            preference_parser=custom_parser
        )
        assert orchestrator.dialogue_manager is custom_dm
        assert orchestrator.preference_parser is custom_parser


class TestAgentOrchestratorMultiTurnExecution:
    """Test suite for multi-turn state accumulation, active filters, and routing."""

    def test_multi_turn_preference_accumulation_and_filter_sync(self):
        """
        Verify multi-turn flow:
        - Turn 1: user asks for a laptop -> DialogueManager accumulates category=laptop
        - Turn 2: user specifies budget < $1000 -> DialogueManager accumulates price < 1000
        - Verify active_filters passed into graph_tool.search() includes both category and price_max
        - Verify session_context is included in response payload and passes schema validation
        """
        async def _run():
            mock_llm = MockLLMHandler()
            mock_graph = MockGraphSearchTool()
            mock_critic = MockCriticAgent()
            mock_parser = MockPreferenceParser()

            # Turn 1 extraction: category=laptop, missing price
            mock_parser.set_extraction("I want a laptop", {
                "current_session_context": {
                    "session_intent": "initial_search",
                    "situational_context": "User needs a laptop",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "category", "operator": "include", "value": "laptop"}
                        ],
                        "soft_preferences": []
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results"
                    }
                }
            })

            # Turn 2 extraction: price < 1000
            mock_parser.set_extraction("My budget is under $1000", {
                "current_session_context": {
                    "session_intent": "refining_options",
                    "situational_context": "User sets budget under 1000",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "price", "operator": "less_than", "value": 1000}
                        ],
                        "soft_preferences": []
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results"
                    }
                }
            })

            dm = DialogueManager(critical_attributes=["category"])
            orchestrator = AgentOrchestrator(
                graph_tool=mock_graph,
                llm_handler=mock_llm,
                critic_agent=mock_critic,
                dialogue_manager=dm,
                preference_parser=mock_parser,
                kecr_tool=MagicMock()
            )

            user_id = "test_user_multi_turn"

            # --- Turn 1 ---
            res1 = await orchestrator.run(user_id=user_id, user_message="I want a laptop")
            assert res1["action"] == "SEARCH"
            assert "session_context" in res1
            assert_valid_session_context({"current_session_context": res1["session_context"]})
            assert res1["session_context"]["session_intent"] == "initial_search"
            
            # Verify GraphSearchTool received category
            assert len(mock_graph.search_calls) == 1
            filters1 = mock_graph.search_calls[0]["structured_filters"]
            assert filters1.get("category") == "laptop"

            # --- Turn 2 ---
            res2 = await orchestrator.run(user_id=user_id, user_message="My budget is under $1000")
            assert res2["action"] == "SEARCH"
            assert "session_context" in res2
            assert_valid_session_context({"current_session_context": res2["session_context"]})
            assert res2["session_context"]["session_intent"] == "refining_options"

            # Verify GraphSearchTool accumulated BOTH category and price_max
            assert len(mock_graph.search_calls) == 2
            filters2 = mock_graph.search_calls[1]["structured_filters"]
            assert filters2.get("category") == "laptop"
            assert filters2.get("price_max") == 1000.0

        asyncio.run(_run())

    def test_guardrail_switches_search_to_clarify_when_critical_attributes_missing(self):
        """
        Verify guardrail: If the router chooses SEARCH, but dialogue_state indicates
        ready_for_recommendation is False and critical attributes are missing (e.g. category),
        _decide_next_step switches the action to CLARIFY.
        """
        async def _run():
            mock_llm = MockLLMHandler()
            # Router attempts to do SEARCH
            mock_llm.router_responses = [json.dumps({"action": "SEARCH", "reasoning": "Premature search"})]

            mock_parser = MockPreferenceParser()
            # Turn extraction missing category
            mock_parser.set_extraction("I want something cheap", {
                "current_session_context": {
                    "session_intent": "initial_search",
                    "situational_context": "User wants something cheap without stating category",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "price", "operator": "less_than", "value": 300}
                        ],
                        "soft_preferences": []
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": False,
                        "missing_critical_attributes": ["category"],
                        "suggested_system_action": "ask_clarification"
                    }
                }
            })

            dm = DialogueManager(critical_attributes=["category"])
            orchestrator = AgentOrchestrator(
                llm_handler=mock_llm,
                dialogue_manager=dm,
                preference_parser=mock_parser,
                kecr_tool=MagicMock()
            )

            res = await orchestrator.run(user_id="user_guardrail", user_message="I want something cheap")
            assert res["action"] == "CLARIFY"
            # Verify clarification was called
            assert "clarifying question" in mock_llm.recorded_queries[-1].lower() or "critical details are missing" in mock_llm.recorded_queries[-1].lower()

        asyncio.run(_run())

    def test_router_fallback_to_dialogue_action_on_json_error(self):
        """
        Verify that on router JSON parse failure, orchestrator falls back to
        session_context_to_dialogue_action(current_context).
        """
        async def _run():
            mock_llm = MockLLMHandler()
            # Bad JSON from LLM
            mock_llm.router_responses = ["THIS IS NOT VALID JSON AT ALL"]

            mock_parser = MockPreferenceParser()
            mock_parser.set_extraction("Looking for Dell laptops", {
                "current_session_context": {
                    "session_intent": "initial_search",
                    "situational_context": "Looking for Dell laptops",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "category", "operator": "include", "value": "laptop"},
                            {"attribute": "brand", "operator": "include", "value": "Dell"}
                        ],
                        "soft_preferences": []
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results"
                    }
                }
            })

            dm = DialogueManager(critical_attributes=["category"])
            orchestrator = AgentOrchestrator(
                llm_handler=mock_llm,
                dialogue_manager=dm,
                preference_parser=mock_parser,
                kecr_tool=MagicMock()
            )

            # Since suggested_system_action is present_results -> fallback should be SEARCH
            res = await orchestrator.run(user_id="user_fallback", user_message="Looking for Dell laptops")
            assert res["action"] == "SEARCH"

        asyncio.run(_run())

    def test_critic_agent_receives_session_persona(self):
        """
        Verify that CriticAgent receives a user persona constructed from
        session_context soft preferences and situational context.
        """
        async def _run():
            mock_llm = MockLLMHandler()
            mock_graph = MockGraphSearchTool()
            mock_critic = MockCriticAgent()
            mock_parser = MockPreferenceParser()

            mock_parser.set_extraction("I want a lightweight Apple laptop for college", {
                "current_session_context": {
                    "session_intent": "initial_search",
                    "situational_context": "College student needing portable laptop",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "category", "operator": "include", "value": "laptop"},
                            {"attribute": "brand", "operator": "include", "value": "Apple"}
                        ],
                        "soft_preferences": [
                            {"category": "weight", "value": "lightweight", "polarity": 0.9, "confidence": 0.95, "evidence": "mentioned lightweight"}
                        ]
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results"
                    }
                }
            })

            orchestrator = AgentOrchestrator(
                graph_tool=mock_graph,
                llm_handler=mock_llm,
                critic_agent=mock_critic,
                dialogue_manager=DialogueManager(),
                preference_parser=mock_parser,
                kecr_tool=MagicMock()
            )

            await orchestrator.run(user_id="user_critic_persona", user_message="I want a lightweight Apple laptop for college")
            assert len(mock_critic.eval_calls) == 1
            evaluated_profile = mock_critic.eval_calls[0]["profile"]
            
            # Verify persona in profile["preferences"]
            critic_prefs = evaluated_profile.get("preferences", {})
            assert any("brand == Apple" in req for req in critic_prefs.get("hard_requirements", []))
            assert any("lightweight" in pref for pref in critic_prefs.get("preferred_qualities", []))
            assert "College student" in critic_prefs.get("situational_context", "")

        asyncio.run(_run())

    def test_session_id_isolation_and_convenience_accessors(self):
        """
        Verify:
        - Passing an explicit session_id isolates state from default user_id session.
        - orchestrator.get_session_context(session_id) returns canonical wrapper.
        - orchestrator.reset_session(session_id) clears dialogue state.
        """
        async def _run():
            mock_parser = MockPreferenceParser()
            mock_parser.set_extraction("Turn for session A", {
                "current_session_context": {
                    "session_intent": "initial_search",
                    "situational_context": "Session A query",
                    "extracted_parameters": {
                        "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                        "soft_preferences": []
                    },
                    "dialogue_state": {"ready_for_recommendation": True, "missing_critical_attributes": [], "suggested_system_action": "present_results"}
                }
            })

            orchestrator = AgentOrchestrator(
                llm_handler=MockLLMHandler(),
                dialogue_manager=DialogueManager(),
                preference_parser=mock_parser,
                kecr_tool=MagicMock()
            )

            user_id = "user_common"
            session_a = "session_A"
            session_b = "session_B"

            await orchestrator.run(user_id=user_id, user_message="Turn for session A", session_id=session_a)

            # Check session A
            wrapper_a = orchestrator.get_session_context(session_a)
            assert isinstance(wrapper_a, CurrentSessionContextWrapper)
            assert len(wrapper_a.current_session_context.extracted_parameters.hard_constraints) == 1
            assert wrapper_a.current_session_context.extracted_parameters.hard_constraints[0].value == "laptop"

            # Check session B (isolated, empty)
            wrapper_b = orchestrator.get_session_context(session_b)
            assert len(wrapper_b.current_session_context.extracted_parameters.hard_constraints) == 0

            # Reset session A
            orchestrator.reset_session(session_a)
            wrapper_a_cleared = orchestrator.get_session_context(session_a)
            assert len(wrapper_a_cleared.current_session_context.extracted_parameters.hard_constraints) == 0

        asyncio.run(_run())
