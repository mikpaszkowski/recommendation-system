"""
tests/graph_v2/test_transform.py

End-to-end transform on the fixtures (FR-005 … FR-018): AC-001 … AC-003, AC-009 … AC-011, AC-013, AC-016, AC-018 … AC-020.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Dict, List

import pytest

from src.knowledge_graph.graph_v2.csv_io import HEADERS, read_import_csv
from src.knowledge_graph.graph_v2.lineage import InputVerificationError, comparable_view, load_lineage
from src.knowledge_graph.graph_v2.transform import CleanTreeError, in_sample, run_transform

REPO_ROOT = Path(__file__).resolve().parents[2]


def _rows(base: Path, name: str) -> List[Dict[str, str]]:
    return list(read_import_csv(base / "import" / name))


def _all_csv_text(base: Path) -> str:
    return "".join((base / "import" / name).read_text(encoding="utf-8") for name in HEADERS)


def _load_cli():
    spec = importlib.util.spec_from_file_location("build_graph_v2_under_test", REPO_ROOT / "scripts" / "graph_ingestion" / "build_graph_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_meta_not_in_catalogue_counted(fixture_build) -> None:
    """AC-001: meta lines whose parent_asin is not in the catalogue produce no product row and count as not_in_catalogue."""
    result, base = fixture_build
    assert result.lineage.counts.meta.not_in_catalogue == 1
    assert "X999" not in {row["parent_asin:ID(ParentProduct)"] for row in _rows(base, "nodes_product.csv")}
    assert "X999" not in _all_csv_text(base)


def test_catalogue_asin_without_meta(fixture_build) -> None:
    """AC-002: T011 gets no product; its reviews are product_missing; no CSV row references it."""
    result, base = fixture_build
    counts = result.lineage.counts
    assert counts.meta.catalogue_missing_in_meta == 1 and counts.reviews.product_missing == 2
    assert "T011" not in _all_csv_text(base)
    assert "U600" not in _all_csv_text(base) and "U601" not in _all_csv_text(base)


def test_split_exclusion_per_user_and_parent(fixture_build) -> None:
    """AC-003: valid/test pairs are dropped even with a different child asin; train pair kept with in_train_split true; no-split pair false."""
    result, base = fixture_build
    wrote = {row[":END_ID(Review)"]: row[":START_ID(User)"] for row in _rows(base, "rels_wrote.csv")}
    by_user = {wrote[row["review_id:ID(Review)"]]: row for row in _rows(base, "nodes_review.csv")
               if row["review_body"] and "pair" in row["review_body"]}
    assert "U100" not in by_user and "U103" not in by_user
    assert by_user["U101"]["in_train_split:boolean"] == "true"
    assert by_user["U102"]["in_train_split:boolean"] == "false"
    assert result.lineage.counts.reviews.valid_test_pair == 3


def test_brand_nodes_and_case_group_in_lineage(fixture_build) -> None:
    """AC-009: "Anker" and "ANKER" are two Brand rows and one brand_case_duplicate_groups entry."""
    result, base = fixture_build
    brands = {row["name:ID(Brand)"] for row in _rows(base, "nodes_brand.csv")}
    assert {"Anker", "ANKER", "FallbackBrand"} <= brands
    assert result.lineage.counts.brand_case_duplicate_groups == 1
    assert result.lineage.duplicates.brand_case_groups == [["ANKER", "Anker"]]
    has_brand = {row[":START_ID(ParentProduct)"]: row[":END_ID(Brand)"] for row in _rows(base, "rels_has_brand.csv")}
    assert has_brand["T003"] == "FallbackBrand" and "T004" not in has_brand


def test_blank_main_category_has_no_edge(fixture_build) -> None:
    """AC-010: a blank main_category gives no BELONGS_TO_CATEGORY row."""
    _, base = fixture_build
    categories = {row[":START_ID(ParentProduct)"]: row[":END_ID(Category)"] for row in _rows(base, "rels_belongs_to_category.csv")}
    assert "T005" not in categories and categories["T003"] == "Computers"
    assert {row["name:ID(Category)"] for row in _rows(base, "nodes_category.csv")} == {
        "All Electronics", "Cell Phones & Accessories", "Computers", "Home Audio"}


def test_attributes_deduplicated_across_products(fixture_build) -> None:
    """AC-011: identical (name, value) pairs give one Attribute row; nodes_attribute.csv has no numeric_value column."""
    _, base = fixture_build
    attributes = _rows(base, "nodes_attribute.csv")
    pairs = sorted((row["attribute_name"], row["attribute_value"]) for row in attributes)
    assert pairs == [("Color", "Black"), ("Material", "Aluminium"), ("Style", "Modern")]
    assert len(_rows(base, "rels_has_attribute.csv")) == 7
    header = (base / "import" / "nodes_attribute.csv").read_text(encoding="utf-8").split("\n", 1)[0]
    assert "numeric_value" not in header


def test_user_without_kept_reviews_has_no_row(fixture_build) -> None:
    """AC-013: U300 (excluded only) and U301 (beyond cap only) have no User row."""
    _, base = fixture_build
    users = {row["user_id:ID(User)"] for row in _rows(base, "nodes_user.csv")}
    assert "U300" not in users and "U301" not in users and "U025" not in users
    assert {"U001", "U101", "U102", "U023"} <= users
    assert {row[":START_ID(User)"] for row in _rows(base, "rels_wrote.csv")} == users


def test_two_runs_byte_identical(transform_config, clean_git_runner) -> None:
    """AC-016: two runs give byte-identical CSVs and identical lineage counts, outputs and parameters."""
    first = run_transform(transform_config("a"), git_runner=clean_git_runner)
    second = run_transform(transform_config("b"), git_runner=clean_git_runner)
    base_a, base_b = transform_config("a").out_dir, transform_config("b").out_dir
    for name in HEADERS:
        assert (base_a / name).read_bytes() == (base_b / name).read_bytes(), name
    assert comparable_view(first.lineage) == comparable_view(second.lineage)


def test_sha256_mismatch_exits_before_output(fixture_copy: Path, tmp_path: Path) -> None:
    """AC-018: a SHA256SUMS mismatch exits 2 before any output file exists."""
    with open(fixture_copy / "meta.jsonl", "a", encoding="utf-8") as handle:
        handle.write("{}\n")
    out = tmp_path / "out"
    code = _load_cli().main([
        "--meta", str(fixture_copy / "meta.jsonl"), "--reviews", str(fixture_copy / "reviews.jsonl"),
        "--sha256sums", str(fixture_copy / "SHA256SUMS"), "--splits-dir", str(fixture_copy),
        "--catalogue", str(fixture_copy / "catalogue.txt"), "--out-dir", str(out), "--lineage", str(out / "lineage.json"),
    ])
    assert code == 2 and not out.exists()


def test_missing_split_exits_before_output(fixture_copy: Path, tmp_path: Path, transform_config) -> None:
    """AC-018: a missing split file exits 2 before any output file exists."""
    (fixture_copy / "Electronics.valid.csv").unlink()
    config = transform_config("missing_split", splits_dir=fixture_copy)
    with pytest.raises(InputVerificationError):
        run_transform(config)
    assert not config.out_dir.exists() and not config.lineage_path.exists()


def test_sample_mod_selection(fixture_build, transform_config, clean_git_runner) -> None:
    """AC-019: --sample-mod 4 keeps hash-selected products; every relationship row points to a sampled product; review selection equals the full run for those products."""
    full_result, full_base = fixture_build
    config = transform_config("pilot", sample_mod=4)
    result = run_transform(config, git_runner=clean_git_runner)
    pilot = config.out_dir.parent
    sampled = {row["parent_asin:ID(ParentProduct)"] for row in _rows(pilot, "nodes_product.csv")}
    assert sampled == {"T008", "T010"} and all(in_sample(asin, 4) for asin in sampled)
    for name in ("rels_has_brand.csv", "rels_belongs_to_category.csv", "rels_has_attribute.csv", "rels_in_taxon.csv"):
        assert {row[":START_ID(ParentProduct)"] for row in _rows(pilot, name)} <= sampled
    assert {row[":END_ID(ParentProduct)"] for row in _rows(pilot, "rels_about_product.csv")} <= sampled

    def selection(base: Path) -> set:
        about = {row[":START_ID(Review)"]: row[":END_ID(ParentProduct)"] for row in _rows(base, "rels_about_product.csv")}
        return {tuple(sorted(row.items())) for row in _rows(base, "nodes_review.csv") if about[row["review_id:ID(Review)"]] in sampled}

    assert selection(pilot) == selection(full_base) and len(selection(pilot)) == 6
    assert result.lineage.sources.catalogue.sampled_count == 2 and result.lineage.parameters.sample_mod == 4


def test_dry_run_writes_nothing_same_counts(fixture_build, transform_config, clean_git_runner) -> None:
    """AC-020: --dry-run writes no CSV and returns the same counts as a full run."""
    full_result, _ = fixture_build
    config = transform_config("dry", dry_run=True)
    result = run_transform(config, git_runner=clean_git_runner)
    assert not config.out_dir.exists() and not config.lineage_path.exists() and result.wrote_files is False
    assert result.lineage.counts == full_result.lineage.counts
    assert {k: v.rows for k, v in result.lineage.outputs.items()} == {k: v.rows for k, v in full_result.lineage.outputs.items()}


def test_require_clean_refuses_dirty_tree(transform_config) -> None:
    """FR-018: --require-clean exits 2 on a dirty src/ or scripts/ (fake git runner)."""
    def dirty(args):
        if args[0] == "rev-parse":
            return 0, "abc123\n"
        if args[0] == "status":
            return 0, " M src/tools/graph_search_tool.py\n"
        return 0, ""

    config = transform_config("dirty", require_clean=True)
    with pytest.raises(CleanTreeError):
        run_transform(config, git_runner=dirty)
    assert not config.out_dir.exists()


def test_cli_exit_codes(tmp_path: Path, fixture_dir: Path, monkeypatch) -> None:
    """FR-005 / FR-015: build_graph_v2.main returns 0 on success and 2 on GraphBuildError."""
    module = _load_cli()
    out = tmp_path / "cli"
    args = [
        "--meta", str(fixture_dir / "meta.jsonl"), "--reviews", str(fixture_dir / "reviews.jsonl"),
        "--sha256sums", str(fixture_dir / "SHA256SUMS"), "--splits-dir", str(fixture_dir),
        "--catalogue", str(fixture_dir / "catalogue.txt"), "--out-dir", str(out), "--lineage", str(out / "lineage.json"),
    ]
    assert module.main(args) == 0
    assert (out / "import" / "nodes_product.csv").exists() and (out / "lineage.json").exists()
    assert module.main(args[:-2] + ["--lineage", str(tmp_path / "l2.json"), "--sample-mod", "0"]) == 2


def _cli_args(fixture_dir: Path, out: Path) -> List[str]:
    """CLI arguments for a fixture build writing into `out`."""
    return [
        "--meta", str(fixture_dir / "meta.jsonl"), "--reviews", str(fixture_dir / "reviews.jsonl"),
        "--sha256sums", str(fixture_dir / "SHA256SUMS"), "--splits-dir", str(fixture_dir),
        "--catalogue", str(fixture_dir / "catalogue.txt"), "--out-dir", str(out), "--lineage", str(out / "lineage.json"),
    ]


def test_cli_refuses_to_overwrite_without_force(tmp_path: Path, fixture_dir: Path) -> None:
    """Audit DL-2: a second write run refuses (exit 2) unless --force; --dry-run never needs --force."""
    module = _load_cli()
    out = tmp_path / "cli"
    lineage = out / "lineage.json"
    args = _cli_args(fixture_dir, out)
    assert module.main(args) == 0
    first = comparable_view(load_lineage(lineage))
    lineage.write_text("approved lineage", encoding="utf-8")
    assert module.main(args) == 2
    assert lineage.read_text(encoding="utf-8") == "approved lineage"
    assert module.main(args + ["--dry-run"]) == 0
    assert lineage.read_text(encoding="utf-8") == "approved lineage"
    assert module.main(args + ["--force"]) == 0
    assert comparable_view(load_lineage(lineage)) == first


def test_cli_refuses_non_empty_csv_dir_without_lineage(tmp_path: Path, fixture_dir: Path) -> None:
    """Audit DL-2: leftover CSVs without a lineage file also block a write run unless --force."""
    module = _load_cli()
    out = tmp_path / "cli"
    (out / "import").mkdir(parents=True)
    (out / "import" / "nodes_product.csv").write_text("stale", encoding="utf-8")
    args = _cli_args(fixture_dir, out)
    assert module.main(args) == 2
    assert not (out / "lineage.json").exists()
    assert module.main(args + ["--force"]) == 0

