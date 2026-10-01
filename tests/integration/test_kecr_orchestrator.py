"""
Integration tests for the Orchestrator with the KECR tool.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agents.orchestrator import AgentOrchestrator
from src.tools.kecr_tool import PathExtractionResult, GraphReasoningPath
from src.dialog_manager.session_schema import SessionContext, DialogueState, SessionIntent
from langchain_core.messages import HumanMessage

import asyncio

def test_orchestrator_integrates_kecr_tool():
    """Test that AgentOrchestrator successfully calls KECR tool during SEARCH action."""
    async def _run():
        mock_graph_tool = MagicMock()
        mock_graph_tool.search.return_value = {
            "items": [{"asin": "A123", "title": "Phone"}],
            "strategy": "VECTOR_ONLY",
            "count": 1
        }
        mock_graph_tool.fetch_product_attributes.return_value = {}

        mock_profile_tool = MagicMock()
        mock_profile_tool.get_profile.return_value = {}

        mock_history_manager = MagicMock()
        mock_history_manager.get_history.return_value = []

        mock_critic_agent = AsyncMock()
        mock_critic_agent.evaluate_candidates.return_value = [{"asin": "A123", "title": "Phone"}]
        
        mock_llm_handler = AsyncMock()
        # First response for router
        mock_llm_handler.aquery.side_effect = [
            '{"action": "SEARCH", "reasoning": "User wants to search", "semantic_query": "cool phone", "structured_filters": {}}',
            '{"action": "SEARCH", "reasoning": "Search generated", "semantic_query": "cool phone", "structured_filters": {}}',
            "Final LLM recommendation response"
        ]

        mock_dialogue_manager = MagicMock()
        session_context = SessionContext(
            user_id="U1",
            session_id="S1",
            dialogue_state=DialogueState(ready_for_recommendation=True),
            session_intent=SessionIntent.INITIAL_SEARCH
        )
        mock_dialogue_manager.update_turn.return_value = session_context
        mock_dialogue_manager.get_context.return_value = session_context

        mock_preference_parser = MagicMock()
        mock_preference_parser.extract_preferences.return_value = {}

        mock_kecr_tool = MagicMock()
        mock_kecr_tool.extract_paths.return_value = PathExtractionResult(
            user_id="U1",
            gating_alpha=0.4,
            total_paths_extracted=1,
            paths=[
                GraphReasoningPath(
                    target_asin="A123",
                    target_title="Phone",
                    path_type="CONVERSATIONAL_MATCH",
                    composite_score=0.8,
                    historical_score=0.0,
                    conversational_score=0.8,
                    reasoning_path="Matches requested brand"
                )
            ]
        )
        # Re-assign serialized dict
        mock_kecr_tool.extract_paths.return_value.serialized_evidence_dict = [
            {"target_item": "Phone", "reasoning_path": "Matches requested brand"}
        ]

        orchestrator = AgentOrchestrator(
            graph_tool=mock_graph_tool,
            profile_tool=mock_profile_tool,
            llm_handler=mock_llm_handler,
            history_manager=mock_history_manager,
            critic_agent=mock_critic_agent,
            dialogue_manager=mock_dialogue_manager,
            preference_parser=mock_preference_parser,
            kecr_tool=mock_kecr_tool
        )

        result = await orchestrator.run(user_id="U1", user_message="I want a phone")

        assert result["action"] == "SEARCH"
        assert result["answer"] == "Final LLM recommendation response"
        
        # Assert KECR tool was called
        mock_kecr_tool.extract_paths.assert_called_once()
        args, kwargs = mock_kecr_tool.extract_paths.call_args
        assert kwargs["user_id"] == "U1"
        assert kwargs["candidate_items"] == [{"asin": "A123", "title": "Phone"}]
        assert kwargs["session_context"] == session_context
    asyncio.run(_run())
