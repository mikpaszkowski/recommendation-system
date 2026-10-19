#!/usr/bin/env python3
"""
Graph v2 post-import online steps (Technical Specification Graph Rebuild FR-021 … FR-025, FR-027).

Sub-commands (all take --lineage; each first runs the wrong-graph guard FR-021: the product count
must equal lineage.counts.meta.products_written, the Taxon count must equal the lineage Taxon count
(v2-only signature) and no (:GraphVersion) node may exist):
    constraints     the 8 uniqueness constraints of §5.1.4 (IF NOT EXISTS)
    embed           v1-template embeddings, keyset-paginated and resumable (FR-023)
    vector-indexes  5 vector indexes via setup_indexes (5.14 procedure form, no DDL), then db.awaitIndexes
    fulltext-index  product_fulltext_index + smoke test, features_text fallback (FR-025)
    all             constraints -> embed -> vector-indexes -> fulltext-index
    stamp           (:GraphVersion) after the validation gate passed and the user approved it at CP-8 (FR-027)

Exit codes: 0 success; 1 step failure (e.g. index creation or smoke test failed after fallback);
2 guard refused or input error.

Usage:
    post_import_v2.py constraints --lineage graph_versions/v2/lineage.json
    post_import_v2.py embed --lineage … --build-params graph_versions/v2/build_params.json
        [--labels Attribute Brand …] [--batch-size 256] [--report graph_versions/v2/embedding_report.json]
        [--embed-device auto|cpu|mps] [--embed-batch-size 32]
    post_import_v2.py vector-indexes --lineage … [--await-timeout 7200]
    post_import_v2.py fulltext-index --lineage … [--seed 20261019]
    post_import_v2.py all --lineage … --build-params … [--embed-device …] [--embed-batch-size …]

Embedding (FR-023) encodes in batches of --embed-batch-size. On a device out-of-memory error the
batch is halved down to 8 and then that chunk is encoded on the CPU (see graph_v2.embedding_runtime);
pages already written stay written, and the report is rewritten after every label.
    post_import_v2.py stamp --lineage … --validation-report graph_versions/v2/validation_report.json
        --build-params … --embedding-report … --confirm-validation-sha256 <sha256 reviewed at CP-8>
"""
from __future__ import annotations

import argparse
import datetime
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, List, Mapping, NamedTuple, Optional, Protocol, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from src.evaluation.provenance import GitRunner, default_git_runner  # noqa: E402
from src.knowledge_graph.graph_v2.embedding_runtime import (  # noqa: E402
    DEFAULT_EMBED_BATCH_SIZE,
    DEVICE_CHOICES,
    DeviceUnavailableError,
    ResilientEmbedder,
    load_model,
)
from src.knowledge_graph.graph_v2.lineage import InputVerificationError, load_lineage, sha256_file  # noqa: E402
from src.knowledge_graph.graph_v2.models import (  # noqa: E402
    BuildParams,
    EmbeddingReport,
    GraphVersionProps,
    LabelEmbeddingStats,
    Lineage,
    ValidationReport,
)
from src.knowledge_graph.graph_v2.validation import FULLTEXT_SMOKE_LIMIT, pick_smoke_token  # noqa: E402
from src.knowledge_graph.graphdb.embedding_templates import (  # noqa: E402
    TEMPLATE_IDS,
    brand_text_v1,
    category_text_v1,
    product_text_v1,
    review_text_v1,
)
from src.knowledge_graph.graphdb.embedding_templates import attribute_text_v1  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("post_import_v2")

EXIT_OK = 0
EXIT_STEP_FAILED = 1
EXIT_GUARD = 2
GUARD_MESSAGE = "connected graph does not match lineage or is sealed"
DEFAULT_LINEAGE = REPO_ROOT / "graph_versions" / "v2" / "lineage.json"
DEFAULT_BUILD_PARAMS = REPO_ROOT / "graph_versions" / "v2" / "build_params.json"
DEFAULT_EMBEDDING_REPORT = REPO_ROOT / "graph_versions" / "v2" / "embedding_report.json"
DEFAULT_VALIDATION_REPORT = REPO_ROOT / "graph_versions" / "v2" / "validation_report.json"
DEFAULT_BATCH_SIZE = 256
DEFAULT_AWAIT_TIMEOUT_S = 7200
DEFAULT_SEED = 20261019
SKIPPED_KEYS_SAMPLE_CAP = 50

CONSTRAINT_STATEMENTS: Tuple[str, ...] = (
    "CREATE CONSTRAINT product_id IF NOT EXISTS FOR (p:ParentProduct) REQUIRE p.parent_asin IS UNIQUE",
    "CREATE CONSTRAINT review_id IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE",
    "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE",
    "CREATE CONSTRAINT brand_id IF NOT EXISTS FOR (b:Brand) REQUIRE b.name IS UNIQUE",
    "CREATE CONSTRAINT category_id IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT taxon_id IF NOT EXISTS FOR (t:Taxon) REQUIRE t.taxon_id IS UNIQUE",
    "CREATE CONSTRAINT attribute_key IF NOT EXISTS FOR (a:Attribute) REQUIRE (a.attribute_name, a.attribute_value) IS UNIQUE",
    "CREATE CONSTRAINT graph_version_id IF NOT EXISTS FOR (g:GraphVersion) REQUIRE g.version IS UNIQUE",
)
EMBED_LABEL_ORDER: Tuple[str, ...] = ("Attribute", "Brand", "Category", "ParentProduct", "Review")
FULLTEXT_INDEX_NAME = "product_fulltext_index"
FULLTEXT_FIELDS: Tuple[str, ...] = ("title", "description", "features", "details_text")
FULLTEXT_FALLBACK_FIELDS: Tuple[str, ...] = ("title", "description", "features_text", "details_text")
GUARD_PRODUCT_COUNT_QUERY = "MATCH (p:ParentProduct) RETURN count(p) AS n"
GUARD_GRAPH_VERSION_QUERY = "MATCH (g:GraphVersion) RETURN count(g) AS n"
GUARD_TAXON_COUNT_QUERY = "MATCH (t:Taxon) RETURN count(t) AS n"
SMOKE_CANDIDATE_LIMIT = 2000
SMOKE_CANDIDATES_QUERY = (
    "MATCH (p:ParentProduct) WHERE p.features IS NOT NULL "
    "RETURN p.parent_asin AS parent_asin, p.title AS title, p.description AS description, "
    "p.features AS features, p.details_text AS details_text ORDER BY p.parent_asin LIMIT $limit"
)
SMOKE_QUERY = (
    "CALL db.index.fulltext.queryNodes($index, $token) YIELD node, score "
    "RETURN node.parent_asin AS parent_asin LIMIT $limit"
)
FEATURES_TEXT_QUERY = (
    "MATCH (p:ParentProduct) WHERE p.features IS NOT NULL "
    "CALL { WITH p SET p.features_text = reduce(s = '', f IN p.features | "
    "CASE WHEN s = '' THEN f ELSE s + '\\n' + f END) } IN TRANSACTIONS OF 10000 ROWS"
)
DROP_FULLTEXT_QUERY = "DROP INDEX product_fulltext_index IF EXISTS"
AWAIT_INDEX_QUERY = "CALL db.awaitIndex($name, $timeout)"
AWAIT_INDEXES_QUERY = "CALL db.awaitIndexes($timeout)"
FULLTEXT_PROPERTIES_QUERY = "SHOW INDEXES YIELD name, properties WHERE name = $name RETURN properties"
STAMP_QUERY = "CREATE (g:GraphVersion $props)"
STAMP_COUNT_QUERIES: Dict[str, str] = {
    "ParentProduct": "MATCH (n:ParentProduct) RETURN count(n) AS n",
    "Review": "MATCH (n:Review) RETURN count(n) AS n",
    "User": "MATCH (n:User) RETURN count(n) AS n",
    "Taxon": "MATCH (n:Taxon) RETURN count(n) AS n",
}
TEMPLATE_ID_ORDER: Tuple[str, ...] = ("ParentProduct", "Review", "Brand", "Attribute", "Category")

SessionFactory = Callable[[], ContextManager[Any]]


class Embedder(Protocol):
    """The subset of EmbeddingService used here (a fake in tests)."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embeds a batch of non-empty texts."""
        ...


class LabelEmbedSpec(NamedTuple):
    """How one label is read, turned into text and written back (FR-023)."""

    label: str
    key_fields: Tuple[str, ...]                          # unique key (Attribute: name, value)
    fetch_query: str                                     # keyset page: WHERE key > $after AND embedding IS NULL ORDER BY key LIMIT $batch
    eligible_query: str                                  # eligible count (Review: embed_rank IS NOT NULL)
    embedded_query: str                                  # embedding IS NOT NULL count within scope
    write_query: str                                     # UNWIND $rows AS row MATCH (n:<Label> {<key>: row.k}) SET n.embedding = row.e
    text_builder: Callable[[Mapping[str, Any]], Optional[str]]


class GuardError(Exception):
    """FR-021 wrong-graph or sealed-graph refusal (exit 2)."""


class StampRefused(Exception):
    """FR-027 precondition not met (exit 2)."""


def build_parser() -> argparse.ArgumentParser:
    """Sub-command parser of §4.1.7 (plus --build-params for embed/all and --confirm-validation-sha256 for stamp)."""
    parser = argparse.ArgumentParser(description="Graph v2 post-import steps: constraints, embeddings, indexes, stamp.")
    sub = parser.add_subparsers(dest="command", required=True)
    parsers = {name: sub.add_parser(name) for name in ("constraints", "embed", "vector-indexes", "fulltext-index", "all", "stamp")}
    for p in parsers.values():
        p.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    for name in ("embed", "all"):
        parsers[name].add_argument("--build-params", type=Path, default=DEFAULT_BUILD_PARAMS)
        parsers[name].add_argument("--labels", nargs="+", choices=EMBED_LABEL_ORDER, default=list(EMBED_LABEL_ORDER))
        parsers[name].add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Neo4j page size (nodes read and written per transaction)")
        parsers[name].add_argument("--embed-device", choices=DEVICE_CHOICES, default="auto",
                                   help="SentenceTransformer device (auto picks MPS on Apple silicon)")
        parsers[name].add_argument("--embed-batch-size", type=int, default=DEFAULT_EMBED_BATCH_SIZE,
                                   help="Texts per model.encode batch; halved automatically on device out-of-memory")
        parsers[name].add_argument("--report", type=Path, default=DEFAULT_EMBEDDING_REPORT)
    for name in ("vector-indexes", "all"):
        parsers[name].add_argument("--await-timeout", type=int, default=DEFAULT_AWAIT_TIMEOUT_S)
    for name in ("fulltext-index", "all"):
        parsers[name].add_argument("--seed", type=int, default=DEFAULT_SEED)
    stamp = parsers["stamp"]
    stamp.add_argument("--validation-report", type=Path, default=DEFAULT_VALIDATION_REPORT)
    stamp.add_argument("--build-params", type=Path, default=DEFAULT_BUILD_PARAMS)
    stamp.add_argument("--embedding-report", type=Path, default=DEFAULT_EMBEDDING_REPORT)
    stamp.add_argument("--confirm-validation-sha256", required=True,
                       help="SHA-256 of the validation report the user approved at CP-8")
    return parser


def _scalar(session: Any, cypher: str, **params: Any) -> int:
    """Single `n` from a count query."""
    record = session.run(cypher, **params).single()
    if record is None:
        raise RuntimeError(f"count query returned no row: {cypher[:80]}")
    return int(record["n"])


def _now() -> str:
    """Current UTC time, ISO-8601 with Z."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_graph_guard(session_factory: SessionFactory, lineage: Lineage) -> None:
    """FR-021: raises GuardError(GUARD_MESSAGE) unless count(:ParentProduct) = products_written, no GraphVersion exists
    and count(:Taxon) = lineage.counts.nodes["Taxon"]. The Taxon check is a v2-only signature: when every catalogue
    ASIN is found in the raw metadata, products_written equals the v1 product count, so the product count alone
    cannot tell v1 (which has no Taxon nodes) from v2 (NFR-004)."""
    with session_factory() as session:
        products = _scalar(session, GUARD_PRODUCT_COUNT_QUERY)
        versions = _scalar(session, GUARD_GRAPH_VERSION_QUERY)
        taxa = _scalar(session, GUARD_TAXON_COUNT_QUERY)
    expected = lineage.counts.meta.products_written
    expected_taxa = lineage.counts.nodes.get("Taxon", 0)
    if products != expected or taxa != expected_taxa or versions > 0:
        raise GuardError(
            f"{GUARD_MESSAGE} (products {products} vs lineage {expected}, Taxon {taxa} vs lineage {expected_taxa}, "
            f"GraphVersion nodes {versions})"
        )


def run_constraints(session_factory: SessionFactory) -> int:
    """Issues exactly CONSTRAINT_STATEMENTS in order (AC-024); a failure is logged with the statement and returns 1."""
    failures: List[str] = []
    with session_factory() as session:
        for statement in CONSTRAINT_STATEMENTS:
            try:
                session.run(statement).consume()
                logger.info(f"Constraint ok: {statement}")
            except Exception as e:
                failures.append(statement)
                hint = " (composite uniqueness: record the attribute_key fallback, H-18)" if "attribute_key" in statement else ""
                logger.error(f"Constraint failed{hint}: {statement}: {e}")
    return EXIT_STEP_FAILED if failures else EXIT_OK


_PRODUCT_CONTENT_CYPHER = {
    "title_description_features": (
        "((n.title IS NOT NULL AND trim(n.title) <> '') OR (n.description IS NOT NULL AND trim(n.description) <> '') "
        "OR any(f IN coalesce(n.features, []) WHERE trim(f) <> ''))"
    ),
    "title_description": (
        "((n.title IS NOT NULL AND trim(n.title) <> '') OR (n.description IS NOT NULL AND trim(n.description) <> ''))"
    ),
}


def label_specs(product_content_rule: str) -> Dict[str, LabelEmbedSpec]:
    """The five LabelEmbedSpec definitions using embedding_templates (product, review, brand, attribute, category_v1)."""
    if product_content_rule not in _PRODUCT_CONTENT_CYPHER:
        raise ValueError(f"unknown product content rule {product_content_rule!r}")
    content = _PRODUCT_CONTENT_CYPHER[product_content_rule]
    return {
        "Attribute": LabelEmbedSpec(
            label="Attribute", key_fields=("attribute_name", "attribute_value"),
            fetch_query=(
                "MATCH (n:Attribute) WHERE n.embedding IS NULL AND "
                "(n.attribute_name > $after0 OR (n.attribute_name = $after0 AND n.attribute_value > $after1)) "
                "RETURN n.attribute_name AS k0, n.attribute_value AS k1, n.attribute_name AS name, n.attribute_value AS value "
                "ORDER BY n.attribute_name, n.attribute_value LIMIT $batch"
            ),
            eligible_query="MATCH (n:Attribute) RETURN count(n) AS n",
            embedded_query="MATCH (n:Attribute) WHERE n.embedding IS NOT NULL RETURN count(n) AS n",
            write_query=(
                "UNWIND $rows AS row MATCH (n:Attribute {attribute_name: row.k0, attribute_value: row.k1}) "
                "SET n.embedding = row.e"
            ),
            text_builder=lambda row: attribute_text_v1(row["name"], row["value"]),
        ),
        "Brand": LabelEmbedSpec(
            label="Brand", key_fields=("name",),
            fetch_query=(
                "MATCH (n:Brand) WHERE n.embedding IS NULL AND n.name > $after0 "
                "RETURN n.name AS k0, n.name AS name ORDER BY n.name LIMIT $batch"
            ),
            eligible_query="MATCH (n:Brand) RETURN count(n) AS n",
            embedded_query="MATCH (n:Brand) WHERE n.embedding IS NOT NULL RETURN count(n) AS n",
            write_query="UNWIND $rows AS row MATCH (n:Brand {name: row.k0}) SET n.embedding = row.e",
            text_builder=lambda row: brand_text_v1(row["name"]),
        ),
        "Category": LabelEmbedSpec(
            label="Category", key_fields=("name",),
            fetch_query=(
                "MATCH (n:Category) WHERE n.embedding IS NULL AND n.name > $after0 "
                "WITH n ORDER BY n.name LIMIT $batch "
                "OPTIONAL MATCH (p:ParentProduct)-[:BELONGS_TO_CATEGORY]->(n) "
                "WHERE p.title IS NOT NULL AND trim(p.title) <> '' "
                "WITH n, p ORDER BY coalesce(p.review_count, 0) DESC, p.parent_asin ASC "
                "WITH n, collect(p.title)[..5] AS samples "
                "RETURN n.name AS k0, n.name AS name, n.path AS path, samples ORDER BY n.name"
            ),
            eligible_query="MATCH (n:Category) RETURN count(n) AS n",
            embedded_query="MATCH (n:Category) WHERE n.embedding IS NOT NULL RETURN count(n) AS n",
            write_query="UNWIND $rows AS row MATCH (n:Category {name: row.k0}) SET n.embedding = row.e",
            text_builder=lambda row: category_text_v1(row["name"], row["path"], row["samples"] or []),
        ),
        "ParentProduct": LabelEmbedSpec(
            label="ParentProduct", key_fields=("parent_asin",),
            fetch_query=(
                "MATCH (n:ParentProduct) WHERE n.embedding IS NULL AND n.parent_asin > $after0 "
                "WITH n ORDER BY n.parent_asin LIMIT $batch "
                "OPTIONAL MATCH (n)-[:BELONGS_TO_CATEGORY]->(c:Category) "
                "WITH n, min(c.name) AS category "
                "OPTIONAL MATCH (n)-[:HAS_ATTRIBUTE]->(a:Attribute) "
                "WITH n, category, a ORDER BY a.attribute_name, a.attribute_value "
                "WITH n, category, collect(a.attribute_name + ': ' + coalesce(a.attribute_value, '')) AS pairs "
                "RETURN n.parent_asin AS k0, n.title AS title, n.description AS description, n.features AS features, "
                "category, pairs ORDER BY n.parent_asin"
            ),
            eligible_query=f"MATCH (n:ParentProduct) WHERE {content} RETURN count(n) AS n",
            embedded_query="MATCH (n:ParentProduct) WHERE n.embedding IS NOT NULL RETURN count(n) AS n",
            write_query="UNWIND $rows AS row MATCH (n:ParentProduct {parent_asin: row.k0}) SET n.embedding = row.e",
            text_builder=lambda row: product_text_v1(
                row["title"], row["category"], row["pairs"] or [], row["description"], row["features"],
                rule=product_content_rule,
            ),
        ),
        "Review": LabelEmbedSpec(
            label="Review", key_fields=("review_id",),
            fetch_query=(
                "MATCH (n:Review) WHERE n.embed_rank IS NOT NULL AND n.embedding IS NULL AND n.review_id > $after0 "
                "RETURN n.review_id AS k0, n.review_title AS title, n.review_body AS body "
                "ORDER BY n.review_id LIMIT $batch"
            ),
            eligible_query="MATCH (n:Review) WHERE n.embed_rank IS NOT NULL RETURN count(n) AS n",
            embedded_query="MATCH (n:Review) WHERE n.embedding IS NOT NULL RETURN count(n) AS n",
            write_query="UNWIND $rows AS row MATCH (n:Review {review_id: row.k0}) SET n.embedding = row.e",
            text_builder=lambda row: review_text_v1(row["title"], row["body"]),
        ),
    }


def embed_label(
    session_factory: SessionFactory,
    embedder: Embedder,
    spec: LabelEmbedSpec,
    batch_size: int,
    clock: Callable[[], float],
) -> LabelEmbeddingStats:
    """Keyset pagination in ascending key order; None texts are counted and never embedded; resumable (AC-023)."""
    started = clock()
    after: Tuple[str, ...] = ("",) * len(spec.key_fields)
    skipped = 0
    skipped_keys: List[str] = []
    embedded_now = 0
    batches = 0
    while True:
        params = {"batch": batch_size, "after0": after[0], "after1": after[1] if len(after) > 1 else ""}
        with session_factory() as session:
            rows = list(session.run(spec.fetch_query, **params))
        if not rows:
            break
        batches += 1
        texts: List[str] = []
        keys: List[Tuple[str, ...]] = []
        for row in rows:
            key = tuple(row[f"k{i}"] for i in range(len(spec.key_fields)))
            text = spec.text_builder(row)
            if text is None or not text.strip():
                skipped += 1
                if len(skipped_keys) < SKIPPED_KEYS_SAMPLE_CAP:
                    skipped_keys.append(" | ".join(str(k) for k in key))
                continue
            texts.append(text)
            keys.append(key)
        after = tuple(rows[-1][f"k{i}"] for i in range(len(spec.key_fields)))
        if texts:
            vectors = embedder.embed_documents(texts)
            if len(vectors) != len(texts):
                raise RuntimeError(f"{spec.label}: embedder returned {len(vectors)} vectors for {len(texts)} texts")
            payload = [
                {**{f"k{i}": key[i] for i in range(len(key))}, "e": [float(x) for x in vector]}
                for key, vector in zip(keys, vectors)
            ]
            with session_factory() as session:
                session.run(spec.write_query, rows=payload).consume()
            embedded_now += len(texts)
        if len(rows) < batch_size:
            break
    with session_factory() as session:
        eligible = _scalar(session, spec.eligible_query)
        embedded = _scalar(session, spec.embedded_query)
    seconds = clock() - started
    logger.info(f"[Embed] {spec.label}: {embedded_now} embedded now, {embedded}/{eligible} in graph, {skipped} skipped (empty)")
    return LabelEmbeddingStats(
        template_id=TEMPLATE_IDS[spec.label], eligible=eligible, embedded=embedded, skipped_empty=skipped,
        skipped_keys_sample=skipped_keys, batches=batches, seconds=round(seconds, 3),
        texts_per_s=round(embedded_now / seconds, 2) if seconds > 0 and embedded_now else None,
    )


def _library_versions(embedder: Any) -> Dict[str, Optional[str]]:
    """sentence-transformers and torch versions and the embedder's device, when available."""
    versions: Dict[str, Optional[str]] = {"sentence_transformers_version": None, "torch_version": None, "device": None}
    try:
        import sentence_transformers
        versions["sentence_transformers_version"] = getattr(sentence_transformers, "__version__", None)
    except ImportError:
        logger.warning("sentence-transformers not importable; version not recorded")
    try:
        import torch
        versions["torch_version"] = getattr(torch, "__version__", None)
    except ImportError:
        logger.warning("torch not importable; version not recorded")
    device = getattr(embedder, "device", None) or getattr(getattr(embedder, "model", None), "device", None)
    versions["device"] = str(device) if device is not None else None
    return versions


def run_embed(
    session_factory: SessionFactory,
    embedder: Embedder,
    labels: Sequence[str],
    batch_size: int,
    build_params: BuildParams,
    report_path: Path,
    clock: Callable[[], float],
) -> EmbeddingReport:
    """Embeds labels in EMBED_LABEL_ORDER, writes embedding_report.json (with library versions and device).
    Labels from an earlier report are kept, so a resumed or per-label run yields one complete report."""
    specs = label_specs(build_params.product_content_rule)
    stats: Dict[str, LabelEmbeddingStats] = {}
    report_path = Path(report_path)
    if report_path.is_file():
        try:
            stats.update(EmbeddingReport.model_validate_json(report_path.read_text(encoding="utf-8")).labels)
        except ValidationError as e:
            logger.warning(f"Ignoring unreadable earlier embedding report {report_path}: {e}")
    report: Optional[EmbeddingReport] = None
    for label in EMBED_LABEL_ORDER:
        if label in labels:
            stats[label] = embed_label(session_factory, embedder, specs[label], batch_size, clock)
            # Written after every label, so an interrupted run keeps the finished labels (the graph keeps every written page)
            report = _write_embedding_report(report_path, embedder, batch_size, stats)
    return report or _write_embedding_report(report_path, embedder, batch_size, stats)


def _write_embedding_report(report_path: Path, embedder: Embedder, batch_size: int,
                            stats: Mapping[str, LabelEmbeddingStats]) -> EmbeddingReport:
    """Writes embedding_report.json with the device and the requested and effective encode batch sizes."""
    report = EmbeddingReport(
        created_at=_now(), batch_size=batch_size,
        labels={label: stats[label] for label in EMBED_LABEL_ORDER if label in stats},
        embed_batch_size=getattr(embedder, "requested_batch_size", None),
        effective_embed_batch_size=getattr(embedder, "batch_size", None),
        oom_events=int(getattr(embedder, "oom_events", 0) or 0),
        cpu_fallback_batches=int(getattr(embedder, "cpu_fallback_batches", 0) or 0),
        **_library_versions(embedder),
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    logger.info(f"Embedding report written to {report_path} (device {report.device}, "
                f"encode batch {report.embed_batch_size} -> {report.effective_embed_batch_size})")
    return report


def neo4j_version_tuple(session_factory: SessionFactory) -> Tuple[int, int, int]:
    """(major, minor, patch) from dbms.components()."""
    with session_factory() as session:
        record = session.run(
            "CALL dbms.components() YIELD name, versions, edition RETURN versions[0] AS version"
        ).single()
    version = str(record["version"]) if record is not None else ""
    parts = [int(x) for x in re.findall(r"\d+", version)[:3]]
    if len(parts) < 2:
        raise RuntimeError(f"cannot parse Neo4j version {version!r}")
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def run_vector_indexes(session_factory: SessionFactory, connector: Any, await_timeout_s: int) -> int:
    """setup_indexes(connector, allow_ddl_fallback = version >= 5.15) for INDEX_SPECS, then CALL db.awaitIndexes (AC-025)."""
    from src.knowledge_graph.graphdb.setup_indexes import setup_indexes

    version = neo4j_version_tuple(session_factory)
    outcomes = setup_indexes(connector, allow_ddl_fallback=version >= (5, 15, 0))
    failed = {name: outcome for name, outcome in outcomes.items() if outcome.startswith("failed")}
    if failed:
        logger.error(f"Vector index creation failed: {failed}")
        return EXIT_STEP_FAILED
    with session_factory() as session:
        session.run(AWAIT_INDEXES_QUERY, timeout=await_timeout_s).consume()
    logger.info(f"Vector indexes ready: {outcomes}")
    return EXIT_OK


def fulltext_create_statement(fields: Sequence[str]) -> str:
    """CREATE FULLTEXT INDEX product_fulltext_index IF NOT EXISTS FOR (p:ParentProduct) ON EACH [...] english analyzer."""
    allowed = set(FULLTEXT_FIELDS) | set(FULLTEXT_FALLBACK_FIELDS)
    if not fields or any(field not in allowed for field in fields):
        raise ValueError(f"unsupported full-text fields: {list(fields)}")
    columns = ", ".join(f"p.{field}" for field in fields)
    return (
        f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX_NAME} IF NOT EXISTS FOR (p:ParentProduct) ON EACH [{columns}] "
        "OPTIONS {indexConfig: {`fulltext.analyzer`: 'english'}}"
    )


def fulltext_smoke_test(session_factory: SessionFactory, seed: int) -> Tuple[bool, Optional[str], Optional[str]]:
    """(found, token, parent_asin): seeded product/token via validation.pick_smoke_token, queried with limit 50."""
    with session_factory() as session:
        products = [dict(record) for record in session.run(SMOKE_CANDIDATES_QUERY, limit=SMOKE_CANDIDATE_LIMIT)]
    choice = pick_smoke_token(products, seed)
    if choice is None:
        logger.error("Full-text smoke test: no product has a features-only token")
        return False, None, None
    parent_asin, token = choice
    with session_factory() as session:
        hits = [record["parent_asin"] for record in session.run(
            SMOKE_QUERY, index=FULLTEXT_INDEX_NAME, token=token, limit=FULLTEXT_SMOKE_LIMIT,
        )]
    found = parent_asin in hits
    logger.info(f"Full-text smoke test: token {token!r} -> {parent_asin} {'found' if found else 'NOT found'} in {len(hits)} hits")
    return found, token, parent_asin


def _create_and_await_fulltext(session_factory: SessionFactory, fields: Sequence[str], await_timeout_s: int) -> None:
    """Creates the full-text index over `fields` and waits for it to come online."""
    with session_factory() as session:
        session.run(fulltext_create_statement(fields)).consume()
        session.run(AWAIT_INDEX_QUERY, name=FULLTEXT_INDEX_NAME, timeout=await_timeout_s).consume()


def run_fulltext_index(session_factory: SessionFactory, seed: int, await_timeout_s: int) -> Tuple[int, List[str]]:
    """Creates and awaits the index, smoke-tests; on failure writes features_text, recreates over the fallback fields,
    re-tests (AC-026). Returns (exit code, fulltext_fields)."""
    fields = list(FULLTEXT_FIELDS)
    _create_and_await_fulltext(session_factory, fields, await_timeout_s)
    found, _, _ = fulltext_smoke_test(session_factory, seed)
    if found:
        logger.info(f"fulltext_fields = {fields}")
        return EXIT_OK, fields
    logger.warning("Smoke test failed on LIST<STRING> features; falling back to features_text (FR-025)")
    with session_factory() as session:
        session.run(FEATURES_TEXT_QUERY).consume()
        session.run(DROP_FULLTEXT_QUERY).consume()
    fields = list(FULLTEXT_FALLBACK_FIELDS)
    _create_and_await_fulltext(session_factory, fields, await_timeout_s)
    found, _, _ = fulltext_smoke_test(session_factory, seed)
    logger.info(f"fulltext_fields = {fields} (fallback); smoke test {'passed' if found else 'FAILED'}")
    return (EXIT_OK if found else EXIT_STEP_FAILED), fields


def check_stamp_preconditions(
    report: ValidationReport,
    report_sha256: str,
    confirmed_sha256: str,
    lineage_sha256: str,
    graph_counts: Mapping[str, int],
    lineage: Optional[Lineage] = None,
) -> List[str]:
    """FR-027 reasons to refuse: not passed, lineage hash differs, product/review counts differ, CP-8 hash not confirmed (AC-030).
    With `lineage`, a build without a known clean commit is refused too (the stamp records code_commit)."""
    reasons: List[str] = []
    if report.passed is not True:
        reasons.append("validation report has passed: false")
    if report.lineage_sha256 != lineage_sha256:
        reasons.append(f"lineage sha256 {lineage_sha256} differs from the report's {report.lineage_sha256}")
    for label in ("ParentProduct", "Review"):
        if graph_counts.get(label) != report.graph_counts.get(label):
            reasons.append(f"{label} count {graph_counts.get(label)} differs from the report's {report.graph_counts.get(label)}")
    if confirmed_sha256.strip().lower() != report_sha256:
        reasons.append("--confirm-validation-sha256 does not match the validation report (CP-8 approval)")
    if lineage is not None and (not lineage.code.git_commit or lineage.code.git_dirty is not False):
        reasons.append("lineage was not built from a clean, known commit (--require-clean)")
    return reasons


def build_graph_version_props(
    lineage: Lineage,
    file_hashes: Mapping[str, str],
    build_params: BuildParams,
    stamp_commit: str,
    neo4j_version: str,
    fulltext_fields: Sequence[str],
    graph_counts: Mapping[str, int],
    built_at: str,
) -> GraphVersionProps:
    """Exactly the §5.6 properties."""
    return GraphVersionProps(
        version=lineage.graph_version,
        built_at=built_at,
        lineage_sha256=file_hashes["lineage"],
        validation_report_sha256=file_hashes["validation_report"],
        embedding_report_sha256=file_hashes["embedding_report"],
        build_params_sha256=file_hashes["build_params"],
        source_meta_sha256=lineage.sources.meta.sha256,
        source_reviews_sha256=lineage.sources.reviews.sha256,
        splits_sha256=lineage.sources.splits.combined_sha256,
        catalogue_sha256=lineage.sources.catalogue.sha256_content,
        code_commit=str(lineage.code.git_commit),
        stamp_commit=stamp_commit,
        template_ids=[f"{label}={TEMPLATE_IDS[label]}" for label in TEMPLATE_ID_ORDER],
        review_embedding_scope=build_params.review_embedding_scope,
        review_cap=build_params.review_cap,
        fulltext_fields=list(fulltext_fields),
        neo4j_version=neo4j_version,
        product_count=int(graph_counts["ParentProduct"]),
        review_count=int(graph_counts["Review"]),
        user_count=int(graph_counts["User"]),
        taxon_count=int(graph_counts["Taxon"]),
    )


def _read_fulltext_fields(session: Any) -> List[str]:
    """Indexed properties of product_fulltext_index from SHOW INDEXES."""
    record = session.run(FULLTEXT_PROPERTIES_QUERY, name=FULLTEXT_INDEX_NAME).single()
    if record is None:
        raise StampRefused(f"{FULLTEXT_INDEX_NAME} does not exist")
    return list(record["properties"])


def run_stamp(
    session_factory: SessionFactory,
    args: argparse.Namespace,
    git_runner: Optional[GitRunner] = None,
) -> int:
    """Checks preconditions, reads fulltext_fields back from SHOW INDEXES, then CREATE (g:GraphVersion $props)."""
    lineage = load_lineage(args.lineage)
    try:
        report = ValidationReport.model_validate_json(Path(args.validation_report).read_text(encoding="utf-8"))
        build_params = BuildParams.model_validate_json(Path(args.build_params).read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise StampRefused(f"cannot read validation report or build params: {e}") from e
    file_hashes = {
        "lineage": sha256_file(Path(args.lineage)),
        "validation_report": sha256_file(Path(args.validation_report)),
        "embedding_report": sha256_file(Path(args.embedding_report)),
        "build_params": sha256_file(Path(args.build_params)),
    }
    with session_factory() as session:
        graph_counts = {label: _scalar(session, query) for label, query in STAMP_COUNT_QUERIES.items()}
        fulltext_fields = _read_fulltext_fields(session)
        components = session.run(
            "CALL dbms.components() YIELD versions RETURN versions[0] AS version"
        ).single()
    reasons = check_stamp_preconditions(
        report, file_hashes["validation_report"], args.confirm_validation_sha256, file_hashes["lineage"], graph_counts, lineage,
    )
    if report.embedding_report_sha256 != file_hashes["embedding_report"]:
        reasons.append("embedding report changed since validation")
    if report.build_params_sha256 != file_hashes["build_params"]:
        reasons.append("build params changed since validation")
    if reasons:
        raise StampRefused("; ".join(reasons))
    run = git_runner or default_git_runner(REPO_ROOT)
    code, out = run(["rev-parse", "HEAD"])
    if code != 0 or not out.strip():
        raise StampRefused("cannot read the stamp commit (git rev-parse HEAD)")
    props = build_graph_version_props(
        lineage, file_hashes, build_params, out.strip(), str(components["version"]) if components else "unknown",
        fulltext_fields, graph_counts, _now(),
    )
    with session_factory() as session:
        session.run(STAMP_QUERY, props=props.model_dump(mode="json")).consume()
    logger.info(f"GraphVersion {props.version} stamped: {props.model_dump(mode='json')}")
    return EXIT_OK


def _load_build_params(path: Path) -> BuildParams:
    """Reads and validates build_params.json (InputVerificationError when missing or invalid)."""
    try:
        return BuildParams.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValidationError) as e:
        raise InputVerificationError(f"cannot read build params {path}: {e}") from e


def main(
    argv: Optional[Sequence[str]] = None,
    session_factory: Optional[SessionFactory] = None,
    embedder: Optional[Embedder] = None,
    connector: Optional[Any] = None,
) -> int:
    """CLI entry point; Neo4j session factory, embedder and connector are injectable for tests."""
    args = build_parser().parse_args(argv)
    try:
        lineage = load_lineage(args.lineage)
    except InputVerificationError as e:
        logger.error(str(e))
        return EXIT_GUARD
    owned_connector = None
    if session_factory is None:
        from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

        owned_connector = connector or Neo4jConnector()
        if not owned_connector.is_connected():
            owned_connector.connect()
        connector = owned_connector
        session_factory = owned_connector.session
    try:
        check_graph_guard(session_factory, lineage)
        command = args.command
        if command == "stamp":
            return run_stamp(session_factory, args)
        steps = ["constraints", "embed", "vector-indexes", "fulltext-index"] if command == "all" else [command]
        for step in steps:
            if step == "constraints":
                code = run_constraints(session_factory)
            elif step == "embed":
                build_params = _load_build_params(args.build_params)
                if embedder is None:
                    embedder = ResilientEmbedder(load_model(args.embed_device), batch_size=args.embed_batch_size)
                run_embed(session_factory, embedder, args.labels, args.batch_size, build_params, args.report, time.monotonic)
                code = EXIT_OK
            elif step == "vector-indexes":
                code = run_vector_indexes(session_factory, connector, args.await_timeout)
            else:
                code, _ = run_fulltext_index(session_factory, args.seed, getattr(args, "await_timeout", DEFAULT_AWAIT_TIMEOUT_S))
            if code != EXIT_OK:
                logger.error(f"Step {step} failed; stopping")
                return code
        return EXIT_OK
    except (GuardError, StampRefused, InputVerificationError, DeviceUnavailableError) as e:
        logger.error(f"Refused: {e}")
        return EXIT_GUARD
    except Exception as e:
        logger.error(f"post_import_v2 {args.command} failed: {e}")
        return EXIT_STEP_FAILED
    finally:
        if owned_connector is not None:
            owned_connector.close()


if __name__ == "__main__":
    raise SystemExit(main())
