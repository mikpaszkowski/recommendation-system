"""
tests/graph_v2/test_product_mapping.py

Product mapping, brand, category and attribute rules (FR-006 … FR-009): AC-008 … AC-011.
"""
from __future__ import annotations

import json
import math
from collections import Counter

from src.knowledge_graph.graph_v2.csv_io import HEADERS
from src.knowledge_graph.graph_v2.product_mapping import (
    brand_case_groups,
    clean_features,
    description_text,
    details_json,
    details_text,
    extract_attributes,
    map_meta_record,
    parse_price,
    resolve_brand,
)


def _raw(**kw):
    base = {"parent_asin": "T1", "title": "Title", "price": 1.0, "main_category": "All Electronics",
            "categories": ["Electronics"], "store": "Store", "details": {}, "features": [], "description": []}
    base.update(kw)
    return base


def test_title_present_and_blank() -> None:
    """AC-008: a present title is kept as is; a blank title maps to None and counts title_empty."""
    counters: Counter = Counter()
    assert map_meta_record(_raw(title="  Padded Title "), counters).row.title == "  Padded Title "
    assert counters["title_empty"] == 0
    assert map_meta_record(_raw(title="   "), counters).row.title is None
    assert map_meta_record(_raw(title=None), counters).row.title is None
    assert counters["title_empty"] == 2


def test_parse_price_cases() -> None:
    """AC-008: float, int, null, "12.99", "$12.99", "from 9.99", NaN and true map to the expected (price, status)."""
    assert parse_price(12.99) == (12.99, "ok")
    assert parse_price(25) == (25.0, "ok") and isinstance(parse_price(25)[0], float)
    assert parse_price(None) == (None, "null")
    assert parse_price("12.99") == (12.99, "ok")
    assert parse_price("$12.99") == (None, "unparseable")
    assert parse_price("from 9.99") == (None, "unparseable")
    assert parse_price(math.nan) == (None, "unparseable")
    assert parse_price(True) == (None, "unparseable")
    counters: Counter = Counter()
    record = map_meta_record(_raw(price=0), counters)
    assert record.row.price == 0.0 and counters["price_non_positive"] == 1


def test_description_list_and_string() -> None:
    """AC-008: a list is joined with " | "; a string is kept as is; blank -> None."""
    assert description_text(["Line one", " ", "Line two"]) == "Line one | Line two"
    assert description_text("A plain string") == "A plain string"
    assert description_text([]) is None and description_text("  ") is None and description_text(5) is None


def test_features_blank_items_dropped() -> None:
    """AC-008: features keep source order and drop blank items."""
    assert clean_features(["Fast charging", "  ", "", None, "USB-C"]) == ("Fast charging", "USB-C")
    assert clean_features("not a list") == ()


def test_details_text_scalars_only_sorted() -> None:
    """AC-008: details_text keeps str/int/float/bool values only, sorted by key; nested values are excluded."""
    details = {"b": 1, "a": "x", "n": {"k": 1}, "l": [1, 2], "f": 1.5, "t": True}
    assert details_text(details) == "a: x\nb: 1\nf: 1.5\nt: True"
    assert details_text({"n": {"k": 1}}) is None and details_text({}) is None


def test_details_json_canonical() -> None:
    """AC-008: details_json is sort_keys, ensure_ascii=False, compact separators; empty details -> None."""
    details = {"b": "Ü", "a": {"y": 2, "x": 1}}
    assert details_json(details) == '{"a":{"x":1,"y":2},"b":"Ü"}'
    assert json.loads(details_json(details)) == details
    assert details_json({}) is None and details_json(None) is None


def test_brand_store_preferred() -> None:
    """AC-009: a non-blank store wins over details["Brand"]; the name is not stripped."""
    assert resolve_brand(" Anker ", {"Brand": "Other"}) == " Anker "


def test_brand_blank_store_falls_back_to_details() -> None:
    """AC-009: a blank store falls back to details["Brand"]."""
    assert resolve_brand("   ", {"Brand": "FallbackBrand"}) == "FallbackBrand"
    assert resolve_brand(None, {"Brand": "FallbackBrand"}) == "FallbackBrand"


def test_brand_missing() -> None:
    """AC-009: no store and no details Brand gives None and counts brand_missing."""
    assert resolve_brand(None, {}) is None and resolve_brand("", {"Brand": "  "}) is None
    counters: Counter = Counter()
    assert map_meta_record(_raw(store=None, details={}), counters).brand is None
    assert counters["brand_missing"] == 1


def test_brand_case_groups() -> None:
    """AC-009: "Anker" and "ANKER" stay two names and form one case group."""
    assert brand_case_groups(["Anker", "ANKER", "Sony"]) == [["ANKER", "Anker"]]
    assert brand_case_groups(["Anker", "Sony"]) == []


def test_category_is_main_category() -> None:
    """AC-010: main_category is the category; blank main_category gives None and counts main_category_empty."""
    counters: Counter = Counter()
    assert map_meta_record(_raw(main_category="Computers"), counters).main_category == "Computers"
    assert map_meta_record(_raw(main_category="  "), counters).main_category is None
    assert counters["main_category_empty"] == 1


def test_attributes_exact_keys_only() -> None:
    """AC-011: only Material, Color, Style and Size with non-blank string values; "color" is ignored."""
    counters: Counter = Counter()
    details = {"Color": "Black", "color": "red", "Material": "Aluminium", "Style": "  ", "Size": "XL", "Brand": "B"}
    assert extract_attributes(details, counters) == (("Color", "Black"), ("Material", "Aluminium"), ("Size", "XL"))
    assert counters["attribute_non_string"] == 0
    assert not any("numeric_value" in column for column in HEADERS["nodes_attribute.csv"])


def test_attribute_non_string_counted() -> None:
    """AC-011: a list value is skipped and counted as attribute_non_string."""
    counters: Counter = Counter()
    assert extract_attributes({"Size": ["S", "M"], "Color": 3}, counters) == ()
    assert counters["attribute_non_string"] == 2
