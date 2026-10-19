"""
Run provenance and the citable-run policy (R2a, FR-029 … FR-031; Technical Specification §5.1.5).
Graph v2 (Technical Specification Graph Rebuild FR-028, FR-029) adds the (:GraphVersion) node and
two data-quality counts to the graph snapshot, and makes live runs on a graph without a validated
GraphVersion non-citable.

Collects git, benchmark, LLM, Neo4j, graph-snapshot and Python facts for manifest["provenance"]
and decides `manifest["citable"]`. Git calls go through an injectable runner (5 s timeout) so the
logic is unit-testable without real repository state. Environment variables are never recorded:
only git output, file hashes, versions and counts.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

GitRunner = Callable[[Sequence[str]], Tuple[int, str]]  # (args after "git") -> (returncode, stdout)
GIT_TIMEOUT_S: float = 5.0
DEFAULT_SCOPE: Tuple[str, ...] = ("src", "scripts")
_HASH_CHUNK = 1024 * 1024


def default_git_runner(repo_root: Path) -> GitRunner:
    """Returns a runner executing `git <args>` in `repo_root` via subprocess with GIT_TIMEOUT_S."""
    root = str(repo_root)

    def _run(args: Sequence[str]) -> Tuple[int, str]:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False,
            )
            return proc.returncode, proc.stdout
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"[Provenance] git {' '.join(args)} failed: {e}")
            return -1, ""

    return _run


def file_sha256(path: Union[str, Path]) -> Optional[str]:
    """Streaming SHA-256 hex digest of a file; None if it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
                digest.update(chunk)
    except OSError as e:
        logger.warning(f"[Provenance] Cannot hash {path}: {e}")
        return None
    return digest.hexdigest()


def _porcelain_paths(stdout: str) -> Tuple[List[str], List[str]]:
    """(changed paths, untracked paths) from `git status --porcelain` output; renames keep the new path."""
    changed: List[str] = []
    untracked: List[str] = []
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        changed.append(path)
        if status == "??":
            untracked.append(path)
    return changed, untracked


def collect_git_provenance(
    repo_root: Path,
    paths: Sequence[str] = DEFAULT_SCOPE,
    runner: Optional[GitRunner] = None,
) -> Dict[str, Any]:
    """
    git_commit, git_describe (--always --dirty, repository-wide, informational), git_dirty and
    git_dirty_paths (porcelain --untracked-files=all within `paths`), git_diff_sha256
    (SHA-256 of `git diff HEAD -- <paths>`, None when empty) and untracked_files (within `paths`).
    Failed git calls are logged and stored as None.
    """
    run = runner or default_git_runner(repo_root)
    scope = list(paths)

    code, out = run(["rev-parse", "HEAD"])
    commit = out.strip() if code == 0 and out.strip() else None
    code, out = run(["describe", "--always", "--dirty"])
    describe = out.strip() if code == 0 and out.strip() else None

    code, out = run(["status", "--porcelain", "--untracked-files=all", "--", *scope])
    if code == 0:
        dirty_paths, untracked = _porcelain_paths(out)
        dirty: Optional[bool] = bool(dirty_paths)
    else:
        logger.warning("[Provenance] git status failed; working-tree state unknown")
        dirty_paths, untracked, dirty = [], [], None

    code, out = run(["diff", "HEAD", "--", *scope])
    diff_sha = hashlib.sha256(out.encode("utf-8")).hexdigest() if code == 0 and out else None

    return {
        "git_commit": commit,
        "git_describe": describe,
        "git_dirty": dirty,
        "git_dirty_paths": dirty_paths,
        "git_diff_sha256": diff_sha,
        "untracked_files": untracked,
        "git_scope": scope,
    }


def collect_benchmark_provenance(
    repo_root: Path,
    benchmark_path: Path,
    query_count: int,
    runner: Optional[GitRunner] = None,
) -> Dict[str, Any]:
    """path, sha256, git_tracked, git_dirty, query_count, split (None), salt (None) for the benchmark file."""
    run = runner or default_git_runner(repo_root)
    resolved = Path(benchmark_path)
    absolute = resolved if resolved.is_absolute() else Path(repo_root) / resolved
    try:
        rel = os.path.relpath(absolute.resolve(), Path(repo_root).resolve())
    except ValueError:
        rel = str(absolute)
    tracked_code, _ = run(["ls-files", "--error-unmatch", "--", rel])
    status_code, status_out = run(["status", "--porcelain", "--", rel])
    return {
        "path": str(benchmark_path),
        "sha256": file_sha256(absolute),
        "git_tracked": tracked_code == 0,
        "git_dirty": bool(status_out.strip()) if status_code == 0 else None,
        "query_count": int(query_count),
        "split": None,
        "salt": None,
    }


GRAPH_VERSION_QUERY = "MATCH (g:GraphVersion) RETURN properties(g) AS props"
PRODUCTS_UNTITLED_QUERY = "MATCH (p:ParentProduct) WHERE p.title IS NULL OR trim(p.title) = '' RETURN count(p) AS n"
REVIEWS_EMBEDDED_QUERY = "MATCH (r:Review) WHERE r.embedding IS NOT NULL RETURN count(r) AS n"


def _graph_version(session: Any) -> Optional[Dict[str, Any]]:
    """properties(g) of the single GraphVersion node; None (logged) for 0 or more than 1 nodes, or on failure."""
    try:
        records = list(session.run(GRAPH_VERSION_QUERY))
        if len(records) != 1:
            logger.warning(f"[Provenance] Expected exactly one GraphVersion node, found {len(records)}; graph_version = None")
            return None
        return dict(records[0]["props"])
    except Exception as e:
        logger.warning(f"[Provenance] GraphVersion lookup failed: {e}")
        return None


def _scalar(session: Any, cypher: str) -> Optional[int]:
    """Single count from a read query; None (logged) on failure."""
    try:
        record = session.run(cypher).single()
        return int(record["n"]) if record is not None else None
    except Exception as e:
        logger.warning(f"[Provenance] Graph count failed ({cypher.strip()[:60]}): {e}")
        return None


def collect_runtime_provenance(orchestrator: Any, popular_count: Optional[int]) -> Dict[str, Any]:
    """
    llm {alias, resolved_model_ids}, neo4j {name, version, edition} via dbms.components(),
    graph_snapshot {products, categories, reviews, review_embedded_products, graph_version,
    products_untitled, reviews_embedded}, python
    {version, executable} and category_recovery. Each failing query is logged and stored as None.
    Call it after the query loop so the resolved model IDs reported by the API are included.
    """
    handler = getattr(orchestrator, "llm_handler", None)
    resolved = getattr(handler, "resolved_model_ids", None)
    llm = {
        "alias": getattr(handler, "model_name", None) if isinstance(getattr(handler, "model_name", None), str) else None,
        "resolved_model_ids": sorted(str(m) for m in resolved) if isinstance(resolved, (set, list, tuple, frozenset)) else [],
    }

    neo4j: Dict[str, Any] = {"name": None, "version": None, "edition": None}
    snapshot: Dict[str, Any] = {
        "products": None, "categories": None, "reviews": None, "review_embedded_products": popular_count,
        "graph_version": None, "products_untitled": None, "reviews_embedded": None,
    }
    db = getattr(getattr(orchestrator, "graph_tool", None), "db", None)
    if db is not None:
        try:
            with db.session() as session:
                try:
                    record = session.run(
                        "CALL dbms.components() YIELD name, versions, edition "
                        "RETURN name, versions[0] AS version, edition"
                    ).single()
                    if record is not None:
                        neo4j = {"name": record["name"], "version": record["version"], "edition": record["edition"]}
                except Exception as e:
                    logger.warning(f"[Provenance] dbms.components() failed: {e}")
                snapshot["products"] = _scalar(session, "MATCH (p:ParentProduct) RETURN count(p) AS n")
                snapshot["categories"] = _scalar(session, "MATCH (c:Category) RETURN count(c) AS n")
                snapshot["reviews"] = _scalar(session, "MATCH (r:Review) RETURN count(r) AS n")
                snapshot["graph_version"] = _graph_version(session)
                snapshot["products_untitled"] = _scalar(session, PRODUCTS_UNTITLED_QUERY)
                snapshot["reviews_embedded"] = _scalar(session, REVIEWS_EMBEDDED_QUERY)
        except Exception as e:
            logger.warning(f"[Provenance] Could not open a Neo4j session for provenance: {e}")

    recovery = getattr(orchestrator, "category_recovery", None)
    return {
        "llm": llm,
        "neo4j": neo4j,
        "graph_snapshot": snapshot,
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "category_recovery": recovery if isinstance(recovery, bool) else None,
    }


def evaluate_citable(
    mode: str,
    sample_size: Optional[int],
    git: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    llm: Optional[Mapping[str, Any]] = None,
    graph: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, List[str], List[str]]:
    """
    Citable policy (FR-030): True only for mode "live", no sample size, a clean src/scripts
    scope and a tracked, unmodified benchmark. Returns (citable, citable_reasons,
    citable_warnings); warnings (model_id_unresolved, multiple_model_ids) never block.
    Graph v2 (FR-029): in mode "live", `graph` (the runtime graph_snapshot) must carry a
    GraphVersion with validation_passed true, else graph_version_unknown or
    graph_version_not_validated is added. Archived runs are never recomputed.
    """
    reasons: List[str] = []
    warnings: List[str] = []
    if mode != "live":
        reasons.append(f"mode_not_live: {mode}")
    if sample_size:
        reasons.append(f"sample_size_set: {sample_size}")
    if not git.get("git_commit"):
        reasons.append("git_commit_unknown")
    if git.get("git_dirty") is None:
        reasons.append("git_status_unavailable")
    elif git.get("git_dirty"):
        reasons.append(f"git_dirty: {', '.join(git.get('git_dirty_paths') or [])}")
    if not benchmark.get("sha256"):
        reasons.append("benchmark_unreadable")
    if benchmark.get("git_tracked") is not True:
        reasons.append(f"benchmark_untracked: {benchmark.get('path')}")
    if benchmark.get("git_dirty") is None:
        reasons.append("benchmark_status_unavailable")
    elif benchmark.get("git_dirty"):
        reasons.append(f"benchmark_modified: {benchmark.get('path')}")

    if mode == "live":
        graph_version = graph.get("graph_version") if graph is not None else None
        if not graph_version:
            reasons.append("graph_version_unknown")
        elif graph_version.get("validation_passed") is not True:
            reasons.append("graph_version_not_validated")

    if llm is not None:
        resolved = list(llm.get("resolved_model_ids") or [])
        if not resolved:
            warnings.append("model_id_unresolved")
        elif len(resolved) > 1:
            warnings.append("multiple_model_ids")
    return not reasons, reasons, warnings


def offending_paths(git: Mapping[str, Any], benchmark: Mapping[str, Any]) -> List[str]:
    """Paths that make a tree unclean for --require-clean (src/scripts scope plus a dirty or untracked benchmark)."""
    paths = list(git.get("git_dirty_paths") or [])
    if git.get("git_dirty") is None:
        paths.append("<git status unavailable>")
    if benchmark.get("git_dirty") or benchmark.get("git_tracked") is not True:
        paths.append(str(benchmark.get("path")))
    return paths
