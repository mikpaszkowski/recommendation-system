"""
tests/test_hyde_retrieval.py

Unit and integration test suite for RS-08a & AI-10 Dual-Channel HyDE
(Hypothetical Document Embeddings for product and review channels).
Verifies Acceptance Criteria AC-HYDE-001 through AC-HYDE-007 of
production_artifacts/Technical_Specification_HyDE.md.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.agents.orchestrator import (
    HYDE_GENERATION_RULE,
    HYDE_PRODUCT_MAX_CHARS,
    HYDE_REVIEW_MAX_CHARS,
    SEARCH_GENERATION_PROMPT,
    AgentOrchestrator,
    _normalize_hyde_product,
    _normalize_hyde_review,
)
from src.dialog_manager.dialogue_manager import DialogueManager
from src.tools.graph_search_tool import GraphSearchTool
from src.tools.score_fusion import FUSION_ARMS, FusionConfig
from tests.test_agent_orchestrator import (
    MockCriticAgent,
    MockLLMHandler,
    MockPreferenceParser,
)
from tests.test_graph_search_tool import CHANNEL_ROWS, FakeSession, _details


class RecordingGraphSearchTool:
    """Test double that records all kwargs passed to search()."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def search(
        self,
        semantic_query: Optional[str] = "",
        structured_filters: Optional[Dict[str, Any]] = None,
        limit: int = 5,
        soft_preferences: Optional[List[Dict[str, Any]]] = None,
        hyde_product: Optional[str] = None,
        hyde_review: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append({
            "semantic_query": semantic_query,
            "structured_filters": dict(structured_filters or {}),
            "soft_preferences": list(soft_preferences or []),
            "limit": limit,
            "hyde_product": hyde_product,
            "hyde_review": hyde_review,
            **kwargs,
        })
        return {
            "status": "success",
            "strategy": "hybrid_multi_index",
            "count": 1,
            "items": [
                {
                    "asin": "B00HYDE001",
                    "title": "Silent Mechanical Keyboard",
                    "price": 89.0,
                    "brand": "Keychron",
                    "category": ["Keyboards"],
                    "score": 0.049,
                }
            ],
            "metadata": {"cypher": "", "params": {}},
        }

    def fetch_product_attributes(self, asins: List[str], **kwargs: Any) -> Dict[str, Any]:
        return {asin: [{"name": "Switch", "value": "Silent Red", "source": "catalog"}] for asin in asins}


class TestHydePromptAndNormalization:
    """AC-HYDE-001, AC-HYDE-002, AC-HYDE-003: Prompt rules, template normalization, and guards."""

    def test_search_prompt_includes_hyde_rules_and_preserves_rs23(self) -> None:
        """AC-HYDE-001: SEARCH_GENERATION_PROMPT specifies hyde_product and hyde_review while preserving RS-23."""
        assert "hyde_product" in SEARCH_GENERATION_PROMPT
        assert "hyde_review" in SEARCH_GENERATION_PROMPT
        assert HYDE_GENERATION_RULE in SEARCH_GENERATION_PROMPT
        assert "Product: <generic product title>. Category: <category>." in SEARCH_GENERATION_PROMPT
        assert "When `product_type_decided` is false, `hyde_product` MUST be null." in SEARCH_GENERATION_PROMPT
        assert "When `product_type_decided` is false, `hyde_review` MUST be null." in SEARCH_GENERATION_PROMPT
        # Preserve RS-23 invariants
        assert "UPDATE `price_max` to 1500." in SEARCH_GENERATION_PROMPT
        assert "Copy numbers exactly as the user states them; never rescale, round or convert units." in SEARCH_GENERATION_PROMPT
        assert "Never guess a category." in SEARCH_GENERATION_PROMPT

    def test_normalize_hyde_product_template_and_truncation(self) -> None:
        """AC-HYDE-002: _normalize_hyde_product wraps bare text into Product: template and caps length."""
        already_templated = (
            "Product: Silent Tenkeyless Keyboard. Category: Keyboards. "
            "Features: Linear Red Switches, Dampening Foam. Description: Quiet typing."
        )
        assert _normalize_hyde_product(already_templated, "keyboard") == already_templated

        # Bare description gets wrapped into the canonical product_text_v1 format
        wrapped = _normalize_hyde_product("Compact 65W GaN wall charger with 4 USB-C ports", "wall charger")
        assert wrapped is not None
        assert wrapped.startswith("Product: Compact 65W GaN wall charger")
        assert "Category: wall charger." in wrapped
        assert "Description: Compact 65W GaN wall charger" in wrapped

        # Long text is truncated to HYDE_PRODUCT_MAX_CHARS
        huge = "Product: " + ("X" * 1500)
        normalized_huge = _normalize_hyde_product(huge)
        assert normalized_huge is not None
        assert len(normalized_huge) == HYDE_PRODUCT_MAX_CHARS

        # Null-like values return None
        for empty_val in (None, "", "   ", "null", "None", "N/A", "unknown", 123):
            assert _normalize_hyde_product(empty_val, "laptop") is None

    def test_normalize_hyde_review_truncation_and_nulls(self) -> None:
        """AC-HYDE-002: _normalize_hyde_review strips null-like strings and truncates to 800 chars."""
        review = "Whisper-quiet keys.   I use this keyboard every night and nobody hears a thing."
        assert _normalize_hyde_review(review) == "Whisper-quiet keys. I use this keyboard every night and nobody hears a thing."

        long_review = "Great build. " + ("A" * 1000)
        truncated = _normalize_hyde_review(long_review)
        assert truncated is not None
        assert len(truncated) == HYDE_REVIEW_MAX_CHARS

        for empty_val in (None, "", "  ", "null", "NONE", "n/a", ["list"]):
            assert _normalize_hyde_review(empty_val) is None

    def test_generate_search_params_clears_hyde_when_product_type_undecided(self) -> None:
        """AC-HYDE-003: When product_type_decided is False, hyde_product and hyde_review are None."""
        llm = MockLLMHandler()
        llm.search_param_responses = [
            json.dumps({
                "thought": "User has not decided on product type",
                "product_type_decided": False,
                "structured_filters": {"category": None, "price_max": 80},
                "semantic_query": "college dorm gift",
                "hyde_product": "Product: Desk Lamp. Category: Lamps. Features: LED. Description: Lamp.",
                "hyde_review": "Nice lamp for a dorm.",
            }),
            json.dumps({
                "thought": "User wants a mechanical keyboard",
                "product_type_decided": True,
                "structured_filters": {"category": "keyboard", "price_max": 100},
                "semantic_query": "silent mechanical keyboard",
                "hyde_product": "Silent TKL Mechanical Keyboard with linear switches",
                "hyde_review": "Super quiet keys. Works great at night.",
            }),
        ]
        orch = AgentOrchestrator(
            graph_tool=RecordingGraphSearchTool(),
            llm_handler=llm,
            critic_agent=MockCriticAgent(),
            dialogue_manager=DialogueManager(critical_attributes=["category"]),
            preference_parser=MockPreferenceParser(),
            kecr_tool=MagicMock(),
        )

        undecided_res = asyncio.run(orch._generate_search_params("something for a dorm under $80", {}, ""))
        assert undecided_res["product_type_decided"] is False
        assert undecided_res["hyde_product"] is None
        assert undecided_res["hyde_review"] is None

        decided_res = asyncio.run(orch._generate_search_params("silent keyboard under $100", {}, ""))
        assert decided_res["product_type_decided"] is True
        assert decided_res["hyde_product"].startswith("Product: Silent TKL Mechanical Keyboard")
        assert "Category: keyboard." in decided_res["hyde_product"]
        assert decided_res["hyde_review"] == "Super quiet keys. Works great at night."


class TestGraphSearchToolHydeRouting:
    """AC-HYDE-004, AC-HYDE-005, AC-HYDE-006, AC-HYDE-007: Per-channel vector routing & ablation arms."""

    @staticmethod
    def _make_tool(session: FakeSession, fusion_config: Optional[FusionConfig] = None) -> GraphSearchTool:
        connector = MagicMock()
        connector.session.return_value.__enter__.return_value = session
        embedder = MagicMock()

        def _fake_embed(text: str) -> List[float]:
            if text.startswith("Product:"):
                return [1.0, 0.0, 0.0]
            if text.startswith("Whisper-quiet"):
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]

        embedder.embed_query.side_effect = _fake_embed
        gst = GraphSearchTool(
            db_connector=connector,
            embedding_service=embedder,
            resolver=MagicMock(),
            fusion_config=fusion_config or FUSION_ARMS["rrf3"],
        )
        gst.resolver = None
        return gst

    def test_per_channel_hyde_vector_routing(self) -> None:
        """AC-HYDE-004: product channel receives v_product, review receives v_review, attribute receives v_query."""
        session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
        gst = self._make_tool(session, FUSION_ARMS["rrf3"])

        hyde_prod = "Product: Silent Mechanical Keyboard. Category: Keyboards. Features: Silent Red. Description: Quiet."
        hyde_rev = "Whisper-quiet keys. I type all night without waking anyone."
        res = gst.search(
            semantic_query="quiet keyboard",
            structured_filters={"price_max": 100},
            limit=3,
            hyde_product=hyde_prod,
            hyde_review=hyde_rev,
        )

        vectors_by_index: Dict[str, List[float]] = {}
        for cypher, params in session.calls:
            for index_name in ("product_embedding_index", "attribute_embedding_index", "review_embedding_index"):
                if index_name in cypher:
                    vectors_by_index[index_name] = params["vector"]

        assert vectors_by_index["product_embedding_index"] == [1.0, 0.0, 0.0]
        assert vectors_by_index["review_embedding_index"] == [0.0, 1.0, 0.0]
        assert vectors_by_index["attribute_embedding_index"] == [0.0, 0.0, 1.0]
        assert res["metadata"]["hyde"] == {
            "enabled": True,
            "product_used": True,
            "review_used": True,
            "hyde_product": hyde_prod,
            "hyde_review": hyde_rev,
        }

    def test_no_hyde_ablation_arm_forces_semantic_query_vector(self) -> None:
        """AC-HYDE-005: rrf3_no_hyde (use_hyde=False) ignores hyde_product/hyde_review and uses v_query everywhere."""
        session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
        gst = self._make_tool(session, FUSION_ARMS["rrf3_no_hyde"])

        res = gst.search(
            semantic_query="quiet keyboard",
            structured_filters={"price_max": 100},
            limit=3,
            hyde_product="Product: Silent Mechanical Keyboard. Category: Keyboards. Features: . Description: Quiet.",
            hyde_review="Whisper-quiet keys. Great keyboard.",
        )

        assert gst.embedder.embed_query.call_count == 1
        for cypher, params in session.calls:
            if "queryNodes" in cypher:
                assert params["vector"] == [0.0, 0.0, 1.0]
        assert res["metadata"]["hyde"] == {
            "enabled": False,
            "product_used": False,
            "review_used": False,
            "hyde_product": None,
            "hyde_review": None,
        }
        assert FUSION_ARMS["hyde_only"].channels == ("product", "review")
        assert FUSION_ARMS["hyde_only"].use_hyde is True

    def test_missing_hyde_falls_back_to_query_vector_without_extra_embeds(self) -> None:
        """AC-HYDE-006: When hyde_product/hyde_review are None, only 1 embed_query call is made."""
        session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
        gst = self._make_tool(session, FUSION_ARMS["rrf3"])

        res = gst.search(semantic_query="quiet keyboard", structured_filters={"price_max": 100}, limit=3)

        assert gst.embedder.embed_query.call_count == 1
        assert res["metadata"]["hyde"]["product_used"] is False
        assert res["metadata"]["hyde"]["review_used"] is False

    def test_macs_relaxation_preserves_hyde_vectors(self) -> None:
        """AC-HYDE-007: MACS progressive relaxation passes preserve hyde_product and hyde_review vectors."""
        rows = {"product": [{"asin": "A", "similarity": 0.9, "reason": "Product Title Match"}]}
        session = FakeSession(channel_rows=rows, details=_details("A"))
        gst = self._make_tool(session, FUSION_ARMS["rrf3"])

        res = gst.search(
            semantic_query="quiet keyboard",
            structured_filters={"price_max": 60.0, "category": "Keyboards"},
            limit=5,
            hyde_product="Product: Silent Keyboard. Category: Keyboards. Features: . Description: Quiet.",
            hyde_review="Whisper-quiet keys. Solid build.",
        )

        assert "relaxed_constraints" in res
        product_calls = [p for c, p in session.calls if "product_embedding_index" in c]
        review_calls = [p for c, p in session.calls if "review_embedding_index" in c]
        assert len(product_calls) >= 2
        assert all(p["vector"] == [1.0, 0.0, 0.0] for p in product_calls)
        assert all(p["vector"] == [0.0, 1.0, 0.0] for p in review_calls)

    def test_orchestrator_forwards_hyde_to_graph_tool_and_eval_trace(self) -> None:
        """FR-HYDE-003: AgentOrchestrator forwards hyde_product and hyde_review to search() and eval_trace."""
        llm = MockLLMHandler()
        llm.search_param_responses = [json.dumps({
            "thought": "User wants a quiet mechanical keyboard under $100",
            "product_type_decided": True,
            "structured_filters": {"category": "keyboard", "price_max": 100},
            "semantic_query": "quiet mechanical keyboard",
            "hyde_product": "Product: Silent Mechanical Keyboard. Category: Keyboards. Features: Silent Red Switches. Description: Noiseless typing.",
            "hyde_review": "Whisper-quiet keys. I code late at night and my roommate never hears a click.",
        })]
        parser = MockPreferenceParser()
        msg = "I need a quiet mechanical keyboard under $100"
        parser.set_extraction(msg, {
            "current_session_context": {
                "session_intent": "initial_search",
                "situational_context": "Night coding keyboard",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "category", "operator": "include", "value": "keyboard"},
                        {"attribute": "price", "operator": "less_than", "value": 100},
                    ],
                    "soft_preferences": [
                        {"category": "noise_level", "value": "quiet", "polarity": 0.9, "confidence": 0.9, "evidence": "quiet"}
                    ],
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results",
                },
            }
        })
        graph_tool = RecordingGraphSearchTool()
        orch = AgentOrchestrator(
            graph_tool=graph_tool,  # type: ignore[arg-type]
            llm_handler=llm,
            critic_agent=MockCriticAgent(),
            dialogue_manager=DialogueManager(critical_attributes=["category"]),
            preference_parser=parser,
            kecr_tool=MagicMock(),
        )

        result = asyncio.run(orch.run(user_id="u_hyde", user_message=msg))

        assert result["action"] == "SEARCH"
        assert len(graph_tool.calls) == 1
        call = graph_tool.calls[0]
        assert call["hyde_product"].startswith("Product: Silent Mechanical Keyboard.")
        assert call["hyde_review"].startswith("Whisper-quiet keys.")
        search_req = result["eval_trace"]["search_request"]
        assert search_req["hyde_product"] == call["hyde_product"]
        assert search_req["hyde_review"] == call["hyde_review"]
