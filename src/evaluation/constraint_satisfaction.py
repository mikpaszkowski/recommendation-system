"""
Three-valued constraint-satisfaction@K (R2a, RS-20 rest; Technical Specification §4.4).

Pure functions, no I/O. Each (item, constraint) pair is judged "satisfied", "violated" or
"unknown" against facts fetched from the live graph (`GraphSearchTool.fetch_constraint_facts`).
Unknown is never scored as a violation (principle P-2). Category constraints are out of scope
here; they are measured by type_precision@K.

Two flavours share these functions:
- gold: constraints hand-annotated from the utterance (`gold_constraints` in the benchmark);
- request: constraints derived from the executed `search_request.structured_filters`.

Numeric verdicts read only `Attribute.numeric_value` (Open Question 2). On the live graph this
property is never set: the full ingest (`scripts/graph_ingestion/batch_ingest.py`) reads
`processed_metadata.csv`, which keeps only the brand / material / color / style / size detail
columns. Every numeric verdict is therefore "unknown", and coverage is reported as such.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

Verdict = str  # "satisfied" | "violated" | "unknown"
SATISFIED: Verdict = "satisfied"
VIOLATED: Verdict = "violated"
UNKNOWN: Verdict = "unknown"
VERDICT_CODE: Dict[str, str] = {SATISFIED: "S", VIOLATED: "V", UNKNOWN: "U"}
KINDS: Tuple[str, ...] = ("price", "brand", "numeric")
OPERATORS: Dict[str, frozenset] = {
    "price": frozenset({"less_than", "greater_than"}),
    "brand": frozenset({"include", "exclude"}),
    "numeric": frozenset({"greater_than", "less_than", "equal"}),
}
GOLD_ACTIONS: frozenset = frozenset({"SEARCH", "CLARIFY"})
_OPERATOR_SYMBOL: Dict[str, str] = {"less_than": "<=", "greater_than": ">=", "equal": "="}


@dataclass(frozen=True)
class GoldConstraint:
    """One annotated or request-derived constraint."""

    kind: str
    attribute: str
    operator: str
    value: Union[float, str, Tuple[str, ...]]
    unit: Optional[str] = None
    graph_attribute_names: Tuple[str, ...] = ()
    graph_unit_scale: float = 1.0
    tolerance: float = 0.05
    evidence: str = ""

    @property
    def label(self) -> str:
        """Compact human-readable label, e.g. "price<=60", "brand+Samsung", "brand-HP", "storage>=128GB"."""
        if self.kind == "brand":
            values = self.value if isinstance(self.value, tuple) else (str(self.value),)
            return f"brand{'+' if self.operator == 'include' else '-'}{'|'.join(values)}"
        symbol = _OPERATOR_SYMBOL.get(self.operator, self.operator)
        return f"{self.attribute}{symbol}{_format_number(self.value)}{self.unit or ''}"


def _format_number(value: Any) -> str:
    """Integers without a decimal point, other floats in shortest form."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:g}" if isinstance(value, float) else str(value)


def _positive_number(value: Any) -> Optional[float]:
    """The value as a finite float > 0, else None (bools are rejected)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _parse_one(raw: Mapping[str, Any], where: str) -> GoldConstraint:
    """Parses one constraint dict; raises ValueError naming `where` on schema violations."""
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where}: constraint must be an object, got {type(raw).__name__}")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError(f"{where}: kind {kind!r} not in {list(KINDS)}")
    operator = raw.get("operator")
    if operator not in OPERATORS[kind]:
        raise ValueError(f"{where}: operator {operator!r} not allowed for kind {kind!r} ({sorted(OPERATORS[kind])})")
    attribute = raw.get("attribute", kind)
    if not isinstance(attribute, str) or not attribute.strip():
        raise ValueError(f"{where}: attribute must be a non-empty string")

    raw_value = raw.get("value")
    value: Union[float, str, Tuple[str, ...]]
    if kind == "brand":
        if isinstance(raw_value, str) and raw_value.strip():
            value = raw_value.strip()
        elif isinstance(raw_value, (list, tuple)) and raw_value and all(isinstance(v, str) and v.strip() for v in raw_value):
            value = tuple(v.strip() for v in raw_value)
        else:
            raise ValueError(f"{where}: brand value must be a non-empty string (or list of strings), got {raw_value!r}")
    else:
        number = _positive_number(raw_value)
        if number is None:
            raise ValueError(f"{where}: {kind} value must be a number > 0, got {raw_value!r}")
        value = number

    unit = raw.get("unit")
    if unit is not None and not isinstance(unit, str):
        raise ValueError(f"{where}: unit must be a string")
    names: Tuple[str, ...] = ()
    if kind == "numeric":
        if not unit or not unit.strip():
            raise ValueError(f"{where}: numeric constraints require a unit")
        raw_names = raw.get("graph_attribute_names")
        if not isinstance(raw_names, list):
            raise ValueError(f"{where}: numeric constraints require graph_attribute_names (a list, may be empty)")
        for name in raw_names:
            if not isinstance(name, str) or not name or name != name.lower():
                raise ValueError(f"{where}: graph_attribute_names entries must be lower-case strings, got {name!r}")
        names = tuple(raw_names)

    tolerance = raw.get("tolerance", 0.05)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not (0 < float(tolerance) <= 0.5):
        raise ValueError(f"{where}: tolerance must satisfy 0 < tolerance <= 0.5, got {tolerance!r}")
    scale = raw.get("graph_unit_scale", 1.0)
    if _positive_number(scale) is None:
        raise ValueError(f"{where}: graph_unit_scale must be a number > 0, got {scale!r}")
    evidence = raw.get("evidence", "")
    if not isinstance(evidence, str):
        raise ValueError(f"{where}: evidence must be a string")

    return GoldConstraint(
        kind=kind,
        attribute=attribute.strip(),
        operator=operator,
        value=value,
        unit=unit.strip() if isinstance(unit, str) and unit.strip() else None,
        graph_attribute_names=names,
        graph_unit_scale=float(scale),
        tolerance=float(tolerance),
        evidence=evidence,
    )


def parse_gold_constraints(raw: Sequence[Mapping[str, Any]]) -> List[GoldConstraint]:
    """
    Parses raw `gold_constraints` dicts into `GoldConstraint` objects.

    Raises:
        ValueError: on any schema violation (§5.1.3), naming the offending entry.
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"gold_constraints must be a list, got {type(raw).__name__}")
    return [_parse_one(entry, f"gold_constraints[{i}]") for i, entry in enumerate(raw)]


def validate_gold_annotations(benchmark: Sequence[Mapping[str, Any]]) -> List[str]:
    """
    Validates the optional gold fields of every benchmark item (FR-012, §5.1.3).

    Items without gold fields are valid. Returns one human-readable error string per
    problem (empty list = valid): bad `type_explicit` / `gold_action` types or values,
    `type_explicit = false` without `gold_action = "CLARIFY"`, and constraint schema errors.
    """
    errors: List[str] = []
    if not isinstance(benchmark, (list, tuple)):
        return [f"benchmark must be a list, got {type(benchmark).__name__}"]
    for index, item in enumerate(benchmark):
        if not isinstance(item, Mapping):
            errors.append(f"item {index}: must be an object")
            continue
        qid = item.get("query_id") or item.get("id") or f"item {index}"
        type_explicit = item.get("type_explicit")
        gold_action = item.get("gold_action")
        if "type_explicit" in item and not isinstance(type_explicit, bool):
            errors.append(f"{qid}: type_explicit must be a bool, got {type_explicit!r}")
        if "gold_action" in item and gold_action not in GOLD_ACTIONS:
            errors.append(f"{qid}: gold_action must be one of {sorted(GOLD_ACTIONS)}, got {gold_action!r}")
        if type_explicit is False and gold_action != "CLARIFY":
            errors.append(f"{qid}: type_explicit = false requires gold_action = 'CLARIFY', got {gold_action!r}")
        if "gold_product_type" in item and not isinstance(item.get("gold_product_type"), str):
            errors.append(f"{qid}: gold_product_type must be a string")
        if "gold_annotation" in item and not isinstance(item.get("gold_annotation"), Mapping):
            errors.append(f"{qid}: gold_annotation must be an object")
        if "gold_constraints" in item:
            try:
                parse_gold_constraints(item.get("gold_constraints"))
            except ValueError as e:
                errors.append(f"{qid}: {e}")
    return errors


def constraints_from_search_request(search_request: Optional[Mapping[str, Any]]) -> List[GoldConstraint]:
    """
    Derives request-flavour constraints from `search_request["structured_filters"]` (§4.4.3):
    price_max -> price less_than, price_min -> price greater_than, brand -> brand include,
    brands (list) -> brand include (any-of tuple), exclude_brand -> brand exclude.
    Category and all other keys are ignored. Returns [] for a missing request.
    """
    if not isinstance(search_request, Mapping):
        return []
    filters = search_request.get("structured_filters")
    if not isinstance(filters, Mapping):
        return []
    constraints: List[GoldConstraint] = []
    evidence = "search_request.structured_filters"

    for key, operator in (("price_max", "less_than"), ("price_min", "greater_than")):
        raw = filters.get(key)
        try:
            number = _positive_number(float(raw)) if raw is not None and not isinstance(raw, bool) else None
        except (TypeError, ValueError):
            number = None
        if number is not None:
            constraints.append(GoldConstraint("price", "price", operator, number, evidence=evidence))

    brand = filters.get("brand")
    if isinstance(brand, str) and brand.strip():
        constraints.append(GoldConstraint("brand", "brand", "include", brand.strip(), evidence=evidence))
    brands = filters.get("brands")
    if isinstance(brands, (list, tuple)):
        names = tuple(str(b).strip() for b in brands if isinstance(b, str) and b.strip())
        if names:
            constraints.append(GoldConstraint("brand", "brand", "include", names, evidence=evidence))
    excluded = filters.get("exclude_brand")
    if isinstance(excluded, str) and excluded.strip():
        constraints.append(GoldConstraint("brand", "brand", "exclude", excluded.strip(), evidence=evidence))
    return constraints


def brand_matches(brand_names: Sequence[str], title: Optional[str], value: str) -> bool:
    """
    Python mirror of the `_build_filters` brand predicate: case-insensitive equality or
    mutual containment against each non-empty brand name, or `value` contained in the title.
    """
    wanted = str(value or "").strip().lower()
    if not wanted:
        return False
    for name in brand_names or []:
        if not isinstance(name, str):
            continue
        have = name.strip().lower()
        if have and (have == wanted or wanted in have or have in wanted):
            return True
    return isinstance(title, str) and wanted in title.lower()


def _price_verdict(facts: Mapping[str, Any], constraint: GoldConstraint) -> Verdict:
    price = facts.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(float(price)) or float(price) <= 0:
        return UNKNOWN
    bound = float(constraint.value)  # type: ignore[arg-type]
    if constraint.operator == "less_than":
        return SATISFIED if float(price) <= bound else VIOLATED
    return SATISFIED if float(price) >= bound else VIOLATED


def _brand_verdict(facts: Mapping[str, Any], constraint: GoldConstraint) -> Verdict:
    names = [n for n in (facts.get("brands") or []) if isinstance(n, str) and n.strip()]
    title = facts.get("title")
    values = constraint.value if isinstance(constraint.value, tuple) else (str(constraint.value),)
    matched = any(brand_matches(names, title, v) for v in values)
    if constraint.operator == "include":
        if matched:
            return SATISFIED
        return VIOLATED if names else UNKNOWN
    if matched:
        return VIOLATED
    return SATISFIED if names else UNKNOWN


def _numeric_verdict(facts: Mapping[str, Any], constraint: GoldConstraint) -> Verdict:
    wanted_names = {n.lower() for n in constraint.graph_attribute_names}
    if not wanted_names:
        return UNKNOWN
    observed: List[float] = []
    for attr in facts.get("numeric_attributes") or []:
        if not isinstance(attr, Mapping):
            continue
        name = str(attr.get("name") or "").lower()
        raw = attr.get("value")
        if name in wanted_names and not isinstance(raw, bool) and isinstance(raw, (int, float)) and math.isfinite(float(raw)):
            observed.append(float(raw) * constraint.graph_unit_scale)
    if not observed:
        return UNKNOWN
    target = float(constraint.value)  # type: ignore[arg-type]
    for x in observed:
        if constraint.operator == "greater_than" and x >= target:
            return SATISFIED
        if constraint.operator == "less_than" and x <= target:
            return SATISFIED
        if constraint.operator == "equal" and abs(x - target) <= constraint.tolerance * abs(target):
            return SATISFIED
    return VIOLATED


def judge(facts: Optional[Mapping[str, Any]], constraint: GoldConstraint) -> Verdict:
    """
    Three-valued verdict for one item and one constraint, following the truth table in §4.4.2.
    Missing facts, missing price / brand / numeric evidence, or an empty
    `graph_attribute_names` give "unknown". Bounds are inclusive.
    """
    if not isinstance(facts, Mapping):
        return UNKNOWN
    if constraint.kind == "price":
        return _price_verdict(facts, constraint)
    if constraint.kind == "brand":
        return _brand_verdict(facts, constraint)
    if constraint.kind == "numeric":
        return _numeric_verdict(facts, constraint)
    return UNKNOWN


def verdict_matrix(
    asins: Sequence[str],
    facts: Mapping[str, Mapping[str, Any]],
    constraints: Sequence[GoldConstraint],
) -> List[str]:
    """
    One verdict string per item (in `asins` order, deduplicated), one `VERDICT_CODE` letter per
    constraint, e.g. ["SUU", "VSU"]. Returns [] when there are no constraints.
    """
    if not constraints:
        return []
    facts = facts or {}
    return [
        "".join(VERDICT_CODE[judge(facts.get(asin), c)] for c in constraints)
        for asin in dict.fromkeys(a for a in asins if a)
    ]


def cs_scores_at_k(verdict_rows: Sequence[str], k: int) -> Optional[Dict[str, Optional[float]]]:
    """
    CS aggregates over the first k verdict rows (§4.4.4): cs_sat, cs_viol, cs_unk, cs_known,
    violation_free, cs_coverage. Returns None when there are no items or no constraints.
    """
    if k <= 0:
        return None
    rows = [r for r in list(verdict_rows or [])[:k]]
    if not rows or not all(rows):
        return None
    total = sum(len(r) for r in rows)
    sat = sum(r.count("S") for r in rows)
    viol = sum(r.count("V") for r in rows)
    unk = sum(r.count("U") for r in rows)
    cs_unk = unk / total
    return {
        "cs_sat": sat / total,
        "cs_viol": viol / total,
        "cs_unk": cs_unk,
        "cs_known": sat / (sat + viol) if (sat + viol) else None,
        "violation_free": sum(1 for r in rows if "V" not in r) / len(rows),
        "cs_coverage": 1.0 - cs_unk,
    }


def attribute_names_for(constraints: Sequence[GoldConstraint]) -> List[str]:
    """Lower-cased, deduplicated union of `graph_attribute_names` over numeric constraints."""
    return list(dict.fromkeys(
        name.lower() for c in constraints if c.kind == "numeric" for name in c.graph_attribute_names
    ))
