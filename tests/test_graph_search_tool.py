import pytest
import logging
from unittest.mock import MagicMock
from src.tools.graph_search_tool import GraphSearchTool
from src.knowledge_graph.graphdb.resolver_service import ResolverService

logging.basicConfig(level=logging.INFO)

def test_resolver_waterfall_mocked():
    # Test that resolver returns what we expect
    connector_mock = MagicMock()
    session_mock = MagicMock()
    session_mock.run.return_value = [{"name": "Asus", "score": 1.0}]
    connector_mock.session.return_value.__enter__.return_value = session_mock
    
    resolver = ResolverService(connector=connector_mock, embed_svc=MagicMock())
    matches = resolver.resolve_brand("asus")
    
    assert len(matches) > 0
    assert matches[0]["name"] == "Asus"

def test_graph_search_tool_filters():
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=MagicMock())
    
    # Test exclusions
    filters = {"excluded_asins": ["B0123", "B0456"]}
    where, params = gst._build_filters(filters)
    assert any("NOT node.parent_asin IN $excluded_asins" in w for w in where)
    assert params["excluded_asins"] == ["B0123", "B0456"]

    # Test EAV Numeric
    filters = {"refresh_rate_min": 120.0, "screen_size_exact": 27.0}
    where, params = gst._build_filters(filters)
    assert any("refresh_rate" in w and "COALESCE" in w and ">=" in w for w in where)
    assert any("screen_size" in w and "COALESCE" in w and "=" in w for w in where)
    assert params["refresh_rate_min"] == 120.0
    assert params["screen_size_exact"] == 27.0

def test_gst_multi_index_query_generation():
    # Verify the CYpher query generation
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=MagicMock())
    gst.embedder.embed_query.return_value = [0.1] * 384
    
    res = gst.search(semantic_query="120hz monitor", structured_filters={"price_max": 500})
    
    # The mock won't return items, but we want to ensure it doesn't crash on syntax
    assert "status" in res

# ---------------------------------------------------------------------------
# R1 fused retrieval (Technical Specification AC-007 … AC-011)
# ---------------------------------------------------------------------------
from src.tools.score_fusion import FUSION_ARMS


class FakeSession:
    """Routes Cypher to canned rows by query shape and records every call."""

    def __init__(self, channel_rows=None, details=None, legacy_rows=None, scalar_rows=None):
        self.channel_rows = channel_rows or {}
        self.details = details or {}
        self.legacy_rows = legacy_rows or []
        self.scalar_rows = scalar_rows or []
        self.calls = []

    def run(self, cypher, params=None, **kwargs):
        params = dict(params or {}, **kwargs)
        self.calls.append((cypher, params))
        if "sum(score)" in cypher:
            return [dict(r) for r in self.legacy_rows]
        for channel, index in (("product", "product_embedding_index"),
                               ("attribute", "attribute_embedding_index"),
                               ("review", "review_embedding_index")):
            if index in cypher:
                return [dict(r) for r in self.channel_rows.get(channel, [])]
        if "node.title AS title" in cypher:
            return [dict(self.details[a], asin=a) for a in params.get("asins", []) if a in self.details]
        return [dict(r) for r in self.scalar_rows]


def _tool_with(session, fusion_config=None):
    connector = MagicMock()
    connector.session.return_value.__enter__.return_value = session
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.1] * 384
    gst = GraphSearchTool(db_connector=connector, embedding_service=embedder, resolver=MagicMock(),
                          fusion_config=fusion_config or FUSION_ARMS["rrf3"])
    gst.resolver = None  # keep filters verbatim
    return gst


def _details(*asins):
    return {a: {"title": f"Webcam {a}", "price": 49.0, "brand": "Brand", "category": ["Webcams"], "id": f"id-{a}"} for a in asins}


CHANNEL_ROWS = {
    "product": [
        {"asin": "A", "similarity": 0.90, "reason": "Product Title Match"},
        {"asin": "B", "similarity": 0.80, "reason": "Product Title Match"},
        {"asin": "C", "similarity": 0.70, "reason": "Product Title Match"},
    ],
    "attribute": [
        {"asin": "B", "similarity": 0.75, "reason": "Attribute Match: Resolution=1080p"},
        {"asin": "C", "similarity": 0.60, "reason": "Attribute Match: Mic=Yes"},
    ],
    "review": [
        {"asin": "C", "similarity": 0.65, "reason": "Review Match: great"},
    ],
}


def test_fused_search_orders_items_and_exposes_evidence():
    """AC-007: fused order, original keys and per-channel evidence on every item."""
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
    gst = _tool_with(session)

    res = gst.search(semantic_query="1080p webcam", structured_filters={"price_max": 60}, limit=3)

    assert [i["asin"] for i in res["items"]] == ["C", "B", "A"]
    top = res["items"][0]
    for key in ("title", "price", "brand", "category", "score", "id", "asin", "match_reasons", "fused_score", "soft_bonus", "fusion"):
        assert key in top
    assert top["fused_score"] == pytest.approx(1 / 63 + 1 / 62 + 1 / 61)
    assert top["fusion"]["method"] == "rrf3"
    assert top["fusion"]["channels"]["review"] == {"rank": 1, "similarity": 0.65, "reason": "Review Match: great"}
    assert top["match_reasons"] == ["Product Title Match", "Attribute Match: Mic=Yes", "Review Match: great"]
    assert res["metadata"]["fusion"]["name"] == "rrf3"
    assert res["metadata"]["channel_counts"] == {"product": 3, "attribute": 2, "review": 1}


def test_soft_bonus_is_scaled_to_fused_range():
    """AC-008: one matched preference adds 0.25 x max fused score and cannot lift a clearly weaker match."""
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
    session.details["A"]["title"] = "Webcam A with privacy shutter"
    gst = _tool_with(session)
    unit = FUSION_ARMS["rrf3"].soft_bonus_unit()

    res = gst.search(semantic_query="1080p webcam", structured_filters={"price_max": 60}, limit=3,
                     soft_preferences=[{"category": "feature", "value": "privacy shutter", "polarity": 1.0}])

    by_asin = {i["asin"]: i for i in res["items"]}
    assert unit == pytest.approx(0.25 * 3 / 61)
    assert by_asin["A"]["soft_bonus"] == pytest.approx(unit)
    assert by_asin["A"]["score"] == pytest.approx(by_asin["A"]["fused_score"] + unit)
    # C leads A by more than one unit, so A must stay behind C
    assert by_asin["C"]["fused_score"] - by_asin["A"]["fused_score"] > unit
    assert [i["asin"] for i in res["items"]].index("C") < [i["asin"] for i in res["items"]].index("A")


def test_sum_legacy_keeps_legacy_query_and_bonus():
    """AC-008 / AC-009: sum_legacy runs the sum(score) UNION query and keeps the 0.2 bonus unit."""
    session = FakeSession(legacy_rows=[
        {"asin": "A", "title": "Webcam A privacy shutter", "price": 49.0, "brand": "B", "category": [], "score": 1.0, "id": "1", "match_reasons": []},
    ])
    gst = _tool_with(session, FUSION_ARMS["sum_legacy"])

    res = gst.search(semantic_query="webcam", structured_filters={"price_max": 60}, limit=5,
                     soft_preferences=[{"category": "feature", "value": "privacy shutter", "polarity": 1.0}])

    # One result triggers MACS, so the legacy query runs again with the widened budget
    assert session.calls and all("sum(score)" in c for c, _ in session.calls)
    assert not any("max(score)" in c for c, _ in session.calls)
    assert res["items"][0]["score"] == pytest.approx(1.2)
    assert res["metadata"]["fusion"]["name"] == "sum_legacy"


def test_default_path_runs_one_query_per_channel_plus_details():
    """AC-009: no sum(score); one query per enabled channel and one detail query."""
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
    gst = _tool_with(session)

    gst.search(semantic_query="webcam", structured_filters={"price_max": 60}, limit=3)

    queries = [c for c, _ in session.calls]
    assert not any("sum(score)" in q for q in queries)
    assert sum("queryNodes" in q for q in queries) == 3
    assert sum("node.title AS title" in q for q in queries) == 1
    assert all("max(score)" in q for q in queries if "attribute_embedding_index" in q or "review_embedding_index" in q)


def test_rrf2_skips_review_channel_query():
    """RS-02 ablation: rrf2 never queries the review index."""
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
    gst = _tool_with(session)

    res = gst.search(semantic_query="webcam", structured_filters={"price_max": 60}, limit=3, fusion_config=FUSION_ARMS["rrf2"])

    assert not any("review_embedding_index" in c for c, _ in session.calls)
    assert all("review" not in i["fusion"]["channels"] for i in res["items"])


def test_channel_queries_are_parameterised():
    """AC-010: user values travel as parameters, never inside the new channel or detail Cypher."""
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
    gst = _tool_with(session)

    gst.search(semantic_query="webcam", structured_filters={"price_max": 61.5, "brand": "Logitech"}, limit=3)

    for cypher, params in session.calls:
        assert "Logitech" not in cypher
        assert "61.5" not in cypher
    channel_params = session.calls[0][1]
    assert channel_params["brand_filter"] == "Logitech"
    assert channel_params["price_max"] == 61.5
    assert channel_params["k"] == 3 * 30
    assert channel_params["depth"] == 100
    assert "vector" in channel_params
    detail_cypher, detail_params = session.calls[-1]
    assert "$asins" in detail_cypher
    assert detail_params["asins"] == ["C", "B", "A"]


def test_macs_still_relaxes_through_fused_path():
    """AC-011: fewer than 3 fused results triggers MACS and records relaxed constraints."""
    rows = {"product": [{"asin": "A", "similarity": 0.9, "reason": "Product Title Match"}]}
    session = FakeSession(channel_rows=rows, details=_details("A"))
    gst = _tool_with(session)

    res = gst.search(semantic_query="webcam", structured_filters={"price_max": 60.0, "category": "Webcams"}, limit=5)

    assert "Widened budget ceiling by 15%" in res["relaxed_constraints"]
    assert any("Dropped explicit category" in r for r in res["relaxed_constraints"])
    price_params = [p.get("price_max") for c, p in session.calls if "product_embedding_index" in c]
    assert price_params[0] == pytest.approx(60.0)
    assert price_params[1] == pytest.approx(69.0)


def test_vector_only_path_has_no_where_clause():
    """FR-007: vector-only search uses the fused path without filters."""
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("A", "B", "C"))
    gst = _tool_with(session)

    res = gst.search(semantic_query="webcam", limit=3)

    assert res["strategy"] == "vector_only"
    assert all("WHERE" not in c for c, _ in session.calls if "queryNodes" in c)


def test_missing_detail_row_is_dropped():
    """A fused ASIN absent from the detail query is dropped rather than returned half-empty."""
    session = FakeSession(channel_rows=CHANNEL_ROWS, details=_details("B", "C"))
    gst = _tool_with(session)

    res = gst.search(semantic_query="webcam", structured_filters={"price_max": 60}, limit=3)

    assert [i["asin"] for i in res["items"]] == ["C", "B"]


def test_match_category_and_review_embedded_helpers():
    """Helpers for type-precision@K and popularity-bias@K."""
    session = FakeSession(scalar_rows=[{"asin": "A"}, {"asin": "C"}])
    gst = _tool_with(session)

    assert gst.match_category(["A", "B", "C"], "Webcams") == {"A", "C"}
    cypher, params = session.calls[-1]
    assert params["asins"] == ["A", "B", "C"]
    assert params["category_filter"] == "Webcams"
    assert gst.match_category([], "Webcams") == set()
    assert gst.fetch_review_embedded_asins() == {"A", "C"}
    assert "r.embedding IS NOT NULL" in session.calls[-1][0]


def test_fusion_arm_read_after_connector_loads_env(monkeypatch):
    """RETRIEVAL_FUSION_ARM loaded from .env by Neo4jConnector() is honoured (read after the connector)."""
    import src.tools.graph_search_tool as gst_module

    monkeypatch.delenv("RETRIEVAL_FUSION_ARM", raising=False)

    def connector_loading_env():
        monkeypatch.setenv("RETRIEVAL_FUSION_ARM", "cc3")
        return MagicMock()

    monkeypatch.setattr(gst_module, "Neo4jConnector", connector_loading_env)
    gst = GraphSearchTool(embedding_service=MagicMock(), resolver=MagicMock())

    assert gst.fusion_config.name == "cc3"


if __name__ == "__main__":
    pytest.main(["-v", "tests/test_graph_search_tool.py"])
