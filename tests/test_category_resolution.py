import os
import pytest
from unittest.mock import MagicMock
from neo4j import GraphDatabase

from src.tools.graph_search_tool import GraphSearchTool
from src.knowledge_graph.graphdb.resolver_service import (
    ResolverService,
    CATEGORY_CONFIDENCE,
    CATEGORY_MARGIN,
)
from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "recommendation_password")


@pytest.fixture
def neo4j_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception:
        pytest.skip("Neo4j database not reachable")
    yield driver
    driver.close()


def test_category_constants_and_ac_compliance():
    """AC-003.1: Verify CATEGORY_CONFIDENCE=0.70 and CATEGORY_MARGIN=0.05."""
    assert CATEGORY_CONFIDENCE == 0.70
    assert CATEGORY_MARGIN == 0.05
    assert GraphSearchTool.CATEGORY_CONFIDENCE == 0.70
    assert GraphSearchTool.CATEGORY_MARGIN == 0.05
    assert ResolverService.CATEGORY_CONFIDENCE == 0.70
    assert ResolverService.CATEGORY_MARGIN == 0.05


def test_category_normalization_plural_resolution():
    """AC-003.2: Singular 'mouse' normalizes to canonical node 'Mice'."""
    tool = GraphSearchTool()
    raw_filters = {"category": "mouse"}
    normalized = tool._normalize_filters(raw_filters)
    assert normalized["category"] == "Mice", (
        f"Expected category 'mouse' to normalize to 'Mice', got '{normalized.get('category')}'"
    )


def test_category_normalization_margin_check():
    """AC-003.1: Ambiguous term with runner-up within 0.05 margin preserves raw string."""
    tool = GraphSearchTool()
    raw_filters = {"category": "cord"}
    normalized = tool._normalize_filters(raw_filters)
    assert normalized["category"] == "cord", (
        f"Ambiguous category 'cord' should not be normalized; got '{normalized.get('category')}'"
    )


def test_category_word_boundary_isolation(neo4j_driver):
    """AC-003.3: Whole-token / word-boundary category regex isolation.
    Searching for 'phone' must NOT match 'Headphones, Earbuds & Accessories'.
    """
    with neo4j_driver.session() as session:
        cypher = """
        MATCH (c:Category)
        WHERE c.name =~ '(?i).*(^|[^a-z])phone(s)?([^a-z]|$).*'
        RETURN collect(c.name) AS matched_categories
        """
        result = session.run(cypher).single()
        matches = result["matched_categories"]
        assert "Cell Phones & Accessories" in matches, (
            f"Expected 'Cell Phones & Accessories' in {matches}"
        )
        assert "Headphones, Earbuds & Accessories" not in matches, (
            f"Overmatching leak: 'phone' matched {matches}"
        )


def test_category_multi_word_conjunction_title_fallback():
    """AC-003.4 & AC-003.5: Multi-word category fallback uses token conjunction."""
    gst = GraphSearchTool(db_connector=MagicMock(), embedding_service=MagicMock(), resolver=MagicMock())

    # Query 4: mechanical keyboard
    where_kb, params_kb = gst._build_filters({"category": "mechanical keyboard"})
    assert len(where_kb) == 1
    clause_kb = where_kb[0]
    assert "toLower(node.title) CONTAINS 'mechanical'" in clause_kb
    assert "toLower(node.title) CONTAINS 'keyboard'" in clause_kb
    assert " AND " in clause_kb
    assert "SUBCATEGORY_OF*0..3" in clause_kb

    # Query 25: external ssd
    where_ssd, params_ssd = gst._build_filters({"category": "external ssd"})
    assert len(where_ssd) == 1
    clause_ssd = where_ssd[0]
    assert "toLower(node.title) CONTAINS 'external'" in clause_ssd
    assert "toLower(node.title) CONTAINS 'ssd'" in clause_ssd
    assert " AND " in clause_ssd
    assert "SUBCATEGORY_OF*0..3" in clause_ssd


def test_category_resolver_unit_margin_logic():
    """Unit test for ResolverService.validate_category_candidates margin rules."""
    resolver = ResolverService(connector=MagicMock(), embed_svc=MagicMock())

    # Case 1: Below confidence (0.65 < 0.70) -> None
    assert resolver.validate_category_candidates([{"name": "Mice", "score": 0.65}]) is None

    # Case 2: Above confidence with valid margin (0.78 vs 0.70 disparate -> diff 0.08 >= 0.05) -> Accepted
    res = resolver.validate_category_candidates([
        {"name": "Mice", "path": None, "score": 0.78},
        {"name": "Tools & Home", "path": None, "score": 0.70},
    ])
    assert res is not None
    assert res["name"] == "Mice"

    # Case 3: Ambiguous candidates (diff 0.02 < 0.05) -> Rejected
    res_ambig = resolver.validate_category_candidates([
        {"name": "Home Audio", "path": None, "score": 0.72},
        {"name": "All Electronics", "path": None, "score": 0.71},
    ])
    assert res_ambig is None

    # Case 4: Same-branch candidate (parent contains child name) not treated as cross-domain
    res_branch = resolver.validate_category_candidates([
        {"name": "Mice", "path": ["Keyboards, Mice & Accessories", "Mice"], "score": 0.796},
        {"name": "Keyboards, Mice & Accessories", "path": ["Keyboards, Mice & Accessories"], "score": 0.762},
        {"name": "Tools & Home", "path": None, "score": 0.636},
    ])
    assert res_branch is not None
    assert res_branch["name"] == "Mice"
