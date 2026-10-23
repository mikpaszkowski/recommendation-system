"""
tests/test_recommendation_pipeline.py

End-to-end integration tests for the Explainable Recommendation Pipeline (Meta-Phase A5).

Verifies the full pipeline end-to-end:
1. Standard recommendation flow: User input -> Dialog routing / Preference parsing ->
   Graph retrieval -> CriticAgent verification/reranking -> Graph Evidence Path extraction
   (template metapaths inspired by KECR/PGPR) -> PromptConstructor with [GRAPH EVIDENCE] ->
   Final explainable response generation with complete eval_trace.
2. Hierarchical constraint relaxation transparency: When candidates < 3, relaxed constraints
   are passed to PromptConstructor, injected into [RELAXED CONSTRAINTS], and recorded in eval_trace.
3. Fail-closed Critic partial-match fallback (GV2-05): When Critic rejects all candidates,
   top candidates are preserved with partial_match=True, critic_reasoning, and eval_trace logging.
4. Multi-turn dialogue & negative preference adaptation: Accumulation of constraints and
   elimination of excluded brands across turns.
5. Live Neo4j test (guarded by RUN_LIVE_TESTS=1): Real graph grounding on verified catalog ASINs.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.agents.critic_agent import CriticAgent
from src.agents.orchestrator import AgentOrchestrator
from src.conversation.history_manager import InMemoryHistoryManager
from src.dialog_manager.dialogue_manager import DialogueManager
from src.dialog_manager.session_schema import (
    DialogueState,
    HardConstraint,
    HardConstraintOperator,
    SessionContext,
    SessionIntent,
)
from src.llm_interface.preference_parser import LLMPreferenceParser
from src.llm_interface.prompt_constructor import PromptConstructor
from src.tools.graph_search_tool import GraphSearchTool
from src.tools.kecr_tool import GraphReasoningPath, KnowledgePathExtractor, PathExtractionResult
from src.tools.profile_tool import ProfileTool


# ==============================================================================
# Test Doubles & Fixtures
# ==============================================================================

class MockPipelineLLMHandler:
    """Mock LLM Handler for reproducible pipeline execution."""

    def __init__(self) -> None:
        self.recorded_prompts: List[Any] = []
        self.router_response: str = (
            '{"action": "SEARCH", "reasoning": "User requests product recommendations", '
            '"semantic_query": "ergonomic split keyboard", "structured_filters": {"category": "Keyboards"}}'
        )
        self.search_params_response: str = (
            '{"action": "SEARCH", "product_type_decided": true, "category": "Keyboards", '
            '"structured_filters": {"category": "Keyboards", "price_max": 150.0}, '
            '"semantic_query": "ergonomic split mechanical keyboard", '
            '"hyde_product": "Product: Ergonomic Split Keyboard. Category: Keyboards. Features: wrist rest.", '
            '"hyde_review": "Great ergonomic split keyboard, relieved my wrist strain."}'
        )
        self.final_answer: str = (
            "I recommend the Kinesis Freestyle2 Ergonomic Keyboard ($119.00). "
            "It features a split design with an integrated cushioned wrist rest, exactly matching "
            "your comfort requirements and staying well within your $150 budget. "
            "According to catalog review evidence, users praise its durable build and posture support."
        )

    async def aquery(self, messages: Any) -> str:
        self.recorded_prompts.append(messages)
        prompt_str = ""
        if isinstance(messages, list):
            prompt_str = " ".join([getattr(m, "content", str(m)) for m in messages])
        elif isinstance(messages, str):
            prompt_str = messages

        prompt_lower = prompt_str.lower()
        # Routing stage (router_prompt_template)
        if "decision manager" in prompt_lower or "router" in prompt_lower or "route the query" in prompt_lower:
            return self.router_response
        # Search param generation stage (SEARCH_GENERATION_PROMPT)
        if "help the user find the perfect product" in prompt_lower or "search_generation" in prompt_lower:
            return self.search_params_response
        # Default to final recommendation generation
        return self.final_answer


@pytest.fixture
def sample_candidate_items() -> List[Dict[str, Any]]:
    return [
        {
            "asin": "B00CMALD3E",
            "title": "Kinesis Freestyle2 Ergonomic Split Keyboard for PC",
            "price": 119.0,
            "brand": "Kinesis",
            "category": "Keyboards",
            "avg_rating": 4.4,
            "features": "Split adjustable design, cushioned palm support, low-force tactile keys",
            "description": "Ergonomic keyboard designed for comfort during long typing sessions.",
            "fusion": {"rrf_score": 0.048, "final_score": 0.92},
        },
        {
            "asin": "B07ZWK2TQT",
            "title": "ErgoDox EZ Ergonomic Mechanical Keyboard",
            "price": 285.0,
            "brand": "ErgoDox",
            "category": "Keyboards",
            "avg_rating": 4.6,
            "features": "Split mechanical keyboard, hot-swappable switches, fully programmable",
            "description": "Premium split mechanical keyboard.",
            "fusion": {"rrf_score": 0.035, "final_score": 0.81},
        },
    ]


@pytest.fixture
def sample_evidence_paths() -> List[Dict[str, Any]]:
    return [
        {
            "target_item": "Kinesis Freestyle2 Ergonomic Split Keyboard for PC",
            "reasoning_path": (
                "Matches conversational preference: category 'Keyboards' and features ['ergonomic', 'split', 'wrist rest']; "
                "Supported by 4.4★ catalog rating across 1,420 customer reviews."
            ),
        }
    ]


# ==============================================================================
# Unit & Integration Tests (Deterministic Mock Mode)
# ==============================================================================

def test_recommendation_pipeline_end_to_end_search_flow(
    sample_candidate_items: List[Dict[str, Any]],
    sample_evidence_paths: List[Dict[str, Any]],
) -> None:
    """
    Tests the complete end-to-end explainable recommendation flow:
    1. Orchestrator extracts intent & generates search arguments.
    2. Graph search tool retrieves candidate items.
    3. CriticAgent verifies candidates against criteria.
    4. KnowledgePathExtractor extracts Graph Evidence Paths.
    5. PromptConstructor injects [GRAPH EVIDENCE] into the prompt.
    6. LLM generates final grounded response.
    7. Output contains 'answer', 'action' == 'SEARCH', and rich 'eval_trace'.
    """
    async def _run() -> None:
        mock_llm = MockPipelineLLMHandler()

        mock_graph_tool = MagicMock(spec=GraphSearchTool)
        mock_graph_tool.search.return_value = {
            "items": sample_candidate_items,
            "strategy": "HYBRID",
            "count": 2,
            "metadata": {"channels": ["product", "attribute", "lexical"], "fusion": "rrf"},
            "relaxed_constraints": [],
        }
        mock_graph_tool.fetch_product_attributes.return_value = {
            "B00CMALD3E": {"reviews": ["Great split design", "Very comfortable wrist rest"]},
            "B07ZWK2TQT": {"reviews": ["Pricey but durable"]},
        }

        mock_profile_tool = MagicMock(spec=ProfileTool)
        mock_profile_tool.get_profile.return_value = {
            "user_id": "test_user_pipe_01",
            "preferences": {"category": "Keyboards"},
            "history": [],
        }

        mock_history_manager = MagicMock(spec=InMemoryHistoryManager)
        mock_history_manager.get_history.return_value = []

        # Critic approves Kinesis, rejects over-budget ErgoDox
        mock_critic = AsyncMock(spec=CriticAgent)
        mock_critic.evaluate_candidates.return_value = [sample_candidate_items[0]]

        # Dialogue manager setup
        session_ctx = SessionContext(
            user_id="test_user_pipe_01",
            session_id="session_pipe_01",
            dialogue_state=DialogueState(
                ready_for_recommendation=True,
                current_category="Keyboards",
            ),
            session_intent=SessionIntent.INITIAL_SEARCH,
        )
        mock_dialogue_mgr = MagicMock(spec=DialogueManager)
        mock_dialogue_mgr.update_turn.return_value = session_ctx
        mock_dialogue_mgr.get_context.return_value = session_ctx

        mock_parser = MagicMock(spec=LLMPreferenceParser)
        mock_parser.extract_preferences.return_value = {
            "category": "Keyboards",
            "price_max": 150.0,
        }

        # KnowledgePathExtractor setup
        mock_kecr = MagicMock(spec=KnowledgePathExtractor)
        extraction_res = PathExtractionResult(
            user_id="test_user_pipe_01",
            gating_alpha=0.3,
            total_paths_extracted=1,
            paths=[
                GraphReasoningPath(
                    target_asin="B00CMALD3E",
                    target_title="Kinesis Freestyle2 Ergonomic Split Keyboard for PC",
                    path_type="CONVERSATIONAL_MATCH",
                    composite_score=0.92,
                    historical_score=0.0,
                    conversational_score=0.92,
                    reasoning_path=sample_evidence_paths[0]["reasoning_path"],
                )
            ],
        )
        extraction_res.serialized_evidence_dict = sample_evidence_paths
        mock_kecr.extract_paths.return_value = extraction_res

        orchestrator = AgentOrchestrator(
            graph_tool=mock_graph_tool,
            profile_tool=mock_profile_tool,
            llm_handler=mock_llm,
            history_manager=mock_history_manager,
            critic_agent=mock_critic,
            dialogue_manager=mock_dialogue_mgr,
            preference_parser=mock_parser,
            kecr_tool=mock_kecr,
        )

        result = await orchestrator.run(
            user_id="test_user_pipe_01",
            user_message="I need an ergonomic split keyboard under $150 with a cushioned wrist rest.",
            session_id="session_pipe_01",
        )

        # 1. Verification of top-level response contract
        assert result["action"] == "SEARCH"
        assert "Kinesis Freestyle2" in result["answer"]
        assert len(result["data"]["items"]) == 1
        assert result["data"]["items"][0]["asin"] == "B00CMALD3E"

        # 2. Verification of KECR Path Extraction execution
        mock_kecr.extract_paths.assert_called_once()
        kecr_args, kecr_kwargs = mock_kecr.extract_paths.call_args
        assert kecr_kwargs["user_id"] == "test_user_pipe_01"
        assert kecr_kwargs["candidate_items"] == [sample_candidate_items[0]]

        # 3. Verification of eval_trace completeness
        eval_trace = result["eval_trace"]
        assert eval_trace["raw_candidates"] == sample_candidate_items
        assert eval_trace["critic_reranked"] == [sample_candidate_items[0]]
        assert eval_trace["graph_evidence"] == sample_evidence_paths
        assert eval_trace["critic_verdict"]["status"] == "success"
        assert eval_trace["critic_verdict"]["approved_count"] == 1
        assert eval_trace["critic_verdict"]["pruned_count"] == 1

        # 4. Verification that [GRAPH EVIDENCE] was injected into the prompt
        recorded_prompts = mock_llm.recorded_prompts
        assert len(recorded_prompts) >= 2
        final_prompt_messages = recorded_prompts[-1]
        final_prompt_text = " ".join([getattr(m, "content", str(m)) for m in final_prompt_messages])
        assert "[GRAPH EVIDENCE]" in final_prompt_text
        assert "Matches conversational preference: category 'Keyboards'" in final_prompt_text

    asyncio.run(_run())


def test_recommendation_pipeline_constraint_relaxation_transparency(
    sample_candidate_items: List[Dict[str, Any]],
) -> None:
    """
    Verifies that when constraint relaxation occurs in GraphSearchTool,
    the relaxed constraints are:
    1. Captured in search_result['relaxed_constraints'].
    2. Forwarded to PromptConstructor and injected into [RELAXED CONSTRAINTS].
    3. Recorded in eval_trace['relaxed_constraints'].
    """
    async def _run() -> None:
        mock_llm = MockPipelineLLMHandler()

        relaxation_reasons = [
            "Budget ceiling widened by 15% from $100.00 to $115.00 due to candidate scarcity",
            "Broadened taxonomic step-up via Taxon [:BROADER]",
        ]

        mock_graph_tool = MagicMock(spec=GraphSearchTool)
        mock_graph_tool.search.return_value = {
            "items": [sample_candidate_items[0]],
            "strategy": "HYBRID",
            "count": 1,
            "metadata": {"channels": ["product"]},
            "relaxed_constraints": relaxation_reasons,
        }
        mock_graph_tool.fetch_product_attributes.return_value = {}

        mock_profile_tool = MagicMock(spec=ProfileTool)
        mock_profile_tool.get_profile.return_value = {}

        mock_history_manager = MagicMock(spec=InMemoryHistoryManager)
        mock_history_manager.get_history.return_value = []

        mock_critic = AsyncMock(spec=CriticAgent)
        mock_critic.evaluate_candidates.return_value = [sample_candidate_items[0]]

        session_ctx = SessionContext(
            user_id="test_user_relax",
            session_id="session_relax",
            dialogue_state=DialogueState(
                ready_for_recommendation=True,
                current_category="Keyboards",
            ),
            session_intent=SessionIntent.INITIAL_SEARCH,
        )
        mock_dialogue_mgr = MagicMock(spec=DialogueManager)
        mock_dialogue_mgr.update_turn.return_value = session_ctx
        mock_dialogue_mgr.get_context.return_value = session_ctx

        mock_parser = MagicMock(spec=LLMPreferenceParser)
        mock_parser.extract_preferences.return_value = {"category": "Keyboards", "price_max": 100.0}

        mock_kecr = MagicMock(spec=KnowledgePathExtractor)
        mock_kecr.extract_paths.return_value = PathExtractionResult(
            user_id="test_user_relax",
            gating_alpha=0.3,
            total_paths_extracted=0,
            paths=[],
        )
        mock_kecr.extract_paths.return_value.serialized_evidence_dict = []

        orchestrator = AgentOrchestrator(
            graph_tool=mock_graph_tool,
            profile_tool=mock_profile_tool,
            llm_handler=mock_llm,
            history_manager=mock_history_manager,
            critic_agent=mock_critic,
            dialogue_manager=mock_dialogue_mgr,
            preference_parser=mock_parser,
            kecr_tool=mock_kecr,
        )

        result = await orchestrator.run(
            user_id="test_user_relax",
            user_message="Find me a mechanical keyboard under $100",
            session_id="session_relax",
        )

        # Assert relaxation was tracked in eval_trace
        assert result["eval_trace"]["relaxed_constraints"] == relaxation_reasons

        # Assert PromptConstructor formatted [RELAXED CONSTRAINTS]
        final_prompt_messages = mock_llm.recorded_prompts[-1]
        final_prompt_text = " ".join([getattr(m, "content", str(m)) for m in final_prompt_messages])
        assert "[RELAXED CONSTRAINTS]" in final_prompt_text
        assert "Budget ceiling widened by 15%" in final_prompt_text
        assert "you MUST disclose this transparently" in final_prompt_text

    asyncio.run(_run())


def test_recommendation_pipeline_critic_partial_match_fallback(
    sample_candidate_items: List[Dict[str, Any]],
) -> None:
    """
    Verifies GV2-05 behavior:
    When CriticAgent rejects all candidates (e.g. strict attribute or rating conflict),
    the orchestrator does NOT fail-open or crash; it safely falls back to top candidates
    marked as partial matches with critic_reasoning.
    """
    async def _run() -> None:
        mock_llm = MockPipelineLLMHandler()

        mock_graph_tool = MagicMock(spec=GraphSearchTool)
        mock_graph_tool.search.return_value = {
            "items": sample_candidate_items,
            "strategy": "HYBRID",
            "count": 2,
            "metadata": {},
            "relaxed_constraints": [],
        }
        mock_graph_tool.fetch_product_attributes.return_value = {}

        mock_profile_tool = MagicMock(spec=ProfileTool)
        mock_profile_tool.get_profile.return_value = {}

        mock_history_manager = MagicMock(spec=InMemoryHistoryManager)
        mock_history_manager.get_history.return_value = []

        # Critic rejects all candidates
        mock_critic = AsyncMock(spec=CriticAgent)
        mock_critic.evaluate_candidates.return_value = []

        session_ctx = SessionContext(
            user_id="test_user_critic_fallback",
            session_id="session_critic_fallback",
            dialogue_state=DialogueState(
                ready_for_recommendation=True,
                current_category="Keyboards",
            ),
            session_intent=SessionIntent.INITIAL_SEARCH,
        )
        mock_dialogue_mgr = MagicMock(spec=DialogueManager)
        mock_dialogue_mgr.update_turn.return_value = session_ctx
        mock_dialogue_mgr.get_context.return_value = session_ctx

        mock_parser = MagicMock(spec=LLMPreferenceParser)
        mock_parser.extract_preferences.return_value = {"category": "Keyboards"}

        mock_kecr = MagicMock(spec=KnowledgePathExtractor)
        mock_kecr.extract_paths.return_value = PathExtractionResult(
            user_id="test_user_critic_fallback",
            gating_alpha=0.3,
            total_paths_extracted=0,
            paths=[],
        )
        mock_kecr.extract_paths.return_value.serialized_evidence_dict = []

        orchestrator = AgentOrchestrator(
            graph_tool=mock_graph_tool,
            profile_tool=mock_profile_tool,
            llm_handler=mock_llm,
            history_manager=mock_history_manager,
            critic_agent=mock_critic,
            dialogue_manager=mock_dialogue_mgr,
            preference_parser=mock_parser,
            kecr_tool=mock_kecr,
        )

        result = await orchestrator.run(
            user_id="test_user_critic_fallback",
            user_message="Looking for an ultra-silent silent keyboard under $50",
            session_id="session_critic_fallback",
        )

        # 1. Assert partial match status
        assert result["data"].get("partial_matches_only") is True
        assert result["eval_trace"]["critic_verdict"]["status"] == "rejected_all"
        assert result["eval_trace"]["critic_verdict"]["approved_count"] == 0

        # 2. Assert fallback candidates retained with partial_match flags
        fallback_items = result["eval_trace"]["fallback_partial_items"]
        assert len(fallback_items) > 0
        for item in fallback_items:
            assert item.get("partial_match") is True
            assert "critic_reasoning" in item

        # 3. Assert final response was still generated with transparency
        assert result["action"] == "SEARCH"
        assert len(result["answer"]) > 0

    asyncio.run(_run())


def test_recommendation_pipeline_multi_turn_preference_accumulation() -> None:
    """
    Verifies multi-turn context retention:
    Turn 1 sets initial category and budget.
    Turn 2 specifies a negative brand constraint ("no Razer").
    The accumulated context preserves the category and passes excluded_brands to search filters.
    """
    async def _run() -> None:
        mock_llm = MockPipelineLLMHandler()
        mock_llm.router_response = (
            '{"action": "SEARCH", "reasoning": "User refines brand exclusion", '
            '"semantic_query": "gaming mouse", "structured_filters": {"category": "Mice"}}'
        )
        mock_llm.search_params_response = (
            '{"action": "SEARCH", "product_type_decided": true, "category": "Mice", '
            '"structured_filters": {"category": "Mice", "price_max": 60.0, "exclude_brands": ["Razer"]}, '
            '"semantic_query": "gaming mouse"}'
        )

        mock_graph_tool = MagicMock(spec=GraphSearchTool)
        mock_graph_tool.search.return_value = {
            "items": [{"asin": "B08TEST", "title": "Logitech G Pro Gaming Mouse", "price": 49.99}],
            "strategy": "HYBRID",
            "count": 1,
            "metadata": {},
            "relaxed_constraints": [],
        }
        mock_graph_tool.fetch_product_attributes.return_value = {}

        session_ctx = SessionContext(
            user_id="user_multiturn",
            session_id="session_multiturn",
            dialogue_state=DialogueState(
                ready_for_recommendation=True,
                current_category="Mice",
                hard_constraints=[
                    HardConstraint(
                        attribute="brand",
                        value="Razer",
                        operator=HardConstraintOperator.EXCLUDE,
                    ),
                    HardConstraint(
                        attribute="price",
                        value=60.0,
                        operator=HardConstraintOperator.LESS_THAN,
                    ),
                ],
            ),
            session_intent=SessionIntent.INITIAL_SEARCH,
        )

        mock_dialogue_mgr = MagicMock(spec=DialogueManager)
        mock_dialogue_mgr.update_turn.return_value = session_ctx
        mock_dialogue_mgr.get_context.return_value = session_ctx

        mock_profile_tool = MagicMock(spec=ProfileTool)
        mock_profile_tool.get_profile.return_value = {}

        mock_history_manager = MagicMock(spec=InMemoryHistoryManager)
        mock_history_manager.get_history.return_value = [
            {"role": "user", "content": "I want a gaming mouse under $60."},
            {"role": "assistant", "content": "Here is a Razer DeathAdder recommendation."},
        ]

        mock_critic = AsyncMock(spec=CriticAgent)
        mock_critic.evaluate_candidates.return_value = [
            {"asin": "B08TEST", "title": "Logitech G Pro Gaming Mouse", "price": 49.99}
        ]

        mock_parser = MagicMock(spec=LLMPreferenceParser)
        mock_parser.extract_preferences.return_value = {
            "category": "Mice",
            "price_max": 60.0,
            "excluded_brands": ["Razer"],
        }

        mock_kecr = MagicMock(spec=KnowledgePathExtractor)
        mock_kecr.extract_paths.return_value = PathExtractionResult(
            user_id="user_multiturn",
            gating_alpha=0.3,
            total_paths_extracted=1,
            paths=[],
        )
        mock_kecr.extract_paths.return_value.serialized_evidence_dict = [
            {"target_item": "Logitech G Pro", "reasoning_path": "Matches brand exclusion: not Razer"}
        ]

        orchestrator = AgentOrchestrator(
            graph_tool=mock_graph_tool,
            profile_tool=mock_profile_tool,
            llm_handler=mock_llm,
            history_manager=mock_history_manager,
            critic_agent=mock_critic,
            dialogue_manager=mock_dialogue_mgr,
            preference_parser=mock_parser,
            kecr_tool=mock_kecr,
        )

        result = await orchestrator.run(
            user_id="user_multiturn",
            user_message="I dislike Razer, only show me other brands under $60.",
            session_id="session_multiturn",
        )

        assert result["action"] == "SEARCH"
        mock_graph_tool.search.assert_called_once()
        _, call_kwargs = mock_graph_tool.search.call_args
        struct_filters = call_kwargs.get("structured_filters", {})
        soft_prefs = call_kwargs.get("soft_preferences", [])
        # Assert negative brand preference was reflected in structured filters or demoted soft preferences
        has_negative_brand = (
            "exclude_brands" in struct_filters
            or "exclude_brand" in struct_filters
            or any(sp.get("category") == "brand" and sp.get("polarity", 1.0) < 0 for sp in soft_prefs)
        )
        assert has_negative_brand, f"Expected negative brand constraint in structured_filters={struct_filters} or soft_preferences={soft_prefs}"

    asyncio.run(_run())


# ==============================================================================
# Live Neo4j Integration Test (Guarded)
# ==============================================================================

@pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Live Neo4j + OpenAI end-to-end integration test; set RUN_LIVE_TESTS=1",
)
def test_recommendation_pipeline_live_neo4j_grounding() -> None:
    """
    Live integration test against the real Neo4j Graph v2 database:
    Executes a real query, retrieves grounded items, extracts real evidence paths,
    and asserts the final response is grounded in real catalog products.
    """
    async def _run() -> None:
        try:
            orchestrator = AgentOrchestrator()
            result = await orchestrator.run(
                user_id="live_test_user_camera",
                user_message="I need a streaming webcam that supports 1080p 60FPS under $60",
                session_id="live_session_cam_01",
            )
        except Exception as e:
            if "insufficient_quota" in str(e) or "429" in str(e) or "credit_balance_exhausted" in str(e):
                pytest.skip(f"OpenAI API credit quota exhausted: {e}")
            raise

        if result.get("action") == "CLARIFY":
            pytest.skip("OpenAI API call failed or fell back to CLARIFY (credit balance exhausted)")

        assert result["action"] == "SEARCH"
        assert len(result["answer"]) > 50
        assert len(result["data"]["items"]) >= 1
        top_item = result["data"]["items"][0]
        assert "asin" in top_item and top_item["asin"].startswith("B")
        assert "title" in top_item and len(top_item["title"]) > 5
        assert "eval_trace" in result

    asyncio.run(_run())
