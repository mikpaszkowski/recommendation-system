"""
Tests for Stage 1: Graph v2 Structural & Lexical Consumption (GV2-07 .. GV2-09).

Covers:
- GV2-07: Taxon category resolution, subtree filtering, and MACS BROADER relaxation (RS-24 / RS-10).
- GV2-08: Full-text lexical channel in RRF via product_fulltext_index (RS-03).
- GV2-09: Selectivity-based dynamic ANN oversampling for small Taxon subtrees (RS-07).
"""
import pytest
from unittest.mock import MagicMock, patch

from src.knowledge_graph.graphdb.resolver_service import ResolverService
from src.tools.graph_search_tool import GraphSearchTool
from src.tools.score_fusion import (
    CHANNELS,
    DEFAULT_ARM,
    FUSION_ARMS,
    ChannelHit,
    FusionConfig,
    competition_ranks,
    fuse,
)


# ---------------------------------------------------------------------------
# GV2-07: Taxon Resolution & Subtree Filtering
# ---------------------------------------------------------------------------

def test_gv2_07_resolver_service_resolves_taxon_tier1_exact():
    """AC-S1-01: ResolverService.resolve_category queries :Taxon and returns path and product_count."""
    connector = MagicMock()
    session = MagicMock()
    connector.session.return_value.__enter__.return_value = session

    # Mock Tier 1 exact match returning a Taxon record
    session.run.return_value = [
        {
            "name": "Bookshelf Speakers",
            "path": ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"],
            "product_count": 237,
            "depth": 4,
            "taxon_id": "Electronics > Home Audio > Speakers > Bookshelf Speakers",
            "score": 1.0,
        }
    ]

    resolver = ResolverService(connector=connector)
    matches = resolver.resolve_category("Bookshelf Speakers", k=3)

    assert len(matches) == 1
    assert matches[0]["name"] == "Bookshelf Speakers"
    assert matches[0]["score"] == 1.0
    assert matches[0]["product_count"] == 237
    assert len(matches[0]["path"]) == 4

    # Verify that the Cypher query targeted :Taxon, not :Category
    cypher_called = session.run.call_args_list[0][0][0]
    assert "MATCH (node:Taxon)" in cypher_called
    assert "COALESCE(node.product_count, 0) DESC" in cypher_called


def test_gv2_07_resolver_service_resolves_taxon_tier3_in_memory_vector():
    """AC-S1-01: Tier 3 vector semantic search over cached Taxon nodes works in-memory."""
    connector = MagicMock()
    session = MagicMock()
    connector.session.return_value.__enter__.return_value = session

    # Tier 1 and 2 return empty
    session.run.return_value = []

    embedder = MagicMock()
    embedder.embed_documents.return_value = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    embedder.embed_query.return_value = [0.99, 0.01, 0.0]

    resolver = ResolverService(connector=connector, embed_svc=embedder, min_score=0.50)
    resolver._taxon_cache = [
        {"name": "Bookshelf Speakers", "path": ["Audio", "Speakers"], "product_count": 100, "depth": 2, "taxon_id": "t1"},
        {"name": "Computer Monitors", "path": ["Computers", "Monitors"], "product_count": 500, "depth": 2, "taxon_id": "t2"},
    ]
    import numpy as np
    resolver._taxon_embeddings = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ], dtype=np.float32)

    matches = resolver.resolve_category("acoustic speakers", k=2)
    assert len(matches) >= 1
    assert matches[0]["name"] == "Bookshelf Speakers"
    assert matches[0]["score"] > 0.90


def test_gv2_07_build_filters_generates_taxon_subtree_cypher():
    """AC-S1-02: _build_filters uses IN_TAXON / BROADER*0..7 and quarantines title fallback."""
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock())

    filters = {"category": "Bluetooth Network Adapters", "price_max": 25.0}
    raw_filters = {"category": "Bluetooth Network Adapters", "price_max": 25.0}

    where, params = gst._build_filters(filters, raw_filters)

    assert "category_filter" in params
    assert params["category_filter"] == "Bluetooth Network Adapters"

    cat_where = [w for w in where if "IN_TAXON" in w]
    assert len(cat_where) == 1
    clause = cat_where[0]

    # Must traverse IN_TAXON and BROADER*0..7
    assert "(node)-[:IN_TAXON]->(leaf:Taxon)-[:BROADER*0..7]->(ancestor:Taxon)" in clause
    assert "toLower(ancestor.name) = toLower($category_filter)" in clause
    assert "toLower(leaf.name) = toLower($category_filter)" in clause
    # Title condition must be gated by NOT EXISTS IN_TAXON
    assert "NOT EXISTS { MATCH (node)-[:IN_TAXON]->(:Taxon) }" in clause


def test_gv2_07_build_filters_categories_list_generates_taxon_subtree_cypher():
    """AC-S1-02: Multi-category filters also traverse IN_TAXON / BROADER*0..7."""
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock())

    filters = {"categories": ["Keyboards", "Mice"]}
    raw_filters = {"categories": ["Keyboards", "Mice"]}

    where, params = gst._build_filters(filters, raw_filters)
    assert "categories_filter" in params
    cat_where = [w for w in where if "IN_TAXON" in w]
    assert len(cat_where) == 1
    clause = cat_where[0]
    assert "(node)-[:IN_TAXON]->(leaf:Taxon)-[:BROADER*0..7]->(ancestor:Taxon)" in clause
    assert "ANY(cat_rx IN $categories_filter WHERE ancestor.name =~ cat_rx OR leaf.name =~ cat_rx)" in clause


def test_gv2_07_macs_relaxation_steps_up_broader_hierarchy():
    """AC-S1-03: MACS steps up to parent category before dropping constraint."""
    db = MagicMock()
    session = MagicMock()
    db.session.return_value.__enter__.return_value = session

    gst = GraphSearchTool(db_connector=db, embedding_service=MagicMock())

    # Mock BROADER query returning "Speakers" as parent of "Bookshelf Speakers"
    parent_record = MagicMock()
    parent_record.__getitem__.side_effect = lambda key: "Speakers" if key == "parent_name" else None
    parent_record.get.side_effect = lambda key, d=None: "Speakers" if key == "parent_name" else d
    session.run.return_value.single.return_value = parent_record

    # Mock _execute_hybrid_search: first call returns 0 items, second call (after step-up) returns 3 items
    mock_hybrid = MagicMock()
    mock_hybrid.side_effect = [
        {"count": 0, "items": []},
        {"count": 3, "items": [{"title": "Speaker 1"}, {"title": "Speaker 2"}, {"title": "Speaker 3"}]},
    ]
    gst._execute_hybrid_search = mock_hybrid

    res = gst.search(semantic_query="bookshelf speakers", structured_filters={"category": "Bookshelf Speakers"})

    assert "relaxed_constraints" in res
    assert any("Broadened category constraint from 'Bookshelf Speakers' to parent category 'Speakers'" in r for r in res["relaxed_constraints"])
    assert mock_hybrid.call_count == 2


# ---------------------------------------------------------------------------
# GV2-08: Full-Text Lexical Channel in Score Fusion
# ---------------------------------------------------------------------------

def test_gv2_08_sanitize_lucene_query():
    """AC-S1-04: Lucene query sanitization handles punctuation, operators, and special characters."""
    clean = GraphSearchTool._sanitize_lucene_query("Looking for USB-C cable (under $20) & 65W charging: fast!")
    assert clean == "Looking for USB C cable under 20 65W charging fast"
    assert GraphSearchTool._sanitize_lucene_query("") == "*"
    assert GraphSearchTool._sanitize_lucene_query("   $$$ --- +++   ") == "*"


def test_gv2_08_build_channel_query_lexical():
    """AC-S1-04: _build_channel_query generates Lucene fulltext search query."""
    q = GraphSearchTool._build_channel_query("lexical", where_str="node.price <= 50.0")
    assert "CALL db.index.fulltext.queryNodes('product_fulltext_index', $query_text)" in q
    assert "WHERE node.price <= 50.0" in q
    assert "Fulltext Lexical Match" in q
    assert "RETURN node.parent_asin AS asin, similarity, reason" in q


def test_gv2_08_score_fusion_rrf4_and_wrrf4_presets():
    """AC-S1-05: score_fusion supports rrf4 and wrrf4 across 4 channels."""
    assert "lexical" in CHANNELS
    assert "rrf4" in FUSION_ARMS
    assert "wrrf4" in FUSION_ARMS
    assert "cc4" in FUSION_ARMS

    cfg_rrf4 = FUSION_ARMS["rrf4"]
    assert len(cfg_rrf4.channels) == 4
    assert cfg_rrf4.channels == ("product", "attribute", "review", "lexical")

    cfg_wrrf4 = FUSION_ARMS["wrrf4"]
    assert cfg_wrrf4.weights["lexical"] == 0.30
    assert cfg_wrrf4.weights["product"] == 0.35

    # Fuse with all 4 channels
    hits = {
        "product": [ChannelHit(asin="A", similarity=0.9, reason="title")],
        "attribute": [ChannelHit(asin="A", similarity=0.8, reason="attr")],
        "review": [ChannelHit(asin="A", similarity=0.7, reason="rev")],
        "lexical": [ChannelHit(asin="A", similarity=30.0, reason="lex")],
    }
    fused = fuse(hits, cfg_rrf4)
    assert len(fused) == 1
    assert fused[0].asin == "A"
    assert len(fused[0].channels) == 4
    assert "lexical" in fused[0].channels


# ---------------------------------------------------------------------------
# GV2-09: Selectivity-Based Dynamic ANN Oversampling
# ---------------------------------------------------------------------------

def test_gv2_09_dynamic_ann_oversampling_for_small_subtrees():
    """AC-S1-06: For subtrees with product_count < 5000, ann_k_per_limit dynamically increases."""
    db = MagicMock()
    session = MagicMock()
    db.session.return_value.__enter__.return_value = session
    session.run.return_value = []

    resolver = MagicMock()
    # Mock category with 237 products in subtree
    resolver.resolve_category.return_value = [{"name": "Bookshelf Speakers", "product_count": 237}]

    gst = GraphSearchTool(db_connector=db, embedding_service=MagicMock(), resolver=resolver)

    config = FusionConfig(name="rrf3", ann_k_per_limit=30)
    filter_params = {"category_filter": "Bookshelf Speakers"}

    with patch.object(gst, "_build_channel_query", return_value="RETURN 1") as mock_bc:
        gst._execute_fused_search(
            query_vector=[0.1, 0.2],
            where_str=None,
            filter_params=filter_params,
            limit=5,
            config=config,
            strategy="hybrid",
            text="compact speakers",
        )

    # In session.run call args, params["k"] should be scaled above default (5 * 30 = 150)
    run_calls = session.run.call_args_list
    assert len(run_calls) > 0
    passed_params = run_calls[0][0][1]
    # Scaling factor for 237 products is min(60, max(30, int(30 * (5000/500)))) = 60
    # 5 * 60 = 300
    assert passed_params["k"] == 300
    assert passed_params["query_text"] == "compact speakers"
