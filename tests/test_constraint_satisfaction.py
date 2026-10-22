"""
tests/test_constraint_satisfaction.py

Three-valued constraint-satisfaction@K (Technical Specification AC-017 … AC-020, FR-012).
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from src.evaluation.constraint_satisfaction import (
    GoldConstraint,
    attribute_names_for,
    brand_matches,
    constraints_from_search_request,
    cs_scores_at_k,
    judge,
    parse_gold_constraints,
    validate_gold_annotations,
    verdict_matrix,
)
from src.tools.graph_search_tool import CONSTRAINT_FACTS_QUERY, GraphSearchTool


def _price(op: str, v: float) -> GoldConstraint:
    return GoldConstraint("price", "price", op, v)


def _brand(op: str, v: Any) -> GoldConstraint:
    return GoldConstraint("brand", "brand", op, v)


def _numeric(op: str, v: float, names=("storage",), scale: float = 1.0, tol: float = 0.05) -> GoldConstraint:
    return GoldConstraint("numeric", "storage", op, v, unit="GB", graph_attribute_names=tuple(names),
                          graph_unit_scale=scale, tolerance=tol)


def _facts(price: Any = None, brands: List[str] = (), title: str = "", numeric: List[Dict[str, Any]] = ()) -> Dict[str, Any]:
    return {"price": price, "brands": list(brands), "title": title, "numeric_attributes": list(numeric)}


class TestPriceVerdicts:
    """AC-017 price cells: None, 0, at the bound, over the bound."""

    @pytest.mark.parametrize("price,expected", [(None, "unknown"), (0, "unknown"), (-3.0, "unknown"),
                                                (60.0, "satisfied"), (59.99, "satisfied"), (60.01, "violated")])
    def test_less_than(self, price, expected):
        assert judge(_facts(price=price), _price("less_than", 60.0)) == expected

    @pytest.mark.parametrize("price,expected", [(None, "unknown"), (0.0, "unknown"), (50.0, "satisfied"),
                                                (75.0, "satisfied"), (49.0, "violated")])
    def test_greater_than(self, price, expected):
        assert judge(_facts(price=price), _price("greater_than", 50.0)) == expected

    def test_missing_facts_are_unknown(self):
        for constraint in (_price("less_than", 60.0), _brand("include", "Apple"), _numeric("greater_than", 128)):
            assert judge(None, constraint) == "unknown"
            assert judge({}, constraint) == "unknown"


class TestBrandVerdicts:
    """AC-017 brand cells: include / exclude, with and without HAS_BRAND, title rescue."""

    def test_include(self):
        c = _brand("include", "Samsung")
        assert judge(_facts(brands=["Samsung Electronics"]), c) == "satisfied"
        assert judge(_facts(brands=["SAMSUNG"]), c) == "satisfied"
        assert judge(_facts(brands=["LG"], title="LG phone"), c) == "violated"
        assert judge(_facts(brands=[], title="Galaxy phone"), c) == "unknown"
        assert judge(_facts(brands=[], title="Samsung Galaxy S9+"), c) == "satisfied"
        assert judge(_facts(brands=["Amazon Renewed"], title="Apple iPhone 8"), _brand("include", "Apple")) == "satisfied"

    def test_include_any_of(self):
        c = _brand("include", ("Samsung", "Apple"))
        assert judge(_facts(brands=["Apple"]), c) == "satisfied"
        assert judge(_facts(brands=["Sony"]), c) == "violated"

    def test_exclude(self):
        c = _brand("exclude", "HP")
        assert judge(_facts(brands=["Dell"], title="Dell laptop"), c) == "satisfied"
        assert judge(_facts(brands=["HP Inc."]), c) == "violated"
        assert judge(_facts(brands=[], title="HP Chromebook"), c) == "violated"
        assert judge(_facts(brands=[], title="Laptop"), c) == "unknown"

    def test_brand_matches_mirrors_cypher_predicate(self):
        assert brand_matches(["Samsung Electronics"], None, "samsung")
        assert brand_matches(["LG"], None, "LG Electronics")
        assert brand_matches(["", "Other"], "Fujifilm Instax", "fujifilm")
        assert not brand_matches(["Sony"], "A camera", "Canon")
        assert not brand_matches(["Sony"], "Sony", "  ")


class TestNumericVerdicts:
    """AC-017 numeric cells: >= / <= / = with tolerance and graph_unit_scale; empty names; missing facts."""

    def test_greater_less_equal(self):
        facts = _facts(numeric=[{"name": "storage", "value": 128.0}])
        assert judge(facts, _numeric("greater_than", 128)) == "satisfied"
        assert judge(facts, _numeric("greater_than", 256)) == "violated"
        assert judge(facts, _numeric("less_than", 128)) == "satisfied"
        assert judge(facts, _numeric("less_than", 64)) == "violated"

    def test_equal_with_tolerance(self):
        assert judge(_facts(numeric=[{"name": "storage", "value": 13.3}]), _numeric("equal", 13.0)) == "satisfied"
        assert judge(_facts(numeric=[{"name": "storage", "value": 14.0}]), _numeric("equal", 13.0)) == "violated"
        assert judge(_facts(numeric=[{"name": "storage", "value": 14.0}]), _numeric("equal", 13.0, tol=0.1)) == "satisfied"

    def test_unit_scale(self):
        facts = _facts(numeric=[{"name": "storage", "value": 0.5}])
        assert judge(facts, _numeric("greater_than", 512, scale=1024.0)) == "satisfied"
        assert judge(facts, _numeric("greater_than", 512)) == "violated"

    def test_any_matching_attribute_satisfies(self):
        facts = _facts(numeric=[{"name": "storage", "value": 64.0}, {"name": "storage", "value": 256.0}])
        assert judge(facts, _numeric("greater_than", 128)) == "satisfied"

    def test_unknown_cases(self):
        assert judge(_facts(numeric=[{"name": "storage", "value": 128.0}]), _numeric("greater_than", 128, names=())) == "unknown"
        assert judge(_facts(numeric=[{"name": "ram", "value": 16.0}]), _numeric("greater_than", 128)) == "unknown"
        assert judge(_facts(numeric=[{"name": "storage", "value": None}]), _numeric("greater_than", 128)) == "unknown"
        assert judge(_facts(), _numeric("greater_than", 128)) == "unknown"


class TestAggregates:
    """AC-018."""

    def test_hand_example(self):
        rows = ["SV", "SU", "UU", "VV"]
        k2 = cs_scores_at_k(rows, 2)
        assert k2 == pytest.approx({"cs_sat": 0.5, "cs_viol": 0.25, "cs_unk": 0.25, "cs_known": 2 / 3,
                                    "violation_free": 0.5, "cs_coverage": 0.75})
        k4 = cs_scores_at_k(rows, 4)
        assert k4["cs_sat"] == pytest.approx(2 / 8)
        assert k4["cs_viol"] == pytest.approx(3 / 8)
        assert k4["violation_free"] == pytest.approx(2 / 4)
        assert k4["cs_coverage"] == pytest.approx(1 - k4["cs_unk"])

    def test_none_cases(self):
        assert cs_scores_at_k([], 5) is None
        assert cs_scores_at_k(["", ""], 5) is None
        assert cs_scores_at_k(["S"], 0) is None
        assert cs_scores_at_k(["UU"], 5)["cs_known"] is None

    def test_verdict_matrix_deduplicates_and_orders(self):
        facts = {"A": _facts(price=10.0), "B": _facts(price=99.0)}
        rows = verdict_matrix(["A", "B", "A", "C"], facts, [_price("less_than", 50.0), _brand("include", "X")])
        assert rows == ["SU", "VU", "UU"]
        assert verdict_matrix(["A"], facts, []) == []


class TestRequestConstraints:
    """AC-019."""

    def test_mapping(self):
        request = {"structured_filters": {
            "price_max": 60, "price_min": "10", "brand": "Apple", "brands": ["Samsung", "LG"],
            "exclude_brand": "HP", "category": "wall charger", "categories": ["a"], "refresh_rate": 144,
        }}
        labels = [c.label for c in constraints_from_search_request(request)]
        assert labels == ["price<=60", "price>=10", "brand+Apple", "brand+Samsung|LG", "brand-HP"]

    def test_empty_and_invalid(self):
        assert constraints_from_search_request(None) == []
        assert constraints_from_search_request({}) == []
        assert constraints_from_search_request({"structured_filters": {"price_max": None, "brand": "", "price_min": "abc"}}) == []


class TestSchema:
    """FR-012 validator and parser."""

    def test_valid_and_labels(self):
        parsed = parse_gold_constraints([
            {"kind": "price", "attribute": "price", "operator": "less_than", "value": 60.0},
            {"kind": "numeric", "attribute": "output_power", "operator": "equal", "value": 65, "unit": "W",
             "tolerance": 0.05, "graph_attribute_names": ["output_power"], "graph_unit_scale": 1.0},
            {"kind": "brand", "operator": "exclude", "value": "HP"},
        ])
        assert [c.label for c in parsed] == ["price<=60", "output_power=65W", "brand-HP"]
        assert attribute_names_for(parsed) == ["output_power"]

    @pytest.mark.parametrize("bad", [
        {"kind": "category", "operator": "include", "value": "x"},
        {"kind": "price", "operator": "equal", "value": 5},
        {"kind": "price", "operator": "less_than", "value": 0},
        {"kind": "price", "operator": "less_than", "value": "60"},
        {"kind": "brand", "operator": "include", "value": ""},
        {"kind": "numeric", "attribute": "x", "operator": "equal", "value": 1, "graph_attribute_names": []},
        {"kind": "numeric", "attribute": "x", "operator": "equal", "value": 1, "unit": "W"},
        {"kind": "numeric", "attribute": "x", "operator": "equal", "value": 1, "unit": "W", "graph_attribute_names": ["Mixed"]},
        {"kind": "numeric", "attribute": "x", "operator": "equal", "value": 1, "unit": "W", "graph_attribute_names": [], "tolerance": 0.6},
        {"kind": "numeric", "attribute": "x", "operator": "equal", "value": 1, "unit": "W", "graph_attribute_names": [], "graph_unit_scale": 0},
    ])
    def test_invalid_constraints(self, bad):
        with pytest.raises(ValueError):
            parse_gold_constraints([bad])

    def test_item_level_rules(self):
        errors = validate_gold_annotations([
            {"query_id": "ok"},
            {"query_id": "a", "type_explicit": False, "gold_action": "SEARCH"},
            {"query_id": "b", "gold_action": "ANSWER"},
            {"query_id": "c", "type_explicit": "yes"},
            {"query_id": "d", "gold_constraints": [{"kind": "price", "operator": "less_than", "value": -1}]},
            {"query_id": "e", "type_explicit": False, "gold_action": "CLARIFY"},
        ])
        assert [e.split(":")[0] for e in errors] == ["a", "b", "c", "d"]


class _RecordingSession:
    def __init__(self, rows=None, fail: bool = False):
        self.rows = rows or []
        self.fail = fail
        self.calls = []

    def run(self, cypher, params=None, **kwargs):
        self.calls.append((cypher, dict(params or {}, **kwargs)))
        if self.fail:
            raise RuntimeError("neo4j down")
        return [dict(r) for r in self.rows]


def _tool(session: _RecordingSession) -> GraphSearchTool:
    connector = MagicMock()
    connector.session.return_value.__enter__.return_value = session
    gst = GraphSearchTool(db_connector=connector, embedding_service=MagicMock(), resolver=MagicMock())
    gst.resolver = None
    return gst


class TestFetchConstraintFacts:
    """AC-020."""

    def test_one_parameterised_query(self):
        session = _RecordingSession(rows=[
            {"asin": "A", "price": 10.0, "title": "T", "brands": ["X", None], "numeric_attributes": [{"name": "storage", "value": 128.0}]},
            {"asin": "B", "price": None, "title": None, "brands": [], "numeric_attributes": []},
        ])
        facts = _tool(session).fetch_constraint_facts(["A", "B", "A", "Z'; DROP"], ["Storage", " RAM "])
        assert len(session.calls) == 1
        cypher, params = session.calls[0]
        assert cypher == CONSTRAINT_FACTS_QUERY
        assert params == {"asins": ["A", "B", "Z'; DROP"], "attribute_names": ["storage", "ram"]}
        assert "Z'; DROP" not in cypher and "storage" not in cypher
        assert facts["A"] == {"price": 10.0, "title": "T", "brands": ["X"], "numeric_attributes": [{"name": "storage", "value": 128.0}]}
        assert facts["B"]["title"] == "" and "Z'; DROP" not in facts

    def test_error_and_empty(self, caplog):
        assert _tool(_RecordingSession(fail=True)).fetch_constraint_facts(["A"], []) == {}
        assert "Constraint fact fetch failed" in caplog.text
        session = _RecordingSession()
        assert _tool(session).fetch_constraint_facts([], ["x"]) == {}
        assert session.calls == []


class TestCategoryTelemetry:
    """AC-013 (graph tool side) and FR-016."""

    def test_match_category_default_call_unchanged(self):
        session = _RecordingSession(rows=[{"asin": "A"}])
        gst = _tool(session)
        expected_where, expected_params = gst._build_filters({"category": "Webcams"}, {"category": "Webcams"})
        assert gst.match_category(["A"], "Webcams") == {"A"}
        cypher, params = session.calls[-1]
        assert all(clause in cypher for clause in expected_where)
        assert params == dict(expected_params, asins=["A"])

    def test_match_category_passes_raw_category(self):
        session = _RecordingSession(rows=[])
        gst = _tool(session)
        gst.match_category(["A"], "Chargers & Adapters", raw_category="wall charger")
        cypher, params = session.calls[-1]
        assert params["category_filter"] == "Chargers & Adapters"
        assert params["raw_category_filter"] == "wall charger"
        assert "toLower(node.title) CONTAINS 'wall'" in cypher and "CONTAINS 'charger'" in cypher

    def test_search_records_normalized_filters_before_macs(self):
        gst = _tool(_RecordingSession())
        gst._normalize_filters = MagicMock(return_value={"category": "Chargers", "price_max": 60.0})
        gst.resolver = MagicMock()
        gst._execute_hybrid_search = MagicMock(return_value={"status": "success", "items": [], "count": 0, "metadata": {}})
        res = gst.search(semantic_query="wall charger", structured_filters={"category": "wall charger", "price_max": 60})
        assert res["metadata"]["normalized_filters"] == {"category": "Chargers", "price_max": 60.0}
        assert "Dropped explicit category constraint (relying purely on vector search)" in res["relaxed_constraints"]
