#!/usr/bin/env python3
"""
Graph v2 pre-flight measurements P-01 … P-10 (Technical Specification Graph Rebuild FR-001, §6.2).

Read-only on the raw files, the split CSVs and the running v1 graph. The coverage and funnel
counts come from `transform.run_transform(dry_run=True)` so pre-flight and build share one code
path. Writes graph_versions/v2/preflight_report.json (`PreflightReport`), which the user reviews at
CP-1 before build_params.json is written.

    P-01 meta coverage (+ details key histogram, attribute/Brand key counts)   dry run
    P-02 review funnel (+ distinct users, products with >= 1 / 5 / 20 reviews) dry run
    P-03 top-5 embed scope                                                     dry run
    P-04 embedding throughput on 10,000 texts at several batch sizes           SentenceTransformer
    P-05 taxonomy shape and collision check                                    dry run
    P-06 brand case-duplicate groups, ISBN-like count                           dry run
    P-07 environment: Docker VM memory, free disk, v1 volume, effective v1 settings   CommandRunner + Cypher
    P-08 v1 counts                                                             read-only Cypher
    P-09 template conformance against stored v1 vectors                        read-only Cypher + SentenceTransformer
    P-10 wall-clock per dry-run pass, dry-run peak RSS                         timers

Error isolation: every section is measured inside its own try/except. A failed section is stored as
{"error": "<type>: <message>"} and listed in `failed_sections`, the remaining sections still run, and
the report is always written (exit 0, with a WARNING naming the failed sections; the user judges them
at CP-1). Only input errors of the dry run (hash mismatch, missing catalogue or split, taxon_id
collision) exit 2 without a report.

Embedding on Apple silicon (P-04, P-09): --embed-device {auto,cpu,mps} picks the device. The dry-run
data is released before the model loads, max_seq_length is capped at 256 word pieces, the MPS cache
is emptied between batch sizes, and a batch size that runs out of device memory is retried once at
half size and then recorded as an error for that size. P-09 encodes through
`embedding_runtime.ResilientEmbedder` (halve on out-of-memory, then CPU).

Exit codes: 0 report written; 2 input error.

Usage:
    python scripts/graph_ingestion/preflight_v2.py --out graph_versions/v2/preflight_report.json
        [--throughput-texts 10000] [--throughput-batch-sizes 32 128] [--embed-device auto|cpu|mps]
        [--skip-v1] [--skip-docker]
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import gc
import json
import logging
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
from neo4j.exceptions import DriverError, Neo4jError  # noqa: E402

from src.evaluation.provenance import collect_git_provenance  # noqa: E402
from src.knowledge_graph.graph_v2.graph_queries import collect_graph_snapshot  # noqa: E402
from src.knowledge_graph.graph_v2.embedding_runtime import (  # noqa: E402
    DEFAULT_EMBED_BATCH_SIZE,
    DEVICE_CHOICES,
    ResilientEmbedder,
    device_of,
    empty_device_cache,
    ensure_max_seq_length,
    is_out_of_memory,
    load_model,
)
from src.knowledge_graph.graph_v2.import_command import CommandRunner, build_du_command, default_command_runner  # noqa: E402
from src.knowledge_graph.graph_v2.lineage import GraphBuildError, read_catalogue  # noqa: E402
from src.knowledge_graph.graph_v2.models import PreflightReport  # noqa: E402
from src.knowledge_graph.graph_v2.product_mapping import (  # noqa: E402
    clean_features,
    description_text,
    extract_attributes,
    non_blank_string,
)
from src.knowledge_graph.graph_v2.taxonomy import TaxonIdCollisionError  # noqa: E402
from src.knowledge_graph.graph_v2.transform import TransformConfig, TransformResult, run_transform  # noqa: E402
from src.knowledge_graph.graph_v2.validation import seeded_sample  # noqa: E402
from src.knowledge_graph.graphdb.embedding_templates import (  # noqa: E402
    attribute_pair_v1,
    category_parent_text_legacy,
    category_text_v1,
    product_text_v1,
    review_text_v1,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("preflight_v2")

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
DEFAULT_OUT = REPO_ROOT / "graph_versions" / "v2" / "preflight_report.json"
DEFAULT_META = REPO_ROOT / "datasets" / "raw" / "meta_Electronics.jsonl"
DEFAULT_REVIEWS = REPO_ROOT / "datasets" / "raw" / "Electronics.jsonl"
DEFAULT_SHA256SUMS = REPO_ROOT / "datasets" / "raw" / "SHA256SUMS"
DEFAULT_SPLITS_DIR = REPO_ROOT / "datasets"
DEFAULT_CATALOGUE = REPO_ROOT / "graph_versions" / "v2" / "catalogue_asins.txt.gz"
DEFAULT_THROUGHPUT_TEXTS = 10_000
DEFAULT_BATCH_SIZES = (32, 128)
# Errors a measurement section records instead of aborting the run (specific families, no bare except)
SECTION_ERRORS = (
    RuntimeError, OSError, ValueError, LookupError, TypeError, AttributeError, ArithmeticError, ImportError,
    MemoryError, Neo4jError, DriverError,
)
DRY_RUN_SECTIONS = ("p01", "p02", "p03", "p05", "p06", "p10")
SECTION_FIELDS: Dict[str, str] = {
    "p01": "p01_meta_coverage", "p02": "p02_review_funnel", "p03": "p03_embed_scope", "p04": "p04_throughput",
    "p05": "p05_taxonomy", "p06": "p06_brand_isbn", "p07": "p07_environment", "p08": "p08_v1_snapshot",
    "p09": "p09_template_conformance", "p10": "p10_timing",
}
P09_PRODUCT_SAMPLE = 20
P09_SEED = 20261019
P09_MIN_COSINE = 0.999
V1_CONTAINER_NAME = "neo4j-recommendation"
V1_SETTINGS = (
    "server.memory.heap.max_size", "server.memory.heap.initial_size", "server.memory.pagecache.size",
    "db.transaction.timeout", "dbms.transaction.timeout", "db.tx_log.rotation.retention_policy",
)

SessionFactory = Callable[[], ContextManager[Any]]


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of §4.1.7 (input paths default to the repository layout)."""
    parser = argparse.ArgumentParser(description="Read-only pre-flight measurements for the graph v2 build.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--sha256sums", type=Path, default=DEFAULT_SHA256SUMS)
    parser.add_argument("--splits-dir", type=Path, default=DEFAULT_SPLITS_DIR)
    parser.add_argument("--catalogue", type=Path, default=DEFAULT_CATALOGUE)
    parser.add_argument("--throughput-texts", type=int, default=DEFAULT_THROUGHPUT_TEXTS)
    parser.add_argument("--throughput-batch-sizes", type=int, nargs="+", default=list(DEFAULT_BATCH_SIZES))
    parser.add_argument("--embed-device", choices=DEVICE_CHOICES, default="auto",
                        help="SentenceTransformer device for P-04 and P-09 (auto picks MPS on Apple silicon)")
    parser.add_argument("--skip-v1", action="store_true", help="Skip P-07 Cypher settings, P-08 and P-09")
    parser.add_argument("--skip-docker", action="store_true", help="Skip the Docker parts of P-07")
    return parser


def peak_rss_bytes() -> Optional[int]:
    """Peak resident set size of this process so far (NFR-002 evidence); None where `resource` is unavailable."""
    try:
        import resource
    except ImportError:
        return None
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024  # macOS reports bytes, Linux kilobytes


def run_dry_transform(config: TransformConfig) -> TransformResult:
    """P-01/P-02/P-03/P-05/P-06/P-10 source: transform.run_transform with dry_run=True."""
    return run_transform(dataclasses.replace(config, dry_run=True, require_clean=False))


def sample_throughput_texts(config: TransformConfig, n: int) -> List[str]:
    """n/2 product_text_v1 and n/2 review_text_v1 texts built from the first in-scope raw records (deterministic)."""
    catalogue, _ = read_catalogue(config.catalogue_path)
    in_scope = set(catalogue)
    half = max(n // 2, 1)
    products: List[str] = []
    with open(config.meta_path, "rb") as handle:
        for line in handle:
            if len(products) >= half:
                break
            try:
                raw = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(raw, dict) or raw.get("parent_asin") not in in_scope:
                continue
            pairs = [attribute_pair_v1(name, value) for name, value in extract_attributes(raw.get("details"), Counter())]
            text = product_text_v1(
                non_blank_string(raw.get("title")), non_blank_string(raw.get("main_category")), pairs,
                description_text(raw.get("description")), clean_features(raw.get("features")),
            )
            if text is not None:
                products.append(text)
    reviews: List[str] = []
    with open(config.reviews_path, "rb") as handle:
        for line in handle:
            if len(reviews) >= half:
                break
            try:
                raw = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(raw, dict) and raw.get("parent_asin") in in_scope:
                text = review_text_v1(raw.get("title"), raw.get("text"))
                if text is not None:
                    reviews.append(text)
    return products + reviews


def _error(exc: BaseException) -> Dict[str, Any]:
    """Section payload for a failed measurement."""
    return {"error": f"{type(exc).__name__}: {exc}"}


def _time_encode(model: Any, texts: Sequence[str], batch_size: int, device: str) -> float:
    """Seconds for one model.encode pass over `texts` on `device`."""
    started = time.perf_counter()
    model.encode(list(texts), batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False, device=device)
    return time.perf_counter() - started


def _measure_batch_size(model: Any, texts: Sequence[str], batch_size: int, device: str) -> Dict[str, Any]:
    """One batch size: texts/s, or after an out-of-memory error one retry at half size, or the error."""
    try:
        elapsed = _time_encode(model, texts, batch_size, device)
        return {"batch_size": batch_size, "texts_per_s": round(len(texts) / elapsed, 2) if elapsed > 0 else 0.0}
    except RuntimeError as first:
        if not is_out_of_memory(first):
            raise
        empty_device_cache(device)
        half = max(1, batch_size // 2)
        logger.warning(f"[P-04] out of memory on {device} at batch size {batch_size}; retrying once at {half}")
        try:
            elapsed = _time_encode(model, texts, half, device)
        except RuntimeError as second:
            if not is_out_of_memory(second):
                raise
            empty_device_cache(device)
            logger.error(f"[P-04] out of memory on {device} again at batch size {half}; recording the error for {batch_size}")
            return {"batch_size": batch_size, "retried_at": half, **_error(second), "first_error": f"{type(first).__name__}: {first}"}
        return {"batch_size": half, "requested_batch_size": batch_size, "retried_after_oom": True,
                "first_error": f"{type(first).__name__}: {first}", "texts_per_s": round(len(texts) / elapsed, 2) if elapsed > 0 else 0.0}


def measure_throughput(model: Any, texts: Sequence[str], batch_sizes: Sequence[int], label_counts: Optional[Dict[str, int]],
                       device: Optional[str] = None) -> Dict[str, Any]:
    """P-04: device actually used, max_seq_length, per batch size texts/s (or its error), extrapolated minutes per label.
    Raises RuntimeError when no batch size completed (the section is then recorded as failed)."""
    device = device or device_of(model)
    max_seq_length = ensure_max_seq_length(model)
    per_size: Dict[str, Dict[str, Any]] = {}
    for batch_size in batch_sizes:
        per_size[str(batch_size)] = _measure_batch_size(model, texts, batch_size, device)
        empty_device_cache(device)
    rates = {size: entry["texts_per_s"] for size, entry in per_size.items() if "texts_per_s" in entry}
    if not rates:
        raise RuntimeError(f"no batch size completed on {device}: {per_size}")
    best_size, best_rate = max(rates.items(), key=lambda item: item[1])
    return {
        "device": device,
        "max_seq_length": max_seq_length,
        "texts": len(texts),
        "batch_sizes": per_size,
        "texts_per_s": rates,
        "best_batch_size": int(per_size[best_size]["batch_size"]),
        "minutes_per_label": {
            label: round(count / best_rate / 60.0, 1) if best_rate else None for label, count in (label_counts or {}).items()
        },
    }


def _docker_environment(runner: CommandRunner) -> Dict[str, Any]:
    """Docker VM memory, the v1 data volume (from the v1 container mounts) and its size."""
    env: Dict[str, Any] = {}
    code, out = runner(["docker", "info", "--format", "{{.MemTotal}}"])
    env["docker_vm_memory_bytes"] = int(out.strip()) if code == 0 and out.strip().isdigit() else None
    code, out = runner(["docker", "inspect", V1_CONTAINER_NAME, "--format", "{{json .Mounts}}"])
    volume = None
    if code == 0 and out.strip():
        mounts = json.loads(out)
        volume = next((m.get("Name") for m in mounts if m.get("Destination") == "/data"), None)
    env["v1_data_volume"] = volume
    if volume:
        code, out = runner(build_du_command(volume))
        env["v1_data_volume_kb"] = int(out.split()[0]) if code == 0 and out.strip() else None
    return env


def collect_environment(runner: Optional[CommandRunner], session_factory: Optional[SessionFactory], repo_root: Path) -> Dict[str, Any]:
    """P-07: docker info memory, free host disk, v1 data volume name and size, effective v1 settings (dbms.listConfig)."""
    env: Dict[str, Any] = {"free_disk_bytes": shutil.disk_usage(repo_root).free}
    if runner is not None:
        try:
            env.update(_docker_environment(runner))
        except (ValueError, json.JSONDecodeError) as e:
            env["docker_error"] = str(e)
    if session_factory is not None:
        try:
            with session_factory() as session:
                env["v1_settings"] = {
                    record["name"]: record["value"]
                    for record in session.run(
                        "CALL dbms.listConfig() YIELD name, value WHERE name IN $names RETURN name, value",
                        names=list(V1_SETTINGS),
                    )
                }
        except Exception as e:
            env["v1_settings_error"] = str(e)
    return env


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors."""
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denominator = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / denominator) if denominator else 0.0


def template_conformance(session_factory: SessionFactory, embedder: Any) -> Dict[str, Any]:
    """P-09: cosine of rebuilt v1 texts (20 seeded titled products with <= 1 attribute, all categories in both forms) vs stored vectors."""
    with session_factory() as session:
        asins = [record["asin"] for record in session.run(
            "MATCH (p:ParentProduct) WHERE p.title IS NOT NULL AND trim(p.title) <> '' AND p.embedding IS NOT NULL "
            "AND COUNT { (p)-[:HAS_ATTRIBUTE]->() } <= 1 RETURN p.parent_asin AS asin ORDER BY asin LIMIT 5000"
        )]
        products = []
        for asin in seeded_sample(asins, P09_PRODUCT_SAMPLE, P09_SEED):
            record = session.run(
                "MATCH (p:ParentProduct {parent_asin: $asin}) OPTIONAL MATCH (p)-[:BELONGS_TO_CATEGORY]->(c:Category) "
                "WITH p, min(c.name) AS category OPTIONAL MATCH (p)-[:HAS_ATTRIBUTE]->(a:Attribute) "
                "WITH p, category, collect(a.attribute_name + ': ' + coalesce(a.attribute_value, a.normalized_value, '')) AS pairs "
                "RETURN p.title AS title, p.description AS description, category, pairs, p.embedding AS e", asin=asin,
            ).single()
            text = product_text_v1(record["title"], record["category"], record["pairs"] or [], record["description"], None)
            products.append((asin, text, record["e"]))
        categories = [dict(record) for record in session.run(
            "MATCH (c:Category) WHERE c.embedding IS NOT NULL "
            "OPTIONAL MATCH (c)-[:CHILD_OF]->(parent:Category) "
            "OPTIONAL MATCH (p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(c) WHERE p.title IS NOT NULL AND trim(p.title) <> '' "
            "WITH c, min(parent.name) AS parent_name, p ORDER BY coalesce(p.review_count, 0) DESC, p.parent_asin ASC "
            "WITH c, parent_name, collect(p.title)[..5] AS samples "
            "RETURN c.name AS name, c.path AS path, parent_name, samples, c.embedding AS e ORDER BY name"
        )]
    product_vectors = embedder.embed_documents([text for _, text, _ in products]) if products else []
    product_scores = {asin: round(_cosine(vec, stored), 6) for (asin, _, stored), vec in zip(products, product_vectors)}
    forms = {
        "category_v1": [category_text_v1(c["name"] or "", c["path"] or [], c["samples"] or []) for c in categories],
        "category_parent_legacy": [category_parent_text_legacy(c["name"], c["parent_name"]) for c in categories],
    }
    category_scores: Dict[str, Dict[str, float]] = {}
    for form, texts in forms.items():
        vectors = embedder.embed_documents(texts) if texts else []
        category_scores[form] = {c["name"]: round(_cosine(v, c["e"]), 6) for c, v in zip(categories, vectors)}

    def _summary(scores: Mapping[str, float]) -> Dict[str, Any]:
        values = list(scores.values())
        return {"n": len(values), "min": min(values, default=None), "mean": round(sum(values) / len(values), 6) if values else None,
                "share_ge_threshold": round(sum(v >= P09_MIN_COSINE for v in values) / len(values), 4) if values else None}

    return {
        "threshold": P09_MIN_COSINE,
        "product_v1": {"summary": _summary(product_scores), "scores": product_scores},
        **{form: {"summary": _summary(scores), "scores": scores} for form, scores in category_scores.items()},
    }


def dry_run_sections(result: TransformResult) -> Dict[str, Dict[str, Any]]:
    """P-01, P-02, P-03, P-05, P-06 and the P-10 timing part from the dry-run lineage."""
    lineage = result.lineage
    counts = lineage.counts
    return {
        "p01": {
            **counts.meta.model_dump(), "details_key_histogram": result.diagnostics.details_key_histogram,
            "attribute_key_counts": result.diagnostics.attribute_key_counts,
            "sanitized": counts.sanitized.model_dump(), "parent_asin_conflicting": lineage.duplicates.parent_asin_conflicting,
        },
        "p02": {
            **counts.reviews.model_dump(), "distinct_users": counts.nodes.get("User", 0),
            "products_with_reviews": result.products_with_reviews, "reference_kept_measured": 3388842,
        },
        "p03": {"embed_selected": counts.reviews.embed_selected, "empty_text": counts.reviews.empty_text},
        "p05": {**counts.taxonomy.model_dump(), "nodes": counts.nodes.get("Taxon", 0),
                "broader_edges": counts.relationships.get("BROADER", 0), "collision": False},
        "p06": {
            "brand_case_duplicate_groups": counts.brand_case_duplicate_groups,
            "brand_case_groups": lineage.duplicates.brand_case_groups,
            "isbn_like_count": len(result.diagnostics.isbn_like_asins), "isbn_like": result.diagnostics.isbn_like_asins,
        },
        "p10": {"timing_s": lineage.timing_s, "lines": {"meta": counts.meta.lines, "reviews": counts.reviews.lines}},
    }


def embedding_label_counts(result: TransformResult) -> Dict[str, int]:
    """Texts to embed per label (P-04 extrapolation)."""
    counts = result.lineage.counts
    return {
        "ParentProduct": counts.meta.products_written - counts.meta.content_empty,
        "Review": counts.reviews.embed_selected,
        "Brand": counts.nodes.get("Brand", 0), "Category": counts.nodes.get("Category", 0),
        "Attribute": counts.nodes.get("Attribute", 0),
    }


def assemble_report(sections: Mapping[str, Dict[str, Any]], failed: Sequence[str], git_commit: Optional[str], created_at: str) -> PreflightReport:
    """Maps the measured (or failed) sections to P-01 … P-10; sections never measured are {"skipped": True}."""
    return PreflightReport(
        created_at=created_at, git_commit=git_commit, failed_sections=list(failed),
        **{field: dict(sections.get(key, {"skipped": True})) for key, field in SECTION_FIELDS.items()},
    )


def run_section(name: str, sections: Dict[str, Dict[str, Any]], failed: List[str], measure: Callable[[], Dict[str, Any]]) -> None:
    """Runs one measurement; a SECTION_ERRORS exception is recorded as the section's error and does not stop the run."""
    try:
        sections[name] = measure()
    except SECTION_ERRORS as e:
        logger.error(f"[{name.upper()}] measurement failed: {type(e).__name__}: {e}")
        sections[name] = _error(e)
        failed.append(name)


class _ModelHolder:
    """Loads the embedding model once, on first use; a load error is remembered and re-raised for every later section."""

    def __init__(self, device_choice: str, model: Optional[Any] = None) -> None:
        self.device_choice = device_choice
        self._model = model
        self._error: Optional[BaseException] = None

    def get(self) -> Any:
        if self._model is None:
            if self._error is not None:
                raise self._error
            try:
                self._model = load_model(self.device_choice)
            except SECTION_ERRORS as e:
                self._error = e
                raise
        return self._model


def write_report(report: PreflightReport, path: Path) -> None:
    """Writes the report JSON (indented, UTF-8, trailing newline)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(
    argv: Optional[Sequence[str]] = None,
    session_factory: Optional[SessionFactory] = None,
    runner: Optional[CommandRunner] = None,
    model: Optional[Any] = None,
    dry_run: Optional[Callable[[TransformConfig], TransformResult]] = None,
) -> int:
    """CLI entry point; returns 0 when the report is written (even with failed sections), 2 on a dry-run input error.
    `model` (a SentenceTransformer-like object) and `dry_run` are injectable for tests."""
    args = build_parser().parse_args(argv)
    config = TransformConfig(
        meta_path=args.meta, reviews_path=args.reviews, sha256sums_path=args.sha256sums, splits_dir=args.splits_dir,
        catalogue_path=args.catalogue, out_dir=REPO_ROOT / "datasets" / "graph_build" / "preflight_unused",
        lineage_path=REPO_ROOT / "datasets" / "graph_build" / "preflight_unused" / "lineage.json",
        dry_run=True, repo_root=REPO_ROOT,
    )
    sections: Dict[str, Dict[str, Any]] = {}
    failed: List[str] = []
    label_counts: Optional[Dict[str, int]] = None
    try:
        result = (dry_run or run_dry_transform)(config)
    except (GraphBuildError, TaxonIdCollisionError) as e:
        logger.error(f"Pre-flight dry run failed on its inputs: {e}")
        return EXIT_INPUT_ERROR
    except SECTION_ERRORS as e:
        logger.error(f"Pre-flight dry run failed: {type(e).__name__}: {e}")
        for name in DRY_RUN_SECTIONS:
            sections[name] = _error(e)
        failed.extend(DRY_RUN_SECTIONS)
    else:
        sections.update(dry_run_sections(result))
        label_counts = embedding_label_counts(result)
        # Release the dry-run data before the embedding model loads (the 16 GB host shares memory with MPS)
        del result
        gc.collect()
    if "p10" in sections and "error" not in sections["p10"]:
        # Measured before the embedding model is loaded, so it reflects the transform passes (NFR-002)
        sections["p10"]["dry_run_peak_rss_bytes"] = peak_rss_bytes()

    holder = _ModelHolder(args.embed_device, model)

    def _p04() -> Dict[str, Any]:
        texts = sample_throughput_texts(config, args.throughput_texts)
        loaded = holder.get()
        return measure_throughput(loaded, texts, args.throughput_batch_sizes, label_counts)

    run_section("p04", sections, failed, _p04)

    owned = None
    connect_error: Optional[BaseException] = None
    if not args.skip_v1 and session_factory is None:
        from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

        try:
            owned = Neo4jConnector()
            owned.connect()
            session_factory = owned.session
        except SECTION_ERRORS as e:
            logger.error(f"Cannot connect to v1 Neo4j: {type(e).__name__}: {e}")
            connect_error = e
            session_factory = None
    try:
        docker_runner = None if args.skip_docker else (runner or default_command_runner())
        env_session = None if args.skip_v1 else session_factory
        run_section("p07", sections, failed, lambda: {
            **collect_environment(docker_runner, env_session, REPO_ROOT),
            **({"v1_settings_error": f"{type(connect_error).__name__}: {connect_error}"} if connect_error else {}),
        })
        if not args.skip_v1:
            def _require_session() -> SessionFactory:
                if session_factory is None:
                    raise connect_error or RuntimeError("no v1 Neo4j session")
                return session_factory

            def _p08() -> Dict[str, Any]:
                with _require_session()() as session:
                    return collect_graph_snapshot(session)

            run_section("p08", sections, failed, _p08)

            def _p09() -> Dict[str, Any]:
                factory = _require_session()
                loaded = holder.get()
                empty_device_cache(device_of(loaded))
                return template_conformance(factory, ResilientEmbedder(loaded, batch_size=DEFAULT_EMBED_BATCH_SIZE))

            run_section("p09", sections, failed, _p09)
    finally:
        if owned is not None:
            owned.close()

    git = collect_git_provenance(REPO_ROOT)
    report = assemble_report(sections, failed, git.get("git_commit"), datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    write_report(report, args.out)
    if failed:
        logger.warning(f"Pre-flight report written to {args.out} with FAILED sections {failed}; review them at CP-1")
    else:
        logger.info(f"Pre-flight report written to {args.out}; review it at CP-1 before writing build_params.json")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
