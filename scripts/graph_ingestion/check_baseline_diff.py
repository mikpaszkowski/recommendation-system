#!/usr/bin/env python3
"""
Baseline-commit allow-list check for the v2 baseline re-run (Technical Specification Graph Rebuild §6.6, OQ-2, AC-045).

Prints `git diff --name-only <base> <head> -- src scripts live_eval_dataset.json` and exits 1 if any
path is outside the allow-list, so the retrieval code at baseline commit B is identical to the v1
reference runs (commit 88cdbdf) apart from the graph v2 work.

Exit codes: 0 every changed path allowed; 1 a path outside the allow-list; 2 git failure.

Usage:
    python scripts/graph_ingestion/check_baseline_diff.py --base 88cdbdf [--head HEAD]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.provenance import GitRunner, default_git_runner  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("check_baseline_diff")

EXIT_OK = 0
EXIT_OUTSIDE_ALLOWLIST = 1
EXIT_GIT_ERROR = 2
DIFF_SCOPE: Tuple[str, ...] = ("src", "scripts", "live_eval_dataset.json")
ALLOWED_EXACT: Tuple[str, ...] = (
    "src/evaluation/provenance.py",
    "src/knowledge_graph/graphdb/embedding_templates.py",
    "src/knowledge_graph/graphdb/backfill_embeddings.py",
    "src/knowledge_graph/graphdb/backfill_category_embeddings.py",
    "src/knowledge_graph/graphdb/setup_indexes.py",
    "src/knowledge_graph/graphdb/create_vector_indexes.cypher",
    "src/knowledge_graph/graphdb/create_indexes.py",
    "src/utils/AmazonDataProcessor.py",
    "src/llm_interface/prompts/graph_cypher_prompt.py",
    "scripts/evaluate_retrieval.py",
    "scripts/archive_eval_run.py",
)
ALLOWED_PREFIXES: Tuple[str, ...] = (
    "src/knowledge_graph/graph_v2/",
    "scripts/graph_ingestion/",
)


def build_parser() -> argparse.ArgumentParser:
    """Argument parser."""
    parser = argparse.ArgumentParser(description="Check that the baseline commit differs from the base only in allow-listed paths.")
    parser.add_argument("--base", required=True, help="Base commit of the v1 reference runs, e.g. 88cdbdf")
    parser.add_argument("--head", default="HEAD")
    return parser


def is_allowed(path: str) -> bool:
    """True if `path` is in ALLOWED_EXACT or under an ALLOWED_PREFIXES entry."""
    return path in ALLOWED_EXACT or any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def changed_paths(base: str, head: str, runner: GitRunner) -> List[str]:
    """`git diff --name-only base head -- DIFF_SCOPE`; raises RuntimeError on git failure."""
    code, out = runner(["diff", "--name-only", base, head, "--", *DIFF_SCOPE])
    if code != 0:
        raise RuntimeError(f"git diff --name-only {base} {head} failed (exit {code})")
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def main(argv: Optional[Sequence[str]] = None, runner: Optional[GitRunner] = None) -> int:
    """Logs every changed path with its verdict; returns 0 / 1 / 2."""
    args = build_parser().parse_args(argv)
    run = runner or default_git_runner(REPO_ROOT)
    try:
        paths = changed_paths(args.base, args.head, run)
    except RuntimeError as e:
        logger.error(str(e))
        return EXIT_GIT_ERROR
    outside: List[str] = []
    for path in paths:
        allowed = is_allowed(path)
        logger.info(f"{'allowed' if allowed else 'OUTSIDE ALLOW-LIST'}: {path}")
        if not allowed:
            outside.append(path)
    if outside:
        logger.error(f"{len(outside)} changed path(s) outside the allow-list between {args.base} and {args.head}: {outside}")
        return EXIT_OUTSIDE_ALLOWLIST
    logger.info(f"{len(paths)} changed path(s) between {args.base} and {args.head}, all allow-listed.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
