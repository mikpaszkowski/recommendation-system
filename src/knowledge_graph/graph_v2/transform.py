"""
Graph v2 transform orchestration (FR-005 … FR-018, NFR-001, NFR-002).

Execution order (the §5.3 `timing_s` keys are not an execution order):
    1. verify inputs (SHA256SUMS, split hashes, catalogue)          -> exit 2 on any problem
    2. `--require-clean`: refuse if src/ or scripts/ are dirty      -> exit 2
    3. meta pass: one ProductRecord per catalogue ASIN (first line wins), taxonomy, brands,
       categories, attributes; product-side CSVs
    4. review pass 1: stream Electronics.jsonl with byte offsets; drop in FR-011 order
       (json_errors, missing_ids, not_in_catalogue / product_missing, valid_test_pair); offer the
       rest to TopKSelector
    5. selection: cap_rank, embed_rank, selected (user_id, parent_asin) pairs
    6. train mark: stream Electronics.train.csv once against the selected pairs
    7. review pass 2: read selected lines in ascending byte offset; write nodes_review.csv,
       rels_about_product.csv, rels_wrote.csv; users collected and written sorted
    8. lineage: counts, outputs, invariants, then lineage.json

The meta pass runs before review pass 1 so `product_missing` is decided in the FR-011 drop order.
In sample mode (`--sample-mod N`) the effective catalogue is the sampled subset: unsampled meta and
review lines count as `not_in_catalogue`, and `sources.catalogue.sampled_count` records the size.
`dry_run` runs every pass and counter with count-only writers and writes neither CSVs nor lineage.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

from src.evaluation.provenance import GitRunner, collect_git_provenance
from src.knowledge_graph.graph_v2.csv_io import HEADERS, ImportCsvWriter, attribute_node_id
from src.knowledge_graph.graph_v2.import_command import NODE_FILES, REL_FILES
from src.knowledge_graph.graph_v2.lineage import (
    DUPLICATE_LIST_CAP,
    GraphBuildError,
    IntegrityTracker,
    assert_invariants,
    cap_list,
    catalogue_info,
    default_columns,
    default_parameters,
    hash_splits,
    read_catalogue,
    split_paths,
    verify_raw_inputs,
    write_lineage,
)
from src.knowledge_graph.graph_v2.models import (
    CodeInfo,
    Duplicates,
    FileStats,
    Lineage,
    LineageCounts,
    MetaCounts,
    ReviewCounts,
    SanitizedCounts,
    Sources,
    TaxonomyCounts,
)
from src.knowledge_graph.graph_v2.product_mapping import (
    ATTRIBUTE_KEYS,
    DETAILS_BRAND_KEY,
    ProductRecord,
    brand_case_groups,
    map_meta_record,
    product_csv_values,
)
from src.knowledge_graph.graph_v2.review_selection import (
    DEFAULT_EMBED_TOP_N,
    DEFAULT_REVIEW_CAP,
    Pair,
    SelectedReview,
    TopKSelector,
    build_selection,
    candidate_from_record,
    has_review_text,
    load_pair_set,
    mark_train_pairs,
    review_node_values,
)
from src.knowledge_graph.graph_v2.taxonomy import TaxonomyBuilder
from src.knowledge_graph.graph_v2.validation import ISBN_PATTERN

logger = logging.getLogger(__name__)

CLEAN_TREE_SCOPE: Tuple[str, ...] = ("src", "scripts")
PROGRESS_EVERY_LINES: int = 1_000_000
DETAILS_HISTOGRAM_TOP: int = 100
SCRIPT_PATH: str = "scripts/graph_ingestion/build_graph_v2.py"


class CleanTreeError(GraphBuildError):
    """`--require-clean` was given and src/ or scripts/ have uncommitted or untracked changes (FR-018)."""


@dataclass(frozen=True)
class TransformConfig:
    """All inputs and parameters of one transform run (CLI flags of build_graph_v2.py, §4.1.7).
    `out_dir` is the directory that receives the 14 import CSVs."""

    meta_path: Path
    reviews_path: Path
    sha256sums_path: Path
    splits_dir: Path
    catalogue_path: Path
    out_dir: Path
    lineage_path: Path
    review_cap: int = DEFAULT_REVIEW_CAP
    embed_top_n: int = DEFAULT_EMBED_TOP_N
    sample_mod: Optional[int] = None
    dry_run: bool = False
    require_clean: bool = False
    repo_root: Path = Path(".")


class MetaDiagnostics(NamedTuple):
    """Pre-flight-only meta facts that are not part of the lineage schema (P-01, P-06)."""

    details_key_histogram: Dict[str, int]      # top 100 `details` keys over in-scope records
    attribute_key_counts: Dict[str, int]       # per ATTRIBUTE_KEYS key and "Brand"
    isbn_like_asins: List[str]                 # ^\d{9}[\dX]$ parent_asins (R-06)


class MetaPassResult(NamedTuple):
    """Output of the meta pass held for the review passes and the writers."""

    records: Dict[str, ProductRecord]          # parent_asin -> record (written product set)
    taxonomy: TaxonomyBuilder
    conflicting_duplicates: List[str]
    diagnostics: MetaDiagnostics


class ReviewPassResult(NamedTuple):
    """Output of review pass 1 and selection."""

    selection: Dict[int, SelectedReview]       # byte offset -> selected review
    selected_pairs: Set[Pair]
    lines: int


class ReviewWriters(NamedTuple):
    """The three presorted writers fed by pass 2 (nodes_review, rels_about_product, rels_wrote)."""

    reviews: ImportCsvWriter
    about_product: ImportCsvWriter
    wrote: ImportCsvWriter


class TransformResult(NamedTuple):
    """Return value of run_transform: the lineage (written unless dry run) and pre-flight diagnostics."""

    lineage: Lineage
    diagnostics: MetaDiagnostics
    wrote_files: bool
    products_with_reviews: Dict[str, int]      # products with >= 1, >= 5 and >= 20 kept reviews (P-02)


def in_sample(parent_asin: str, sample_mod: Optional[int]) -> bool:
    """FR-016: True when sample_mod is None, else `int(sha256(parent_asin).hexdigest(), 16) % sample_mod == 0`."""
    if sample_mod is None:
        return True
    if sample_mod < 1:
        raise ValueError(f"sample_mod must be >= 1, got {sample_mod}")
    return int(hashlib.sha256(parent_asin.encode("utf-8")).hexdigest(), 16) % sample_mod == 0


def require_clean_tree(repo_root: Path, runner: Optional[GitRunner] = None) -> Dict[str, Any]:
    """Runs collect_git_provenance over src/ and scripts/; raises CleanTreeError if dirty or unknown; returns the git facts."""
    git = collect_git_provenance(Path(repo_root), CLEAN_TREE_SCOPE, runner)
    if git.get("git_dirty") is None:
        raise CleanTreeError("--require-clean: git status is unavailable, cannot prove a clean tree")
    if git.get("git_dirty"):
        raise CleanTreeError(f"--require-clean: uncommitted or untracked changes in src/ or scripts/: {git.get('git_dirty_paths')}")
    if not git.get("git_commit"):
        raise CleanTreeError("--require-clean: git commit is unknown")
    return git


def _parse_json_line(line: bytes) -> Optional[Dict[str, Any]]:
    """A JSON object from one line, or None for a malformed line or a non-object."""
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def run_meta_pass(meta_path: Path, catalogue: AbstractSet[str], counters: "Counter[str]") -> MetaPassResult:
    """Streams meta_Electronics.jsonl once (FR-006 … FR-010); first line per parent_asin wins."""
    records: Dict[str, ProductRecord] = {}
    digests: Dict[str, bytes] = {}
    conflicting: List[str] = []
    conflicting_seen: Set[str] = set()
    taxonomy = TaxonomyBuilder()
    details_hist: "Counter[str]" = Counter()
    key_counts: "Counter[str]" = Counter()
    with open(meta_path, "rb") as handle:
        for line in handle:
            counters["lines"] += 1
            if counters["lines"] % PROGRESS_EVERY_LINES == 0:
                logger.info(f"[Transform] meta: {counters['lines']:,} lines, {len(records):,} products")
            raw = _parse_json_line(line)
            if raw is None:
                counters["json_errors"] += 1
                continue
            parent_asin = raw.get("parent_asin")
            if not isinstance(parent_asin, str) or parent_asin not in catalogue:
                counters["not_in_catalogue"] += 1
                continue
            digest = hashlib.sha1(
                json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).digest()
            if parent_asin in digests:
                counters["duplicate_parent_asin"] += 1
                if digests[parent_asin] != digest and parent_asin not in conflicting_seen:
                    conflicting_seen.add(parent_asin)
                    conflicting.append(parent_asin)
                continue
            digests[parent_asin] = digest
            record = map_meta_record(raw, counters)
            taxonomy.add_product(parent_asin, record.levels, record.main_category)
            records[parent_asin] = record
            counters["products_written"] += 1
            details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
            details_hist.update(details.keys())
            for key in ATTRIBUTE_KEYS + (DETAILS_BRAND_KEY,):
                if key in details:
                    key_counts[key] += 1
    counters["catalogue_missing_in_meta"] = len(catalogue) - len(records)
    diagnostics = MetaDiagnostics(
        details_key_histogram=dict(details_hist.most_common(DETAILS_HISTOGRAM_TOP)),
        attribute_key_counts={key: key_counts[key] for key in ATTRIBUTE_KEYS + (DETAILS_BRAND_KEY,)},
        isbn_like_asins=sorted(asin for asin in records if ISBN_PATTERN.match(asin)),
    )
    logger.info(f"[Transform] meta pass done: {counters['lines']:,} lines, {len(records):,} products")
    return MetaPassResult(records, taxonomy, conflicting, diagnostics)


def run_review_pass1(
    reviews_path: Path,
    catalogue: AbstractSet[str],
    products: AbstractSet[str],
    excluded_pairs: AbstractSet[Pair],
    review_cap: int,
    embed_top_n: int,
    counters: "Counter[str]",
) -> ReviewPassResult:
    """Streams Electronics.jsonl with byte offsets, applies the FR-011 drop order, selects and ranks (FR-011, FR-012)."""
    selector = TopKSelector(review_cap)
    offset = 0
    with open(reviews_path, "rb") as handle:
        for line in handle:
            line_offset = offset
            offset += len(line)
            counters["lines"] += 1
            if counters["lines"] % PROGRESS_EVERY_LINES == 0:
                logger.info(f"[Transform] reviews pass 1: {counters['lines']:,} lines")
            raw = _parse_json_line(line)
            if raw is None:
                counters["json_errors"] += 1
                continue
            parsed = candidate_from_record(raw, line_offset, counters)
            if parsed is None:
                continue
            parent_asin, candidate = parsed
            if parent_asin not in catalogue:
                counters["not_in_catalogue"] += 1
                continue
            if parent_asin not in products:
                counters["product_missing"] += 1
                continue
            if (candidate.user_id, parent_asin) in excluded_pairs:
                counters["valid_test_pair"] += 1
                continue
            selector.offer(parent_asin, candidate)
    counters["duplicate_review_id"] = selector.duplicate_count
    counters["beyond_cap"] = selector.beyond_cap_count
    selection = build_selection(selector.ranked(), embed_top_n)
    counters["kept"] = len(selection)
    counters["embed_selected"] = sum(1 for sel in selection.values() if sel.embed_rank is not None)
    selected_pairs = {(sel.user_id, sel.parent_asin) for sel in selection.values()}
    logger.info(f"[Transform] reviews pass 1 done: {counters['lines']:,} lines, {len(selection):,} kept")
    return ReviewPassResult(selection, selected_pairs, counters["lines"])


def run_review_pass2(
    reviews_path: Path,
    selection: Mapping[int, SelectedReview],
    train_pairs: AbstractSet[Pair],
    writers: ReviewWriters,
    integrity: IntegrityTracker,
    counters: "Counter[str]",
) -> Set[str]:
    """Reads the selected lines by ascending byte offset and writes review rows and their edges; returns the user IDs."""
    users: Set[str] = set()
    with open(reviews_path, "rb") as handle:
        for offset in sorted(selection):
            handle.seek(offset)
            raw = _parse_json_line(handle.readline())
            if raw is None:
                raise GraphBuildError(f"{reviews_path}: selected line at byte {offset} no longer parses (file changed?)")
            selected = selection[offset]
            in_train = (selected.user_id, selected.parent_asin) in train_pairs
            counters["kept_in_train_split" if in_train else "kept_no_split"] += 1
            if raw.get("timestamp") is None:
                counters["missing_timestamp"] += 1
            if not has_review_text(raw.get("title"), raw.get("text")):
                counters["empty_text"] += 1
            writers.reviews.add(review_node_values(raw, selected, in_train), key=offset)
            writers.about_product.add([selected.review_id, selected.parent_asin], key=offset)
            writers.wrote.add([selected.user_id, selected.review_id], key=offset)
            integrity.add_node("Review", selected.review_id)
            integrity.check_edge("ABOUT_PRODUCT", "Review", selected.review_id, "ParentProduct", selected.parent_asin)
            integrity.check_edge("WROTE", "User", selected.user_id, "Review", selected.review_id)
            users.add(selected.user_id)
    return users


def _writer(out_dir: Optional[Path], name: str, counters: "Counter[str]", presorted: bool = False) -> ImportCsvWriter:
    """Writer for one import file (count-only when out_dir is None)."""
    return ImportCsvWriter(out_dir / name if out_dir is not None else None, HEADERS[name], counters, presorted_key=presorted)


def write_product_side(
    meta: MetaPassResult,
    out_dir: Optional[Path],
    integrity: IntegrityTracker,
    counters: "Counter[str]",
) -> Dict[str, FileStats]:
    """Writes the product, brand, category, attribute and taxon node files and their relationship files (sorted)."""
    products = _writer(out_dir, "nodes_product.csv", counters)
    has_brand = _writer(out_dir, "rels_has_brand.csv", counters)
    belongs = _writer(out_dir, "rels_belongs_to_category.csv", counters)
    has_attr = _writer(out_dir, "rels_has_attribute.csv", counters)
    brands: Set[str] = set()
    categories: Set[str] = set()
    attributes: Dict[str, Tuple[str, str]] = {}
    edges: List[Tuple[str, str, str, str, str]] = []
    for parent_asin in sorted(meta.records):
        record = meta.records[parent_asin]
        products.add(product_csv_values(record.row))
        integrity.add_node("ParentProduct", parent_asin)
        if record.brand is not None:
            brands.add(record.brand)
            has_brand.add([parent_asin, record.brand])
            edges.append(("HAS_BRAND", "ParentProduct", parent_asin, "Brand", record.brand))
        if record.main_category is not None:
            categories.add(record.main_category)
            belongs.add([parent_asin, record.main_category])
            edges.append(("BELONGS_TO_CATEGORY", "ParentProduct", parent_asin, "Category", record.main_category))
        for name, value in record.attributes:
            attr_id = attribute_node_id(name, value)
            attributes[attr_id] = (name, value)
            has_attr.add([parent_asin, attr_id])
            edges.append(("HAS_ATTRIBUTE", "ParentProduct", parent_asin, "Attribute", attr_id))

    brand_nodes = _writer(out_dir, "nodes_brand.csv", counters)
    for name in sorted(brands):
        brand_nodes.add([name])
        integrity.add_node("Brand", name)
    category_nodes = _writer(out_dir, "nodes_category.csv", counters)
    for name in sorted(categories):
        category_nodes.add([name])
        integrity.add_node("Category", name)
    attribute_nodes = _writer(out_dir, "nodes_attribute.csv", counters)
    for attr_id in sorted(attributes):
        name, value = attributes[attr_id]
        attribute_nodes.add([attr_id, name, value])
        integrity.add_node("Attribute", attr_id)

    taxon_nodes = _writer(out_dir, "nodes_taxon.csv", counters)
    for row in meta.taxonomy.nodes():
        taxon_nodes.add([row.taxon_id, row.name, row.path, row.depth, row.product_count, row.direct_product_count])
        integrity.add_node("Taxon", row.taxon_id)
    broader = _writer(out_dir, "rels_broader.csv", counters)
    for child, parent in meta.taxonomy.broader_edges():
        broader.add([child, parent])
        edges.append(("BROADER", "Taxon", child, "Taxon", parent))
    in_taxon = _writer(out_dir, "rels_in_taxon.csv", counters)
    for parent_asin, taxon_id in meta.taxonomy.assignments():
        in_taxon.add([parent_asin, taxon_id])
        edges.append(("IN_TAXON", "ParentProduct", parent_asin, "Taxon", taxon_id))

    for edge in edges:
        integrity.check_edge(*edge)
    writers = {
        "nodes_product.csv": products, "nodes_brand.csv": brand_nodes, "nodes_category.csv": category_nodes,
        "nodes_attribute.csv": attribute_nodes, "nodes_taxon.csv": taxon_nodes, "rels_has_brand.csv": has_brand,
        "rels_belongs_to_category.csv": belongs, "rels_has_attribute.csv": has_attr, "rels_broader.csv": broader,
        "rels_in_taxon.csv": in_taxon,
    }
    return {name: writer.close() for name, writer in writers.items()}


def _now_iso() -> str:
    """Current UTC time, ISO-8601 with Z."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_transform(
    config: TransformConfig,
    git_runner: Optional[GitRunner] = None,
    clock: Optional[Callable[[], float]] = None,
) -> TransformResult:
    """
    Runs the full transform. Raises GraphBuildError (InputVerificationError, CleanTreeError,
    LineageInvariantError) or TaxonIdCollisionError; no output file exists when input verification
    fails (AC-018). In dry-run mode no file is written at all (AC-020).
    """
    tick = clock or time.monotonic
    created_at = _now_iso()
    if config.require_clean:
        git = require_clean_tree(config.repo_root, git_runner)
    else:
        git = collect_git_provenance(Path(config.repo_root), CLEAN_TREE_SCOPE, git_runner)
        if git.get("git_dirty"):
            logger.warning(f"[Transform] src/ or scripts/ are dirty: {git.get('git_dirty_paths')}; the lineage records git_dirty=true")

    meta_source, reviews_source = verify_raw_inputs(config.meta_path, config.reviews_path, config.sha256sums_path)
    splits = hash_splits(config.splits_dir)
    catalogue_list, catalogue_sha = read_catalogue(config.catalogue_path)
    catalogue = {asin for asin in catalogue_list if in_sample(asin, config.sample_mod)}
    paths = split_paths(config.splits_dir)
    excluded = load_pair_set([paths["valid"], paths["test"]])
    logger.info(f"[Transform] catalogue {len(catalogue_list):,} ASINs ({len(catalogue):,} in scope), {len(excluded):,} valid/test pairs")

    out_dir = None if config.dry_run else Path(config.out_dir)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    meta_counts: "Counter[str]" = Counter()
    review_counts: "Counter[str]" = Counter()
    sanitized: "Counter[str]" = Counter()
    integrity = IntegrityTracker()
    timing: Dict[str, float] = {}

    start = tick()
    meta = run_meta_pass(config.meta_path, catalogue, meta_counts)
    timing["meta"] = tick() - start

    start = tick()
    outputs = write_product_side(meta, out_dir, integrity, sanitized)
    timing["write"] = tick() - start

    # NFR-002: the product payloads (text, details, features) are written; keep only what the review
    # passes and the lineage still need, and release the records before the review passes.
    product_ids = set(meta.records)
    case_groups = brand_case_groups({r.brand for r in meta.records.values() if r.brand is not None})
    meta.records.clear()

    start = tick()
    pass1 = run_review_pass1(
        config.reviews_path, catalogue, product_ids, excluded, config.review_cap, config.embed_top_n, review_counts,
    )
    timing["pass1_reviews"] = tick() - start
    del excluded  # the valid ∪ test pair set is only needed by pass 1 (NFR-002)

    start = tick()
    train_pairs = mark_train_pairs(paths["train"], pass1.selected_pairs)
    timing["train_mark"] = tick() - start

    start = tick()
    users = sorted({sel.user_id for sel in pass1.selection.values()})
    for user_id in users:
        integrity.add_node("User", user_id)
    writers = ReviewWriters(
        reviews=_writer(out_dir, "nodes_review.csv", sanitized, presorted=True),
        about_product=_writer(out_dir, "rels_about_product.csv", sanitized, presorted=True),
        wrote=_writer(out_dir, "rels_wrote.csv", sanitized, presorted=True),
    )
    run_review_pass2(config.reviews_path, pass1.selection, train_pairs, writers, integrity, review_counts)
    outputs["nodes_review.csv"] = writers.reviews.close()
    outputs["rels_about_product.csv"] = writers.about_product.close()
    outputs["rels_wrote.csv"] = writers.wrote.close()
    user_writer = _writer(out_dir, "nodes_user.csv", sanitized)
    for user_id in users:
        user_writer.add([user_id])
    outputs["nodes_user.csv"] = user_writer.close()
    timing["pass2_reviews"] = tick() - start

    meta_source = meta_source.model_copy(update={"lines": meta_counts["lines"]})
    reviews_source = reviews_source.model_copy(update={"lines": review_counts["lines"]})
    taxonomy = meta.taxonomy
    counts = LineageCounts(
        meta=MetaCounts(**{key: meta_counts[key] for key in MetaCounts.model_fields}),
        reviews=ReviewCounts(**{key: review_counts[key] for key in ReviewCounts.model_fields}),
        nodes={label: outputs[name].rows for label, name in NODE_FILES},
        relationships={rel: outputs[name].rows for rel, name in REL_FILES},
        taxonomy=TaxonomyCounts(
            roots=len(taxonomy.roots()), max_depth=taxonomy.max_depth(),
            inner_node_assignments=taxonomy.inner_node_assignments(),
            products_without_taxon_by_main_category=taxonomy.products_without_taxon(),
        ),
        brand_case_duplicate_groups=len(case_groups),
        sanitized=SanitizedCounts(**{key: sanitized[key] for key in SanitizedCounts.model_fields}),
    )
    lineage = Lineage(
        created_at=created_at,
        code=CodeInfo(git_commit=git.get("git_commit"), git_dirty=git.get("git_dirty"), script=SCRIPT_PATH),
        sources=Sources(
            meta=meta_source, reviews=reviews_source, splits=splits,
            catalogue=catalogue_info(
                config.catalogue_path, catalogue_sha, len(catalogue_list),
                len(catalogue) if config.sample_mod is not None else None,
            ),
        ),
        parameters=default_parameters(config.review_cap, config.embed_top_n, config.sample_mod),
        columns=default_columns(),
        counts=counts,
        duplicates=Duplicates(
            parent_asin_conflicting=cap_list(meta.conflicting_duplicates, DUPLICATE_LIST_CAP),
            brand_case_groups=cap_list(case_groups, DUPLICATE_LIST_CAP),
        ),
        outputs={name: outputs[name] for name in sorted(outputs)},
        timing_s={key: round(value, 3) for key, value in timing.items()},
    )
    assert_invariants(lineage, integrity)
    if not config.dry_run:
        sha = write_lineage(lineage, Path(config.lineage_path))
        logger.info(f"[Transform] lineage written to {config.lineage_path} (sha256 {sha})")
    per_product: "Counter[str]" = Counter(sel.parent_asin for sel in pass1.selection.values())
    coverage = {f"ge{n}": sum(1 for count in per_product.values() if count >= n) for n in (1, 5, 20)}
    return TransformResult(
        lineage=lineage, diagnostics=meta.diagnostics, wrote_files=not config.dry_run, products_with_reviews=coverage,
    )
