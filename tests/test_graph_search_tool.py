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

if __name__ == "__main__":
    pytest.main(["-v", "tests/test_graph_search_tool.py"])
