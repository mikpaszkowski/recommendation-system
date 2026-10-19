"""
Raw metadata record -> ParentProduct row, brand, category and attributes (FR-006 … FR-009, §5.1.1).

Rules (v1 semantics, G-3, G-11):
    - Brand = `store` if it is a string that is not blank after stripping, else `details["Brand"]`
      under the same test, else none. Names are stored exactly as in the source.
    - Category = non-blank `main_category`.
    - Attributes only for the exact keys Material, Color, Style, Size with non-blank string values;
      values are stored exactly as in the source; non-string values are skipped and counted.
    - Price is parsed by `parse_price`; bool is never numeric.

All functions are pure. Counter keys are the field names of `models.MetaCounts`.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from src.knowledge_graph.graph_v2.taxonomy import normalize_levels

ATTRIBUTE_KEYS: Tuple[str, ...] = ("Material", "Color", "Style", "Size")
DETAILS_BRAND_KEY: str = "Brand"
DESCRIPTION_SEPARATOR: str = " | "
PRICE_PATTERN = re.compile(r"^\s*\d+(\.\d+)?\s*$")
PRICE_STATUSES: Tuple[str, ...] = ("ok", "null", "unparseable")


class ProductRow(NamedTuple):
    """One `nodes_product.csv` row (§5.1.1, §5.2)."""

    parent_asin: str
    title: Optional[str]
    price: Optional[float]
    avg_rating: Optional[float]
    review_count: Optional[int]
    description: Optional[str]
    features: Tuple[str, ...]
    details_json: Optional[str]
    details_text: Optional[str]
    category_path: Tuple[str, ...]
    store: Optional[str]


class ProductRecord(NamedTuple):
    """A mapped product with its derived brand, category, attributes and normalised category levels."""

    row: ProductRow
    brand: Optional[str]
    main_category: Optional[str]
    attributes: Tuple[Tuple[str, str], ...]   # sorted (name, value)
    levels: Tuple[str, ...]                    # normalised category levels


def _visible(value: str) -> bool:
    """True if the string is non-blank after the CSV sanitiser's NUL / U+001F -> space rule (FR-014)."""
    return bool(value.replace("\u0000", " ").replace("\u001f", " ").strip())


def is_blank(value: Any) -> bool:
    """True for None and for strings that are empty after stripping; False for every other value."""
    if value is None:
        return True
    return isinstance(value, str) and not _visible(value)


def non_blank_string(value: Any) -> Optional[str]:
    """`value` unchanged if it is a string that is not blank after stripping, else None (no stripping applied)."""
    if isinstance(value, str) and _visible(value):
        return value
    return None


def _is_number(value: Any) -> bool:
    """True for int/float that are not bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_price(value: Any) -> Tuple[Optional[float], str]:
    """
    (price, status) with status in {"ok", "null", "unparseable"}; bool is never numeric;
    non-finite floats are "unparseable"; strings must match PRICE_PATTERN.
    Non-positive prices are returned with status "ok"; the caller counts them as price_non_positive.
    """
    if value is None:
        return None, "null"
    if isinstance(value, bool):
        return None, "unparseable"
    if _is_number(value):
        number = float(value)
        if not math.isfinite(number):
            return None, "unparseable"
        return number, "ok"
    if isinstance(value, str):
        if not value.strip():
            return None, "null"
        if PRICE_PATTERN.match(value):
            return float(value.strip()), "ok"
        return None, "unparseable"
    return None, "unparseable"


def parse_optional_float(value: Any) -> Optional[float]:
    """Finite int/float (not bool) as float, else None. Used for `average_rating`."""
    if _is_number(value) and math.isfinite(float(value)):
        return float(value)
    return None


def parse_optional_int(value: Any) -> Optional[int]:
    """Integral int/float (not bool) as int, else None. Used for `rating_number` (v1 `review_count` semantics)."""
    if not _is_number(value):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    return int(value)


def description_text(value: Any) -> Optional[str]:
    """`" | ".join` of the non-blank string items of a list; a string is kept as is; blank or other types -> None."""
    if isinstance(value, str):
        return non_blank_string(value)
    if isinstance(value, list):
        items = [item for item in value if non_blank_string(item) is not None]
        return DESCRIPTION_SEPARATOR.join(items) if items else None
    return None


def clean_features(value: Any) -> Tuple[str, ...]:
    """Feature strings in source order with blank and non-string items dropped; non-list -> ()."""
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if non_blank_string(item) is not None)


def details_json(details: Any) -> Optional[str]:
    """`json.dumps(details, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`; None for an empty or non-dict value."""
    if not isinstance(details, dict) or not details:
        return None
    return json.dumps(details, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def details_text(details: Any) -> Optional[str]:
    """`"\\n".join(f"{k}: {v}")` over the sorted keys whose value is str, int, float or bool; None if no such key."""
    if not isinstance(details, dict):
        return None
    lines = [f"{key}: {details[key]}" for key in sorted(details) if isinstance(details[key], (str, int, float, bool))]
    return "\n".join(lines) if lines else None


def resolve_brand(store: Any, details: Mapping[str, Any]) -> Optional[str]:
    """FR-007: `store` if non-blank string, else `details["Brand"]` if non-blank string, else None. Exact name, never stripped."""
    brand = non_blank_string(store)
    if brand is not None:
        return brand
    if isinstance(details, Mapping):
        return non_blank_string(details.get(DETAILS_BRAND_KEY))
    return None


def extract_attributes(details: Any, counters: "Counter[str]") -> Tuple[Tuple[str, str], ...]:
    """
    FR-009: sorted (name, value) pairs for the exact keys in ATTRIBUTE_KEYS whose value is a
    non-blank string. A present non-string value increments `attribute_non_string`; blank strings are ignored.
    """
    if not isinstance(details, dict):
        return ()
    pairs: List[Tuple[str, str]] = []
    for key in ATTRIBUTE_KEYS:
        if key not in details or details[key] is None:
            continue
        value = details[key]
        if not isinstance(value, str):
            counters["attribute_non_string"] += 1
            continue
        if value.strip():
            pairs.append((key, value))
    return tuple(sorted(pairs))


def map_meta_record(raw: Mapping[str, Any], counters: "Counter[str]") -> ProductRecord:
    """
    Maps one raw metadata record whose `parent_asin` the caller has already checked against the
    catalogue. Increments title_empty, description_empty, features_empty, content_empty,
    features_only_content, categories_empty, main_category_empty, price_null, price_unparseable,
    price_non_positive, brand_missing and attribute_non_string.
    """
    details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
    title = non_blank_string(raw.get("title"))
    description = description_text(raw.get("description"))
    features = clean_features(raw.get("features"))
    if title is None:
        counters["title_empty"] += 1
    if description is None:
        counters["description_empty"] += 1
    if not features:
        counters["features_empty"] += 1
    if title is None and description is None:
        counters["content_empty" if not features else "features_only_content"] += 1

    price, status = parse_price(raw.get("price"))
    if status == "null":
        counters["price_null"] += 1
    elif status == "unparseable":
        counters["price_unparseable"] += 1
    elif price is not None and price <= 0:
        counters["price_non_positive"] += 1

    levels = normalize_levels(raw.get("categories"))
    if not levels:
        counters["categories_empty"] += 1
    main_category = non_blank_string(raw.get("main_category"))
    if main_category is None:
        counters["main_category_empty"] += 1
    brand = resolve_brand(raw.get("store"), details)
    if brand is None:
        counters["brand_missing"] += 1

    row = ProductRow(
        parent_asin=str(raw["parent_asin"]),
        title=title,
        price=price,
        avg_rating=parse_optional_float(raw.get("average_rating")),
        review_count=parse_optional_int(raw.get("rating_number")),
        description=description,
        features=features,
        details_json=details_json(details),
        details_text=details_text(details),
        category_path=levels,
        store=non_blank_string(raw.get("store")),
    )
    return ProductRecord(
        row=row,
        brand=brand,
        main_category=main_category,
        attributes=extract_attributes(details, counters),
        levels=levels,
    )


def product_csv_values(row: ProductRow) -> List[Any]:
    """Values of `row` in the `nodes_product.csv` header order (§5.2); encoding happens in csv_io."""
    return [
        row.parent_asin, row.title, row.price, row.avg_rating, row.review_count, row.description,
        row.features, row.details_json, row.details_text, row.category_path, row.store,
    ]


def _canonical(record: Mapping[str, Any]) -> str:
    """Canonical JSON of a raw record (NaN allowed, keys sorted)."""
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def records_conflict(first: Mapping[str, Any], later: Mapping[str, Any]) -> bool:
    """True if two raw metadata lines for the same parent_asin differ in content (canonical JSON comparison)."""
    return _canonical(first) != _canonical(later)


def brand_case_groups(names: Iterable[str]) -> List[List[str]]:
    """Groups of distinct brand names that are equal under `str.casefold()`, each sorted, groups sorted (G-11, R-05)."""
    groups: Dict[str, set] = defaultdict(set)
    for name in names:
        groups[name.casefold()].add(name)
    return sorted(sorted(group) for group in groups.values() if len(group) > 1)


def sorted_unique(values: Sequence[str]) -> List[str]:
    """Distinct values in ascending order (deterministic node lists)."""
    return sorted(set(values))
