#!/usr/bin/env python3
"""
Graph v2 transform CLI (Technical Specification Graph Rebuild FR-005 … FR-018, §4.1.7).

Turns the raw Amazon Reviews 2023 Electronics files into neo4j-admin import CSVs plus
graph_versions/v2/lineage.json. No Neo4j, no Docker: the output is files only. The logic lives in
`src/knowledge_graph/graph_v2/transform.py`; this script parses flags and maps errors to exit codes.

Exit codes: 0 success; 2 input verification failure, dirty tree with --require-clean, taxon_id
collision, lineage invariant failure (no lineage is written), or existing output without --force.

Usage:
    python scripts/graph_ingestion/build_graph_v2.py \\
        --meta datasets/raw/meta_Electronics.jsonl --reviews datasets/raw/Electronics.jsonl \\
        --sha256sums datasets/raw/SHA256SUMS --splits-dir datasets \\
        --catalogue graph_versions/v2/catalogue_asins.txt.gz \\
        --out-dir datasets/graph_build/v2 --lineage graph_versions/v2/lineage.json \\
        [--review-cap 20] [--embed-top-n 5] [--sample-mod N] [--dry-run] [--require-clean] [--force]
    python scripts/graph_ingestion/build_graph_v2.py --sample-mod 20 --require-clean    # pilot, default paths
    python scripts/graph_ingestion/build_graph_v2.py --require-clean                    # full build, default paths

`--dry-run` runs both passes and every counter but writes neither CSVs nor lineage.json; the
counts are logged as JSON.

Every path flag is optional and defaults to the repository layout (`lineage.build_paths` /
`lineage.shared_input`). With `--sample-mod` the defaults are the pilot artefacts
(`datasets/graph_build/v2_pilot`, `graph_versions/v2/pilot/lineage.json`), the same paths
`validate_graph.py --pilot` reads; without it, the full build (`datasets/graph_build/v2`,
`graph_versions/v2/lineage.json`).

A run that writes output refuses (exit 2) when the target lineage file already exists or the CSV
directory is not empty, so an approved lineage (CP-1 … CP-8) cannot be replaced by an accidental
re-run. Pass `--force` to rebuild on purpose. `--dry-run` writes nothing and needs no `--force`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.knowledge_graph.graph_v2.lineage import GraphBuildError, build_paths, shared_input  # noqa: E402
from src.knowledge_graph.graph_v2.taxonomy import TaxonIdCollisionError  # noqa: E402
from src.knowledge_graph.graph_v2.transform import TransformConfig, run_transform  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_graph_v2")

EXIT_OK = 0
EXIT_INPUT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of §4.1.7."""
    parser = argparse.ArgumentParser(description="Build the graph v2 import CSVs and lineage from the raw Amazon files.")
    parser.add_argument("--meta", type=Path, default=None, help="default: datasets/raw/meta_Electronics.jsonl")
    parser.add_argument("--reviews", type=Path, default=None, help="default: datasets/raw/Electronics.jsonl")
    parser.add_argument("--sha256sums", type=Path, default=None, help="default: datasets/raw/SHA256SUMS")
    parser.add_argument("--splits-dir", type=Path, default=None, help="Directory holding Electronics.{train,valid,test}.csv (default: datasets)")
    parser.add_argument("--catalogue", type=Path, default=None, help="default: graph_versions/v2/catalogue_asins.txt.gz")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Output root; CSVs go to <out-dir>/import/ (default: datasets/graph_build/v2, or v2_pilot with --sample-mod)")
    parser.add_argument("--lineage", type=Path, default=None,
                        help="default: graph_versions/v2/lineage.json, or graph_versions/v2/pilot/lineage.json with --sample-mod")
    parser.add_argument("--review-cap", type=int, default=20)
    parser.add_argument("--embed-top-n", type=int, default=5)
    parser.add_argument("--sample-mod", type=int, default=None, help="Pilot: keep ASINs with int(sha256) %% N == 0")
    parser.add_argument("--dry-run", action="store_true", help="Count only; write no CSV and no lineage")
    parser.add_argument("--require-clean", action="store_true", help="Refuse if src/ or scripts/ are dirty")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing lineage file and non-empty CSV directory (refused otherwise)")
    return parser


def config_from_args(args: argparse.Namespace, repo_root: Path = REPO_ROOT) -> TransformConfig:
    """Maps parsed flags to a TransformConfig (CSV directory = <out-dir>/import); unset paths take the
    full-build defaults, or the pilot defaults when --sample-mod is given."""
    paths = build_paths(repo_root, pilot=args.sample_mod is not None)
    return TransformConfig(
        meta_path=args.meta or shared_input(repo_root, "meta"),
        reviews_path=args.reviews or shared_input(repo_root, "reviews"),
        sha256sums_path=args.sha256sums or shared_input(repo_root, "sha256sums"),
        splits_dir=args.splits_dir or shared_input(repo_root, "splits_dir"),
        catalogue_path=args.catalogue or shared_input(repo_root, "catalogue"),
        out_dir=Path(args.out_dir or paths.out_dir) / "import",
        lineage_path=args.lineage or paths.lineage,
        review_cap=args.review_cap,
        embed_top_n=args.embed_top_n,
        sample_mod=args.sample_mod,
        dry_run=args.dry_run,
        require_clean=args.require_clean,
        repo_root=repo_root,
    )


def result_path(args: argparse.Namespace) -> Path:
    """The lineage path this invocation writes."""
    return Path(config_from_args(args).lineage_path)


def existing_outputs(config: TransformConfig) -> List[Path]:
    """Outputs of a previous build that a non-dry run would overwrite: the lineage file and a non-empty CSV directory."""
    found: List[Path] = []
    lineage_path = Path(config.lineage_path)
    out_dir = Path(config.out_dir)
    if lineage_path.exists():
        found.append(lineage_path)
    if out_dir.is_dir() and any(out_dir.iterdir()):
        found.append(out_dir)
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Runs the transform; returns 0, or 2 on GraphBuildError / TaxonIdCollisionError."""
    args = build_parser().parse_args(argv)
    if args.review_cap < 1 or args.embed_top_n < 0 or (args.sample_mod is not None and args.sample_mod < 1):
        logger.error("--review-cap must be >= 1, --embed-top-n >= 0 and --sample-mod >= 1")
        return EXIT_INPUT_ERROR
    config = config_from_args(args)
    if not args.dry_run and not args.force:
        existing = existing_outputs(config)
        if existing:
            logger.error(f"Refusing to overwrite existing build output {[str(x) for x in existing]}; "
                         f"re-run with --force to rebuild on purpose")
            return EXIT_INPUT_ERROR
    try:
        result = run_transform(config)
    except (GraphBuildError, TaxonIdCollisionError) as e:
        logger.error(f"Graph v2 transform aborted: {e}")
        return EXIT_INPUT_ERROR
    counts = result.lineage.counts
    if args.dry_run:
        logger.info("Dry run: no CSV and no lineage written. Counts:\n" + json.dumps(counts.model_dump(mode="json"), indent=2))
    else:
        logger.info(f"Transform complete: {counts.nodes} nodes, {counts.relationships} relationships; lineage {result_path(args)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
