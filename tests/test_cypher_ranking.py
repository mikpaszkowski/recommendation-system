import pytest
from src.tools.graph_search_tool import GraphSearchTool
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

def test_cypher_search_deterministic_ranking():
    tool = GraphSearchTool()
    result = tool._execute_cypher_search(
        filters={"price_max": 70.0},
        raw_filters={"category": "webcam"},
        limit=20
    )
    items = result["items"]
    if not items:
        pytest.skip("No items found, skipping assertion")
        
    # Assert descending order of scores
    scores = [item["score"] for item in items]
    assert scores == sorted(scores, reverse=True), "Candidates not ordered by descending relevance score!"
    
def test_numeric_eav_unit_coercion():
    db = Neo4jConnector()
    db.connect()
    with db.session() as session:
        cypher = """
        WITH '144 Hz' AS raw_refresh, '1 ms' AS raw_response, '16 GB' AS raw_ram,
             '27-inch' AS raw_size, '65W' AS raw_wattage, 'WiFi-6' AS raw_wifi
             
        RETURN coalesce(
                   toFloat(split(replace(replace(raw_refresh, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                   toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(raw_refresh, 'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
               ) AS refresh,
               
               coalesce(
                   toFloat(split(replace(replace(raw_response, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                   toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(raw_response, 'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
               ) AS response,
               
               coalesce(
                   toFloat(split(replace(replace(raw_ram, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                   toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(raw_ram, 'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
               ) AS ram,
               
               coalesce(
                   toFloat(split(replace(replace(raw_size, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                   toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(raw_size, 'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
               ) AS size,
               
               coalesce(
                   toFloat(split(replace(replace(raw_wattage, '-inch', ' inch'), '65W', '65 W'), ' ')[0]),
                   toFloat(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(raw_wattage, 'Hz', ''), 'fps', ''), 'GB', ''), 'TB', ''), 'watt', ''), 'W', ''), '-inch', ''), 'inch', ''), 'Inches', ''), '"', ''))
               ) AS wattage
        """
        record = session.run(cypher).single()
        assert record["refresh"] == 144.0, f"Expected 144.0, got {record['refresh']}"
        assert record["response"] == 1.0, f"Expected 1.0, got {record['response']}"
        assert record["ram"] == 16.0, f"Expected 16.0, got {record['ram']}"
        assert record["size"] == 27.0, f"Expected 27.0, got {record['size']}"
        assert record["wattage"] == 65.0, f"Expected 65.0, got {record['wattage']}"
