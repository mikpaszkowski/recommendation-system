"""
tests/graph_v2/test_validation.py

Validation gates and report (FR-026, §5.5): AC-028, AC-029; pilot thresholds (amendment A-3): AC-047.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping

import pytest

from src.knowledge_graph.graph_v2 import validation as v
from src.knowledge_graph.graph_v2.lineage import InputVerificationError
from src.knowledge_graph.graph_v2.models import BuildParams, EmbeddingReport, LabelEmbeddingStats, ValidationReport
from src.knowledge_graph.graph_v2.transform import run_transform

from .conftest import FakeEmbedder, FakeSession, fixture_config, make_clean_git_runner


@pytest.fixture(scope="module")
def ctx(fixture_build):
    """Fixture lineage plus build params and embedding report consistent with it."""
    result, _ = fixture_build
    lineage = result.lineage
    params = BuildParams(
        accepted_untitled_count=lineage.counts.meta.title_empty, accepted_catalogue_missing=1,
        expected_review_count=lineage.counts.reviews.kept, expected_embed_reviews=lineage.counts.reviews.embed_selected,
        embedding_device="cpu", build_profile={}, preflight_report_sha256="p" * 64, approved_on="2026-10-19",
    )
    coverage = {label: v.LabelCoverage(embedded=5, eligible=5, wrong_dimension=0) for label in ("Attribute", "Brand", "Category", "ParentProduct")}
    coverage["Review"] = v.LabelCoverage(embedded=params.expected_embed_reviews, eligible=params.expected_embed_reviews, wrong_dimension=0)
    report = EmbeddingReport(
        created_at="t", sentence_transformers_version=None, torch_version=None, device=None, batch_size=256,
        labels={label: LabelEmbeddingStats(template_id="x", eligible=c.eligible, embedded=c.embedded) for label, c in coverage.items()},
    )
    online = [v.IndexState(name, "VECTOR", "ONLINE", 100.0, ("embedding",)) for name in v.VECTOR_INDEX_NAMES]
    online.append(v.IndexState(v.FULLTEXT_INDEX_NAME, "FULLTEXT", "ONLINE", 100.0, ("title", "description", "features", "details_text")))
    return {"lineage": lineage, "params": params, "coverage": coverage, "report": report, "online": online}


def _cases(c):
    lineage, params = c["lineage"], c["params"]
    nodes, rels = dict(lineage.counts.nodes), dict(lineage.counts.relationships)
    off_by_one = {**nodes, "Review": nodes["Review"] + 1}
    bad_dim = {**c["coverage"], "Brand": v.LabelCoverage(5, 5, 1)}
    at_99 = [s if s.name != "review_embedding_index" else s._replace(population_percent=99.5) for s in c["online"]]
    sample = [("U1", "T1", True), ("U2", "T1", False)]
    good_taxa = [v.TaxonCountCheck("A", 3, 3)]
    return [
        ("H-01", lambda: v.gate_product_count(11, lineage, params, 12), lambda: v.gate_product_count(10, lineage, params, 12)),
        ("H-02", lambda: v.gate_catalogue_membership(["T001", "T002"], {"T001", "T002"}),
                 lambda: v.gate_catalogue_membership(["T001", None, "X999"], {"T001"})),
        ("H-03", lambda: v.gate_untitled(3, lineage, params), lambda: v.gate_untitled(4, lineage, params)),
        ("H-04", lambda: v.gate_ghost_signature(0), lambda: v.gate_ghost_signature(1)),
        ("H-05", lambda: v.gate_review_integrity(0, 0), lambda: v.gate_review_integrity(1, 0)),
        ("H-06", lambda: v.gate_split_exclusion(0, sample, {("U1", "T1")}), lambda: v.gate_split_exclusion(1, sample, {("U1", "T1")})),
        ("H-07", lambda: v.gate_cap(20, 0, 20), lambda: v.gate_cap(21, 0, 20)),
        ("H-08", lambda: v.gate_review_count(34, lineage, params), lambda: v.gate_review_count(33, lineage, params)),
        ("H-09", lambda: v.gate_constraints(v.REQUIRED_CONSTRAINTS, False), lambda: v.gate_constraints(v.REQUIRED_CONSTRAINTS[:-1], False)),
        ("H-10", lambda: v.gate_embedding_coverage(c["coverage"], c["report"], params),
                 lambda: v.gate_embedding_coverage(bad_dim, c["report"], params)),
        ("H-11", lambda: v.gate_no_blank_embeddings(0, 0, {"product_blank[Unknown]": 0.61, "review_blank": 0.42}),
                 lambda: v.gate_no_blank_embeddings(0, 0, {"product_blank[Unknown]": 0.99995})),
        ("H-12", lambda: v.gate_indexes_online(c["online"]), lambda: v.gate_indexes_online(at_99)),
        ("H-13", lambda: v.gate_fulltext_smoke(True, "nylonsheath", "T1", ["title"]), lambda: v.gate_fulltext_smoke(False, "nylonsheath", "T1", ["title"])),
        ("H-14", lambda: v.gate_import_fidelity(10, []),
                 lambda: v.gate_import_fidelity(10, [v.FidelityMismatch("Review", "r1", "review_body", "a\nb", "a\r\nb")])),
        ("H-15", lambda: v.gate_benchmark_grounding(None, 21), lambda: v.gate_benchmark_grounding("ServiceUnavailable: no route", 21)),
        ("H-16", lambda: v.gate_no_legacy_schema({"ParentProduct": 11}, {"WROTE": 34}, 0),
                 lambda: v.gate_no_legacy_schema({"Variant": 1}, {}, 0)),
        ("H-17", lambda: v.gate_taxon_integrity(0, 0, rels["IN_TAXON"], lineage, good_taxa),
                 lambda: v.gate_taxon_integrity(0, 0, rels["IN_TAXON"], lineage, [v.TaxonCountCheck("A", 3, 2)])),
        ("H-18", lambda: v.gate_counts_match(nodes, rels, lineage, 0), lambda: v.gate_counts_match(off_by_one, rels, lineage, 0)),
    ]


def test_each_gate_passes_and_fails(ctx) -> None:
    """AC-028: table-driven; each gate H-01 … H-18 passes on a conforming input and fails on a minimal violation."""
    cases = _cases(ctx)
    assert [gate_id for gate_id, _, _ in cases] == list(v.GATE_NAMES)
    for gate_id, ok, bad in cases:
        good, broken = ok(), bad()
        assert (good.id, good.passed) == (gate_id, True), (gate_id, good)
        assert (broken.id, broken.passed) == (gate_id, False), (gate_id, broken)
        assert good.name == v.GATE_NAMES[gate_id]
    lineage, params = ctx["lineage"], ctx["params"]
    assert not v.gate_split_exclusion(0, [("U1", "T1", False)], {("U1", "T1")}).passed
    assert not v.gate_cap(20, 1, 20).passed
    assert not v.gate_counts_match(dict(lineage.counts.nodes), dict(lineage.counts.relationships), lineage, 1).passed
    assert v.gate_constraints(v.REQUIRED_CONSTRAINTS[:6] + ("graph_version_id",), True).passed
    assert not v.gate_benchmark_grounding(None, 0).passed and v.gate_benchmark_grounding(None, 0, allow_empty=True).passed
    assert not v.gate_review_count(34, lineage, params.model_copy(update={"expected_review_count": 35})).passed


def test_report_validates_and_fails_on_gate(ctx) -> None:
    """AC-029: the report validates against ValidationReport; any failed hard gate gives passed: false and exit 1."""
    good = [ok() for _, ok, _ in _cases(ctx)]
    kwargs = dict(pilot=False, seed=20261019, lineage_sha256="l", build_params_sha256="b", embedding_report_sha256="e",
                  graph_counts={"ParentProduct": 11, "Review": 34}, created_at="2026-10-19T00:00:00Z")
    report = v.build_report(good, {}, **kwargs)
    assert report.passed is True and v.exit_code(report) == 0 and [g.id for g in report.hard_gates] == list(v.GATE_NAMES)
    assert set(report.report_only) == set(v.REPORT_ONLY_IDS)
    failing = good[:3] + [v.gate_ghost_signature(1)] + good[4:]
    bad_report = v.build_report(failing, {}, **kwargs)
    assert bad_report.passed is False and v.exit_code(bad_report) == 1
    assert ValidationReport.model_validate_json(bad_report.model_dump_json()) == bad_report
    missing = v.build_report(good[:-1], {}, **kwargs)
    assert missing.passed is False and missing.hard_gates[-1].detail == "gate not evaluated"


def test_report_only_never_changes_passed(ctx) -> None:
    """AC-029: report-only findings never change passed."""
    good = [ok() for _, ok, _ in _cases(ctx)]
    alarming = {"R-04": {"count": 10_000, "identical_with_different_text": ["x"]}, "R-07": {"differences": [{"query_id": "q"}]},
                "R-01": {"error": "RuntimeError: query failed"}}
    report = v.build_report(good, alarming, pilot=True, seed=1, lineage_sha256="l", build_params_sha256="b",
                            embedding_report_sha256="e", graph_counts={}, created_at="t")
    assert report.passed is True and report.report_only["R-04"]["count"] == 10_000
    json.loads(report.model_dump_json())


def test_pick_smoke_token_seeded() -> None:
    """FR-025 / H-13 (support): pick_smoke_token is deterministic for a seed and skips tokens present in title, description or details_text."""
    products = [
        {"parent_asin": "P1", "title": "Charging cable", "description": "braided", "details_text": None,
         "features": ["Braided charging cable", "Kevlar reinforced"]},
        {"parent_asin": "P2", "title": "Hub", "description": None, "details_text": "Ports: aluminium",
         "features": ["Aluminium shell"]},
        {"parent_asin": "P3", "title": "x", "description": None, "details_text": None, "features": ["short"]},
    ]
    choice = v.pick_smoke_token(products, 20261019)
    assert choice == v.pick_smoke_token(products, 20261019)
    assert choice == ("P1", "reinforced")
    assert v.pick_smoke_token(products[1:], 1) is None
    assert v.isbn_like(["0123456789", "012345678X", "B0123", "123456789"]) == ["0123456789", "012345678X"]


# ------------------------------------------------------------------------- AC-047: pilot thresholds (A-3)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_pilot_test", REPO_ROOT / "scripts" / "graph_ingestion" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VG = _script("validate_graph")
FULL_PARAMS = BuildParams(
    accepted_untitled_count=3, accepted_catalogue_missing=1, expected_review_count=34, expected_embed_reviews=18,
    embedding_device="cpu", build_profile={"NEO4J_HEAP": "4G"}, preflight_report_sha256="p" * 64, approved_on="2026-10-19",
    product_content_rule="title_description", review_cap=20,
)


@pytest.fixture(scope="module")
def pilot_build(tmp_path_factory):
    """Fixture transform at --sample-mod 4 (products T008, T010): (TransformResult, base dir)."""
    base = tmp_path_factory.mktemp("pilot_build")
    return run_transform(fixture_config(base, sample_mod=4), git_runner=make_clean_git_runner()), base


def test_pilot_build_params_substitutes_three_counts(pilot_build) -> None:
    """AC-047: pilot_build_params copies exactly the three lineage counts; every other field is unchanged."""
    lineage = pilot_build[0].lineage
    pilot = v.pilot_build_params(FULL_PARAMS, lineage)
    assert pilot.accepted_catalogue_missing == lineage.counts.meta.catalogue_missing_in_meta == 0
    assert pilot.expected_review_count == lineage.counts.reviews.kept == 6
    assert pilot.expected_embed_reviews == lineage.counts.reviews.embed_selected == 6
    changed = {k for k in BuildParams.model_fields if getattr(pilot, k) != getattr(FULL_PARAMS, k)}
    assert changed == {"accepted_catalogue_missing", "expected_review_count", "expected_embed_reviews"}
    assert FULL_PARAMS.expected_review_count == 34


class _FakeGraph:
    """Answers the H-01 … H-04, H-07/H-08 and H-10 collector queries; any other query fails its own collector."""

    def __init__(self, products: int, asins, untitled: int, reviews: int, embedded: Mapping[str, int]) -> None:
        self.products, self.asins, self.untitled, self.reviews, self.embedded = products, list(asins), untitled, reviews, dict(embedded)

    def __call__(self, cypher: str, params: Mapping[str, Any]):
        if "size(n.embedding) <>" in cypher or "keys(p)" in cypher or "collect(DISTINCT r.cap_rank)" in cypher:
            return [{"n": 0}]
        if "trim(p.title) = ''" in cypher:
            return [{"n": self.untitled}]
        if cypher == "MATCH (p:ParentProduct) RETURN p.parent_asin AS asin":
            return [{"asin": a} for a in self.asins]
        if cypher == "MATCH (p:ParentProduct) RETURN count(p) AS n":
            return [{"n": self.products}]
        if "RETURN max(COUNT" in cypher:
            return [{"n": min(self.reviews, 3)}]
        if cypher == "MATCH (r:Review) RETURN count(r) AS n":
            return [{"n": self.reviews}]
        match = re.match(r"MATCH \(n:(\w+)\)", cypher)
        if match and match.group(1) in self.embedded and cypher.endswith("RETURN count(n) AS n"):
            return [{"n": self.embedded[match.group(1)]}]
        raise AssertionError(f"query outside this test's scope: {cypher[:60]}")


def _embedding_report(counts: Mapping[str, int]) -> EmbeddingReport:
    return EmbeddingReport(created_at="t", sentence_transformers_version=None, torch_version=None, device="cpu", batch_size=256,
                           labels={label: LabelEmbeddingStats(template_id="x", eligible=n, embedded=n) for label, n in counts.items()})


def _pilot_args(tmp_path: Path, pilot: bool = True):
    benchmark = tmp_path / "bench.json"
    benchmark.write_text('[{"query_id": "q1", "target_asin": "T001"}]', encoding="utf-8")
    argv = ["--lineage", str(tmp_path / "l.json"), "--build-params", str(tmp_path / "b.json"),
            "--embedding-report", str(tmp_path / "e.json"), "--splits-dir", str(tmp_path / "no_splits"),
            "--catalogue", str(tmp_path / "c.txt"), "--import-dir", str(tmp_path / "no_import"),
            "--benchmark", str(benchmark), "--out", str(tmp_path / "out.json")]
    return VG.build_parser().parse_args(argv + (["--pilot"] if pilot else []))


def _gates(report: ValidationReport) -> Dict[str, bool]:
    return {gate.id: gate.passed for gate in report.hard_gates}


def _run(pilot_build, tmp_path: Path, graph: _FakeGraph, lineage=None, pilot: bool = True) -> ValidationReport:
    lineage = lineage or pilot_build[0].lineage
    counts = {"Attribute": 1, "Brand": 1, "Category": 1, "ParentProduct": 2, "Review": lineage.counts.reviews.embed_selected}
    inputs = VG.ValidationInputs(lineage, FULL_PARAMS, _embedding_report(counts), {"T008", "T010"},
                                 {"lineage": "l" * 64, "build_params": "b" * 64, "embedding_report": "e" * 64})
    return VG.run_validation(_pilot_args(tmp_path, pilot), lambda: FakeSession(graph), object(), FakeEmbedder(), inputs)


def test_pilot_counts_pass_against_pilot_graph(pilot_build, tmp_path: Path) -> None:
    """AC-047 (a): in --pilot mode H-01, H-08 and H-10 pass when the fake graph matches the pilot lineage."""
    graph = _FakeGraph(2, ["T008", "T010"], 0, 6, {"Attribute": 1, "Brand": 1, "Category": 1, "ParentProduct": 2, "Review": 6})
    gates_passed = _gates(_run(pilot_build, tmp_path, graph))
    assert (gates_passed["H-01"], gates_passed["H-03"], gates_passed["H-08"], gates_passed["H-10"]) == (True, True, True, True)


def test_pilot_counts_fail_against_full_build_graph(pilot_build, tmp_path: Path) -> None:
    """AC-047 (b): the same gates fail when the fake graph matches the full-build counts instead."""
    graph = _FakeGraph(11, ["T008", "T010"], 0, 34, {"Attribute": 1, "Brand": 1, "Category": 1, "ParentProduct": 2, "Review": 18})
    gates_passed = _gates(_run(pilot_build, tmp_path, graph))
    assert (gates_passed["H-01"], gates_passed["H-08"], gates_passed["H-10"]) == (False, False, False)


def test_pilot_untitled_bound_stays_from_build_params(pilot_build, tmp_path: Path) -> None:
    """AC-047 (c): H-03 fails when the untitled count equals the lineage title_empty but exceeds accepted_untitled_count."""
    lineage = pilot_build[0].lineage
    noisy = lineage.model_copy(deep=True)
    noisy.counts.meta.title_empty = 4
    graph = _FakeGraph(2, ["T008", "T010"], 4, 6, {"Attribute": 1, "Brand": 1, "Category": 1, "ParentProduct": 2, "Review": 6})
    report = _run(pilot_build, tmp_path, graph, lineage=noisy)
    h03 = next(g for g in report.hard_gates if g.id == "H-03")
    assert h03.passed is False and h03.expected == {"lineage_title_empty": 4, "max": 3}


def test_pilot_report_hashes_file_read_and_mode_errors(pilot_build, fixture_build, fixture_dir: Path, tmp_path: Path) -> None:
    """AC-047 (d): build_params_sha256 is the hash of the file read; without --pilot the counts are unchanged and a pilot
    lineage is an input error (exit 2); --pilot with a full lineage is an input error too."""
    _, pilot_base = pilot_build
    _, full_base = fixture_build
    (tmp_path / "b.json").write_text(FULL_PARAMS.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "e.json").write_text(_embedding_report({"Review": 6}).model_dump_json(), encoding="utf-8")
    common = ["--build-params", str(tmp_path / "b.json"), "--embedding-report", str(tmp_path / "e.json"),
              "--splits-dir", str(fixture_dir), "--catalogue", str(fixture_dir / "catalogue.txt"),
              "--import-dir", str(tmp_path / "no_import"), "--benchmark", str(tmp_path / "none.json"), "--out", str(tmp_path / "out.json")]
    args = VG.resolve_paths(VG.build_parser().parse_args(["--pilot", "--lineage", str(pilot_base / "lineage.json"), *common]))
    inputs = VG.load_inputs(args)
    assert inputs.file_hashes["build_params"] == hashlib.sha256((tmp_path / "b.json").read_bytes()).hexdigest()
    assert inputs.build_params == FULL_PARAMS and inputs.catalogue == {"T008", "T010"}
    (tmp_path / "none.json").write_text("[]", encoding="utf-8")
    report = VG.run_validation(args, lambda: FakeSession(_FakeGraph(2, [], 0, 6, {})), object(), FakeEmbedder(), inputs)
    assert report.build_params_sha256 == inputs.file_hashes["build_params"] and report.pilot is True

    full_inputs = VG.ValidationInputs(fixture_build[0].lineage, FULL_PARAMS, None, set(), {})
    assert VG.effective_build_params(full_inputs, pilot=False) is FULL_PARAMS
    with pytest.raises(InputVerificationError):
        VG.run_validation(_pilot_args(tmp_path, pilot=False), lambda: FakeSession(lambda c, p: []), object(), FakeEmbedder(), inputs)
    embedder = FakeEmbedder()
    no_pilot = ["--lineage", str(pilot_base / "lineage.json"), *common]
    assert VG.main(no_pilot, session_factory=lambda: pytest.fail("no session on input error"), embedder=embedder) == 2
    wrong_lineage = ["--pilot", "--lineage", str(full_base / "lineage.json"), *common]
    assert VG.main(wrong_lineage, session_factory=lambda: pytest.fail("no session on input error"), embedder=embedder) == 2


def test_pilot_default_paths_consistent(tmp_path: Path) -> None:
    """A-3 / §6.4: build_graph_v2 --sample-mod and validate_graph --pilot default to the same pilot artefacts."""
    build = _script("build_graph_v2")
    root = Path("/repo")
    pilot_cfg = build.config_from_args(build.build_parser().parse_args(["--sample-mod", "20"]), repo_root=root)
    full_cfg = build.config_from_args(build.build_parser().parse_args([]), repo_root=root)
    assert pilot_cfg.out_dir == root / "datasets/graph_build/v2_pilot/import"
    assert pilot_cfg.lineage_path == root / "graph_versions/v2/pilot/lineage.json"
    assert full_cfg.out_dir == root / "datasets/graph_build/v2/import" and full_cfg.lineage_path == root / "graph_versions/v2/lineage.json"
    assert pilot_cfg.meta_path == full_cfg.meta_path == root / "datasets/raw/meta_Electronics.jsonl"
    pilot_args = VG.resolve_paths(VG.build_parser().parse_args(["--pilot"]), repo_root=root)
    assert pilot_args.lineage == pilot_cfg.lineage_path and pilot_args.import_dir == pilot_cfg.out_dir
    assert pilot_args.embedding_report == root / "graph_versions/v2/pilot/embedding_report.json"
    assert pilot_args.out == root / "graph_versions/v2/pilot/validation_report.json"
    assert pilot_args.build_params == root / "graph_versions/v2/build_params.json"
    full_args = VG.resolve_paths(VG.build_parser().parse_args([]), repo_root=root)
    assert full_args.lineage == full_cfg.lineage_path and full_args.import_dir == full_cfg.out_dir
    assert full_args.build_params == pilot_args.build_params
    explicit = VG.resolve_paths(VG.build_parser().parse_args(["--pilot", "--out", str(tmp_path / "x.json")]), repo_root=root)
    assert explicit.out == tmp_path / "x.json"
