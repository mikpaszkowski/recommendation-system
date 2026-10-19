#!/usr/bin/env python3
"""
Graph v2 validation gate (Technical Specification Graph Rebuild FR-026, FR-038, §5.5).

Runs the read-only Cypher behind hard gates H-01 … H-18 and report-only checks R-01 … R-08 and
hands the observed values to the pure gate functions in `src/knowledge_graph/graph_v2/validation.py`.
Thresholds come only from build_params.json and lineage.json; samples use the fixed --seed.
In --pilot mode (FR-026, amendment A-3) there is no pilot build_params file: the full build's
graph_versions/v2/build_params.json is read, and `validation.pilot_build_params` replaces only the
three expected counts with the pilot lineage's values (H-01 catalogue_missing_in_meta, H-08 kept,
H-10 embed_selected). The H-03 bound accepted_untitled_count, review_cap and product_content_rule
stay as in build_params. The report's build_params_sha256 is the hash of the file read. H-15 covers
only benchmark targets inside the sample. A pilot lineage without --pilot, or --pilot with a full
lineage, is an input error (exit 2).

Every path flag defaults to the artefact layout of `lineage.build_paths` (full build, or
`graph_versions/v2/pilot/` and `datasets/graph_build/v2_pilot/` with --pilot), the same defaults
build_graph_v2.py uses in sample mode.

Exit codes: 0 all hard gates pass; 1 any hard gate fails; 2 input error (missing or invalid artefact).

Usage:
    python scripts/graph_ingestion/validate_graph.py [--pilot] [--seed 20261019]
        [--lineage …] [--build-params …] [--embedding-report …] [--splits-dir …] [--catalogue …]
        [--import-dir …] [--benchmark …] [--out …] [--attribute-key-fallback]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import heapq
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import AbstractSet, Any, Callable, ContextManager, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from src.knowledge_graph.graph_v2 import validation as gates  # noqa: E402
from src.knowledge_graph.graph_v2.csv_io import decode_array, read_import_csv  # noqa: E402
from src.knowledge_graph.graph_v2.graph_queries import (  # noqa: E402
    PRODUCTS_UNTITLED_QUERY,
    benchmark_target_facts,
    collect_graph_snapshot,
    count_nodes_by_label,
    count_relationships_by_type,
    scalar,
)
from src.knowledge_graph.graph_v2.lineage import (  # noqa: E402
    InputVerificationError,
    build_paths,
    load_lineage,
    read_catalogue,
    sha256_file,
    shared_input,
    split_paths,
)
from src.knowledge_graph.graph_v2.models import (  # noqa: E402
    BuildParams,
    EmbeddingReport,
    GateResult,
    Lineage,
    ValidationReport,
)
from src.knowledge_graph.graph_v2.product_mapping import brand_case_groups  # noqa: E402
from src.knowledge_graph.graph_v2.review_selection import iter_split_pairs, load_pair_set  # noqa: E402
from src.knowledge_graph.graph_v2.transform import in_sample  # noqa: E402
from src.knowledge_graph.graph_v2.validation import FidelityMismatch, IndexState, LabelCoverage, TaxonCountCheck  # noqa: E402
from src.knowledge_graph.graphdb.embedding_templates import product_text_v1  # noqa: E402
from src.knowledge_graph.graphdb.vector_search_helper import build_vector_search_query  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validate_graph")

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_INPUT_ERROR = 2
DEFAULT_SEED = 20261019
V1_SNAPSHOT = REPO_ROOT / "graph_versions" / "v1" / "snapshot.json"
V1_BENCHMARK_TARGETS = REPO_ROOT / "graph_versions" / "v1" / "benchmark_targets.json"
EVALUATE_RETRIEVAL_SCRIPT = REPO_ROOT / "scripts" / "evaluate_retrieval.py"
POST_IMPORT_SCRIPT = Path(__file__).resolve().parent / "post_import_v2.py"
EMBED_LABELS: Tuple[str, ...] = ("Attribute", "Brand", "Category", "ParentProduct", "Review")
SPECIAL_REVIEW_CHARS: Tuple[str, ...] = ('"', "\\", "\n")

SessionFactory = Callable[[], ContextManager[Any]]


class ValidationInputs:
    """Loaded and validated artefacts for one validation run."""

    def __init__(
        self,
        lineage: Lineage,
        build_params: BuildParams,
        embedding_report: EmbeddingReport,
        catalogue: AbstractSet[str],
        file_hashes: Mapping[str, str],
    ) -> None:
        """Holds the inputs as read; file_hashes has lineage, build_params and embedding_report SHA-256."""
        self.lineage = lineage
        self.build_params = build_params
        self.embedding_report = embedding_report
        self.catalogue = catalogue
        self.file_hashes = dict(file_hashes)


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of §4.1.7 (plus --attribute-key-fallback when the pilot recorded the H-09 fallback)."""
    parser = argparse.ArgumentParser(description="Validate a graph v2 build (hard gates H-01 … H-18, report-only R-01 … R-08).")
    parser.add_argument("--lineage", type=Path, default=None, help="default: full or pilot lineage.json")
    parser.add_argument("--build-params", type=Path, default=None, help="default: graph_versions/v2/build_params.json (also for --pilot)")
    parser.add_argument("--embedding-report", type=Path, default=None, help="default: full or pilot embedding_report.json")
    parser.add_argument("--splits-dir", type=Path, default=None, help="default: datasets")
    parser.add_argument("--catalogue", type=Path, default=None, help="default: graph_versions/v2/catalogue_asins.txt.gz")
    parser.add_argument("--import-dir", type=Path, default=None, help="default: full or pilot import CSV directory")
    parser.add_argument("--benchmark", type=Path, default=None, help="default: live_eval_dataset.json")
    parser.add_argument("--out", type=Path, default=None, help="default: full or pilot validation_report.json")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--attribute-key-fallback", action="store_true",
                        help="The pilot showed 5.14 rejects the composite attribute_key constraint (H-18 duplicate check instead)")
    return parser


def resolve_paths(args: argparse.Namespace, repo_root: Path = REPO_ROOT) -> argparse.Namespace:
    """Fills every unset path flag from the full or pilot defaults (lineage.build_paths / shared_input)."""
    paths = build_paths(repo_root, bool(args.pilot))
    defaults = {
        "lineage": paths.lineage, "embedding_report": paths.embedding_report, "import_dir": paths.import_dir,
        "out": paths.validation_report, "build_params": shared_input(repo_root, "build_params"),
        "splits_dir": shared_input(repo_root, "splits_dir"), "catalogue": shared_input(repo_root, "catalogue"),
        "benchmark": shared_input(repo_root, "benchmark"),
    }
    for name, default in defaults.items():
        if getattr(args, name, None) is None:
            setattr(args, name, default)
    return args


def _load_script(path: Path, name: str) -> Any:
    """Loads a sibling script as a module (scripts are not a package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_inputs(args: argparse.Namespace) -> ValidationInputs:
    """Loads lineage, build params, embedding report and catalogue; raises InputVerificationError on any problem."""
    lineage = load_lineage(args.lineage)
    try:
        build_params = BuildParams.model_validate_json(Path(args.build_params).read_text(encoding="utf-8"))
        embedding_report = EmbeddingReport.model_validate_json(Path(args.embedding_report).read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise InputVerificationError(f"cannot read build params or embedding report: {e}") from e
    asins, _ = read_catalogue(args.catalogue)
    sample_mod = lineage.parameters.sample_mod
    catalogue = {asin for asin in asins if in_sample(asin, sample_mod)}
    check_pilot_mode(lineage, bool(args.pilot))
    for path in split_paths(args.splits_dir).values():
        if not path.is_file():
            raise InputVerificationError(f"split file missing: {path}")
    hashes = {
        "lineage": sha256_file(Path(args.lineage)),
        "build_params": sha256_file(Path(args.build_params)),
        "embedding_report": sha256_file(Path(args.embedding_report)),
    }
    return ValidationInputs(lineage, build_params, embedding_report, catalogue, hashes)


def check_pilot_mode(lineage: Lineage, pilot: bool) -> None:
    """A pilot lineage needs --pilot and --pilot needs a pilot lineage; otherwise InputVerificationError (exit 2)."""
    sample_mod = lineage.parameters.sample_mod
    if not pilot and sample_mod is not None:
        raise InputVerificationError("the lineage is a pilot lineage (sample_mod set); pass --pilot")
    if pilot and sample_mod is None:
        raise InputVerificationError("--pilot needs the pilot lineage (sample_mod set); this lineage is a full build")


def effective_build_params(inputs: ValidationInputs, pilot: bool) -> BuildParams:
    """build_params as read, or with the three pilot-lineage counts substituted under --pilot (A-3)."""
    check_pilot_mode(inputs.lineage, pilot)
    if not pilot:
        return inputs.build_params
    params = gates.pilot_build_params(inputs.build_params, inputs.lineage)
    logger.info(
        "Pilot counts from the pilot lineage: "
        f"accepted_catalogue_missing={params.accepted_catalogue_missing}, expected_review_count={params.expected_review_count}, "
        f"expected_embed_reviews={params.expected_embed_reviews}; accepted_untitled_count={params.accepted_untitled_count} "
        "and other thresholds from build_params"
    )
    return params


def _seeded_key(seed: int, value: str) -> str:
    """Deterministic sampling key for a string ID."""
    return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()


def collect_h01_h04(session: Any) -> Tuple[int, List[Optional[str]], int, int]:
    """(product count, streamed parent_asins, untitled count, ghost-signature count)."""
    products = scalar(session, "MATCH (p:ParentProduct) RETURN count(p) AS n")
    asins = [record["asin"] for record in session.run("MATCH (p:ParentProduct) RETURN p.parent_asin AS asin")]
    untitled = scalar(session, PRODUCTS_UNTITLED_QUERY)
    ghosts = scalar(session, "MATCH (p:ParentProduct) WHERE size([k IN keys(p) WHERE k <> 'embedding']) <= 1 RETURN count(p) AS n")
    return products, asins, untitled, ghosts


def collect_h05(session: Any) -> Tuple[int, int]:
    """(reviews without exactly one ABOUT_PRODUCT / WROTE, users without WROTE)."""
    bad = scalar(session, "MATCH (r:Review) WHERE COUNT { (r)-[:ABOUT_PRODUCT]->() } <> 1 OR COUNT { ()-[:WROTE]->(r) } <> 1 RETURN count(r) AS n")
    lonely = scalar(session, "MATCH (u:User) WHERE NOT EXISTS { (u)-[:WROTE]->() } RETURN count(u) AS n")
    return bad, lonely


def collect_h06(session: Any, splits_dir: Path, seed: int) -> Tuple[int, List[Tuple[str, str, bool]], AbstractSet[Tuple[str, str]]]:
    """(graph pairs in valid ∪ test, seeded 10,000-review sample, sample pairs found in the train CSV)."""
    paths = split_paths(splits_dir)
    excluded = load_pair_set([paths["valid"], paths["test"]])
    hits = 0
    rows: List[Tuple[str, str, str, bool]] = []

    def _stream() -> Iterable[Tuple[str, str, str, bool]]:
        nonlocal hits
        for record in session.run(
            "MATCH (u:User)-[:WROTE]->(r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct) "
            "RETURN u.user_id AS u, p.parent_asin AS p, r.review_id AS id, r.in_train_split AS t"
        ):
            if (record["u"], record["p"]) in excluded:
                hits += 1
            yield _seeded_key(seed, record["id"]), record["u"], record["p"], bool(record["t"])

    rows = heapq.nsmallest(gates.H06_SAMPLE_SIZE, _stream())
    sample = [(u, p, t) for _, u, p, t in rows]
    wanted = {(u, p) for u, p, _ in sample}
    train_hits = {pair for pair in iter_split_pairs(paths["train"]) if pair in wanted}
    return hits, sample, train_hits


def collect_h07_h08(session: Any) -> Tuple[int, int, int]:
    """(max reviews per product, products whose cap_ranks are not exactly 1 … n, review count)."""
    record = session.run("MATCH (p:ParentProduct) RETURN max(COUNT { (:Review)-[:ABOUT_PRODUCT]->(p) }) AS n").single()
    max_reviews = int(record["n"] or 0) if record is not None else 0
    bad = scalar(session, (
        "MATCH (r:Review)-[:ABOUT_PRODUCT]->(p:ParentProduct) "
        "WITH p, count(r) AS n, collect(DISTINCT r.cap_rank) AS ranks "
        "WHERE size(ranks) <> n OR any(x IN ranks WHERE x < 1 OR x > n) RETURN count(p) AS n"
    ))
    reviews = scalar(session, "MATCH (r:Review) RETURN count(r) AS n")
    return max_reviews, bad, reviews


def collect_h09(session: Any) -> List[str]:
    """Constraint names from SHOW CONSTRAINTS."""
    return [record["name"] for record in session.run("SHOW CONSTRAINTS YIELD name RETURN name")]


def collect_h10(session: Any, product_content_rule: str) -> Dict[str, LabelCoverage]:
    """Per-label embedded, eligible (recomputed in Cypher) and wrong-dimension counts."""
    specs = _load_script(POST_IMPORT_SCRIPT, "post_import_v2_for_validation").label_specs(product_content_rule)
    coverage: Dict[str, LabelCoverage] = {}
    for label in EMBED_LABELS:
        spec = specs[label]
        coverage[label] = LabelCoverage(
            embedded=scalar(session, spec.embedded_query),
            eligible=scalar(session, spec.eligible_query),
            wrong_dimension=scalar(session, (
                f"MATCH (n:{label}) WHERE n.embedding IS NOT NULL AND size(n.embedding) <> {gates.EMBEDDING_DIM} "
                "RETURN count(n) AS n"
            )),
        )
    return coverage


def collect_h11(session: Any, embedder: Any, product_content_rule: str = "title_description_features") -> Tuple[int, int, Dict[str, float]]:
    """(content-free embedded products, blank embedded reviews, blank-template probe -> top-1 score)."""
    content = (
        "((n.title IS NOT NULL AND trim(n.title) <> '') OR (n.description IS NOT NULL AND trim(n.description) <> '')"
        + (" OR any(f IN coalesce(n.features, []) WHERE trim(f) <> ''))" if product_content_rule == "title_description_features" else ")")
    )
    empty_products = scalar(session, f"MATCH (n:ParentProduct) WHERE n.embedding IS NOT NULL AND NOT {content} RETURN count(n) AS n")
    blank_reviews = scalar(session, (
        "MATCH (r:Review) WHERE r.embedding IS NOT NULL AND (r.review_title IS NULL OR trim(r.review_title) = '') "
        "AND (r.review_body IS NULL OR trim(r.review_body) = '') RETURN count(r) AS n"
    ))
    categories = sorted(record["name"] for record in session.run("MATCH (c:Category) RETURN c.name AS name"))
    probes: Dict[str, Tuple[str, str]] = {
        f"product_blank[{name}]": ("product_embedding_index", f"Product: . Category: {name}. Features: . Description: ")
        for name in categories + ["Unknown"]
    }
    probes["review_blank"] = ("review_embedding_index", ". ")
    vectors = embedder.embed_documents([text for _, text in probes.values()])
    scores: Dict[str, float] = {}
    for (probe, (index, _)), vector in zip(probes.items(), vectors):
        query = build_vector_search_query(index, 1, return_clause="RETURN score")
        record = session.run(query, vector=[float(x) for x in vector]).single()
        scores[probe] = float(record["score"]) if record is not None else 0.0
    return empty_products, blank_reviews, scores


def collect_h12_h13(session_factory: SessionFactory, seed: int) -> Tuple[List[IndexState], bool, Optional[str], Optional[str], List[str]]:
    """(index states, smoke found, token, parent_asin, full-text fields read from SHOW INDEXES)."""
    with session_factory() as session:
        indexes = [
            IndexState(
                name=record["name"], type=record["type"], state=record["state"],
                population_percent=float(record["populationPercent"] or 0.0), properties=tuple(record["properties"] or ()),
            )
            for record in session.run(
                "SHOW INDEXES YIELD name, type, state, populationPercent, properties "
                "RETURN name, type, state, populationPercent, properties"
            )
        ]
    fields = next((list(index.properties) for index in indexes if index.name == gates.FULLTEXT_INDEX_NAME), [])
    found, token, asin = _load_script(POST_IMPORT_SCRIPT, "post_import_v2_for_smoke").fulltext_smoke_test(session_factory, seed)
    return indexes, found, token, asin, fields


def _csv_sample(path: Path, key_field: str, k: int, seed: int, extra: Optional[Callable[[Dict[str, str]], bool]] = None,
                extra_k: int = 0) -> List[Dict[str, str]]:
    """Seeded sample of k rows (plus up to extra_k rows matching `extra`) from an import CSV."""
    main: List[Tuple[str, Dict[str, str]]] = []
    special: List[Tuple[str, Dict[str, str]]] = []
    for row in read_import_csv(path):
        key = _seeded_key(seed, row[key_field])
        main.append((key, row))
        if extra is not None and extra(row):
            special.append((key, row))
        if len(main) > 4 * k:
            main = heapq.nsmallest(k, main, key=lambda item: item[0])
        if len(special) > 4 * max(extra_k, 1):
            special = heapq.nsmallest(extra_k, special, key=lambda item: item[0])
    chosen = {row[key_field]: row for _, row in heapq.nsmallest(k, main, key=lambda item: item[0])}
    for _, row in heapq.nsmallest(extra_k, special, key=lambda item: item[0]):
        chosen.setdefault(row[key_field], row)
    return list(chosen.values())


def _csv_value(field: str, raw: str) -> Any:
    """Typed value of an import CSV field as Neo4j stores it (empty -> None)."""
    if raw == "":
        return None
    if field in ("features",):
        return decode_array(raw)
    if field == "rating":
        return float(raw)
    if field in ("timestamp", "helpful_vote"):
        return int(raw)
    if field == "verified":
        return raw == "true"
    return raw


def collect_h14(session: Any, import_dir: Path, seed: int) -> Tuple[int, List[FidelityMismatch]]:
    """Compares seeded graph values with the values parsed back from the import CSVs (2,000 + 2,000 + up to 500 special)."""
    def _special(row: Dict[str, str]) -> bool:
        body = row.get("review_body", "")
        return any(ch in body for ch in SPECIAL_REVIEW_CHARS) or any(ord(ch) > 127 for ch in body)

    products = _csv_sample(Path(import_dir) / "nodes_product.csv", "parent_asin:ID(ParentProduct)", gates.H14_PRODUCT_SAMPLE, seed)
    reviews = _csv_sample(Path(import_dir) / "nodes_review.csv", "review_id:ID(Review)", gates.H14_REVIEW_SAMPLE, seed,
                          extra=_special, extra_k=gates.H14_SPECIAL_REVIEW_SAMPLE)
    mismatches: List[FidelityMismatch] = []
    compared = 0
    jobs = (
        ("ParentProduct", "parent_asin", "parent_asin:ID(ParentProduct)", products, gates.FIDELITY_PRODUCT_FIELDS,
         {"features": "features:string[]"}),
        ("Review", "review_id", "review_id:ID(Review)", reviews, gates.FIDELITY_REVIEW_FIELDS,
         {"rating": "rating:double", "timestamp": "timestamp:long", "helpful_vote": "helpful_vote:long", "verified": "verified:boolean"}),
    )
    for label, key, key_column, rows, fields, typed in jobs:
        by_id = {row[key_column]: row for row in rows}
        returns = ", ".join(f"n.{field} AS {field}" for field in fields)
        graph_rows = {
            record["k"]: record
            for record in session.run(f"UNWIND $ids AS id MATCH (n:{label} {{{key}: id}}) RETURN n.{key} AS k, {returns}", ids=sorted(by_id))
        }
        for node_id, row in sorted(by_id.items()):
            record = graph_rows.get(node_id)
            for field in fields:
                csv_value = _csv_value(field, row[typed.get(field, field)])
                graph_value = record[field] if record is not None else "<missing node>"
                if isinstance(graph_value, tuple):
                    graph_value = list(graph_value)
                if graph_value != csv_value:
                    mismatches.append(FidelityMismatch(label, node_id, field, graph_value, csv_value))
            compared += 1
    return compared, mismatches


def collect_h15(connector: Any, benchmark_path: Path, sample_mod: Optional[int]) -> Tuple[Optional[str], int]:
    """Runs evaluate_retrieval.validate_benchmark_graph_grounding (loaded by path); (error message or None, targets checked)."""
    benchmark = json.loads(Path(benchmark_path).read_text(encoding="utf-8"))
    items = [
        item for item in benchmark
        if in_sample(str(item.get("target_asin") or (item.get("ground_truth_asins") or [""])[0]), sample_mod)
    ]
    if not items:
        return None, 0
    module = _load_script(EVALUATE_RETRIEVAL_SCRIPT, "evaluate_retrieval_for_validation")
    try:
        module.validate_benchmark_graph_grounding(items, connector)
    except Exception as e:
        return f"{type(e).__name__}: {e}", len(items)
    return None, len(items)


def collect_h16_h18(session: Any, seed: int) -> Dict[str, Any]:
    """Label and type counts, numeric_value count, taxon BROADER / IN_TAXON checks, sampled product_count checks, duplicate attribute pairs."""
    taxon_ids = [record["id"] for record in session.run("MATCH (t:Taxon) RETURN t.taxon_id AS id")]
    checks: List[TaxonCountCheck] = []
    for taxon_id in gates.seeded_sample(taxon_ids, gates.H17_TAXON_SAMPLE, seed):
        record = session.run(
            "MATCH (t:Taxon {taxon_id: $id}) RETURN t.product_count AS stored, "
            "COUNT { (:ParentProduct)-[:IN_TAXON]->(:Taxon)-[:BROADER*0..]->(t) } AS recomputed", id=taxon_id,
        ).single()
        if record is None:
            checks.append(TaxonCountCheck(taxon_id, -1, 0))  # vanished between the two reads: recorded as a mismatch
            continue
        checks.append(TaxonCountCheck(taxon_id, int(record["stored"] or 0), int(record["recomputed"] or 0)))
    return {
        "nodes": count_nodes_by_label(session),
        "relationships": count_relationships_by_type(session),
        "numeric_value": scalar(session, "MATCH (a:Attribute) WHERE a.numeric_value IS NOT NULL RETURN count(a) AS n"),
        "bad_broader": scalar(session, (
            "MATCH (t:Taxon) WITH t, [(t)-[:BROADER]->(p:Taxon) | p.depth] AS parents "
            "WHERE (t.depth = 1 AND size(parents) <> 0) OR (t.depth > 1 AND (size(parents) <> 1 OR parents[0] <> t.depth - 1)) "
            "RETURN count(t) AS n"
        )),
        "multi_taxon": scalar(session, "MATCH (p:ParentProduct) WHERE COUNT { (p)-[:IN_TAXON]->() } > 1 RETURN count(p) AS n"),
        "taxon_checks": checks,
        "duplicate_attributes": scalar(session, (
            "MATCH (a:Attribute) WITH a.attribute_name AS name, a.attribute_value AS value, count(*) AS c "
            "WHERE c > 1 RETURN count(*) AS n"
        )),
    }


COVERAGE_RETURN = (
    "count(p) AS products, "
    "sum(CASE WHEN p.title IS NOT NULL THEN 1 ELSE 0 END) AS with_title, "
    "sum(CASE WHEN p.price IS NOT NULL THEN 1 ELSE 0 END) AS with_price, "
    "sum(CASE WHEN EXISTS { (p)-[:HAS_BRAND]->() } THEN 1 ELSE 0 END) AS with_brand, "
    "sum(CASE WHEN p.features IS NOT NULL THEN 1 ELSE 0 END) AS with_features, "
    "sum(CASE WHEN p.description IS NOT NULL THEN 1 ELSE 0 END) AS with_description, "
    "sum(CASE WHEN p.details_text IS NOT NULL THEN 1 ELSE 0 END) AS details_ge1, "
    "sum(CASE WHEN size(split(coalesce(p.details_text, ''), '\\n')) >= 5 THEN 1 ELSE 0 END) AS details_ge5, "
    "sum(CASE WHEN COUNT { (:Review)-[:ABOUT_PRODUCT]->(p) } >= 1 THEN 1 ELSE 0 END) AS reviews_ge1, "
    "sum(CASE WHEN COUNT { (:Review)-[:ABOUT_PRODUCT]->(p) } >= 5 THEN 1 ELSE 0 END) AS reviews_ge5"
)


def _coverage(session: Any, cypher: str) -> Dict[str, Dict[str, Any]]:
    """group -> coverage shares for a grouped coverage query returning `grp` and COVERAGE_RETURN columns."""
    result: Dict[str, Dict[str, Any]] = {}
    for record in session.run(cypher):
        data = dict(record)
        products = int(data.pop("products") or 0)
        group = str(data.pop("grp"))
        result[group] = {"products": products, **{k: round(int(v or 0) / products, 4) if products else None for k, v in data.items()}}
    return result


def collect_report_only(session: Any, inputs: ValidationInputs, embedder: Any, seed: int,
                        graph_asins: Sequence[Optional[str]] = ()) -> Dict[str, Dict[str, Any]]:
    """R-01 … R-08 findings (never change `passed`). Each check that fails records its error instead."""
    report: Dict[str, Dict[str, Any]] = {}

    def _try(check_id: str, fn: Callable[[], Dict[str, Any]]) -> None:
        try:
            report[check_id] = fn()
        except Exception as e:
            logger.warning(f"[{check_id}] report-only check failed: {e}")
            report[check_id] = {"error": f"{type(e).__name__}: {e}"}

    _try("R-01", lambda: {"by_main_category": _coverage(session, (
        "MATCH (p:ParentProduct) OPTIONAL MATCH (p)-[:BELONGS_TO_CATEGORY]->(c:Category) "
        f"WITH coalesce(c.name, '') AS grp, p RETURN grp, {COVERAGE_RETURN} ORDER BY grp"
    ))})
    _try("R-02", lambda: {
        f"depth_{depth}": _coverage(session, (
            "MATCH (p:ParentProduct)-[:IN_TAXON]->(:Taxon)-[:BROADER*0..]->(t:Taxon) "
            f"WHERE t.depth = {depth} WITH t.taxon_id AS grp, p RETURN grp, {COVERAGE_RETURN} ORDER BY grp"
        ))
        for depth in (1, 2)
    })
    _try("R-03", lambda: {
        "depth_distribution": {str(record["d"]): int(record["n"]) for record in session.run(
            "MATCH (t:Taxon) RETURN t.depth AS d, count(*) AS n ORDER BY d")},
        **inputs.lineage.counts.taxonomy.model_dump(mode="json"),
    })

    def _r04() -> Dict[str, Any]:
        asins = [record["asin"] for record in session.run(
            "MATCH (p:ParentProduct) WHERE p.embedding IS NOT NULL RETURN p.parent_asin AS asin")]
        fetch = (
            "MATCH (n:ParentProduct {parent_asin: $asin}) OPTIONAL MATCH (n)-[:BELONGS_TO_CATEGORY]->(c:Category) "
            "WITH n, min(c.name) AS category OPTIONAL MATCH (n)-[:HAS_ATTRIBUTE]->(a:Attribute) "
            "WITH n, category, a ORDER BY a.attribute_name, a.attribute_value "
            "WITH n, category, collect(a.attribute_name + ': ' + coalesce(a.attribute_value, '')) AS pairs "
            "RETURN n.title AS title, n.description AS description, n.features AS features, category, pairs, n.embedding AS e"
        )
        neighbour = build_vector_search_query(
            "product_embedding_index", 2, where_clause="node.parent_asin <> $asin",
            return_clause="RETURN node.parent_asin AS other, score", order_by="score DESC", limit=1,
        )
        groups: List[Dict[str, Any]] = []
        for asin in gates.seeded_sample(asins, gates.R04_PRODUCT_SAMPLE, seed):
            row = session.run(fetch, asin=asin).single()
            hit = session.run(neighbour, vector=list(row["e"]), asin=asin).single()
            if hit is None or float(hit["score"]) < gates.IDENTICAL_EMBEDDING_SCORE:
                continue
            other = session.run(fetch, asin=hit["other"]).single()
            texts = [product_text_v1(r["title"], r["category"], r["pairs"] or [], r["description"], r["features"]) for r in (row, other)]
            if texts[0] != texts[1]:
                groups.append({"asin": asin, "other": hit["other"], "score": float(hit["score"])})
        return {"sampled": min(len(asins), gates.R04_PRODUCT_SAMPLE), "identical_with_different_text": groups[:200], "count": len(groups)}

    _try("R-04", _r04)

    def _r05() -> Dict[str, Any]:
        products = {record["name"]: int(record["n"]) for record in session.run(
            "MATCH (b:Brand) RETURN b.name AS name, COUNT { (:ParentProduct)-[:HAS_BRAND]->(b) } AS n")}
        groups = brand_case_groups(products)
        return {"groups": [[{"name": n, "products": products[n]} for n in group] for group in groups[:200]], "count": len(groups)}

    _try("R-05", _r05)
    _try("R-06", lambda: (lambda found: {"count": len(found), "asins": found[:200]})(
        gates.isbn_like(a for a in graph_asins if a)))

    def _r07() -> Dict[str, Any]:
        if not V1_BENCHMARK_TARGETS.is_file():
            return {"skipped": f"{V1_BENCHMARK_TARGETS} not found"}
        v1 = json.loads(V1_BENCHMARK_TARGETS.read_text(encoding="utf-8"))
        v2 = [benchmark_target_facts(session, t["query_id"], t["target_asin"]) for t in v1]
        return {"differences": gates.diff_benchmark_targets(v1, v2)}

    _try("R-07", _r07)

    def _r08() -> Dict[str, Any]:
        if not V1_SNAPSHOT.is_file():
            return {"skipped": f"{V1_SNAPSHOT} not found"}
        return gates.compare_counts(json.loads(V1_SNAPSHOT.read_text(encoding="utf-8")), collect_graph_snapshot(session))

    _try("R-08", _r08)
    return report


def _failed(gate_id: str, error: Exception) -> GateResult:
    """A gate whose evidence could not be collected."""
    logger.error(f"[{gate_id}] collection failed: {error}")
    return GateResult(id=gate_id, name=gates.GATE_NAMES[gate_id], passed=False, detail=f"{type(error).__name__}: {error}")


def run_validation(
    args: argparse.Namespace,
    session_factory: SessionFactory,
    connector: Any,
    embedder: Any,
    inputs: Optional[ValidationInputs] = None,
) -> ValidationReport:
    """Collects everything, evaluates the gates, assembles the report."""
    inputs = inputs or load_inputs(args)
    lineage, params = inputs.lineage, effective_build_params(inputs, bool(args.pilot))
    rule = params.product_content_rule
    results: List[GateResult] = []
    graph_asins: List[Optional[str]] = []
    graph_counts: Dict[str, int] = {}

    with session_factory() as session:
        try:
            products, graph_asins, untitled, ghosts = collect_h01_h04(session)
            graph_counts["ParentProduct"] = products
            results += [
                gates.gate_product_count(products, lineage, params, len(inputs.catalogue)),
                gates.gate_catalogue_membership(graph_asins, inputs.catalogue),
                gates.gate_untitled(untitled, lineage, params),
                gates.gate_ghost_signature(ghosts),
            ]
        except Exception as e:
            results += [_failed(g, e) for g in ("H-01", "H-02", "H-03", "H-04")]
        for gate_id, fn in (
            ("H-05", lambda: gates.gate_review_integrity(*collect_h05(session))),
            ("H-06", lambda: gates.gate_split_exclusion(*collect_h06(session, args.splits_dir, args.seed))),
            ("H-09", lambda: gates.gate_constraints(collect_h09(session), args.attribute_key_fallback)),
            ("H-10", lambda: gates.gate_embedding_coverage(collect_h10(session, rule), inputs.embedding_report, params)),
            ("H-11", lambda: gates.gate_no_blank_embeddings(*collect_h11(session, embedder, rule))),
            ("H-14", lambda: gates.gate_import_fidelity(*collect_h14(session, args.import_dir, args.seed))),
        ):
            try:
                results.append(fn())
            except Exception as e:
                results.append(_failed(gate_id, e))
        try:
            max_reviews, bad_ranks, reviews = collect_h07_h08(session)
            graph_counts["Review"] = reviews
            results += [gates.gate_cap(max_reviews, bad_ranks, params.review_cap), gates.gate_review_count(reviews, lineage, params)]
        except Exception as e:
            results += [_failed(g, e) for g in ("H-07", "H-08")]
        try:
            facts = collect_h16_h18(session, args.seed)
            results += [
                gates.gate_no_legacy_schema(facts["nodes"], facts["relationships"], facts["numeric_value"]),
                gates.gate_taxon_integrity(facts["bad_broader"], facts["multi_taxon"], facts["relationships"].get("IN_TAXON", 0),
                                           lineage, facts["taxon_checks"]),
                gates.gate_counts_match(facts["nodes"], facts["relationships"], lineage, facts["duplicate_attributes"]),
            ]
        except Exception as e:
            results += [_failed(g, e) for g in ("H-16", "H-17", "H-18")]
        report_only = collect_report_only(session, inputs, embedder, args.seed, graph_asins)
    try:
        indexes, found, token, asin, fields = collect_h12_h13(session_factory, args.seed)
        results += [gates.gate_indexes_online(indexes), gates.gate_fulltext_smoke(found, token, asin, fields)]
    except Exception as e:
        results += [_failed(g, e) for g in ("H-12", "H-13")]
    try:
        error, checked = collect_h15(connector, args.benchmark, lineage.parameters.sample_mod)
        results.append(gates.gate_benchmark_grounding(error, checked, allow_empty=bool(args.pilot)))
    except Exception as e:
        results.append(_failed("H-15", e))

    return gates.build_report(
        results, report_only, pilot=bool(args.pilot), seed=args.seed,
        lineage_sha256=inputs.file_hashes["lineage"], build_params_sha256=inputs.file_hashes["build_params"],
        embedding_report_sha256=inputs.file_hashes["embedding_report"], graph_counts=graph_counts,
        created_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def write_report(report: ValidationReport, path: Path) -> str:
    """Writes the validation report JSON; returns its SHA-256."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False, default=str) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(
    argv: Optional[Sequence[str]] = None,
    session_factory: Optional[SessionFactory] = None,
    connector: Optional[Any] = None,
    embedder: Optional[Any] = None,
) -> int:
    """CLI entry point; returns 0 / 1 / 2."""
    args = resolve_paths(build_parser().parse_args(argv))
    try:
        inputs = load_inputs(args)
    except InputVerificationError as e:
        logger.error(f"Input error: {e}")
        return EXIT_INPUT_ERROR
    owned = None
    if session_factory is None:
        from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

        owned = connector or Neo4jConnector()
        try:
            if not owned.is_connected():
                owned.connect()
        except Exception as e:
            logger.error(f"Cannot connect to Neo4j: {e}")
            return EXIT_GATE_FAILED
        connector = owned
        session_factory = owned.session
    if embedder is None:
        from src.knowledge_graph.graphdb.embedding_service import EmbeddingService

        embedder = EmbeddingService()
    try:
        report = run_validation(args, session_factory, connector, embedder, inputs)
    except InputVerificationError as e:
        logger.error(f"Input error: {e}")
        return EXIT_INPUT_ERROR
    finally:
        if owned is not None:
            owned.close()
    sha = write_report(report, args.out)
    failed = [gate.id for gate in report.hard_gates if not gate.passed]
    logger.info(f"Validation report {args.out} (sha256 {sha}): passed={report.passed}; failed gates: {failed or 'none'}")
    return gates.exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
