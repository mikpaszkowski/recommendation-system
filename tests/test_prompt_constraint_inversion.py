"""
tests/test_prompt_constraint_inversion.py

Verification suite for AFP-004: Prompt Schema Realignment & Intent Inversion Elimination.
Covers Acceptance Criteria AC-004.1 through AC-004.5.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from src.agents.orchestrator import AgentOrchestrator
from src.dialog_manager.dialogue_manager import DialogueManager
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
from src.dialog_manager.session_adapter import hard_constraints_to_structured_filters
from src.llm_interface.preference_parser import (
    LLMPreferenceParser,
    VALID_OPERATORS,
    validate_hard_constraint,
)
from src.llm_interface.prompts import preference_extract_prompt
from src.tools.graph_search_tool import GraphSearchTool


def test_prompt_template_removes_negative_only_restriction():
    """AC-004.1: Prompt rule forbidding affirmative brand is removed from preference_extract_prompt.py."""
    prompt_text = preference_extract_prompt.get_system_prompt()
    assert 'brand (ONLY when the operator is "exclude")' not in prompt_text
    assert 'ONLY when operator is exclude' not in prompt_text
    assert 'EITHER affirmative inclusion OR negative exclusion' in prompt_text
    assert '"equal" or "include"' in prompt_text


def test_validate_hard_constraint_accepts_affirmative_brand():
    """AC-004.2: Preference parser accepts brand with operator equal and include."""
    assert validate_hard_constraint({"attribute": "brand", "operator": "equal", "value": "LG"}) is True
    assert validate_hard_constraint({"attribute": "brand", "operator": "include", "value": "Sony"}) is True
    assert validate_hard_constraint({"attribute": "brand", "operator": "exclude", "value": "Acer"}) is True
    assert validate_hard_constraint({"attribute": "category", "operator": "include", "value": "laptop"}) is True
    assert validate_hard_constraint({"attribute": "price", "operator": "less_than", "value": 150.0}) is True

    # Invalid cases
    assert validate_hard_constraint({"attribute": "brand", "operator": "less_than", "value": "LG"}) is False
    assert validate_hard_constraint({"attribute": "unknown_attr", "operator": "equal", "value": "val"}) is False
    assert validate_hard_constraint({"attribute": "brand", "operator": "equal", "value": ""}) is False


def test_affirmative_brand_parsing_and_sanitization():
    """AC-004.3: Extraction / parsing accepts affirmative brand 'LG' without inversion."""
    parser = LLMPreferenceParser()
    raw_payload = {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "User looking for LG monitor under $150",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "monitor"},
                    {"attribute": "price", "operator": "less_than", "value": 150.0},
                    {"attribute": "brand", "operator": "equal", "value": "LG"},
                ],
                "soft_preferences": [
                    {"category": "refresh_rate", "value": "144Hz", "polarity": 1.0, "confidence": 1.0, "evidence": "144Hz"}
                ]
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results"
            }
        }
    }

    parsed = parser._parse_response(raw_payload)
    ctx = parsed["current_session_context"]
    hard_constraints = ctx["extracted_parameters"]["hard_constraints"]
    brand_constraints = [c for c in hard_constraints if c["attribute"] == "brand"]

    assert len(brand_constraints) == 1
    assert brand_constraints[0]["value"] == "LG"
    assert brand_constraints[0]["operator"] in ["equal", "include"]
    assert brand_constraints[0]["operator"] != "exclude"

    # Adapter mapping
    filters = hard_constraints_to_structured_filters(hard_constraints)
    assert filters.get("brand") == "LG"
    assert "exclude_brand" not in filters


def test_orchestrator_routes_affirmative_brand_to_search():
    """AC-004.4: Dialogue router proceeds to SEARCH for well-specified brand queries."""
    async def _run():
        class MockRouterLLM:
            async def aquery(self, messages):
                prompt_str = " ".join([getattr(m, "content", str(m)) for m in messages]) if isinstance(messages, list) else str(messages)
                if "Classify the user's intent into ONE action" in prompt_str or "AVAILABLE ACTIONS" in prompt_str:
                    # Even if raw router tentatively suggested CLARIFY due to older logic,
                    # affirmative brand immunization should override to SEARCH
                    return json.dumps({"action": "CLARIFY", "reasoning": "Tentative clarification"})
                if "structured_filters" in prompt_str:
                    return json.dumps({"thought": "ok", "structured_filters": {"brand": "LG", "category": "monitor"}, "semantic_query": "monitor"})
                return json.dumps({"action": "SEARCH", "reasoning": "Searching"})

        class MockGraphTool:
            def __init__(self):
                self.search_calls = []

            def search(self, semantic_query=None, structured_filters=None, limit=5):
                self.search_calls.append({"semantic_query": semantic_query, "structured_filters": structured_filters})
                return {"strategy": "hybrid", "count": 1, "items": [{"asin": "B08TEST", "title": "LG 32-inch 4K Monitor", "price": 149.0}]}

            def fetch_product_attributes(self, asins):
                return {asin: [{"name": "brand", "value": "LG", "source": "catalog"}] for asin in asins}

        class MockCritic:
            async def evaluate_candidates(self, profile, candidates, attributes_map):
                return candidates

        class MockParser:
            async def aparse(self, text):
                return self.extract_preferences(text)

            def extract_preferences(self, text):
                return {
                    "current_session_context": {
                        "session_intent": "initial_search",
                        "situational_context": "Looking for LG monitor",
                        "extracted_parameters": {
                            "hard_constraints": [
                                {"attribute": "category", "operator": "include", "value": "monitor"},
                                {"attribute": "brand", "operator": "equal", "value": "LG"},
                                {"attribute": "price", "operator": "less_than", "value": 150.0}
                            ],
                            "soft_preferences": []
                        },
                        "dialogue_state": {
                            "ready_for_recommendation": True,
                            "missing_critical_attributes": [],
                            "suggested_system_action": "present_results"
                        }
                    }
                }

            def format_for_recommender(self, prefs):
                return {"preferences": {}}

        mock_graph = MockGraphTool()
        orchestrator = AgentOrchestrator(
            graph_tool=mock_graph,
            llm_handler=MockRouterLLM(),
            critic_agent=MockCritic(),
            dialogue_manager=DialogueManager(),
            preference_parser=MockParser(),
            kecr_tool=MagicMock()
        )

        utterance = "I want a 32-inch 4K 144Hz monitor for under $150 from LG"
        result = await orchestrator.run(user_id="test_user_lg", user_message=utterance)

        assert result["action"] == "SEARCH", f"Expected action 'SEARCH' but got '{result['action']}'"
        assert len(mock_graph.search_calls) == 1
        assert mock_graph.search_calls[0]["structured_filters"].get("brand") == "LG"

    import asyncio
    asyncio.run(_run())


def test_cypher_brand_filter_supports_corporate_suffixes():
    """AC-004.5: Cypher brand filter supports corporate suffixes via case-insensitive containment."""
    tool = object.__new__(GraphSearchTool)
    filters = {"brand": "Samsung", "category": "phone"}
    raw_filters = {"brand": "Samsung", "category": "phone"}

    where_clauses, params = tool._build_filters(filters, raw_filters=raw_filters)
    brand_clause = next((c for c in where_clauses if "HAS_BRAND" in c), None)

    assert brand_clause is not None, "Brand WHERE clause missing from _build_filters output"
    assert "toLower(b.name) = toLower($brand_filter)" in brand_clause
    assert "toLower(b.name) CONTAINS toLower($brand_filter)" in brand_clause
    assert "toLower($brand_filter) CONTAINS toLower(b.name)" in brand_clause
    assert params["brand_filter"] == "Samsung"
