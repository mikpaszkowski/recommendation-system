"""
Validation gate definitions as pure functions over query results (FR-026, §5.5, AC-028, AC-029).

`scripts/graph_ingestion/validate_graph.py` runs the Cypher and passes the observed values here.
Each `gate_*` returns a `GateResult`; any failed hard gate makes the report `passed: false` (exit 1).
Report-only helpers (R-01 … R-08) never change `passed`. Thresholds come only from `BuildParams`
and `Lineage`.
"""
from __future__ import annotations

import random
import re
from typing import AbstractSet, Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from src.knowledge_graph.graph_v2.models import BuildParams, EmbeddingReport, GateResult, Lineage, ValidationReport

GATE_NAMES: Dict[str, str] = {
    "H-01": "product count",
    "H-02": "catalogue membership",
    "H-03": "untitled products",
    "H-04": "no ghost signature",
    "H-05": "review integrity",
    "H-06": "split exclusion",
    "H-07": "cap",
    "H-08": "review count",
    "H-09": "constraints",
    "H-10": "embedding coverage",
    "H-11": "no blank embeddings",
    "H-12": "indexes online",
    "H-13": "full-text smoke test",
    "H-14": "import fidelity",
    "H-15": "benchmark grounding",
    "H-16": "no legacy schema",
    "H-17": "taxon integrity",
    "H-18": "counts match lineage",
}
REPORT_ONLY_IDS: Tuple[str, ...] = ("R-01", "R-02", "R-03", "R-04", "R-05", "R-06", "R-07", "R-08")
REQUIRED_CONSTRAINTS: Tuple[str, ...] = (
    "product_id", "review_id", "user_id", "brand_id", "category_id", "taxon_id", "attribute_key", "graph_version_id",
)
ATTRIBUTE_KEY_FALLBACK: str = "attribute_key"
VECTOR_INDEX_NAMES: Tuple[str, ...] = (
    "product_embedding_index", "brand_embedding_index", "category_embedding_index",
    "attribute_embedding_index", "review_embedding_index",
)
FULLTEXT_INDEX_NAME: str = "product_fulltext_index"
LEGACY_LABELS: Tuple[str, ...] = ("Variant", "Product", "PriceRange")
LEGACY_REL_TYPES: Tuple[str, ...] = ("RATED", "REVIEWS", "SUBCATEGORY_OF", "IN_PRICE_RANGE", "IS_VARIANT_OF", "CHILD_OF")
EMBEDDING_DIM: int = 384
BLANK_TEMPLATE_MAX_SCORE: float = 0.9999
IDENTICAL_EMBEDDING_SCORE: float = 0.99999
ISBN_PATTERN = re.compile(r"^\d{9}[\dX]$")
SMOKE_TOKEN_PATTERN = re.compile(r"[A-Za-z]{6,}")
FULLTEXT_SMOKE_LIMIT: int = 50
H06_SAMPLE_SIZE: int = 10_000
H14_PRODUCT_SAMPLE: int = 2_000
H14_REVIEW_SAMPLE: int = 2_000
H14_SPECIAL_REVIEW_SAMPLE: int = 500
H17_TAXON_SAMPLE: int = 200
R04_PRODUCT_SAMPLE: int = 5_000
FIDELITY_PRODUCT_FIELDS: Tuple[str, ...] = ("title", "description", "features", "details_json")
FIDELITY_REVIEW_FIELDS: Tuple[str, ...] = (
    "review_title", "review_body", "rating", "timestamp", "helpful_vote", "verified",
)


class LabelCoverage(NamedTuple):
    """H-10 inputs for one label."""

    embedded: int          # count(n.embedding IS NOT NULL)
    eligible: int          # eligible count recomputed in Cypher
    wrong_dimension: int   # embeddings with size <> 384


class IndexState(NamedTuple):
    """One row of SHOW INDEXES relevant to H-12 / H-13."""

    name: str
    type: str
    state: str
    population_percent: float
    properties: Tuple[str, ...]


class FidelityMismatch(NamedTuple):
    """One H-14 difference between the graph value and the value parsed back from the import CSV."""

    label: str
    key: str
    field: str
    graph_value: Any
    csv_value: Any


class TaxonCountCheck(NamedTuple):
    """H-17 subtree product_count check for one sampled taxon."""

    taxon_id: str
    stored: int
    recomputed: int


def _gate(gate_id: str, passed: bool, expected: Any = None, observed: Any = None, detail: Optional[Any] = None) -> GateResult:
    """GateResult with the canonical name."""
    return GateResult(id=gate_id, name=GATE_NAMES[gate_id], expected=expected, observed=observed, passed=bool(passed), detail=detail)


def pilot_build_params(build_params: BuildParams, lineage: Lineage) -> BuildParams:
    """
    Pilot thresholds (FR-026, amendment A-3, audit M-3 option a). There is no pilot build_params file:
    the pilot reads the full build's build_params.json, and only the three expected counts are taken
    from the pilot lineage -- accepted_catalogue_missing <- counts.meta.catalogue_missing_in_meta (H-01),
    expected_review_count <- counts.reviews.kept (H-08), expected_embed_reviews <- counts.reviews.embed_selected
    (H-10). Every other field (accepted_untitled_count for H-03, review_cap, product_content_rule, …) is unchanged.
    """
    return build_params.model_copy(update={
        "accepted_catalogue_missing": lineage.counts.meta.catalogue_missing_in_meta,
        "expected_review_count": lineage.counts.reviews.kept,
        "expected_embed_reviews": lineage.counts.reviews.embed_selected,
    })


def seeded_sample(items: Sequence[Any], k: int, seed: int) -> List[Any]:
    """Deterministic sample of up to k items (random.Random(seed).sample over a sorted copy)."""
    ordered = sorted(items)
    if k >= len(ordered):
        return ordered
    return random.Random(seed).sample(ordered, k)


def gate_product_count(observed: int, lineage: Lineage, build_params: BuildParams, catalogue_count: int) -> GateResult:
    """H-01: observed = products_written and products_written = catalogue count − accepted_catalogue_missing."""
    written = lineage.counts.meta.products_written
    expected_written = catalogue_count - build_params.accepted_catalogue_missing
    passed = observed == written and written == expected_written
    return _gate("H-01", passed, expected={"products_written": written, "catalogue_minus_accepted_missing": expected_written},
                 observed=observed)


def gate_catalogue_membership(graph_asins: Iterable[Optional[str]], catalogue: AbstractSet[str]) -> GateResult:
    """H-02: every streamed parent_asin is non-null and in the catalogue."""
    nulls = 0
    outside: List[str] = []
    seen = 0
    for asin in graph_asins:
        seen += 1
        if asin is None:
            nulls += 1
        elif asin not in catalogue:
            outside.append(asin)
    passed = nulls == 0 and not outside
    return _gate("H-02", passed, expected={"null": 0, "outside_catalogue": 0},
                 observed={"checked": seen, "null": nulls, "outside_catalogue": len(outside)},
                 detail=sorted(outside)[:50] or None)


def gate_untitled(observed_untitled: int, lineage: Lineage, build_params: BuildParams) -> GateResult:
    """H-03: observed = lineage title_empty and <= accepted_untitled_count."""
    expected = lineage.counts.meta.title_empty
    passed = observed_untitled == expected and observed_untitled <= build_params.accepted_untitled_count
    return _gate("H-03", passed, expected={"lineage_title_empty": expected, "max": build_params.accepted_untitled_count},
                 observed=observed_untitled)


def gate_ghost_signature(ghost_count: int) -> GateResult:
    """H-04: zero products whose only non-embedding key is parent_asin."""
    return _gate("H-04", ghost_count == 0, expected=0, observed=ghost_count)


def gate_review_integrity(bad_reviews: int, users_without_wrote: int) -> GateResult:
    """H-05: every review has exactly one ABOUT_PRODUCT and one incoming WROTE; no user without WROTE."""
    return _gate("H-05", bad_reviews == 0 and users_without_wrote == 0, expected={"bad_reviews": 0, "users_without_wrote": 0},
                 observed={"bad_reviews": bad_reviews, "users_without_wrote": users_without_wrote})


def gate_split_exclusion(
    excluded_hits: int,
    sample: Sequence[Tuple[str, str, bool]],
    train_hits: AbstractSet[Tuple[str, str]],
) -> GateResult:
    """H-06: zero graph pairs in valid ∪ test; for each sampled (user_id, parent_asin, in_train_split), the flag equals train membership."""
    wrong = [(u, p, flag) for u, p, flag in sample if bool(flag) != ((u, p) in train_hits)]
    passed = excluded_hits == 0 and not wrong and len(sample) > 0
    return _gate("H-06", passed, expected={"excluded_hits": 0, "in_train_split_mismatches": 0},
                 observed={"excluded_hits": excluded_hits, "sampled": len(sample), "in_train_split_mismatches": len(wrong)},
                 detail=[list(item) for item in wrong[:20]] or None)


def gate_cap(max_reviews_per_product: int, products_with_bad_cap_ranks: int, cap: int) -> GateResult:
    """H-07: max reviews per product <= cap and cap_rank per product is exactly 1 … n."""
    passed = max_reviews_per_product <= cap and products_with_bad_cap_ranks == 0
    return _gate("H-07", passed, expected={"max_reviews_per_product": f"<= {cap}", "bad_cap_ranks": 0},
                 observed={"max_reviews_per_product": max_reviews_per_product, "bad_cap_ranks": products_with_bad_cap_ranks})


def gate_review_count(observed: int, lineage: Lineage, build_params: BuildParams) -> GateResult:
    """H-08: count(:Review) = lineage kept = expected_review_count."""
    kept = lineage.counts.reviews.kept
    passed = observed == kept == build_params.expected_review_count
    return _gate("H-08", passed, expected={"lineage_kept": kept, "expected_review_count": build_params.expected_review_count},
                 observed=observed)


def gate_constraints(constraint_names: Iterable[str], attribute_key_fallback: bool) -> GateResult:
    """H-09: all 8 constraints exist (attribute_key may be absent only if the pilot recorded the fallback)."""
    present = set(constraint_names)
    required = [name for name in REQUIRED_CONSTRAINTS if not (attribute_key_fallback and name == ATTRIBUTE_KEY_FALLBACK)]
    missing = [name for name in required if name not in present]
    return _gate("H-09", not missing, expected=required, observed=sorted(present), detail=missing or None)


def gate_embedding_coverage(coverage: Mapping[str, LabelCoverage], embedding_report: EmbeddingReport, build_params: BuildParams) -> GateResult:
    """H-10: per label embedded = report embedded = eligible; reviews eligible = expected_embed_reviews; zero wrong dimension."""
    problems: List[str] = []
    for label in ("Attribute", "Brand", "Category", "ParentProduct", "Review"):
        observed = coverage.get(label)
        reported = embedding_report.labels.get(label)
        if observed is None or reported is None:
            problems.append(f"{label}: missing from {'graph' if observed is None else 'embedding report'}")
            continue
        if not (observed.embedded == reported.embedded == observed.eligible):
            problems.append(f"{label}: graph embedded {observed.embedded}, report embedded {reported.embedded}, eligible {observed.eligible}")
        if observed.wrong_dimension:
            problems.append(f"{label}: {observed.wrong_dimension} embeddings with size <> {EMBEDDING_DIM}")
    review = coverage.get("Review")
    if review is not None and review.eligible != build_params.expected_embed_reviews:
        problems.append(f"Review: eligible {review.eligible} <> expected_embed_reviews {build_params.expected_embed_reviews}")
    return _gate("H-10", not problems, expected="embedded = report = eligible per label",
                 observed={label: cov._asdict() for label, cov in sorted(coverage.items())}, detail=problems or None)


def gate_no_blank_embeddings(empty_products_embedded: int, blank_reviews_embedded: int, blank_template_top_scores: Mapping[str, float]) -> GateResult:
    """H-11: no content-free embedded node, and every blank-template probe's top-1 score < BLANK_TEMPLATE_MAX_SCORE."""
    hot = {probe: score for probe, score in blank_template_top_scores.items() if score >= BLANK_TEMPLATE_MAX_SCORE}
    passed = empty_products_embedded == 0 and blank_reviews_embedded == 0 and not hot
    return _gate("H-11", passed, expected={"empty_products_embedded": 0, "blank_reviews_embedded": 0, "max_probe_score": f"< {BLANK_TEMPLATE_MAX_SCORE}"},
                 observed={"empty_products_embedded": empty_products_embedded, "blank_reviews_embedded": blank_reviews_embedded,
                           "probes": len(blank_template_top_scores), "max_probe_score": max(blank_template_top_scores.values(), default=None)},
                 detail=hot or None)


def gate_indexes_online(indexes: Sequence[IndexState]) -> GateResult:
    """H-12: the 5 vector indexes and the full-text index exist, are ONLINE and at populationPercent 100.0."""
    by_name = {index.name: index for index in indexes}
    problems: List[str] = []
    for name in VECTOR_INDEX_NAMES + (FULLTEXT_INDEX_NAME,):
        index = by_name.get(name)
        if index is None:
            problems.append(f"{name}: missing")
        elif index.state != "ONLINE" or float(index.population_percent) != 100.0:
            problems.append(f"{name}: state {index.state}, population {index.population_percent}")
    return _gate("H-12", not problems, expected="ONLINE at 100.0",
                 observed={name: [by_name[name].state, by_name[name].population_percent] for name in sorted(by_name)},
                 detail=problems or None)


def gate_fulltext_smoke(found: bool, token: Optional[str], parent_asin: Optional[str], fields: Sequence[str]) -> GateResult:
    """H-13: the FR-025 smoke test passed on the final index fields (no candidate token is a failure)."""
    passed = bool(found) and token is not None and parent_asin is not None
    return _gate("H-13", passed, expected="product found by a features-only token",
                 observed={"found": bool(found), "token": token, "parent_asin": parent_asin, "fields": list(fields)})


def gate_import_fidelity(compared: int, mismatches: Sequence[FidelityMismatch]) -> GateResult:
    """H-14: zero mismatches over the compared sample (and compared > 0)."""
    return _gate("H-14", compared > 0 and not mismatches, expected={"mismatches": 0},
                 observed={"compared": compared, "mismatches": len(mismatches)},
                 detail=[{k: repr(v) if k in ("graph_value", "csv_value") else v for k, v in m._asdict().items()} for m in mismatches[:20]] or None)


def gate_benchmark_grounding(error: Optional[str], checked: int, allow_empty: bool = False) -> GateResult:
    """H-15: validate_benchmark_graph_grounding raised nothing; a connection error is a failure.
    `allow_empty` (pilot only) accepts a sample that contains no benchmark target."""
    passed = error is None and (checked > 0 or allow_empty)
    return _gate("H-15", passed, expected="no grounding violation", observed={"checked": checked}, detail=error)


def gate_no_legacy_schema(label_counts: Mapping[str, int], rel_counts: Mapping[str, int], numeric_value_count: int) -> GateResult:
    """H-16: zero legacy labels, relationship types and Attribute.numeric_value."""
    found = {label: label_counts.get(label, 0) for label in LEGACY_LABELS if label_counts.get(label, 0)}
    found.update({rel: rel_counts.get(rel, 0) for rel in LEGACY_REL_TYPES if rel_counts.get(rel, 0)})
    if numeric_value_count:
        found["Attribute.numeric_value"] = numeric_value_count
    return _gate("H-16", not found, expected=0, observed=found or 0)


def gate_taxon_integrity(
    bad_broader: int,
    products_with_multiple_taxa: int,
    in_taxon_count: int,
    lineage: Lineage,
    count_checks: Sequence[TaxonCountCheck],
) -> GateResult:
    """H-17: one BROADER parent of depth − 1 for non-roots, none for roots; <= 1 IN_TAXON per product; counts match lineage and the sample."""
    expected_in_taxon = lineage.counts.relationships.get("IN_TAXON")
    wrong_counts = [check for check in count_checks if check.stored != check.recomputed]
    passed = bad_broader == 0 and products_with_multiple_taxa == 0 and in_taxon_count == expected_in_taxon and not wrong_counts
    return _gate("H-17", passed,
                 expected={"bad_broader": 0, "multi_taxon_products": 0, "in_taxon": expected_in_taxon, "product_count_mismatches": 0},
                 observed={"bad_broader": bad_broader, "multi_taxon_products": products_with_multiple_taxa,
                           "in_taxon": in_taxon_count, "sampled": len(count_checks), "product_count_mismatches": len(wrong_counts)},
                 detail=[c._asdict() for c in wrong_counts[:20]] or None)


def gate_counts_match(node_counts: Mapping[str, int], rel_counts: Mapping[str, int], lineage: Lineage, duplicate_attribute_pairs: int) -> GateResult:
    """H-18: every label and type count equals lineage.counts.nodes / relationships; zero duplicate attribute pairs."""
    problems: List[str] = []
    for label, expected in lineage.counts.nodes.items():
        if node_counts.get(label, 0) != expected:
            problems.append(f"{label}: graph {node_counts.get(label, 0)} <> lineage {expected}")
    for rel, expected in lineage.counts.relationships.items():
        if rel_counts.get(rel, 0) != expected:
            problems.append(f"{rel}: graph {rel_counts.get(rel, 0)} <> lineage {expected}")
    if duplicate_attribute_pairs:
        problems.append(f"{duplicate_attribute_pairs} duplicate (attribute_name, attribute_value) pairs")
    return _gate("H-18", not problems, expected={"nodes": lineage.counts.nodes, "relationships": lineage.counts.relationships},
                 observed={"nodes": dict(node_counts), "relationships": dict(rel_counts), "duplicate_attribute_pairs": duplicate_attribute_pairs},
                 detail=problems or None)


def _tokens(text: Optional[str]) -> set:
    """Lower-cased alphabetic tokens of >= 6 letters."""
    return {token.lower() for token in SMOKE_TOKEN_PATTERN.findall(text or "")}


def pick_smoke_token(products: Sequence[Mapping[str, Any]], seed: int) -> Optional[Tuple[str, str]]:
    """FR-025: seeded choice of (parent_asin, token) with a >= 6-letter features token absent (case-insensitive)
    from the product's title, description and details_text (the longest such token per product); None if no product qualifies."""
    candidates: List[Tuple[str, str]] = []
    for product in products:
        features = product.get("features") or []
        feature_tokens = set()
        for item in features:
            feature_tokens |= _tokens(item)
        other = _tokens(product.get("title")) | _tokens(product.get("description")) | _tokens(product.get("details_text"))
        unique = sorted(feature_tokens - other, key=lambda token: (-len(token), token))
        if unique and product.get("parent_asin"):
            # the longest token is the rarest in practice, so the product ranks inside the top-50 hits
            candidates.append((str(product["parent_asin"]), unique[0]))
    if not candidates:
        return None
    return random.Random(seed).choice(sorted(candidates))


def isbn_like(asins: Iterable[str]) -> List[str]:
    """R-06: sorted parent_asins matching ISBN_PATTERN."""
    return sorted(asin for asin in asins if ISBN_PATTERN.match(asin))


def diff_benchmark_targets(v1_targets: Sequence[Mapping[str, Any]], v2_targets: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """R-07: per query, the fields whose value differs between v1 and v2."""
    v2_by_query = {target.get("query_id"): target for target in v2_targets}
    diffs: List[Dict[str, Any]] = []
    for v1 in v1_targets:
        v2 = v2_by_query.get(v1.get("query_id"), {})
        changed = {
            field: {"v1": v1.get(field), "v2": v2.get(field)}
            for field in ("target_asin", "title", "price", "brands", "categories", "review_nodes")
            if v1.get(field) != v2.get(field)
        }
        if changed:
            diffs.append({"query_id": v1.get("query_id"), "changes": changed})
    return diffs


def compare_counts(v1_snapshot: Mapping[str, Any], v2_snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """R-08: v1 vs v2 counts, review-embedding product coverage and untitled share."""
    def _share(snapshot: Mapping[str, Any], key: str) -> Optional[float]:
        products = (snapshot.get("nodes") or {}).get("ParentProduct")
        value = snapshot.get(key)
        return round(value / products, 6) if products and value is not None else None

    labels = sorted(set(v1_snapshot.get("nodes") or {}) | set(v2_snapshot.get("nodes") or {}))
    types = sorted(set(v1_snapshot.get("relationships") or {}) | set(v2_snapshot.get("relationships") or {}))
    return {
        "nodes": {label: {"v1": (v1_snapshot.get("nodes") or {}).get(label), "v2": (v2_snapshot.get("nodes") or {}).get(label)} for label in labels},
        "relationships": {t: {"v1": (v1_snapshot.get("relationships") or {}).get(t), "v2": (v2_snapshot.get("relationships") or {}).get(t)} for t in types},
        "untitled_share": {"v1": _share(v1_snapshot, "products_untitled"), "v2": _share(v2_snapshot, "products_untitled")},
        "review_embedded_product_coverage": {"v1": _share(v1_snapshot, "review_embedded_products"), "v2": _share(v2_snapshot, "review_embedded_products")},
    }


def build_report(
    hard_gates: Sequence[GateResult],
    report_only: Mapping[str, Mapping[str, Any]],
    *,
    pilot: bool,
    seed: int,
    lineage_sha256: str,
    build_params_sha256: str,
    embedding_report_sha256: str,
    graph_counts: Mapping[str, int],
    created_at: str,
) -> ValidationReport:
    """Assembles the report; `passed` is the conjunction of hard gates only (AC-029)."""
    ids = [gate.id for gate in hard_gates]
    missing = [gate_id for gate_id in GATE_NAMES if gate_id not in ids]
    gates = list(hard_gates) + [_gate(gate_id, False, detail="gate not evaluated") for gate_id in missing]
    gates.sort(key=lambda gate: gate.id)
    return ValidationReport(
        created_at=created_at, pilot=pilot, seed=seed, lineage_sha256=lineage_sha256,
        build_params_sha256=build_params_sha256, embedding_report_sha256=embedding_report_sha256,
        graph_counts=dict(graph_counts), passed=all(gate.passed for gate in gates), hard_gates=gates,
        report_only={key: dict(report_only.get(key, {})) for key in REPORT_ONLY_IDS},
    )


def exit_code(report: ValidationReport) -> int:
    """0 if passed, else 1."""
    return 0 if report.passed else 1
