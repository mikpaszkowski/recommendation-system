"""
tests/graph_v2/test_post_import.py

Post-import sub-commands with fake sessions and embedder (FR-021 … FR-025, FR-027): AC-023 … AC-027, AC-030.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest

from src.knowledge_graph.graph_v2 import embedding_runtime
from src.knowledge_graph.graph_v2.models import (
    BuildParams,
    EmbeddingReport,
    GateResult,
    GraphVersionProps,
    LabelEmbeddingStats,
    ValidationReport,
)

from .conftest import FakeEmbedder, FakeSession, make_clean_git_runner
from .fakes_embedding import FakeModel

REPO_ROOT = Path(__file__).resolve().parents[2]
SECTION_5_6_KEYS = {
    "version", "built_at", "lineage_sha256", "validation_report_sha256", "embedding_report_sha256", "build_params_sha256",
    "source_meta_sha256", "source_reviews_sha256", "splits_sha256", "catalogue_sha256", "code_commit", "stamp_commit",
    "embedding_model", "template_ids", "review_embedding_scope", "review_cap", "fulltext_fields", "neo4j_version",
    "product_count", "review_count", "user_count", "taxon_count", "validation_passed",
}


def _module():
    spec = importlib.util.spec_from_file_location("post_import_v2_under_test", REPO_ROOT / "scripts" / "graph_ingestion" / "post_import_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewGraph:
    """In-memory Review nodes answering the Review LabelEmbedSpec queries."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        for i in range(7):
            self.nodes[f"r{i}"] = {"title": f"Title {i}", "body": "Body", "embed_rank": i + 1, "embedding": None}
        self.nodes["r_blank"] = {"title": " ", "body": "", "embed_rank": 9, "embedding": None}
        self.nodes["r_unranked"] = {"title": "Has text", "body": "but no embed_rank", "embed_rank": None, "embedding": None}
        self.after_values: List[str] = []
        self.unwritable: set = set()

    def __call__(self, cypher: str, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
        if cypher.startswith("MATCH (n:Review) WHERE n.embed_rank IS NOT NULL AND n.embedding IS NULL"):
            self.after_values.append(params["after0"])
            keys = sorted(k for k, n in self.nodes.items()
                          if n["embed_rank"] is not None and n["embedding"] is None and k > params["after0"])
            return [{"eid": f"4:db:{k}", "k0": k, "title": self.nodes[k]["title"], "body": self.nodes[k]["body"]}
                    for k in keys[:params["batch"]]]
        if cypher.startswith("UNWIND $rows AS row MATCH (n:Review) WHERE elementId(n) = row.id"):
            written = 0
            for row in params["rows"]:
                key = row["id"].split(":", 2)[2]
                if key in self.nodes and key not in self.unwritable:
                    self.nodes[key]["embedding"] = row["e"]
                    written += 1
            return [{"written": written}]
        if "n.embed_rank IS NOT NULL RETURN count" in cypher:
            return [{"n": sum(1 for n in self.nodes.values() if n["embed_rank"] is not None)}]
        if "n.embedding IS NOT NULL RETURN count" in cypher:
            return [{"n": sum(1 for n in self.nodes.values() if n["embedding"] is not None)}]
        raise AssertionError(f"unexpected query: {cypher}")


def _embed(graph: ReviewGraph, embedder: FakeEmbedder, batch_size: int = 3):
    module = _module()
    spec = module.label_specs("title_description_features")["Review"]
    return module.embed_label(lambda: FakeSession(graph), embedder, spec, batch_size, time.monotonic)


def test_embed_never_sends_none() -> None:
    """AC-023: the embedder never receives a None or blank text."""
    graph, embedder = ReviewGraph(), FakeEmbedder()
    _embed(graph, embedder)
    texts = [text for batch in embedder.batches for text in batch]
    assert len(texts) == 7 and all(text and text.strip() for text in texts)


def test_embed_ascending_keyset_order() -> None:
    """AC-023: pages are read in ascending key order with WHERE key > $after."""
    graph = ReviewGraph()
    _embed(graph, FakeEmbedder())
    assert graph.after_values == sorted(graph.after_values) and graph.after_values[0] == ""
    assert len(set(graph.after_values)) == len(graph.after_values)
    spec = _module().label_specs("title_description_features")["Review"]
    assert "n.review_id > $after0" in spec.fetch_query and "ORDER BY n.review_id" in spec.fetch_query


def test_embed_resumes_without_reembedding() -> None:
    """AC-023: after an interruption a second run embeds only the remaining nodes."""
    graph = ReviewGraph()
    first = FakeEmbedder(fail_after_batches=1)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        _embed(graph, first)
    done_first = [text for batch in first.batches for text in batch]
    assert len(done_first) == 3
    second = FakeEmbedder()
    stats = _embed(graph, second)
    done_second = [text for batch in second.batches for text in batch]
    assert not set(done_first) & set(done_second) and len(done_first) + len(done_second) == 7
    assert stats.embedded == 7


def test_embed_reviews_only_with_embed_rank() -> None:
    """AC-023: only Review nodes with embed_rank are fetched and written."""
    graph = ReviewGraph()
    _embed(graph, FakeEmbedder())
    assert graph.nodes["r_unranked"]["embedding"] is None
    assert all(n["embedding"] is not None for k, n in graph.nodes.items() if k.startswith("r") and k[1:].isdigit())


def test_embed_report_counts(tmp_path: Path) -> None:
    """AC-023: eligible, embedded and skipped_empty are reported correctly."""
    stats = _embed(ReviewGraph(), FakeEmbedder())
    assert (stats.eligible, stats.embedded, stats.skipped_empty) == (8, 7, 1)
    assert stats.skipped_keys_sample == ["r_blank"] and stats.template_id == "review_v1"
    module = _module()
    graph = ReviewGraph()
    params = BuildParams(accepted_untitled_count=0, accepted_catalogue_missing=0, expected_review_count=9,
                         expected_embed_reviews=8, embedding_device="cpu", build_profile={}, preflight_report_sha256="x",
                         approved_on="2026-10-19")
    report = module.run_embed(lambda: FakeSession(graph), FakeEmbedder(), ["Review"], 4, params, tmp_path / "er.json", time.monotonic)
    loaded = EmbeddingReport.model_validate_json((tmp_path / "er.json").read_text(encoding="utf-8"))
    assert loaded.labels["Review"].embedded == 7 and report.batch_size == 4


def test_constraints_statements() -> None:
    """AC-024: constraints issues exactly the 8 statements of §5.1.4."""
    session = FakeSession(lambda cypher, params: [])
    module = _module()
    assert module.run_constraints(lambda: session) == 0
    assert [cypher for cypher, _ in session.calls] == list(module.CONSTRAINT_STATEMENTS)
    assert len(module.CONSTRAINT_STATEMENTS) == 8
    assert module.CONSTRAINT_STATEMENTS[6] == (
        "CREATE CONSTRAINT attribute_key IF NOT EXISTS FOR (a:Attribute) REQUIRE (a.attribute_name, a.attribute_value) IS UNIQUE")


class _Connector:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def is_connected(self) -> bool:
        return True

    def session(self) -> FakeSession:
        return self._session


def _index_responder(procedure_fails: bool = False):
    def respond(cypher: str, params: Mapping[str, Any]):
        if "dbms.components" in cypher:
            return [{"version": "5.14.0"}]
        if cypher.startswith("SHOW INDEXES"):
            return [{"exists": False}]
        if "createNodeIndex" in cypher and procedure_fails:
            raise RuntimeError("procedure failed")
        return []
    return respond


def test_vector_indexes_procedure_only_on_514() -> None:
    """AC-025: createNodeIndex for the 5 specs then db.awaitIndexes; no CREATE VECTOR INDEX on 5.14."""
    module = _module()
    session = FakeSession(_index_responder())
    assert module.run_vector_indexes(lambda: session, _Connector(session), 30) == 0
    queries = [cypher for cypher, _ in session.calls]
    created = [params["name"] for cypher, params in session.calls if "db.index.vector.createNodeIndex" in cypher]
    assert created == ["product_embedding_index", "brand_embedding_index", "category_embedding_index",
                       "attribute_embedding_index", "review_embedding_index"]
    assert queries[-1] == module.AWAIT_INDEXES_QUERY
    assert not any("CREATE VECTOR INDEX" in q for q in queries)

    failing = FakeSession(_index_responder(procedure_fails=True))
    assert module.run_vector_indexes(lambda: failing, _Connector(failing), 30) == 1
    assert not any("CREATE VECTOR INDEX" in cypher for cypher, _ in failing.calls)


def test_fulltext_fallback() -> None:
    """AC-026: a failed smoke test writes features_text, recreates the index over the fallback fields, re-tests and records fulltext_fields."""
    module = _module()
    state = {"smoke_calls": 0}

    def respond(cypher: str, params: Mapping[str, Any]):
        if cypher == module.SMOKE_CANDIDATES_QUERY:
            return [{"parent_asin": "T1", "title": "Cable", "description": None,
                     "features": ["Braided nylonsheath jacket"], "details_text": None}]
        if cypher == module.SMOKE_QUERY:
            state["smoke_calls"] += 1
            return [] if state["smoke_calls"] == 1 else [{"parent_asin": "T1"}]
        if cypher == module.FEATURES_TEXT_COUNT_QUERY:
            return [{"n": 0}]
        return []

    session = FakeSession(respond)
    code, fields = module.run_fulltext_index(lambda: session, 20261019, 30)
    queries = [cypher for cypher, _ in session.calls]
    assert code == 0 and fields == ["title", "description", "features_text", "details_text"]
    assert module.FEATURES_TEXT_QUERY in queries and module.DROP_FULLTEXT_QUERY in queries
    creates = [q for q in queries if q.startswith("CREATE FULLTEXT INDEX")]
    assert "p.features]" not in creates[1] and "p.features_text" in creates[1] and "p.features," in creates[0]
    assert "'english'" in creates[0]
    smoke_queries = [params["query"] for cypher, params in session.calls if cypher == module.SMOKE_QUERY]
    assert smoke_queries == ['"Braided nylonsheath jacket"', '"Braided nylonsheath jacket"']
    assert module.REMOVE_FEATURES_TEXT_QUERY not in queries


def _guard_session(products: int, versions: int, taxa: int) -> FakeSession:
    def respond(cypher: str, params: Mapping[str, Any]):
        if cypher == "MATCH (p:ParentProduct) RETURN count(p) AS n":
            return [{"n": products}]
        if cypher == "MATCH (g:GraphVersion) RETURN count(g) AS n":
            return [{"n": versions}]
        if cypher == "MATCH (t:Taxon) RETURN count(t) AS n":
            return [{"n": taxa}]
        raise AssertionError(f"no work may run after a refused guard: {cypher}")
    return FakeSession(respond)


@pytest.mark.parametrize("command", [
    ["constraints"], ["embed"], ["vector-indexes"], ["fulltext-index"], ["all"],
    ["stamp", "--confirm-validation-sha256", "x"],
])
def test_guard_product_count_mismatch(command, fixture_build) -> None:
    """AC-027: every sub-command exits 2 when the product count differs from the lineage."""
    result, base = fixture_build
    session = _guard_session(products=999, versions=0, taxa=result.lineage.counts.nodes["Taxon"])
    assert _module().main([*command, "--lineage", str(base / "lineage.json")], session_factory=lambda: session) == 2


@pytest.mark.parametrize("command", [
    ["constraints"], ["embed"], ["vector-indexes"], ["fulltext-index"], ["all"],
    ["stamp", "--confirm-validation-sha256", "x"],
])
def test_guard_sealed_graph(command, fixture_build) -> None:
    """AC-027: every sub-command exits 2 when a GraphVersion node exists."""
    result, base = fixture_build
    session = _guard_session(products=result.lineage.counts.meta.products_written, versions=1,
                             taxa=result.lineage.counts.nodes["Taxon"])
    assert _module().main([*command, "--lineage", str(base / "lineage.json")], session_factory=lambda: session) == 2


@pytest.mark.parametrize("command", [
    ["constraints"], ["embed"], ["vector-indexes"], ["fulltext-index"], ["all"],
    ["stamp", "--confirm-validation-sha256", "x"],
])
def test_guard_v1_lookalike_graph(command, fixture_build) -> None:
    """FR-021 / NFR-004 (audit fix): a graph with the lineage product count but no Taxon nodes (v1 when no
    catalogue ASIN is missing from the raw metadata) is refused with exit 2."""
    result, base = fixture_build
    assert result.lineage.counts.nodes["Taxon"] > 0
    session = _guard_session(products=result.lineage.counts.meta.products_written, versions=0, taxa=0)
    assert _module().main([*command, "--lineage", str(base / "lineage.json")], session_factory=lambda: session) == 2


def _stamp_inputs(tmp_path: Path, lineage_path: Path, passed: bool = True, lineage_sha: str = "", counts=None) -> Dict[str, Path]:
    params = BuildParams(accepted_untitled_count=3, accepted_catalogue_missing=1, expected_review_count=34,
                         expected_embed_reviews=18, embedding_device="cpu", build_profile={"NEO4J_HEAP": "4G"},
                         preflight_report_sha256="p" * 64, approved_on="2026-10-19")
    report_e = EmbeddingReport(created_at="t", sentence_transformers_version=None, torch_version=None, device=None, batch_size=256,
                               labels={"Review": LabelEmbeddingStats(template_id="review_v1", eligible=18, embedded=18)})
    paths = {"build_params": tmp_path / "build_params.json", "embedding_report": tmp_path / "embedding_report.json",
             "validation_report": tmp_path / "validation_report.json"}
    paths["build_params"].write_text(params.model_dump_json(), encoding="utf-8")
    paths["embedding_report"].write_text(report_e.model_dump_json(), encoding="utf-8")
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    validation = ValidationReport(
        created_at="t", lineage_sha256=lineage_sha or sha(lineage_path), build_params_sha256=sha(paths["build_params"]),
        embedding_report_sha256=sha(paths["embedding_report"]), graph_counts=counts or {"ParentProduct": 11, "Review": 34},
        passed=passed, hard_gates=[GateResult(id="H-01", name="product count", passed=passed)], report_only={},
    )
    paths["validation_report"].write_text(validation.model_dump_json(), encoding="utf-8")
    return paths


def _stamp_responder(products: int = 11, reviews: int = 34, taxon_guard: int = 8):
    created: List[Dict[str, Any]] = []

    def respond(cypher: str, params: Mapping[str, Any]):
        counts = {"ParentProduct": products, "Review": reviews, "User": 33, "Taxon": 8}
        for label, n in counts.items():
            if cypher == f"MATCH (n:{label}) RETURN count(n) AS n":
                return [{"n": n}]
        if cypher == "MATCH (p:ParentProduct) RETURN count(p) AS n":
            return [{"n": 11}]
        if cypher == "MATCH (g:GraphVersion) RETURN count(g) AS n":
            return [{"n": 0}]
        if cypher == "MATCH (t:Taxon) RETURN count(t) AS n":
            return [{"n": taxon_guard}]
        if cypher.startswith("SHOW INDEXES"):
            return [{"properties": ["title", "description", "features", "details_text"]}]
        if "dbms.components" in cypher:
            return [{"version": "5.14.0"}]
        if cypher.startswith("CREATE (g:GraphVersion"):
            created.append(params["props"])
            return []
        raise AssertionError(f"unexpected query: {cypher}")
    return respond, created


def _stamp_args(base: Path, paths: Dict[str, Path], confirm: str) -> List[str]:
    return ["stamp", "--lineage", str(base / "lineage.json"), "--validation-report", str(paths["validation_report"]),
            "--build-params", str(paths["build_params"]), "--embedding-report", str(paths["embedding_report"]),
            "--confirm-validation-sha256", confirm]


def test_stamp_refuses_not_passed(fixture_build, tmp_path: Path) -> None:
    """AC-030: stamp refuses a report with passed: false."""
    _, base = fixture_build
    paths = _stamp_inputs(tmp_path, base / "lineage.json", passed=False)
    respond, created = _stamp_responder()
    confirm = hashlib.sha256(paths["validation_report"].read_bytes()).hexdigest()
    assert _module().main(_stamp_args(base, paths, confirm), session_factory=lambda: FakeSession(respond)) == 2
    assert created == []


def test_stamp_refuses_lineage_hash_mismatch(fixture_build, tmp_path: Path) -> None:
    """AC-030: stamp refuses when the report's lineage_sha256 differs from the lineage file."""
    _, base = fixture_build
    paths = _stamp_inputs(tmp_path, base / "lineage.json", lineage_sha="0" * 64)
    respond, created = _stamp_responder()
    confirm = hashlib.sha256(paths["validation_report"].read_bytes()).hexdigest()
    assert _module().main(_stamp_args(base, paths, confirm), session_factory=lambda: FakeSession(respond)) == 2
    assert created == []


def test_stamp_refuses_count_mismatch(fixture_build, tmp_path: Path) -> None:
    """AC-030: stamp refuses when graph counts differ from the report."""
    _, base = fixture_build
    paths = _stamp_inputs(tmp_path, base / "lineage.json")
    respond, created = _stamp_responder(reviews=33)
    confirm = hashlib.sha256(paths["validation_report"].read_bytes()).hexdigest()
    assert _module().main(_stamp_args(base, paths, confirm), session_factory=lambda: FakeSession(respond)) == 2
    assert created == []
    respond_ok, created_ok = _stamp_responder()
    assert _module().main(_stamp_args(base, paths, "f" * 64), session_factory=lambda: FakeSession(respond_ok)) == 2
    assert created_ok == []


def test_stamp_writes_exact_properties(fixture_build, tmp_path: Path, monkeypatch) -> None:
    """AC-030: on success stamp writes exactly the §5.6 properties."""
    result, base = fixture_build
    module = _module()
    monkeypatch.setattr(module, "default_git_runner", lambda root: make_clean_git_runner("def456"))
    paths = _stamp_inputs(tmp_path, base / "lineage.json")
    respond, created = _stamp_responder()
    confirm = hashlib.sha256(paths["validation_report"].read_bytes()).hexdigest()
    assert module.main(_stamp_args(base, paths, confirm), session_factory=lambda: FakeSession(respond)) == 0
    assert len(created) == 1
    props = created[0]
    assert set(props) == SECTION_5_6_KEYS == set(GraphVersionProps.model_fields)
    lineage = result.lineage
    assert props["version"] == "v2" and props["validation_passed"] is True
    assert props["code_commit"] == "abc123" and props["stamp_commit"] == "def456"
    assert props["source_meta_sha256"] == lineage.sources.meta.sha256
    assert props["splits_sha256"] == lineage.sources.splits.combined_sha256
    assert props["catalogue_sha256"] == lineage.sources.catalogue.sha256_content
    assert props["lineage_sha256"] == hashlib.sha256((base / "lineage.json").read_bytes()).hexdigest()
    assert props["template_ids"] == ["ParentProduct=product_v1", "Review=review_v1", "Brand=brand_v1",
                                     "Attribute=attribute_v1", "Category=category_v1"]
    assert (props["product_count"], props["review_count"], props["user_count"], props["taxon_count"]) == (11, 34, 33, 8)
    assert props["fulltext_fields"] == ["title", "description", "features", "details_text"]
    assert props["neo4j_version"] == "5.14.0" and props["review_cap"] == 20
    assert all(isinstance(v, (str, int, bool)) or (isinstance(v, list) and all(isinstance(x, str) for x in v)) for v in props.values())
    json.dumps(props)


# ------------------------------------------------------------- embed step on Apple MPS (OOM resilience)


class TwoLabelGraph(ReviewGraph):
    """ReviewGraph plus Brand nodes, to check that the report keeps finished labels."""

    def __init__(self) -> None:
        super().__init__()
        self.brands: Dict[str, Any] = {"Anker": None, "Sony": None}

    def __call__(self, cypher: str, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
        if "MATCH (n:Brand) WHERE n.embedding IS NULL" in cypher:
            keys = sorted(k for k, e in self.brands.items() if e is None and k > params["after0"])
            return [{"eid": f"4:db:{k}", "k0": k, "name": k} for k in keys[:params["batch"]]]
        if "MATCH (n:Brand) WHERE elementId(n) = row.id" in cypher:
            for row in params["rows"]:
                self.brands[row["id"].split(":", 2)[2]] = row["e"]
            return [{"written": len(params["rows"])}]
        if cypher == "MATCH (n:Brand) RETURN count(n) AS n":
            return [{"n": len(self.brands)}]
        if cypher == "MATCH (n:Brand) WHERE n.embedding IS NOT NULL RETURN count(n) AS n":
            return [{"n": sum(1 for e in self.brands.values() if e is not None)}]
        return super().__call__(cypher, params)


@pytest.fixture
def no_cache(monkeypatch) -> List[str]:
    calls: List[str] = []
    monkeypatch.setattr(embedding_runtime, "empty_device_cache", lambda device: calls.append(device))
    return calls


def _params() -> BuildParams:
    return BuildParams(accepted_untitled_count=0, accepted_catalogue_missing=0, expected_review_count=9, expected_embed_reviews=8,
                       embedding_device="mps", build_profile={}, preflight_report_sha256="x", approved_on="2026-10-19")


def test_embed_survives_mps_oom_by_halving(no_cache) -> None:
    """Embed step: MPS OOM halves the encode batch; every eligible review is still embedded exactly once."""
    graph = ReviewGraph()
    embedder = embedding_runtime.ResilientEmbedder(FakeModel(oom_above=2), batch_size=8, min_batch_size=2)
    stats = _embed(graph, embedder, batch_size=3)
    assert stats.embedded == 7 and embedder.batch_size == 2 and embedder.oom_events == 2
    assert embedder.cpu_fallback_batches == 0 and no_cache == ["mps:0", "mps:0"]


def test_embed_falls_back_to_cpu_and_keeps_written_pages(no_cache) -> None:
    """Embed step: at the floor a chunk is encoded on the CPU; when even that fails, pages already written stay written and a rerun only does the rest."""
    graph = ReviewGraph()
    model = FakeModel(oom_always=True)
    embedder = embedding_runtime.ResilientEmbedder(model, batch_size=4, min_batch_size=4)
    model.cpu_error_on_call = 4  # first page: mps OOM -> cpu ok (calls 1-2); second page: mps OOM -> cpu fails (calls 3-4)
    with pytest.raises(RuntimeError, match="cpu encode failed"):
        _embed(graph, embedder, batch_size=3)
    written = {k for k, n in graph.nodes.items() if n["embedding"] is not None}
    assert written == {"r0", "r1", "r2"} and embedder.cpu_fallback_batches == 1
    healthy = embedding_runtime.ResilientEmbedder(FakeModel(device="cpu"), batch_size=4)
    stats = _embed(graph, healthy, batch_size=3)
    assert stats.embedded == 7 and sum(n for n, _, _ in healthy.model.calls) == 4


def test_run_embed_report_records_device_and_batches(tmp_path: Path, no_cache) -> None:
    """The embedding report records the device, the requested and effective encode batch, OOM events and CPU fallbacks."""
    module = _module()
    embedder = embedding_runtime.ResilientEmbedder(FakeModel(oom_above=8), batch_size=32)
    graph = ReviewGraph()
    report = module.run_embed(lambda: FakeSession(graph), embedder, ["Review"], 256, _params(), tmp_path / "er.json", time.monotonic)
    loaded = EmbeddingReport.model_validate_json((tmp_path / "er.json").read_text(encoding="utf-8"))
    assert loaded == report and loaded.device == "mps:0" and loaded.batch_size == 256
    assert (loaded.embed_batch_size, loaded.effective_embed_batch_size, loaded.oom_events, loaded.cpu_fallback_batches) == (32, 8, 2, 0)


def test_run_embed_writes_report_after_each_label(tmp_path: Path, no_cache) -> None:
    """A failure in a later label keeps the finished labels in embedding_report.json."""
    module = _module()
    graph = TwoLabelGraph()
    model = FakeModel(device="cpu", cpu_error_on_call=2)
    embedder = embedding_runtime.ResilientEmbedder(model, batch_size=8)
    with pytest.raises(RuntimeError, match="cpu encode failed"):
        module.run_embed(lambda: FakeSession(graph), embedder, ["Brand", "Review"], 256, _params(), tmp_path / "er.json", time.monotonic)
    partial = EmbeddingReport.model_validate_json((tmp_path / "er.json").read_text(encoding="utf-8"))
    assert set(partial.labels) == {"Brand"} and partial.labels["Brand"].embedded == 2


def test_embed_flags_on_embed_and_all() -> None:
    """--embed-device {auto,cpu,mps} (default auto) and --embed-batch-size (default 32) exist on embed and all, not on other sub-commands."""
    parser = _module().build_parser()
    for command in ("embed", "all"):
        defaults = parser.parse_args([command])
        assert (defaults.embed_device, defaults.embed_batch_size, defaults.batch_size) == ("auto", 32, 256)
        custom = parser.parse_args([command, "--embed-device", "cpu", "--embed-batch-size", "16"])
        assert (custom.embed_device, custom.embed_batch_size) == ("cpu", 16)
    with pytest.raises(SystemExit):
        parser.parse_args(["embed", "--embed-device", "cuda"])
    with pytest.raises(SystemExit):
        parser.parse_args(["constraints", "--embed-device", "cpu"])


def test_main_embed_builds_resilient_embedder(fixture_build, tmp_path: Path, monkeypatch, no_cache) -> None:
    """post_import_v2 embed loads the model on the requested device and wraps it in ResilientEmbedder with --embed-batch-size."""
    result, base = fixture_build
    module = _module()
    requested: List[str] = []

    def fake_load(choice):
        requested.append(choice)
        return FakeModel(oom_above=4)

    monkeypatch.setattr(module, "load_model", fake_load)
    (tmp_path / "bp.json").write_text(_params().model_dump_json(), encoding="utf-8")
    graph = ReviewGraph()
    counts = result.lineage.counts

    def respond(cypher: str, params: Mapping[str, Any]):
        if cypher == "MATCH (p:ParentProduct) RETURN count(p) AS n":
            return [{"n": counts.meta.products_written}]
        if cypher == "MATCH (g:GraphVersion) RETURN count(g) AS n":
            return [{"n": 0}]
        if "Taxon" in cypher and "count" in cypher:
            return [{"n": counts.nodes["Taxon"]}]
        return graph(cypher, params)

    code = module.main(["embed", "--lineage", str(base / "lineage.json"), "--build-params", str(tmp_path / "bp.json"),
                        "--labels", "Review", "--embed-device", "mps", "--embed-batch-size", "16",
                        "--report", str(tmp_path / "er.json")], session_factory=lambda: FakeSession(respond))
    assert code == 0 and requested == ["mps"]
    report = EmbeddingReport.model_validate_json((tmp_path / "er.json").read_text(encoding="utf-8"))
    assert (report.embed_batch_size, report.effective_embed_batch_size, report.device) == (16, 8, "mps:0")  # floor 8, then CPU
    assert report.cpu_fallback_batches == 1 and report.oom_events == 2
    assert report.labels["Review"].embedded == 7


# ------------------------------------------------- full-text: phrase smoke test and recovery of a fallback run


def _fulltext_responder(module, *, existing_fields, features_text_counts, hits_by_call):
    """Scripted full-text session: SHOW INDEXES answer, successive features_text counts, and smoke hits per index build.
    hits_by_call[i] is the set of products the i-th index build can find; a probe finds its product if listed."""
    state = {"counts": list(features_text_counts), "smoke": list(hits_by_call), "build": -1}

    def respond(cypher: str, params: Mapping[str, Any]):
        if cypher == module.FULLTEXT_PROPERTIES_QUERY:
            return [] if existing_fields is None else [{"properties": existing_fields}]
        if cypher == module.FEATURES_TEXT_COUNT_QUERY:
            return [{"n": state["counts"].pop(0) if state["counts"] else 0}]
        if cypher == module.SMOKE_CANDIDATES_QUERY:
            return [
                {"parent_asin": "B00006HC8Q", "title": "Powered Subwoofer", "description": "Deep bass", "details_text": None,
                 "features": ["Corner-loading optimization provides maximum bass performance"]},
                {"parent_asin": "P3", "title": "Cable", "description": None, "details_text": None, "features": ["Kevlar reinforced jacket"]},
            ]
        if cypher.startswith("CREATE FULLTEXT INDEX"):
            state["build"] += 1
            return []
        if cypher == module.SMOKE_QUERY:
            build = max(state["build"], 0)
            findable = state["smoke"][build] if build < len(state["smoke"]) else []
            target = "P3" if "Kevlar" in params["query"] else "B00006HC8Q"
            return [{"parent_asin": target}] if target in findable else [{"parent_asin": "X"}] * 50
        return []
    return respond


def test_fulltext_smoke_uses_escaped_phrase_and_tries_next_candidate() -> None:
    """The smoke test queries quoted, escaped phrases (limit 50) and passes when any probe finds its own product."""
    module = _module()
    session = FakeSession(_fulltext_responder(module, existing_fields=list(module.FULLTEXT_FIELDS), features_text_counts=[0],
                                              hits_by_call=[["P3"]]))
    found, query, asin = module.fulltext_smoke_test(lambda: session, 20261019)
    probes = [params for cypher, params in session.calls if cypher == module.SMOKE_QUERY]
    assert all(p["limit"] == 50 and p["query"].startswith('"') and p["query"].endswith('"') for p in probes)
    assert {p["query"] for p in probes} <= {'"Corner\\-loading optimization provides maximum bass performance"', '"Kevlar reinforced jacket"'}
    assert (found, query, asin) == (True, '"Kevlar reinforced jacket"', "P3") and probes[-1]["query"] == query
    failing = FakeSession(_fulltext_responder(module, existing_fields=None, features_text_counts=[0], hits_by_call=[[]]))
    found, query, asin = module.fulltext_smoke_test(lambda: failing, 20261019)
    assert found is False and query is not None and len([1 for c, _ in failing.calls if c == module.SMOKE_QUERY]) == 2


def test_fulltext_recovers_previous_fallback_run() -> None:
    """An index over the fallback fields is dropped, features_text is removed in paged transactions, the primary index is rebuilt and passes."""
    module = _module()
    session = FakeSession(_fulltext_responder(module, existing_fields=list(module.FULLTEXT_FALLBACK_FIELDS),
                                              features_text_counts=[215032, 0], hits_by_call=[["B00006HC8Q", "P3"]]))
    code, fields = module.run_fulltext_index(lambda: session, 20261019, 30)
    assert code == 0 and fields == list(module.FULLTEXT_FIELDS)
    queries = [cypher for cypher, _ in session.calls]
    drop, remove = queries.index(module.DROP_FULLTEXT_QUERY), queries.index(module.REMOVE_FEATURES_TEXT_QUERY)
    create = next(i for i, q in enumerate(queries) if q.startswith("CREATE FULLTEXT INDEX"))
    assert drop < remove < create and "p.features, p.details_text]" in queries[create]
    assert "IN TRANSACTIONS OF 10000 ROWS" in module.REMOVE_FEATURES_TEXT_QUERY and "REMOVE p.features_text" in module.REMOVE_FEATURES_TEXT_QUERY
    assert module.FEATURES_TEXT_QUERY not in queries


def test_fulltext_keeps_existing_primary_index_and_fails_on_leftover() -> None:
    """An existing primary index is not dropped; features_text that survives the removal fails the step."""
    module = _module()
    session = FakeSession(_fulltext_responder(module, existing_fields=list(module.FULLTEXT_FIELDS), features_text_counts=[0],
                                              hits_by_call=[["B00006HC8Q", "P3"]]))
    assert module.run_fulltext_index(lambda: session, 20261019, 30) == (0, list(module.FULLTEXT_FIELDS))
    assert module.DROP_FULLTEXT_QUERY not in [c for c, _ in session.calls]
    stuck = FakeSession(_fulltext_responder(module, existing_fields=None, features_text_counts=[10, 3], hits_by_call=[]))
    with pytest.raises(RuntimeError, match="features_text still present on 3"):
        module.run_fulltext_index(lambda: stuck, 20261019, 30)


# ------------------------------------------------------------- embed write-back by elementId, counted


class AttributeGraph:
    """Attributes keyed by elementId; two values cannot round-trip (the driver sees '?'), like the live Color values."""

    def __init__(self) -> None:
        self.nodes = {
            "4:db:1": {"name": "Color", "value": "Black", "true_value": "Black", "embedding": None},
            "4:db:2": {"name": "Color", "value": "?Saddle Brown/?Black", "true_value": "\ud83dSaddle Brown/\ud83dBlack", "embedding": None},
            "4:db:3": {"name": "Color", "value": "?????", "true_value": "\ud83d\ud83d\ud83d\ud83d\ud83d", "embedding": None},
            "4:db:4": {"name": "Material", "value": "Aluminium", "true_value": "Aluminium", "embedding": None},
        }

    def __call__(self, cypher: str, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
        if cypher.startswith("MATCH (n:Attribute) WHERE n.embedding IS NULL"):
            rows = sorted((n["name"], n["value"], eid) for eid, n in self.nodes.items() if n["embedding"] is None
                          and (n["name"], n["value"]) > (params["after0"], params["after1"]))
            return [{"eid": eid, "k0": name, "k1": value, "name": name, "value": value} for name, value, eid in rows[:params["batch"]]]
        if cypher.startswith("UNWIND $rows AS row MATCH (n:Attribute) WHERE elementId(n) = row.id"):
            for row in params["rows"]:
                self.nodes[row["id"]]["embedding"] = row["e"]
            return [{"written": len(params["rows"])}]
        if cypher == "MATCH (n:Attribute) RETURN count(n) AS n":
            return [{"n": len(self.nodes)}]
        if cypher == "MATCH (n:Attribute) WHERE n.embedding IS NOT NULL RETURN count(n) AS n":
            return [{"n": sum(1 for n in self.nodes.values() if n["embedding"] is not None)}]
        raise AssertionError(f"unexpected query: {cypher}")


def test_embed_writes_back_by_element_id() -> None:
    """Every label writes by elementId and counts rows; values that do not round-trip are still embedded."""
    module = _module()
    specs = module.label_specs("title_description_features")
    for label, spec in specs.items():
        assert "elementId(n) AS eid" in spec.fetch_query, label
        assert spec.write_query == f"UNWIND $rows AS row MATCH (n:{label}) WHERE elementId(n) = row.id SET n.embedding = row.e RETURN count(n) AS written"
    graph = AttributeGraph()
    session = FakeSession(graph)
    stats = module.embed_label(lambda: session, FakeEmbedder(), specs["Attribute"], 2, time.monotonic)
    assert stats.embedded == stats.eligible == 4
    assert all(n["embedding"] is not None for n in graph.nodes.values())
    payload_keys = {key for cypher, params in session.calls if cypher.startswith("UNWIND") for row in params["rows"] for key in row}
    assert payload_keys == {"id", "e"}


def test_embed_write_count_mismatch_fails_and_rerun_completes(caplog) -> None:
    """A page that writes fewer embeddings than encoded is logged and fails the step after the label; written pages stay,
    and a re-run embeds only the nodes still missing an embedding."""
    module = _module()
    graph = ReviewGraph()
    graph.unwritable = {"r1"}
    with caplog.at_level("ERROR", logger="post_import_v2"):
        with pytest.raises(RuntimeError, match="encoded 3 texts but wrote 2") as raised:
            _embed(graph, FakeEmbedder(), batch_size=3)
    assert type(raised.value).__name__ == "EmbedWriteError" and issubclass(module.EmbedWriteError, RuntimeError)
    assert any("but wrote 2 embeddings" in r.getMessage() for r in caplog.records)
    missing = {k for k, n in graph.nodes.items() if n["embed_rank"] is not None and n["embedding"] is None}
    assert missing == {"r1", "r_blank"}
    graph.unwritable = set()
    rerun = FakeEmbedder()
    stats = _embed(graph, rerun, batch_size=3)
    assert [text for batch in rerun.batches for text in batch] == ["Title 1. Body"]
    assert stats.embedded == 7 and stats.skipped_empty == 1


def test_embed_repeated_page_stops() -> None:
    """If the same page comes back twice (no progress), the label stops instead of looping."""
    module = _module()
    spec = module.label_specs("title_description_features")["Review"]

    def stuck(cypher: str, params: Mapping[str, Any]):
        if cypher.startswith("MATCH (n:Review) WHERE n.embed_rank"):
            return [{"eid": "4:db:x", "k0": "x", "title": " ", "body": ""}]
        raise AssertionError(cypher)

    with pytest.raises(RuntimeError, match="same page was returned twice"):
        module.embed_label(lambda: FakeSession(stuck), FakeEmbedder(), spec, 1, time.monotonic)
