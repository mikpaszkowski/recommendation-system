#!/usr/bin/env python3
"""
Catalogue freeze and v1 snapshot export (Technical Specification Graph Rebuild FR-003, R-1, R-3).

Read-only on the running v1 graph. Writes:
    graph_versions/v2/catalogue_asins.txt.gz   all ParentProduct.parent_asin, sorted, `\\n`-terminated,
                                               gzip with mtime=0 and no file name
    graph_versions/v1/snapshot.json            v1 counts per label / relationship type, products_untitled,
                                               reviews_embedded, review_embedded_products, Neo4j version, taken_at
    graph_versions/v1/benchmark_targets.json   title, price, brands, categories, review_nodes per benchmark target

`--verify-only` recomputes all three and compares them with the files on disk (the snapshot's
`taken_at` is ignored); it writes nothing and exits 1 on any difference.

Exit codes: 0 success / identical; 1 mismatch (--verify-only); 2 input or connection error.

Usage:
    python scripts/graph_ingestion/export_v1_snapshot.py --catalogue-out graph_versions/v2/catalogue_asins.txt.gz \\
        --snapshot-out graph_versions/v1/snapshot.json --benchmark live_eval_dataset.json \\
        --targets-out graph_versions/v1/benchmark_targets.json [--verify-only]
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, ContextManager, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.knowledge_graph.graph_v2.graph_queries import benchmark_target_facts, collect_graph_snapshot, scalar  # noqa: E402
from src.knowledge_graph.graph_v2.lineage import InputVerificationError, encode_catalogue, read_catalogue, write_catalogue  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("export_v1_snapshot")

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_INPUT_ERROR = 2
CATALOGUE_PAGE_SIZE = 50_000
ALL_ASINS_QUERY = (
    "MATCH (p:ParentProduct) WHERE p.parent_asin > $after RETURN p.parent_asin AS asin "
    "ORDER BY p.parent_asin LIMIT $limit"
)
NULL_ASIN_QUERY = "MATCH (p:ParentProduct) WHERE p.parent_asin IS NULL RETURN count(p) AS n"
VOLATILE_SNAPSHOT_KEYS = ("taken_at",)

SessionFactory = Callable[[], ContextManager[Any]]


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of §4.1.7."""
    parser = argparse.ArgumentParser(description="Freeze the v1 catalogue and export the v1 snapshot (read-only).")
    parser.add_argument("--catalogue-out", required=True, type=Path)
    parser.add_argument("--snapshot-out", required=True, type=Path)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--targets-out", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true", help="Recompute and compare; write nothing")
    return parser


def fetch_catalogue(session: Any) -> List[str]:
    """All parent_asin values by keyset pagination; raises if any ParentProduct has a null parent_asin."""
    nulls = scalar(session, NULL_ASIN_QUERY)
    if nulls:
        raise RuntimeError(f"{nulls} ParentProduct nodes have a null parent_asin; the catalogue cannot be frozen")
    asins: List[str] = []
    after = ""
    while True:
        page = [record["asin"] for record in session.run(ALL_ASINS_QUERY, after=after, limit=CATALOGUE_PAGE_SIZE)]
        if not page:
            break
        asins.extend(page)
        after = page[-1]
        if len(page) < CATALOGUE_PAGE_SIZE:
            break
    logger.info(f"Catalogue: {len(asins):,} parent_asins")
    return asins


def collect_snapshot(session: Any, taken_at: str) -> Dict[str, Any]:
    """graph_queries.collect_graph_snapshot plus taken_at."""
    return {**collect_graph_snapshot(session), "taken_at": taken_at}


def _target_asin(item: Mapping[str, Any]) -> Optional[str]:
    """Benchmark target ASIN (target_asin or the first ground_truth_asins entry)."""
    return item.get("target_asin") or (item.get("ground_truth_asins") or [None])[0]


def collect_benchmark_targets(session: Any, benchmark: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Per query: query_id, target_asin, title, price, brands, categories, review_nodes (sorted lists)."""
    targets = []
    for item in benchmark:
        query_id = item.get("query_id") or item.get("id")
        targets.append(dict(benchmark_target_facts(session, str(query_id), str(_target_asin(item)))))
    return targets


def _json_text(data: Any) -> str:
    """Canonical JSON file text (indented, sorted keys, trailing newline)."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_outputs(catalogue: Sequence[str], snapshot: Mapping[str, Any], targets: Sequence[Mapping[str, Any]], args: argparse.Namespace) -> None:
    """Writes the three files (catalogue via lineage.write_catalogue; JSON indented, sorted keys)."""
    sha = write_catalogue(catalogue, args.catalogue_out)
    for path, data in ((args.snapshot_out, snapshot), (args.targets_out, list(targets))):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(_json_text(data), encoding="utf-8")
    logger.info(f"Wrote {args.catalogue_out} (content sha256 {sha}), {args.snapshot_out}, {args.targets_out}")


def verify_outputs(catalogue: Sequence[str], snapshot: Mapping[str, Any], targets: Sequence[Mapping[str, Any]], args: argparse.Namespace) -> List[str]:
    """Differences between the recomputed values and the files on disk (empty list = identical)."""
    problems: List[str] = []
    try:
        stored, stored_sha = read_catalogue(args.catalogue_out)
        if encode_catalogue(stored) != encode_catalogue(catalogue):
            missing = sorted(set(stored) - set(catalogue))[:20]
            extra = sorted(set(catalogue) - set(stored))[:20]
            problems.append(f"catalogue differs: {len(stored)} stored vs {len(catalogue)} live; missing {missing}, new {extra}")
    except InputVerificationError as e:
        problems.append(f"catalogue unreadable: {e}")
    for path, live in ((args.snapshot_out, snapshot), (args.targets_out, list(targets))):
        try:
            stored_json = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"{path} unreadable: {e}")
            continue
        if isinstance(stored_json, dict):
            stored_json = {k: v for k, v in stored_json.items() if k not in VOLATILE_SNAPSHOT_KEYS}
            live = {k: v for k, v in dict(live).items() if k not in VOLATILE_SNAPSHOT_KEYS}
        if json.loads(_json_text(live)) != stored_json:
            problems.append(f"{path} differs from the live v1 graph")
    return problems


def main(argv: Optional[Sequence[str]] = None, session_factory: Optional[SessionFactory] = None) -> int:
    """CLI entry point; returns 0 / 1 / 2."""
    args = build_parser().parse_args(argv)
    try:
        benchmark = json.loads(Path(args.benchmark).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Cannot read benchmark {args.benchmark}: {e}")
        return EXIT_INPUT_ERROR
    owned = None
    if session_factory is None:
        from src.knowledge_graph.graphdb.neo4j_connector import Neo4jConnector

        owned = Neo4jConnector()
        try:
            owned.connect()
        except Exception as e:
            logger.error(f"Cannot connect to Neo4j: {e}")
            return EXIT_INPUT_ERROR
        session_factory = owned.session
    try:
        with session_factory() as session:
            catalogue = fetch_catalogue(session)
            snapshot = collect_snapshot(session, datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            targets = collect_benchmark_targets(session, benchmark)
    except Exception as e:
        logger.error(f"Read-only export failed: {e}")
        return EXIT_INPUT_ERROR
    finally:
        if owned is not None:
            owned.close()
    if args.verify_only:
        problems = verify_outputs(catalogue, snapshot, targets, args)
        for problem in problems:
            logger.error(problem)
        if problems:
            return EXIT_MISMATCH
        logger.info("Verify-only: catalogue, snapshot and benchmark targets are unchanged.")
        return EXIT_OK
    write_outputs(catalogue, snapshot, targets, args)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
