"""
Unit and integration tests for Stage 0 of the Graph v2 Consumption Package
(GV2-01 through GV2-06).
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.critic_agent import CriticAgent
from src.agents.orchestrator import AgentOrchestrator
from src.dialog_manager.session_schema import DialogueState, SessionContext, SessionIntent
from src.llm_interface.prompt_constructor import PromptConstructor
from src.tools.graph_search_tool import DETAIL_QUERY, GraphSearchTool
from src.tools.kecr_tool import KnowledgePathExtractor, PathExtractionResult
from src.tools.score_fusion import FUSION_ARMS
from tests.test_graph_search_tool import CHANNEL_ROWS, FakeSession, _tool_with


# ---------------------------------------------------------------------------
# GV2-01: DETAIL_QUERY & Rich Product Fields Wiring
# ---------------------------------------------------------------------------

def test_gv2_01_detail_query_and_fused_items_include_v2_fields():
    """GV2-01: DETAIL_QUERY and _execute_fused_search return features, details_text, description, avg_rating."""
    for field_expr in ("node.features AS features", "node.details_text AS details_text",
                       "node.description AS description", "node.avg_rating AS avg_rating"):
        assert field_expr in DETAIL_QUERY

    details = {
        "A": {
            "title": "Webcam A",
            "price": 49.0,
            "brand": "Logitech",
            "category": ["Webcams"],
            "id": "id-A",
            "features": ["1080p 60fps", "Built-in privacy shutter"],
            "details_text": "Connectivity: USB-C; Resolution: 1920x1080",
            "description": ["Full HD streaming webcam for low light."],
            "avg_rating": 4.6,
        },
        "B": {"title": "Webcam B", "price": 39.0, "brand": "BrandB", "category": ["Webcams"], "id": "id-B"},
        "C": {"title": "Webcam C", "price": 59.0, "brand": "BrandC", "category": ["Webcams"], "id": "id-C"},
    }
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=details)
    gst = _tool_with(session)

    res = gst.search(semantic_query="1080p webcam", structured_filters={"price_max": 60}, limit=3)
    by_asin = {i["asin"]: i for i in res["items"]}

    assert by_asin["A"]["features"] == ["1080p 60fps", "Built-in privacy shutter"]
    assert by_asin["A"]["details_text"] == "Connectivity: USB-C; Resolution: 1920x1080"
    assert by_asin["A"]["description"] == ["Full HD streaming webcam for low light."]
    assert by_asin["A"]["avg_rating"] == pytest.approx(4.6)


def test_gv2_01_critic_agent_receives_rich_product_fields():
    """GV2-01: CriticAgent includes features, details_text, description, and avg_rating in its evaluation prompt."""
    async def _run():
        captured_prompts = []

        async def fake_aquery(messages):
            captured_prompts.append(messages[0].content)
            return '{"fit_score": 92, "reasoning": "Has 1080p and privacy shutter.", "is_recommended": true}'

        llm = MagicMock()
        llm.aquery = AsyncMock(side_effect=fake_aquery)
        critic = CriticAgent(llm_handler=llm)

        candidates = [{
            "asin": "B001",
            "title": "Pro Stream Webcam",
            "price": 69.99,
            "brand": "Logitech",
            "category": ["Webcams"],
            "avg_rating": 4.7,
            "features": ["True 1080p at 60fps", "Integrated privacy cover"],
            "details_text": "Interface: USB 3.0; Focus Type: Autofocus",
            "description": ["Designed for professional video conferencing."],
        }]
        approved = await critic.evaluate_candidates({"preferences": {"feature": "privacy cover"}}, candidates, {})

        assert len(approved) == 1
        assert len(captured_prompts) == 1
        prompt_text = captured_prompts[0]
        assert "Rating: 4.7" in prompt_text
        assert "Feature Bullets: True 1080p at 60fps; Integrated privacy cover" in prompt_text
        assert "Technical Details: Interface: USB 3.0; Focus Type: Autofocus" in prompt_text
        assert "Description: Designed for professional video conferencing." in prompt_text

    asyncio.run(_run())


def test_gv2_01_prompt_constructor_formats_v2_fields_and_avg_rating():
    """GV2-01: PromptConstructor formats list features, avg_rating, details_text, description, and Critic notes."""
    pc = PromptConstructor()
    messages = pc.construct_recommendation_prompt(
        user_query="I need a 1080p webcam with privacy shutter",
        retrieved_items=[{
            "title": "Pro Stream Webcam",
            "category": ["Webcams"],
            "brand": "Logitech",
            "price": 69.99,
            "avg_rating": 4.7,
            "features": ["True 1080p at 60fps", "Integrated privacy cover"],
            "details_text": "Interface: USB 3.0",
            "description": "Broadcast-grade streaming camera.",
            "score": 0.88,
            "partial_match": True,
            "critic_reasoning": "Matches 1080p and privacy shutter, but USB-C was not confirmed.",
        }],
        relaxed_constraints=["Widened budget ceiling by 15%"],
    )
    content = messages[1].content
    assert "- Rating: 4.7/5.0" in content
    assert "- Features: True 1080p at 60fps; Integrated privacy cover" in content
    assert "- Technical Details: Interface: USB 3.0" in content
    assert "- Description: Broadcast-grade streaming camera." in content
    assert "- Match Status: Partial match" in content
    assert "- Critic Assessment: Matches 1080p and privacy shutter" in content
    assert "[RELAXED CONSTRAINTS]" in content
    assert "Widened budget ceiling by 15%" in content


# ---------------------------------------------------------------------------
# GV2-02: AI-06 Review Sorting & Per-Product Subquery Limit
# ---------------------------------------------------------------------------

def test_gv2_02_fetch_product_attributes_uses_per_product_subquery_and_v2_review_properties():
    """GV2-02 (AI-06): fetch_product_attributes queries reviews per product using helpful_vote and timestamp."""
    calls = []

    class AttrSession:
        def run(self, cypher, **kwargs):
            calls.append((cypher, kwargs))
            if "HAS_ATTRIBUTE" in cypher:
                return [{"asin": "A1", "name": "Color", "value": "Black", "source": "catalog"}]
            return [
                {"asin": "A1", "name": "Great mic", "value": "Clear audio", "source": "user_review"},
                {"asin": "A2", "name": "Solid build", "value": "Works well", "source": "user_review"},
            ]

    connector = MagicMock()
    connector.session.return_value.__enter__.return_value = AttrSession()
    gst = GraphSearchTool(db_connector=connector, embedding_service=MagicMock(), resolver=MagicMock())

    res = gst.fetch_product_attributes(["A1", "A2"])

    assert len(calls) == 2
    rev_cypher, rev_params = calls[1]
    assert "UNWIND $asins AS asin" in rev_cypher
    assert "CALL {" in rev_cypher
    assert "r.helpful_vote" in rev_cypher
    assert "r.timestamp" in rev_cypher
    assert "LIMIT $reviews_per_product" in rev_cypher
    assert "LIMIT 20" not in rev_cypher
    assert rev_params["reviews_per_product"] == 5
    assert len(res["A1"]) == 2
    assert len(res["A2"]) == 1


# ---------------------------------------------------------------------------
# GV2-03: Multi-Value `brands`, `exclude_brands`, and `categories` Filters
# ---------------------------------------------------------------------------

def test_gv2_03_normalize_and_build_filters_support_brands_exclude_brands_and_categories_lists(caplog):
    """GV2-03: _normalize_filters and _build_filters handle list-valued brands, exclude_brands, and categories."""
    resolver = MagicMock()
    resolver.resolve_brand.side_effect = lambda b, k=1: [{"name": b.upper(), "score": 0.95}]
    resolver.resolve_category.side_effect = lambda c, k=3: [{"name": c.capitalize(), "score": 0.90, "path": [c.capitalize()]}]

    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=resolver)

    raw_filters = {
        "brand": "asus",
        "brands": ["asus", "dell"],
        "exclude_brands": ["hp", "acer"],
        "categories": ["laptops", "notebooks"],
        "unknown_custom_key": "foo",
    }
    norm = gst._normalize_filters(raw_filters)
    assert norm["brands"] == ["ASUS", "DELL"]
    assert norm["exclude_brands"] == ["HP", "ACER"]
    assert norm["categories"] == ["Laptops", "Notebooks"]

    with caplog.at_level(logging.WARNING):
        where, params = gst._build_filters(norm, raw_filters)

    # Single 'brand' must not emit a separate AND clause when 'brands' list is present
    assert "brand_filter" not in params
    assert params["brands_filter"] == ["ASUS", "DELL"]
    assert params["exclude_brands_filter"] == ["HP", "ACER"]
    assert len(params["categories_filter"]) == 2
    assert any("ANY(bf IN $brands_filter" in w for w in where)
    assert any("ANY(ebf IN $exclude_brands_filter" in w for w in where)
    assert any("ANY(cat_rx IN $categories_filter" in w for w in where)
    assert any("Ignoring unhandled filter key: 'unknown_custom_key'" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# GV2-04: Soft-Preference Bonus Deduplication Across Unit Variations
# ---------------------------------------------------------------------------

def test_gv2_04_soft_preference_unit_variations_award_single_bonus_per_requirement():
    """GV2-04: Unit variations ('128', '128GB', '128 GB') of one requirement award 1x bonus_unit, not 3x."""
    details = {
        "A": {"title": "Laptop A 128GB SSD (128 GB) 16GB RAM", "price": 500.0, "brand": "Asus", "category": ["Laptops"], "id": "id-A"},
        "B": {"title": "Laptop B 128GB SSD", "price": 500.0, "brand": "Asus", "category": ["Laptops"], "id": "id-B"},
        "C": {"title": "Laptop C 64GB SSD", "price": 500.0, "brand": "Asus", "category": ["Laptops"], "id": "id-C"},
    }
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=details)
    gst = _tool_with(session)
    unit = FUSION_ARMS["rrf3"].soft_bonus_unit()

    soft_prefs = [
        {"category": "storage", "value": "128", "polarity": 1.0},
        {"category": "storage", "value": "128GB", "polarity": 1.0},
        {"category": "storage", "value": "128 GB", "polarity": 1.0},
        {"category": "ram", "value": "16", "polarity": 1.0},
        {"category": "ram", "value": "16GB", "polarity": 1.0},
    ]

    res = gst.search(semantic_query="laptop", structured_filters={"price_max": 600}, limit=3, soft_preferences=soft_prefs)
    by_asin = {i["asin"]: i for i in res["items"]}

    # B matches storage (128 / 128GB) -> exactly 1 * unit (not 2 * unit)
    assert by_asin["B"]["soft_bonus"] == pytest.approx(1.0 * unit)
    # A matches storage (128 / 128GB / 128 GB) AND ram (16 / 16GB) -> 2 * unit (not 5 * unit)
    assert by_asin["A"]["soft_bonus"] == pytest.approx(2.0 * unit)
    # C matches neither -> 0.0
    assert by_asin["C"]["soft_bonus"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# GV2-05: Critic Fail-Closed & Orchestrator Partial-Match Fallback
# ---------------------------------------------------------------------------

def test_gv2_05_critic_agent_fails_closed_on_llm_exception():
    """GV2-05: CriticAgent rejects a candidate (is_recommended=False, semantic_score=0) when LLM fails."""
    async def _run():
        llm = MagicMock()
        llm.aquery = AsyncMock(side_effect=RuntimeError("API timeout"))
        critic = CriticAgent(llm_handler=llm)

        candidates = [{"asin": "B001", "title": "Untested Product", "price": 99.0, "score": 0.85}]
        approved = await critic.evaluate_candidates({"preferences": {}}, candidates, {})

        assert approved == []
        assert len(critic.last_evaluated_candidates) == 1
        evaluated = critic.last_evaluated_candidates[0]
        assert evaluated["is_recommended"] is False
        assert evaluated["semantic_score"] == 0
        assert evaluated["eval_error"] is True

    asyncio.run(_run())


def test_gv2_05_orchestrator_falls_back_to_top3_partial_matches_when_critic_rejects_all():
    """GV2-05: When Critic rejects all candidates, Orchestrator passes top-3 RRF partial matches to KECR & PromptConstructor."""
    async def _run():
        mock_graph_tool = MagicMock()
        raw_items = [
            {"asin": "A1", "title": "Monitor 1", "price": 210.0, "score": 0.048},
            {"asin": "A2", "title": "Monitor 2", "price": 220.0, "score": 0.045},
            {"asin": "A3", "title": "Monitor 3", "price": 230.0, "score": 0.042},
            {"asin": "A4", "title": "Monitor 4", "price": 240.0, "score": 0.039},
        ]
        mock_graph_tool.search.return_value = {
            "items": list(raw_items),
            "strategy": "hybrid_multi_index",
            "count": 4,
            "relaxed_constraints": ["Widened budget ceiling by 15%"],
        }
        mock_graph_tool.fetch_product_attributes.return_value = {}

        mock_critic = MagicMock()
        mock_critic.evaluate_candidates = AsyncMock(return_value=[])
        mock_critic.last_evaluated_candidates = [
            {"asin": "A1", "is_recommended": False, "reasoning": "Refresh rate is 75Hz instead of requested 144Hz."},
            {"asin": "A2", "is_recommended": False, "reasoning": "Missing DisplayPort cable info."},
        ]

        mock_llm = AsyncMock()
        mock_llm.aquery.side_effect = [
            '{"action": "SEARCH", "reasoning": "Search", "semantic_query": "144hz monitor", "structured_filters": {"price_max": 200}}',
            '{"thought": "Search", "semantic_query": "144hz monitor", "structured_filters": {"price_max": 200}}',
            "Here are the closest partial matches with budget relaxation disclosed.",
        ]

        mock_dm = MagicMock()
        session_context = SessionContext(
            user_id="U1",
            session_id="S1",
            dialogue_state=DialogueState(ready_for_recommendation=True),
            session_intent=SessionIntent.INITIAL_SEARCH,
        )
        mock_dm.update_turn.return_value = session_context
        mock_dm.get_context.return_value = session_context

        mock_parser = MagicMock()
        mock_parser.extract_preferences.return_value = {}

        mock_kecr = MagicMock()
        mock_kecr.extract_paths.return_value = PathExtractionResult(
            user_id="U1", gating_alpha=0.0, total_paths_extracted=0, paths=[], serialized_evidence_dict=[]
        )

        orchestrator = AgentOrchestrator(
            graph_tool=mock_graph_tool,
            profile_tool=MagicMock(get_profile=MagicMock(return_value={})),
            llm_handler=mock_llm,
            history_manager=MagicMock(get_history=MagicMock(return_value=[])),
            critic_agent=mock_critic,
            dialogue_manager=mock_dm,
            preference_parser=mock_parser,
            kecr_tool=mock_kecr,
        )

        res = await orchestrator.run(user_id="U1", user_message="144hz monitor under $200")

        # eval_trace preserves rejected_all verdict and empty critic_reranked for evaluation integrity
        assert res["eval_trace"]["critic_reranked"] == []
        assert res["eval_trace"]["critic_verdict"]["status"] == "rejected_all"
        assert res["eval_trace"]["critic_verdict"]["fallback_partial_count"] == 3

        # Top-3 partial matches were passed to KECR and PromptConstructor
        partial_items = res["data"]["items"]
        assert [i["asin"] for i in partial_items] == ["A1", "A2", "A3"]
        assert all(i.get("partial_match") is True for i in partial_items)
        assert "75Hz instead of requested 144Hz" in partial_items[0]["critic_reasoning"]

        final_prompt_messages = mock_llm.aquery.call_args_list[-1].args[0]
        final_prompt_text = final_prompt_messages[1].content
        assert "[RELAXED CONSTRAINTS]" in final_prompt_text
        assert "Widened budget ceiling by 15%" in final_prompt_text
        assert "Partial match" in final_prompt_text
        assert "75Hz instead of requested 144Hz" in final_prompt_text

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# GV2-06: Honest Fallback in KECR-Inspired Graph Evidence Path Extractor
# ---------------------------------------------------------------------------

def test_gv2_06_kecr_tool_does_not_fabricate_5_star_rating_in_cypher_fallback():
    """GV2-06: KnowledgePathExtractor Cypher query never fabricates coalesce(cand.avg_rating, 5.0)."""
    captured_queries = []

    class MockConnector:
        def execute_query(self, query, parameters=None):
            captured_queries.append(query)
            return [{
                "target_asin": "B001",
                "target_item": "USB Hub",
                "composite_score": 0.0,
                "historical_score": 0.0,
                "conversational_score": 0.0,
                "reasoning_path": "Matched via hybrid semantic retrieval (no explicit graph path).",
            }]

    extractor = KnowledgePathExtractor(db_connector=MockConnector())
    result = extractor.extract_paths(user_id="", candidate_items=[{"asin": "B001", "title": "USB Hub"}])

    assert len(captured_queries) == 1
    cypher = captured_queries[0]
    assert "coalesce(cand.avg_rating, 5.0)" not in cypher
    assert "Matched via hybrid semantic retrieval" in cypher
    assert result.paths[0].path_type == "SPARSE_FALLBACK"
    assert "5.0★" not in result.paths[0].reasoning_path
