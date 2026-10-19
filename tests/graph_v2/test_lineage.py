"""
tests/graph_v2/test_lineage.py

Lineage model, input verification and invariants (FR-005, FR-015): AC-017, AC-018.
"""
from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

from src.knowledge_graph.graph_v2 import transform as transform_module
from src.knowledge_graph.graph_v2.lineage import (
    InputVerificationError,
    IntegrityTracker,
    LineageInvariantError,
    check_source_balance,
    read_catalogue,
    read_sha256sums,
    verify_raw_inputs,
    write_catalogue,
)
from src.knowledge_graph.graph_v2.models import Lineage


def test_lineage_validates_against_model(fixture_build) -> None:
    """AC-017: the fixture lineage validates against the Lineage model."""
    result, base = fixture_build
    loaded = Lineage.model_validate_json((base / "lineage.json").read_text(encoding="utf-8"))
    assert loaded == result.lineage
    assert loaded.code.git_commit == "abc123" and loaded.code.git_dirty is False
    assert loaded.sources.meta.lines == 15 and loaded.sources.reviews.lines == 50
    assert loaded.sources.catalogue.count == 12 and loaded.sources.splits.train.rows == 14
    assert set(loaded.outputs) == {
        "nodes_product.csv", "nodes_review.csv", "nodes_user.csv", "nodes_brand.csv", "nodes_category.csv",
        "nodes_attribute.csv", "nodes_taxon.csv", "rels_has_brand.csv", "rels_belongs_to_category.csv",
        "rels_has_attribute.csv", "rels_in_taxon.csv", "rels_broader.csv", "rels_about_product.csv", "rels_wrote.csv",
    }
    for name, stats in loaded.outputs.items():
        assert stats.sha256 == hashlib.sha256((base / "import" / name).read_bytes()).hexdigest()
    assert loaded.duplicates.parent_asin_conflicting == ["T001"]


def test_source_balance_holds(fixture_build) -> None:
    """AC-017: for each source lines = sum(drop reasons) + kept."""
    result, _ = fixture_build
    counts = result.lineage.counts
    assert check_source_balance(counts) == []
    meta, reviews = counts.meta, counts.reviews
    assert meta.lines == meta.json_errors + meta.not_in_catalogue + meta.duplicate_parent_asin + meta.products_written
    assert reviews.lines == (reviews.json_errors + reviews.missing_ids + reviews.not_in_catalogue + reviews.product_missing
                             + reviews.valid_test_pair + reviews.duplicate_review_id + reviews.beyond_cap + reviews.kept)
    assert (reviews.kept, reviews.beyond_cap, reviews.missing_ids) == (34, 5, 2)


def test_broken_counter_exits_2(transform_config, clean_git_runner, monkeypatch) -> None:
    """AC-017: a deliberately broken counter makes the run exit 2 and writes no lineage."""
    monkeypatch.setattr(transform_module.TopKSelector, "duplicate_count", property(lambda self: 99))
    config = transform_config("broken")
    with pytest.raises(LineageInvariantError):
        transform_module.run_transform(config, git_runner=clean_git_runner)
    assert not config.lineage_path.exists()


def test_dangling_relationship_detected() -> None:
    """AC-017 (invariant 2): IntegrityTracker reports an edge whose endpoint has no node."""
    tracker = IntegrityTracker()
    tracker.add_node("ParentProduct", "T1")
    tracker.add_node("Brand", "B")
    tracker.check_edge("HAS_BRAND", "ParentProduct", "T1", "Brand", "B")
    assert tracker.error_count == 0
    tracker.check_edge("HAS_BRAND", "ParentProduct", "T2", "Brand", "B")
    assert tracker.error_count == 1 and "T2" in tracker.errors[0]


def test_verify_raw_inputs_mismatch_raises(fixture_copy: Path) -> None:
    """AC-018: verify_raw_inputs raises InputVerificationError on a hash mismatch or a file missing from SHA256SUMS."""
    meta, reviews = verify_raw_inputs(fixture_copy / "meta.jsonl", fixture_copy / "reviews.jsonl", fixture_copy / "SHA256SUMS")
    assert meta.verified_against.endswith("SHA256SUMS") and len(reviews.sha256) == 64
    (fixture_copy / "reviews.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(InputVerificationError, match="mismatch"):
        verify_raw_inputs(fixture_copy / "meta.jsonl", fixture_copy / "reviews.jsonl", fixture_copy / "SHA256SUMS")
    (fixture_copy / "other.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(InputVerificationError, match="no entry"):
        verify_raw_inputs(fixture_copy / "other.jsonl", fixture_copy / "reviews.jsonl", fixture_copy / "SHA256SUMS")


def test_fixture_sha256sums_is_current(fixture_dir: Path) -> None:
    """AC-018 (support): the checked-in fixture SHA256SUMS matches meta.jsonl and reviews.jsonl."""
    sums = read_sha256sums(fixture_dir / "SHA256SUMS")
    for name in ("meta.jsonl", "reviews.jsonl"):
        assert sums[name] == hashlib.sha256((fixture_dir / name).read_bytes()).hexdigest()


def test_catalogue_gzip_reproducible(tmp_path: Path, fixture_dir: Path) -> None:
    """FR-003: write_catalogue is byte-reproducible (mtime 0, no file name) and read_catalogue returns the content hash."""
    asins = ["T003", "T001", "T002"]
    sha_a = write_catalogue(asins, tmp_path / "a.txt.gz")
    sha_b = write_catalogue(list(reversed(asins)), tmp_path / "b.txt.gz")
    assert (tmp_path / "a.txt.gz").read_bytes() == (tmp_path / "b.txt.gz").read_bytes() and sha_a == sha_b
    assert gzip.decompress((tmp_path / "a.txt.gz").read_bytes()) == b"T001\nT002\nT003\n"
    assert read_catalogue(tmp_path / "a.txt.gz") == (["T001", "T002", "T003"], sha_a)
    assert read_catalogue(fixture_dir / "catalogue.txt")[0][:2] == ["T001", "T002"]
    (tmp_path / "bad.txt").write_text("T2\nT1\n", encoding="utf-8")
    with pytest.raises(InputVerificationError):
        read_catalogue(tmp_path / "bad.txt")
