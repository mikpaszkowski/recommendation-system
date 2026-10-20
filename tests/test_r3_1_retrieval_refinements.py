"""
Unit tests for Release R3.1: Precyzja Atrybutów i Hierarchii
- RS-03: Attribute Channel Normalized IDF Rarity Weighting
- RS-10: Graded Category Proximity via Taxonomic Lineage Distance
- RS-07: Adaptive Filter-First Order for small selective subtrees (product_count <= 500)

Acceptance Criteria: AC-R3.1-01 through AC-R3.1-05
"""

import math
from unittest.mock import MagicMock
import pytest

from src.tools.graph_search_tool import DETAIL_QUERY, GraphSearchTool
from src.tools.score_fusion import FUSION_ARMS


# ---------------------------------------------------------------------------
# AC-R3.1-01: Attribute Channel Normalized IDF Weighting
# ---------------------------------------------------------------------------

def test_ac_r3_1_01_attribute_idf_weighting_query_structure():
    """AC-R3.1-01: Attribute MaxP query computes degree-based IDF weighting."""
    query = GraphSearchTool._build_channel_query("attribute", where_str="node.price <= $price_max")

    assert "MATCH (node:ParentProduct)-[:HAS_ATTRIBUTE]->(hit)" in query
    assert "node.price <= $price_max" in query
    assert "count { (:ParentProduct)-[:HAS_ATTRIBUTE]->(hit) } AS deg" in query
    assert "log(1.0 + 265307.0 / (1.0 + deg)) / log(265308.0)" in query
    assert "' [deg=' + toString(deg) + ']'" in query
    assert "ORDER BY score DESC, reason ASC" in query
    assert "WITH node, max(score) AS similarity, head(collect(reason)) AS reason" in query
    assert "RETURN node.parent_asin AS asin, similarity, reason" in query


def test_ac_r3_1_01_attribute_idf_weighting_math():
    """AC-R3.1-01: IDF factor mathematically suppresses generic high-degree attributes."""
    N = 265307.0
    denom = math.log(1.0 + N)

    def idf_factor(deg: float) -> float:
        return math.log(1.0 + N / (1.0 + deg)) / denom

    # Color=Black (deg=44,265) should have ~0.155 multiplier
    factor_generic = idf_factor(44265.0)
    assert 0.15 <= factor_generic <= 0.16

    # Style=Ergonomic Split Keyboard (deg=1) should have ~0.944 multiplier
    factor_rare = idf_factor(1.0)
    assert 0.94 <= factor_rare <= 0.95

    # Rare attribute has ~6x higher weighting than generic attribute
    assert factor_rare / factor_generic > 5.8


# ---------------------------------------------------------------------------
# AC-R3.1-02: Topological Taxonomy Distance & Multipliers
# ---------------------------------------------------------------------------

def test_ac_r3_1_02_compute_taxon_distance():
    """AC-R3.1-02: _compute_taxon_distance accurately computes tree distance via LCP."""
    target = ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"]

    # Distance 0: Exact match
    exact = ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"]
    assert GraphSearchTool._compute_taxon_distance(target, exact) == 0

    # Distance 0: Candidate is descendant (specialization)
    child = ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers", "Active Bookshelf Speakers"]
    assert GraphSearchTool._compute_taxon_distance(target, child) == 0

    # Distance 1: Candidate is immediate parent (broader)
    parent = ["Electronics", "Home Audio", "Speakers"]
    assert GraphSearchTool._compute_taxon_distance(target, parent) == 1

    # Distance 2: Sibling sharing immediate parent
    sibling = ["Electronics", "Home Audio", "Speakers", "Floorstanding Speakers"]
    assert GraphSearchTool._compute_taxon_distance(target, sibling) == 2

    # Distance 3: Cousin sharing grandparent (depth 3 vs depth 4)
    cousin1 = ["Electronics", "Home Audio", "Turntables"]
    assert GraphSearchTool._compute_taxon_distance(target, cousin1) == 3

    # Distance 4: Cousin sharing grandparent (depth 4 vs depth 4)
    cousin2 = ["Electronics", "Home Audio", "Receivers", "Stereo Receivers"]
    assert GraphSearchTool._compute_taxon_distance(target, cousin2) == 4

    # Distance 6: Distant branch (sharing only root 'Electronics')
    distant = ["Electronics", "Camera & Photo", "Bags & Cases", "Camera Cases"]
    assert GraphSearchTool._compute_taxon_distance(target, distant) == 6

    # Distance >= 5: Disjoint trees
    disjoint = ["Clothing, Shoes & Jewelry", "Men", "Clothing", "Shirts"]
    assert GraphSearchTool._compute_taxon_distance(target, disjoint) >= 5

    # None or empty paths return 99
    assert GraphSearchTool._compute_taxon_distance(target, None) == 99
    assert GraphSearchTool._compute_taxon_distance(None, exact) == 99
    assert GraphSearchTool._compute_taxon_distance([], exact) == 99


def test_ac_r3_1_02_taxon_distance_multipliers():
    """AC-R3.1-02: _get_taxon_distance_multiplier maps distance tiers to penalty multipliers."""
    assert GraphSearchTool._get_taxon_distance_multiplier(0) == pytest.approx(1.00)
    assert GraphSearchTool._get_taxon_distance_multiplier(1) == pytest.approx(0.85)
    assert GraphSearchTool._get_taxon_distance_multiplier(2) == pytest.approx(0.85)
    assert GraphSearchTool._get_taxon_distance_multiplier(3) == pytest.approx(0.70)
    assert GraphSearchTool._get_taxon_distance_multiplier(4) == pytest.approx(0.70)
    assert GraphSearchTool._get_taxon_distance_multiplier(5) == pytest.approx(0.20)
    assert GraphSearchTool._get_taxon_distance_multiplier(6) == pytest.approx(0.20)
    assert GraphSearchTool._get_taxon_distance_multiplier(99) == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# AC-R3.1-03: Fused Search Score Rescaling & Proximity Telemetry
# ---------------------------------------------------------------------------

class FakeSessionR3:
    """Mock session simulating fused retrieval with primary_taxon_path."""

    def __init__(self, channel_rows, details):
        self.channel_rows = channel_rows
        self.details = details
        self.calls = []

    def run(self, cypher, params=None, **kwargs):
        params = dict(params or {}, **kwargs)
        self.calls.append((cypher, params))
        for ch in ("product", "attribute", "review", "lexical"):
            if f"{ch}_embedding_index" in cypher or ("fulltext" in cypher and ch == "lexical"):
                return [dict(r) for r in self.channel_rows.get(ch, [])]
        if "node.title AS title" in cypher:
            return [dict(self.details[a], asin=a) for a in params.get("asins", []) if a in self.details]
        return []


def test_ac_r3_1_03_fused_search_applies_taxon_distance_rescaling_and_telemetry():
    """AC-R3.1-03: Fused candidate scores scale by distance multiplier and record telemetry."""
    # Product A: Distant branch (mult = 0.20), high initial vector sim
    # Product B: Sibling category (mult = 0.85), moderate sim
    # Product C: Exact leaf category (mult = 1.00), moderate sim
    channel_rows = {
        "product": [
            {"asin": "A", "similarity": 0.95, "reason": "Match A"},
            {"asin": "B", "similarity": 0.80, "reason": "Match B"},
            {"asin": "C", "similarity": 0.75, "reason": "Match C"},
        ],
    }
    details = {
        "A": {
            "title": "Camera Bag A",
            "price": 30.0,
            "category": ["Camera Cases"],
            "primary_taxon_path": ["Electronics", "Camera & Photo", "Bags & Cases", "Camera Cases"],
        },
        "B": {
            "title": "Floorstanding Speaker B",
            "price": 120.0,
            "category": ["Floorstanding Speakers"],
            "primary_taxon_path": ["Electronics", "Home Audio", "Speakers", "Floorstanding Speakers"],
        },
        "C": {
            "title": "Bookshelf Speaker C",
            "price": 99.0,
            "category": ["Bookshelf Speakers"],
            "primary_taxon_path": ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"],
        },
    }

    session = FakeSessionR3(channel_rows, details)
    connector = MagicMock()
    connector.session.return_value.__enter__.return_value = session
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 384

    resolver = MagicMock()
    # Resolve category "Bookshelf Speakers" with product_count=2000 (standard ANN path)
    resolver.resolve_category.return_value = [{
        "name": "Bookshelf Speakers",
        "path": ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"],
        "product_count": 2000,
        "score": 1.0,
    }]

    gst = GraphSearchTool(db_connector=connector, embedding_service=embedder, resolver=resolver,
                          fusion_config=FUSION_ARMS["rrf4"])

    res = gst.search(semantic_query="good speakers", structured_filters={"category": "Bookshelf Speakers"}, limit=3)

    items = res["items"]
    assert len(items) == 3

    # Product C (exact match, mult=1.00) and B (sibling, mult=0.85) should leapfrog A (distant, mult=0.20)
    asins = [i["asin"] for i in items]
    assert asins[0] == "C"  # Exact match wins
    assert asins[1] == "B"  # Sibling is 2nd
    assert asins[2] == "A"  # Distant camera case dropped to 3rd despite high initial vector sim!

    # Telemetry assertions
    item_c = next(i for i in items if i["asin"] == "C")
    assert item_c["fusion"]["taxon_proximity"]["distance"] == 0
    assert item_c["fusion"]["taxon_proximity"]["multiplier"] == pytest.approx(1.00)
    assert item_c["score"] == pytest.approx(item_c["fused_score"] * 1.00)

    item_b = next(i for i in items if i["asin"] == "B")
    assert item_b["fusion"]["taxon_proximity"]["distance"] == 2
    assert item_b["fusion"]["taxon_proximity"]["multiplier"] == pytest.approx(0.85)
    assert item_b["score"] == pytest.approx(item_b["fused_score"] * 0.85)

    item_a = next(i for i in items if i["asin"] == "A")
    assert item_a["fusion"]["taxon_proximity"]["distance"] >= 5
    assert item_a["fusion"]["taxon_proximity"]["multiplier"] == pytest.approx(0.20)
    assert item_a["score"] == pytest.approx(item_a["fused_score"] * 0.20)


# ---------------------------------------------------------------------------
# AC-R3.1-04: Adaptive Filter-First Order for Selective Subtrees (<= 500)
# ---------------------------------------------------------------------------

def test_ac_r3_1_04_adaptive_filter_first_activation_and_scoring():
    """AC-R3.1-04: Small selective subtree (product_count <= 500) activates filter-first order."""
    connector = MagicMock()
    session_mock = MagicMock()

    # Mock subtree items with 384-d embeddings
    mock_subtree_rows = [
        {
            "asin": "SPK1",
            "title": "Edifier R1280T Powered Bookshelf Speakers",
            "price": 99.99,
            "brand": "Edifier",
            "category": ["Bookshelf Speakers"],
            "primary_taxon_path": ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"],
            "id": "id-spk1",
            "features": ["Studio sound", "Wooden enclosure"],
            "details_text": "Power: 42W",
            "description": ["High quality bookshelf speakers."],
            "avg_rating": 4.6,
            "embedding": [0.1] * 384,
        },
        {
            "asin": "SPK2",
            "title": "Polk Audio T15 Bookshelf Speakers",
            "price": 149.00,
            "brand": "Polk Audio",
            "category": ["Bookshelf Speakers"],
            "primary_taxon_path": ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"],
            "id": "id-spk2",
            "features": ["Dynamic balance"],
            "details_text": "Wall mountable",
            "description": ["Home theater speakers."],
            "avg_rating": 4.5,
            "embedding": [0.08] * 384,
        },
        {
            "asin": "SPK3",
            "title": "Sony SS-CS5 3-Way Bookshelf Speakers",
            "price": 128.00,
            "brand": "Sony",
            "category": ["Bookshelf Speakers"],
            "primary_taxon_path": ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"],
            "id": "id-spk3",
            "features": ["Hi-Res Audio"],
            "details_text": "3-way 3-driver",
            "description": ["Super tweeter."],
            "avg_rating": 4.7,
            "embedding": [0.09] * 384,
        },
    ]

    session_mock.run.return_value = mock_subtree_rows
    connector.session.return_value.__enter__.return_value = session_mock

    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 384

    resolver = MagicMock()
    # Bookshelf Speakers has 237 products in Graph v2 (<= 500)
    resolver.resolve_category.return_value = [{
        "name": "Bookshelf Speakers",
        "path": ["Electronics", "Home Audio", "Speakers", "Bookshelf Speakers"],
        "product_count": 237,
        "score": 1.0,
    }]

    gst = GraphSearchTool(db_connector=connector, embedding_service=embedder, resolver=resolver)

    res = gst.search(semantic_query="edifier studio sound", structured_filters={"category": "Bookshelf Speakers"}, limit=3)

    assert res["status"] == "success"
    assert res["strategy"] == "filter_first_hybrid"
    assert len(res["items"]) == 3

    # Check that Top 1 is Edifier because of high lexical and vector match
    top_item = res["items"][0]
    assert top_item["asin"] == "SPK1"
    assert top_item["fusion"]["method"] == "filter_first"
    assert "Filter-First Subtree Match" in top_item["match_reasons"][0]
    assert top_item["fusion"]["taxon_proximity"]["distance"] == 0
    assert top_item["fusion"]["taxon_proximity"]["multiplier"] == 1.0

    # Ensure Cypher was called with the index-driven Taxon ancestor query
    cypher_called = session_mock.run.call_args[0][0]
    assert "MATCH (ancestor:Taxon)" in cypher_called
    assert "WHERE toLower(ancestor.name) = toLower($category_filter)" in cypher_called
    assert "MATCH (ancestor)<-[:BROADER*0..7]-(leaf:Taxon)<-[:IN_TAXON]-(node:ParentProduct)" in cypher_called


def test_ac_r3_1_04_broad_taxon_bypasses_filter_first():
    """AC-R3.1-04: Categories with product_count > 500 do not activate filter-first."""
    session = FakeSessionR3(
        channel_rows={"product": [{"asin": "P1", "similarity": 0.8, "reason": "Match"}]},
        details={"P1": {"title": "Speaker P1", "price": 50.0, "category": ["Speakers"], "primary_taxon_path": ["Electronics", "Speakers"]}}
    )
    connector = MagicMock()
    connector.session.return_value.__enter__.return_value = session
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 384

    resolver = MagicMock()
    # Speakers has 14,242 products (> 500)
    resolver.resolve_category.return_value = [{
        "name": "Speakers",
        "path": ["Electronics", "Speakers"],
        "product_count": 14242,
        "score": 1.0,
    }]

    gst = GraphSearchTool(db_connector=connector, embedding_service=embedder, resolver=resolver)

    res = gst.search(semantic_query="good speakers", structured_filters={"category": "Speakers"}, limit=1)

    assert res["status"] == "success"
    # Should use multi-index hybrid search, NOT filter_first_hybrid
    assert res["strategy"] == "hybrid_multi_index"
