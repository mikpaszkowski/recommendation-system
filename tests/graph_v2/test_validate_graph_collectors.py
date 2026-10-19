"""
tests/graph_v2/test_validate_graph_collectors.py

Fake-session tests for the Cypher collectors of scripts/graph_ingestion/validate_graph.py (AC-048, amendment A-6, audit M-5):
each collector feeding H-01 … H-18 and R-01 … R-08 issues the expected query shape and maps result rows
to the gate inputs, including empty and None results. No Neo4j, Docker or raw files.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import pytest

from src.knowledge_graph.graph_v2 import validation as gates
from src.knowledge_graph.graph_v2.csv_io import decode_array, read_import_csv

from .conftest import FakeEmbedder, FakeSession

REPO_ROOT = Path(__file__).resolve().parents[2]
Rule = Tuple[str, Any]


def _module():
    spec = importlib.util.spec_from_file_location("validate_graph_under_test", REPO_ROOT / "scripts" / "graph_ingestion" / "validate_graph.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VG = _module()


class Scripted:
    """Responder answering the first rule whose substring occurs in the query; unknown queries fail the test."""

    def __init__(self, rules: Sequence[Rule]) -> None:
        self.rules = list(rules)

    def __call__(self, cypher: str, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
        for needle, answer in self.rules:
            if needle in cypher:
                return answer(params) if callable(answer) else answer
        raise AssertionError(f"unexpected query: {cypher}")


def _session(*rules: Rule) -> FakeSession:
    return FakeSession(Scripted(rules))


# ----------------------------------------------------------------------------------- H-01 … H-09


def test_collect_h01_h04_maps_counts_and_streamed_asins() -> None:
    """H-01 … H-04: product count, streamed parent_asins (None kept for H-02), untitled count, ghost signature."""
    session = _session(
        ("trim(p.title) = ''", [{"n": 3}]),
        ("keys(p)", [{"n": 1}]),
        ("RETURN p.parent_asin AS asin", [{"asin": "T001"}, {"asin": None}]),
        ("MATCH (p:ParentProduct) RETURN count(p) AS n", [{"n": 11}]),
    )
    assert VG.collect_h01_h04(session) == (11, ["T001", None], 3, 1)
    ghost = next(c for c, _ in session.calls if "keys(p)" in c)
    assert "size([k IN keys(p) WHERE k <> 'embedding']) <= 1" in ghost
    untitled = next(c for c, _ in session.calls if "trim(p.title)" in c)
    assert "p.title IS NULL OR trim(p.title) = ''" in untitled


def test_collect_h01_h04_empty_count_row_raises() -> None:
    """H-01: a count query that returns no row raises, so run_validation records a failed gate instead of a pass."""
    session = _session(("ParentProduct", []))
    with pytest.raises(RuntimeError):
        VG.collect_h01_h04(session)


def test_collect_h05_query_shapes() -> None:
    """H-05: reviews without exactly one ABOUT_PRODUCT / incoming WROTE, and users without WROTE."""
    session = _session(("MATCH (r:Review)", [{"n": 2}]), ("MATCH (u:User)", [{"n": 0}]))
    assert VG.collect_h05(session) == (2, 0)
    review_query = session.calls[0][0]
    assert "COUNT { (r)-[:ABOUT_PRODUCT]->() } <> 1" in review_query and "COUNT { ()-[:WROTE]->(r) } <> 1" in review_query
    assert "NOT EXISTS { (u)-[:WROTE]->() }" in session.calls[1][0]


def test_collect_h06_hits_sample_and_train_membership(fixture_dir: Path) -> None:
    """H-06: excluded pairs are counted, in_train_split None maps to False, and train hits come from the train CSV."""
    rows = [
        {"u": "U100", "p": "T003", "id": "r1", "t": False},
        {"u": "U101", "p": "T003", "id": "r2", "t": True},
        {"u": "U102", "p": "T003", "id": "r3", "t": None},
    ]
    session = _session(("MATCH (u:User)-[:WROTE]->(r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct)", rows))
    hits, sample, train_hits = VG.collect_h06(session, fixture_dir, 20261019)
    assert hits == 1
    assert sorted(sample) == [("U100", "T003", False), ("U101", "T003", True), ("U102", "T003", False)]
    assert train_hits == {("U101", "T003")}
    assert VG.collect_h06(_session(("MATCH (u:User)", rows)), fixture_dir, 20261019)[1] == sample
    gate = gates.gate_split_exclusion(hits, sample, train_hits)
    assert gate.passed is False and gate.observed["excluded_hits"] == 1


def test_collect_h06_empty_graph(fixture_dir: Path) -> None:
    """H-06: an empty graph gives no hits and an empty sample, which the gate does not accept as a pass."""
    hits, sample, train_hits = VG.collect_h06(_session(("MATCH (u:User)", [])), fixture_dir, 1)
    assert (hits, sample, train_hits) == (0, [], set())
    assert gates.gate_split_exclusion(hits, sample, train_hits).passed is False


def test_collect_h07_h08_maps_and_handles_null_max() -> None:
    """H-07 / H-08: max reviews per product (None on an empty graph -> 0), bad cap ranks, review count."""
    session = _session(
        ("RETURN max(COUNT", [{"n": 20}]),
        ("collect(DISTINCT r.cap_rank)", [{"n": 0}]),
        ("MATCH (r:Review) RETURN count(r) AS n", [{"n": 34}]),
    )
    assert VG.collect_h07_h08(session) == (20, 0, 34)
    assert "size(ranks) <> n OR any(x IN ranks WHERE x < 1 OR x > n)" in session.calls[1][0]
    empty = _session(("RETURN max(COUNT", [{"n": None}]), ("collect(DISTINCT", [{"n": 0}]), ("MATCH (r:Review)", [{"n": 0}]))
    assert VG.collect_h07_h08(empty) == (0, 0, 0)
    assert VG.collect_h07_h08(_session(("RETURN max(COUNT", []), ("collect(DISTINCT", [{"n": 0}]), ("MATCH (r:Review)", [{"n": 0}])))[0] == 0


def test_collect_h09_constraint_names() -> None:
    """H-09: names from SHOW CONSTRAINTS; none -> []."""
    session = _session(("SHOW CONSTRAINTS", [{"name": "product_id"}, {"name": "taxon_id"}]))
    assert VG.collect_h09(session) == ["product_id", "taxon_id"]
    assert VG.collect_h09(_session(("SHOW CONSTRAINTS", []))) == []


# ---------------------------------------------------------------------------------- H-10 … H-13


@pytest.mark.parametrize("rule, has_features", [("title_description_features", True), ("title_description", False)])
def test_collect_h10_coverage_per_label(rule: str, has_features: bool) -> None:
    """H-10: embedded, eligible (content rule / embed_rank scope) and wrong-dimension counts for the five labels."""
    session = _session(
        (f"size(n.embedding) <> {gates.EMBEDDING_DIM}", [{"n": 0}]),
        ("n.embedding IS NOT NULL RETURN count", [{"n": 5}]),
        ("RETURN count(n) AS n", [{"n": 7}]),
    )
    coverage = VG.collect_h10(session, rule)
    assert set(coverage) == set(VG.EMBED_LABELS)
    assert all(c == gates.LabelCoverage(embedded=5, eligible=7, wrong_dimension=0) for c in coverage.values())
    queries = [c for c, _ in session.calls]
    assert any("MATCH (n:Review) WHERE n.embed_rank IS NOT NULL RETURN count(n)" in q for q in queries)
    product_eligible = next(q for q in queries if q.startswith("MATCH (n:ParentProduct) WHERE ((n.title"))
    assert ("any(f IN coalesce(n.features, [])" in product_eligible) is has_features
    assert len(queries) == 15


def test_collect_h11_probes_and_scores() -> None:
    """H-11: content-free and blank counts, one blank-template probe per category plus Unknown and the review probe."""
    embedder = FakeEmbedder()
    session = _session(
        ("MATCH (n:ParentProduct) WHERE n.embedding IS NOT NULL AND NOT", [{"n": 0}]),
        ("MATCH (r:Review) WHERE r.embedding IS NOT NULL", [{"n": 1}]),
        ("MATCH (c:Category) RETURN c.name AS name", [{"name": "Home Audio"}, {"name": "Cables"}]),
        ("queryNodes('product_embedding_index', 1", lambda params: [{"score": 0.5 if len(params["vector"]) == 384 else 0.0}]),
        ("queryNodes('review_embedding_index', 1", []),
    )
    empty_products, blank_reviews, scores = VG.collect_h11(session, embedder)
    assert (empty_products, blank_reviews) == (0, 1)
    assert scores == {"product_blank[Cables]": 0.5, "product_blank[Home Audio]": 0.5, "product_blank[Unknown]": 0.5, "review_blank": 0.0}
    assert embedder.batches[0] == [
        "Product: . Category: Cables. Features: . Description: ", "Product: . Category: Home Audio. Features: . Description: ",
        "Product: . Category: Unknown. Features: . Description: ", ". ",
    ]
    content_query = session.calls[0][0]
    assert "any(f IN coalesce(n.features, []) WHERE trim(f) <> '')" in content_query
    narrow = _session(("NOT ((n.title", [{"n": 0}]), ("MATCH (r:Review)", [{"n": 0}]),
                      ("MATCH (c:Category)", []), ("queryNodes", [{"score": 0.1}]))
    VG.collect_h11(narrow, FakeEmbedder(), "title_description")
    assert "coalesce(n.features" not in narrow.calls[0][0]


def test_collect_h12_h13_index_states_and_smoke() -> None:
    """H-12 / H-13: SHOW INDEXES rows map to IndexState (None population -> 0.0); full-text fields come from the index; smoke test runs."""
    index_rows = [
        {"name": "product_embedding_index", "type": "VECTOR", "state": "ONLINE", "populationPercent": 100.0, "properties": ["embedding"]},
        {"name": "review_embedding_index", "type": "VECTOR", "state": "POPULATING", "populationPercent": None, "properties": None},
        {"name": gates.FULLTEXT_INDEX_NAME, "type": "FULLTEXT", "state": "ONLINE", "populationPercent": 100.0,
         "properties": ["title", "description", "features", "details_text"]},
    ]
    session = _session(
        ("SHOW INDEXES YIELD name, type, state, populationPercent, properties", index_rows),
        ("WHERE p.features IS NOT NULL RETURN p.parent_asin", [{"parent_asin": "T1", "title": "Cable", "description": None,
                                                                 "features": ["Kevlar reinforced"], "details_text": None}]),
        ("db.index.fulltext.queryNodes", [{"parent_asin": "T1"}]),
    )
    indexes, found, token, asin, fields = VG.collect_h12_h13(lambda: session, 20261019)
    assert indexes[1] == gates.IndexState("review_embedding_index", "VECTOR", "POPULATING", 0.0, ())
    assert (found, token, asin) == (True, "reinforced", "T1")
    assert fields == ["title", "description", "features", "details_text"]
    assert gates.gate_indexes_online(indexes).passed is False


def test_collect_h12_h13_no_fulltext_index() -> None:
    """H-12 / H-13: without the full-text index the fields are [] and no candidate means no smoke pass."""
    session = _session(("SHOW INDEXES", []), ("WHERE p.features IS NOT NULL", []))
    indexes, found, token, asin, fields = VG.collect_h12_h13(lambda: session, 1)
    assert (indexes, found, token, asin, fields) == ([], False, None, None, [])


# ------------------------------------------------------------------------------------------ H-14


def _graph_values(import_dir: Path) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Graph-side values exactly as Neo4j would store the import CSV fields."""
    products = {
        r["parent_asin:ID(ParentProduct)"]: {
            "title": r["title"] or None, "description": r["description"] or None,
            "features": decode_array(r["features:string[]"]) or None, "details_json": r["details_json"] or None,
        }
        for r in read_import_csv(import_dir / "nodes_product.csv")
    }
    reviews = {
        r["review_id:ID(Review)"]: {
            "review_title": r["review_title"] or None, "review_body": r["review_body"] or None,
            "rating": float(r["rating:double"]) if r["rating:double"] else None,
            "timestamp": int(r["timestamp:long"]), "helpful_vote": int(r["helpful_vote:long"]),
            "verified": r["verified:boolean"] == "true",
        }
        for r in read_import_csv(import_dir / "nodes_review.csv")
    }
    return {"ParentProduct": products, "Review": reviews}


def _fidelity_responder(values: Dict[str, Dict[str, Dict[str, Any]]]):
    def answer(label: str):
        def rows(params):
            return [{"k": node_id, **values[label][node_id]} for node_id in params["ids"] if node_id in values[label]]
        return rows
    return Scripted([("MATCH (n:ParentProduct {parent_asin: id})", answer("ParentProduct")),
                     ("MATCH (n:Review {review_id: id})", answer("Review"))])


def test_collect_h14_round_trip_matches(fixture_build) -> None:
    """H-14: graph values equal to the parsed-back CSV values give zero mismatches over every sampled node."""
    _, base = fixture_build
    session = FakeSession(_fidelity_responder(_graph_values(base / "import")))
    compared, mismatches = VG.collect_h14(session, base / "import", 20261019)
    assert (compared, mismatches) == (11 + 34, [])
    product_query = session.calls[0][0]
    assert product_query.startswith("UNWIND $ids AS id MATCH (n:ParentProduct {parent_asin: id}) RETURN n.parent_asin AS k")
    assert all(f"n.{field} AS {field}" in session.calls[1][0] for field in gates.FIDELITY_REVIEW_FIELDS)


def test_collect_h14_detects_altered_and_missing_nodes(fixture_build) -> None:
    """H-14: a changed review body (CRLF vs LF) and a missing product node are both reported."""
    _, base = fixture_build
    values = _graph_values(base / "import")
    special = next(rid for rid, row in values["Review"].items() if row["review_body"] and "\n" in row["review_body"])
    values["Review"][special]["review_body"] = values["Review"][special]["review_body"].replace("\n", "\r\n")
    del values["ParentProduct"]["T001"]
    compared, mismatches = VG.collect_h14(FakeSession(_fidelity_responder(values)), base / "import", 20261019)
    assert compared == 45
    assert {(m.label, m.key, m.field) for m in mismatches if m.label == "Review"} == {("Review", special, "review_body")}
    missing = [m for m in mismatches if m.key == "T001"]
    assert len(missing) == len(gates.FIDELITY_PRODUCT_FIELDS) and all(m.graph_value == "<missing node>" for m in missing)
    assert gates.gate_import_fidelity(compared, mismatches).passed is False


# --------------------------------------------------------------------------------------- H-15 … H-18


class _Grounding:
    def __init__(self, error: Exception = None) -> None:
        self.error = error
        self.items: List[Dict[str, Any]] = []

    def validate_benchmark_graph_grounding(self, items, connector):
        self.items = list(items)
        if self.error is not None:
            raise self.error
        return {"valid_scenarios": len(items)}


def test_collect_h15_runs_grounding_on_sampled_targets(tmp_path: Path, monkeypatch) -> None:
    """H-15: all targets are checked in a full build, only in-sample targets in a pilot, and errors become the gate detail."""
    benchmark = tmp_path / "bench.json"
    benchmark.write_text(json.dumps([{"query_id": "q1", "target_asin": "T008"}, {"query_id": "q2", "target_asin": "T001"},
                                     {"query_id": "q3", "ground_truth_asins": ["T010"]}]), encoding="utf-8")
    fake = _Grounding()
    monkeypatch.setattr(VG, "_load_script", lambda path, name: fake)
    assert VG.collect_h15(object(), benchmark, None) == (None, 3)
    assert VG.collect_h15(object(), benchmark, 4) == (None, 2)
    assert [item["query_id"] for item in fake.items] == ["q1", "q3"]
    failing = _Grounding(ValueError("Benchmark contains 1 ungrounded target entities."))
    monkeypatch.setattr(VG, "_load_script", lambda path, name: failing)
    error, checked = VG.collect_h15(object(), benchmark, None)
    assert checked == 3 and error.startswith("ValueError: Benchmark contains 1")


def test_collect_h15_empty_pilot_sample(tmp_path: Path, monkeypatch) -> None:
    """H-15: a pilot sample without targets returns (None, 0) without loading evaluate_retrieval."""
    benchmark = tmp_path / "bench.json"
    benchmark.write_text(json.dumps([{"query_id": "q2", "target_asin": "T001"}]), encoding="utf-8")
    monkeypatch.setattr(VG, "_load_script", lambda path, name: pytest.fail("must not load evaluate_retrieval"))
    assert VG.collect_h15(object(), benchmark, 4) == (None, 0)


def _h16_h18_rules(taxon_record) -> List[Rule]:
    return [
        ("MATCH (t:Taxon) RETURN t.taxon_id AS id", [{"id": "A"}, {"id": "A > B"}]),
        ("MATCH (t:Taxon {taxon_id: $id})", taxon_record),
        ("CALL db.labels()", [{"label": "ParentProduct"}, {"label": "Taxon"}]),
        ("CALL db.relationshipTypes()", [{"relationshipType": "IN_TAXON"}]),
        ("MATCH (n:`ParentProduct`)", [{"n": 11}]),
        ("MATCH (n:`Taxon`)", [{"n": 2}]),
        ("MATCH ()-[r:`IN_TAXON`]->()", [{"n": 10}]),
        ("a.numeric_value IS NOT NULL", [{"n": 0}]),
        ("[(t)-[:BROADER]->(p:Taxon) | p.depth]", [{"n": 0}]),
        ("COUNT { (p)-[:IN_TAXON]->() } > 1", [{"n": 0}]),
        ("WITH a.attribute_name AS name, a.attribute_value AS value, count(*) AS c", [{"n": 1}]),
    ]


def test_collect_h16_h18_maps_counts_and_taxon_checks() -> None:
    """H-16 … H-18: label / type counts, numeric_value, BROADER and IN_TAXON checks, sampled subtree counts, duplicate attributes."""
    session = _session(*_h16_h18_rules(lambda params: [{"stored": 3, "recomputed": 3 if params["id"] == "A" else 2}]))
    facts = VG.collect_h16_h18(session, 20261019)
    assert facts["nodes"] == {"ParentProduct": 11, "Taxon": 2} and facts["relationships"] == {"IN_TAXON": 10}
    assert (facts["numeric_value"], facts["bad_broader"], facts["multi_taxon"], facts["duplicate_attributes"]) == (0, 0, 0, 1)
    assert sorted(facts["taxon_checks"]) == [gates.TaxonCountCheck("A", 3, 3), gates.TaxonCountCheck("A > B", 3, 2)]
    recount = next(c for c, _ in session.calls if "{taxon_id: $id}" in c)
    assert "COUNT { (:ParentProduct)-[:IN_TAXON]->(:Taxon)-[:BROADER*0..]->(t) }" in recount


def test_collect_h16_h18_missing_taxon_row_is_mismatch() -> None:
    """H-17: a sampled taxon whose recount returns no row is recorded as a mismatch, not a crash."""
    facts = VG.collect_h16_h18(_session(*_h16_h18_rules([])), 1)
    assert all(check.stored == -1 for check in facts["taxon_checks"])
    assert len(facts["taxon_checks"]) == 2


# ----------------------------------------------------------------------------------------- R-01 … R-08


def _report_only_rules(tmp_path: Path) -> List[Rule]:
    coverage_row = {"grp": "All Electronics", "products": 4, "with_title": 3, "with_price": 2, "with_brand": 4,
                    "with_features": 1, "with_description": 0, "details_ge1": 2, "details_ge5": None,
                    "reviews_ge1": 4, "reviews_ge5": 1}
    return [
        ("OPTIONAL MATCH (p)-[:BELONGS_TO_CATEGORY]->(c:Category) WITH coalesce(c.name, '') AS grp",
         [coverage_row, {**coverage_row, "grp": "", "products": 0}]),
        ("WHERE t.depth = 1 WITH t.taxon_id AS grp", [{**coverage_row, "grp": "Electronics"}]),
        ("WHERE t.depth = 2 WITH t.taxon_id AS grp", []),
        ("MATCH (t:Taxon) RETURN t.depth AS d", [{"d": 1, "n": 2}, {"d": 2, "n": 3}]),
        ("MATCH (p:ParentProduct) WHERE p.embedding IS NOT NULL RETURN p.parent_asin AS asin", [{"asin": "T1"}, {"asin": "T2"}]),
        ("MATCH (n:ParentProduct {parent_asin: $asin})", lambda params: [{
            "title": f"Title {params['asin']}", "description": None, "features": None, "category": "C", "pairs": [],
            "e": [0.1] * 384}]),
        ("queryNodes('product_embedding_index', 2", lambda params: [{"other": "T2" if params["asin"] == "T1" else "T1", "score": 1.0}]),
        ("MATCH (b:Brand) RETURN b.name AS name", [{"name": "Anker", "n": 5}, {"name": "ANKER", "n": 1}, {"name": "Sony", "n": 2}]),
        ("AS review_nodes", lambda params: [{
            "title": "New", "price": 9.0, "brands": ["B"], "categories": ["C"], "review_nodes": 3}]),
        ("CALL db.labels()", [{"label": "ParentProduct"}]),
        ("CALL db.relationshipTypes()", []),
        ("MATCH (n:`ParentProduct`)", [{"n": 4}]),
        ("trim(p.title) = ''", [{"n": 0}]),
        ("MATCH (r:Review) WHERE r.embedding IS NOT NULL RETURN count(r)", [{"n": 0}]),
        ("count(DISTINCT p)", [{"n": 0}]),
        ("dbms.components", [{"name": "Neo4j Kernel", "version": "5.14.0", "edition": "community"}]),
    ]


def test_collect_report_only_maps_every_check(fixture_build, tmp_path: Path, monkeypatch) -> None:
    """R-01 … R-08: every check is present; shares use None for empty groups; R-04 flags identical vectors with different text."""
    result, _ = fixture_build
    v1_targets = tmp_path / "benchmark_targets.json"
    v1_targets.write_text(json.dumps([{"query_id": "q1", "target_asin": "T1", "title": "Old", "price": 9.0,
                                       "brands": ["B"], "categories": ["C"], "review_nodes": 3}]), encoding="utf-8")
    v1_snapshot = tmp_path / "snapshot.json"
    v1_snapshot.write_text(json.dumps({"nodes": {"ParentProduct": 8}, "relationships": {}, "products_untitled": 2,
                                       "review_embedded_products": 1}), encoding="utf-8")
    monkeypatch.setattr(VG, "V1_BENCHMARK_TARGETS", v1_targets)
    monkeypatch.setattr(VG, "V1_SNAPSHOT", v1_snapshot)
    inputs = VG.ValidationInputs(result.lineage, None, None, set(), {})
    report = VG.collect_report_only(_session(*_report_only_rules(tmp_path)), inputs, None, 20261019,
                                    graph_asins=["0123456789", "T1", None])
    assert set(report) == set(gates.REPORT_ONLY_IDS)
    r01 = report["R-01"]["by_main_category"]
    assert r01["All Electronics"]["products"] == 4 and r01["All Electronics"]["with_title"] == 0.75
    assert r01["All Electronics"]["details_ge5"] == 0.0 and r01[""]["with_title"] is None
    assert report["R-02"] == {"depth_1": {"Electronics": r01["All Electronics"]}, "depth_2": {}}
    assert report["R-03"]["depth_distribution"] == {"1": 2, "2": 3} and report["R-03"]["roots"] == result.lineage.counts.taxonomy.roots
    assert report["R-04"]["count"] == 2 and report["R-04"]["sampled"] == 2
    assert report["R-05"] == {"groups": [[{"name": "ANKER", "products": 1}, {"name": "Anker", "products": 5}]], "count": 1}
    assert report["R-06"] == {"count": 1, "asins": ["0123456789"]}
    assert report["R-07"]["differences"] == [{"query_id": "q1", "changes": {"title": {"v1": "Old", "v2": "New"}}}]
    assert report["R-08"]["nodes"]["ParentProduct"] == {"v1": 8, "v2": 4}


def test_collect_report_only_errors_and_missing_v1_files(fixture_build, tmp_path: Path, monkeypatch) -> None:
    """R-01 … R-08: a failing query is recorded as {"error": …} and missing v1 files are reported as skipped; nothing raises."""
    result, _ = fixture_build
    monkeypatch.setattr(VG, "V1_BENCHMARK_TARGETS", tmp_path / "absent_targets.json")
    monkeypatch.setattr(VG, "V1_SNAPSHOT", tmp_path / "absent_snapshot.json")

    def broken(cypher, params):
        raise RuntimeError("connection reset")

    report = VG.collect_report_only(FakeSession(broken), VG.ValidationInputs(result.lineage, None, None, set(), {}), None, 1)
    for check in ("R-01", "R-02", "R-03", "R-04", "R-05"):
        assert report[check] == {"error": "RuntimeError: connection reset"}
    assert report["R-06"] == {"count": 0, "asins": []}
    assert "skipped" in report["R-07"] and "skipped" in report["R-08"]


# --------------------------------------------------------------------------------- run_validation wiring

COLLECTOR_GATES = {
    "collect_h01_h04": ("H-01", "H-02", "H-03", "H-04"),
    "collect_h05": ("H-05",),
    "collect_h06": ("H-06",),
    "collect_h07_h08": ("H-07", "H-08"),
    "collect_h09": ("H-09",),
    "collect_h10": ("H-10",),
    "collect_h11": ("H-11",),
    "collect_h12_h13": ("H-12", "H-13"),
    "collect_h14": ("H-14",),
    "collect_h15": ("H-15",),
    "collect_h16_h18": ("H-16", "H-17", "H-18"),
}


def _wiring(monkeypatch, fixture_build, tmp_path: Path, failing: str = "") -> Tuple[Any, Dict[str, Any]]:
    """Patches every collector with values that make its gates pass (or raise for `failing`); returns (report, captured args)."""
    from src.knowledge_graph.graph_v2.models import BuildParams, EmbeddingReport, LabelEmbeddingStats

    result, _ = fixture_build
    lineage = result.lineage
    params = BuildParams(accepted_untitled_count=3, accepted_catalogue_missing=1, expected_review_count=34, expected_embed_reviews=18,
                         embedding_device="cpu", build_profile={}, preflight_report_sha256="p" * 64, approved_on="2026-10-19",
                         product_content_rule="title_description")
    coverage = {label: gates.LabelCoverage(4, 4, 0) for label in ("Attribute", "Brand", "Category", "ParentProduct")}
    coverage["Review"] = gates.LabelCoverage(18, 18, 0)
    report_e = EmbeddingReport(created_at="t", sentence_transformers_version=None, torch_version=None, device=None, batch_size=1,
                               labels={k: LabelEmbeddingStats(template_id="x", eligible=c.eligible, embedded=c.embedded) for k, c in coverage.items()})
    online = [gates.IndexState(n, "VECTOR", "ONLINE", 100.0, ("embedding",)) for n in gates.VECTOR_INDEX_NAMES]
    online.append(gates.IndexState(gates.FULLTEXT_INDEX_NAME, "FULLTEXT", "ONLINE", 100.0, ("title",)))
    captured: Dict[str, Any] = {}
    values = {
        "collect_h01_h04": (11, ["T001", "T002"], 3, 0),
        "collect_h05": (0, 0),
        "collect_h06": (0, [("U1", "T001", True)], {("U1", "T001")}),
        "collect_h07_h08": (20, 0, 34),
        "collect_h09": list(gates.REQUIRED_CONSTRAINTS),
        "collect_h10": coverage,
        "collect_h11": (0, 0, {"review_blank": 0.3}),
        "collect_h12_h13": (online, True, "reinforced", "T001", ["title"]),
        "collect_h14": (45, []),
        "collect_h15": (None, 21),
        "collect_h16_h18": {"nodes": dict(lineage.counts.nodes), "relationships": dict(lineage.counts.relationships),
                            "numeric_value": 0, "bad_broader": 0, "multi_taxon": 0,
                            "taxon_checks": [gates.TaxonCountCheck("Electronics", 9, 9)], "duplicate_attributes": 0},
    }
    for name, value in values.items():
        def fake(*args, _name=name, _value=value, **kwargs):
            captured[_name] = args
            if _name == failing:
                raise RuntimeError(f"boom in {_name}")
            return _value
        monkeypatch.setattr(VG, name, fake)
    monkeypatch.setattr(VG, "collect_report_only", lambda *a, **k: {"R-01": {"ok": True}})
    inputs = VG.ValidationInputs(lineage, params, report_e, {f"T{i:03d}" for i in range(1, 13)},
                                 {"lineage": "l" * 64, "build_params": "b" * 64, "embedding_report": "e" * 64})
    args = VG.build_parser().parse_args(["--splits-dir", str(tmp_path), "--import-dir", str(tmp_path), "--benchmark", str(tmp_path / "b.json")])
    report = VG.run_validation(VG.resolve_paths(args), lambda: FakeSession(lambda c, p: []), "connector", "embedder", inputs)
    return report, captured


def test_run_validation_wires_every_collector_to_its_gates(monkeypatch, fixture_build, tmp_path: Path) -> None:
    """AC-048: each collector's output reaches the right gate ID; all-conforming inputs give passed: true."""
    report, captured = _wiring(monkeypatch, fixture_build, tmp_path)
    assert [g.id for g in report.hard_gates] == list(gates.GATE_NAMES)
    assert all(g.passed for g in report.hard_gates), [g for g in report.hard_gates if not g.passed]
    assert report.passed is True and report.graph_counts == {"ParentProduct": 11, "Review": 34}
    assert report.report_only["R-01"] == {"ok": True} and report.build_params_sha256 == "b" * 64
    assert captured["collect_h10"][1] == "title_description" and captured["collect_h11"][2] == "title_description"
    assert captured["collect_h15"] == ("connector", Path(tmp_path / "b.json"), None)
    assert next(g for g in report.hard_gates if g.id == "H-08").observed == 34
    assert next(g for g in report.hard_gates if g.id == "H-14").observed == {"compared": 45, "mismatches": 0}


@pytest.mark.parametrize("collector", sorted(COLLECTOR_GATES))
def test_run_validation_collector_exception_fails_its_gates(collector: str, monkeypatch, fixture_build, tmp_path: Path) -> None:
    """AC-048: a collector exception yields failed gates with exactly that collector's IDs and passed: false; other gates still run."""
    report, _ = _wiring(monkeypatch, fixture_build, tmp_path, failing=collector)
    failed = {g.id for g in report.hard_gates if not g.passed}
    assert failed == set(COLLECTOR_GATES[collector])
    assert report.passed is False
    for gate in report.hard_gates:
        if gate.id in failed:
            assert gate.detail == f"RuntimeError: boom in {collector}" and gate.name == gates.GATE_NAMES[gate.id]
