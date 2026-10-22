"""
tests/graph_v2/test_csv_io.py

Import CSV encoding (FR-014, §5.2): AC-014, AC-015.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from src.knowledge_graph.graph_v2.csv_io import (
    ARRAY_DELIMITER,
    HEADERS,
    CsvOrderError,
    ImportCsvWriter,
    decode_array,
    format_value,
    read_import_csv,
)

TRICKY = [
    'quote " inside',
    "comma, inside",
    "back\\slash",
    "line\nbreak",
    "crlf\r\nbreak",
    "lone\rcr",
    "unit\u001fsep",
    "nul\u0000char",
    "  edge spaces  ",
    "Ünïcödé — 日本語",
]
SANITISED = [
    'quote " inside',
    "comma, inside",
    "back\\slash",
    "line\nbreak",
    "crlf\nbreak",
    "lone\ncr",
    "unit sep",
    "nul char",
    "  edge spaces  ",
    "Ünïcödé — 日本語",
]


def _write(tmp_path: Path, rows, header=("id:ID(X)", "text", "items:string[]"), counters=None):
    path = tmp_path / "out.csv"
    writer = ImportCsvWriter(path, list(header), counters)
    for row in rows:
        writer.add(row)
    return path, writer.close()


def test_round_trip_special_characters(tmp_path: Path) -> None:
    """AC-014: quote, comma, backslash, LF, CRLF, lone CR, U+001F, U+0000, edge spaces and non-ASCII read back as the sanitised originals."""
    path, stats = _write(tmp_path, [[f"id{i:02d}", value, None] for i, value in enumerate(TRICKY)])
    back = {row["id:ID(X)"]: row["text"] for row in read_import_csv(path)}
    assert [back[f"id{i:02d}"] for i in range(len(TRICKY))] == SANITISED
    assert stats.rows == len(TRICKY) and len(stats.sha256) == 64
    assert path.read_bytes()[:3] != b"\xef\xbb\xbf"


def test_array_round_trip(tmp_path: Path) -> None:
    """AC-014: arrays are joined with U+001F, empty items dropped (counted) and split back."""
    counters: Counter = Counter()
    path, _ = _write(tmp_path, [["a", "x", ("one", " ", "two, \"q\"", "")], ["b", "y", ()]], counters=counters)
    back = {row["id:ID(X)"]: row["items:string[]"] for row in read_import_csv(path)}
    assert decode_array(back["a"]) == ["one", 'two, "q"'] and ARRAY_DELIMITER in back["a"]
    assert back["b"] == "" and decode_array(back["b"]) == []
    assert counters["empty_array_items"] == 2


def test_normalisations_counted() -> None:
    """AC-014: every normalisation increments its sanitized counter."""
    counters: Counter = Counter()
    for value in TRICKY + ["   "]:
        format_value(value, counters)
    assert counters == Counter({"carriage_return": 2, "unit_separator": 1, "nul": 1, "blank_to_null": 1})


def test_blank_written_as_empty_field(tmp_path: Path) -> None:
    """AC-014: values blank after stripping are written as empty fields."""
    counters: Counter = Counter()
    path, _ = _write(tmp_path, [["a", "   ", None], ["b", "\u0000", None]], counters=counters)
    rows = list(read_import_csv(path))
    assert [row["text"] for row in rows] == ["", ""]
    assert counters["blank_to_null"] == 2
    assert path.read_text(encoding="utf-8").splitlines()[1] == "a,,"


def test_bool_and_float_formatting() -> None:
    """AC-014 (support): booleans are true/false and floats repr()."""
    counters: Counter = Counter()
    assert format_value(True, counters) == "true" and format_value(False, counters) == "false"
    assert format_value(0.1, counters) == "0.1" and format_value(12.0, counters) == "12.0"
    assert format_value(7, counters) == "7" and format_value(None, counters) == ""
    with pytest.raises(ValueError):
        format_value(float("nan"), counters)


def test_rows_sorted_and_deterministic(tmp_path: Path) -> None:
    """AC-016 (support): buffered writers sort rows by every column; identical input gives identical bytes and sha256."""
    rows = [["b", "2", None], ["a", "9", None], ["a", "1", None]]
    first, stats1 = _write(tmp_path, rows)
    data1 = first.read_bytes()
    second, stats2 = _write(tmp_path, list(reversed(rows)))
    assert second.read_bytes() == data1 and stats1.sha256 == stats2.sha256
    assert [r["id:ID(X)"] + r["text"] for r in read_import_csv(second)] == ["a1", "a9", "b2"]


def test_presorted_writer_rejects_out_of_order_key(tmp_path: Path) -> None:
    """AC-016 (support): presorted mode raises CsvOrderError on a non-increasing key."""
    writer = ImportCsvWriter(tmp_path / "p.csv", ["id:ID(X)"], presorted_key=True)
    writer.add(["x"], key=5)
    with pytest.raises(CsvOrderError):
        writer.add(["y"], key=5)
    dry = ImportCsvWriter(None, ["id:ID(X)"], presorted_key=True)
    dry.add(["x"], key=1)
    stats = dry.close()
    assert (stats.rows, stats.bytes, stats.sha256) == (1, 0, None)


def test_headers_match_spec(fixture_build) -> None:
    """AC-015: every header equals §5.2 exactly (14 files)."""
    spec = {
        "nodes_product.csv": "parent_asin:ID(ParentProduct),title,price:double,avg_rating:double,review_count:long,description,features:string[],details_json,details_text,category_path:string[],store",
        "nodes_review.csv": "review_id:ID(Review),review_title,review_body,rating:double,verified:boolean,timestamp:long,helpful_vote:long,asin,in_train_split:boolean,cap_rank:int,embed_rank:int",
        "nodes_user.csv": "user_id:ID(User)",
        "nodes_brand.csv": "name:ID(Brand)",
        "nodes_category.csv": "name:ID(Category)",
        "nodes_attribute.csv": ":ID(Attribute),attribute_name,attribute_value",
        "nodes_taxon.csv": "taxon_id:ID(Taxon),name,path:string[],depth:int,product_count:long,direct_product_count:long",
        "rels_has_brand.csv": ":START_ID(ParentProduct),:END_ID(Brand)",
        "rels_belongs_to_category.csv": ":START_ID(ParentProduct),:END_ID(Category)",
        "rels_has_attribute.csv": ":START_ID(ParentProduct),:END_ID(Attribute)",
        "rels_in_taxon.csv": ":START_ID(ParentProduct),:END_ID(Taxon)",
        "rels_broader.csv": ":START_ID(Taxon),:END_ID(Taxon)",
        "rels_about_product.csv": ":START_ID(Review),:END_ID(ParentProduct)",
        "rels_wrote.csv": ":START_ID(User),:END_ID(Review)",
    }
    assert {name: ",".join(header) for name, header in HEADERS.items()} == spec
    _, base = fixture_build
    for name, header in spec.items():
        assert (base / "import" / name).read_text(encoding="utf-8").split("\n", 1)[0] == header
