import pytest
import logging
from unittest.mock import MagicMock, patch
from src.tools.graph_search_tool import GraphSearchTool

logging.basicConfig(level=logging.INFO)

def test_macs_relaxation():
    # We mock _execute_hybrid_search to return 0 results on the first call, 
    # then 1 result on the second call to simulate MACS behavior.
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=MagicMock())
    
    # We will track how many times _execute_hybrid_search is called
    call_count = [0]
    
    def fake_execute(text, filters, raw_filters, limit, soft_preferences=None):
        call_count[0] += 1
        # First call: return 0
        if call_count[0] == 1:
            return {"count": 0, "items": []}
        # Subsequent call: return 1
        return {"count": 1, "items": [{"id": "1", "score": 1.0}]}
        
    gst._execute_hybrid_search = fake_execute
    
    filters = {"price_max": 100.0, "category": "laptop"}
    result = gst.search(semantic_query="test", structured_filters=filters)
    
    # It should have called _execute_hybrid_search 3 times because 1 < 3
    assert call_count[0] == 3
    # The budget should be widened 
    assert "relaxed_constraints" in result
    assert "Widened budget ceiling by 15%" in result["relaxed_constraints"]
    assert "Dropped explicit category constraint (relying purely on vector search)" in result["relaxed_constraints"]
    
def test_macs_relaxation_drop_category():
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=MagicMock())
    
    call_count = [0]
    
    def fake_execute(text, filters, raw_filters, limit, soft_preferences=None):
        call_count[0] += 1
        # Always return 0 to force drop category
        if call_count[0] < 3:
            return {"count": 0, "items": []}
        return {"count": 1, "items": [{"id": "1", "score": 1.0}]}
        
    gst._execute_hybrid_search = fake_execute
    
    filters = {"price_max": 100.0, "category": "laptop"}
    result = gst.search(semantic_query="test", structured_filters=filters)
    
    assert call_count[0] == 3
    assert "relaxed_constraints" in result
    assert "Dropped explicit category constraint (relying purely on vector search)" in result["relaxed_constraints"]
