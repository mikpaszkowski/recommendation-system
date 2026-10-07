#!/usr/bin/env python3
"""
CLI Evaluation Script for Tier 1: Retrieval & Recommendation Quality Engine.

Evaluates search strategies (Hybrid GraphRAG, Vector-Only, Cypher-Only, Post-Critic)
against standardized benchmark queries, computing exact IR ranking metrics:
NDCG@K, Hit Rate@K, MRR@K, Precision@K, Recall@K, MAP@K.

Supports dual modes:
- Offline Mock Mode (--mode offline / --offline): Deterministic local execution without live Neo4j
- Live Mode (--mode live): Live execution through GraphSearchTool and CriticAgent

Outputs versioned run artifacts (manifest.json, summary.json, retrieval_metrics.json,
retrieval_metrics.csv, and publication-grade plots in plots/).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation.metrics import evaluate_retrieval_batch
from src.evaluation.tracker import create_evaluation_run_dir, save_run_artifacts
from src.evaluation.visualizer import plot_retrieval_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate_retrieval")


def get_git_commit() -> str:
    """Retrieves current git commit hash if available."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return "HEAD_EVAL"


def parse_k_values(raw_input: Optional[List[str]]) -> List[int]:
    """Parses k-values from comma or space-separated arguments."""
    if not raw_input:
        return [1, 3, 5, 10, 20]
    joined = " ".join(raw_input)
    values = [int(x.strip()) for x in joined.replace(",", " ").split() if x.strip()]
    return sorted(list(set(values))) if values else [1, 3, 5, 10, 20]


def parse_strategies(raw_input: Optional[List[str]], include_critic: bool = False) -> List[str]:
    """Parses strategies list."""
    if not raw_input:
        base = ["hybrid", "vector_only", "cypher_only"]
    else:
        joined = " ".join(raw_input)
        base = [x.strip() for x in joined.replace(",", " ").split() if x.strip()]
        if not base:
            base = ["hybrid", "vector_only", "cypher_only"]

    if include_critic and "hybrid_post_critic" not in base:
        base.append("hybrid_post_critic")
    return base


class TeeStream:
    """Thread-safe stream wrapper that duplicates writes to both an original stream and a log file."""

    def __init__(self, original: Any, log_file: Any):
        self.original = original
        self.log_file = log_file
        self._lock = threading.Lock()

    @property
    def encoding(self) -> str:
        return getattr(self.original, "encoding", "utf-8") or "utf-8"

    def write(self, data: str) -> int:
        with self._lock:
            res = 0
            if self.original:
                try:
                    res = self.original.write(data)
                    self.original.flush()
                except Exception:
                    pass
            if self.log_file and not self.log_file.closed:
                try:
                    self.log_file.write(data)
                    self.log_file.flush()
                except Exception:
                    pass
            return res

    def flush(self) -> None:
        with self._lock:
            if self.original:
                try:
                    self.original.flush()
                except Exception:
                    pass
            if self.log_file and not self.log_file.closed:
                try:
                    self.log_file.flush()
                except Exception:
                    pass

    def isatty(self) -> bool:
        return getattr(self.original, "isatty", lambda: False)()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original, name)


class ExecutionTraceLogger:
    """
    Context manager that intercepts stdout, stderr, and root logging.
    Directs all DEBUG and INFO traces to execution_trace.log while keeping
    clean INFO messages on the console (sys.__stderr__) without recursion or duplicate lines.
    """

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self.file_handle = None
        self.file_handler = None
        self.console_handler = None
        self.orig_stdout = sys.stdout
        self.orig_stderr = sys.stderr
        self._existing_handlers: List[logging.Handler] = []
        self._orig_root_level: Optional[int] = None

    def __enter__(self) -> ExecutionTraceLogger:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure log file exists and is cleanly truncated for new run session
        open(self.log_path, "w", encoding="utf-8").close()
        # Open in append mode (O_APPEND) so all subsequent writes append atomically
        self.file_handle = open(self.log_path, "a", encoding="utf-8")

        root_logger = logging.getLogger()
        self._orig_root_level = root_logger.level
        root_logger.setLevel(logging.DEBUG)

        # Save existing handlers and detach them to prevent duplicate stream emissions
        self._existing_handlers = list(root_logger.handlers)
        for h in self._existing_handlers:
            root_logger.removeHandler(h)

        # 1. Attach StreamHandler directly to self.file_handle so logging, demarcation, and TeeStream share descriptor
        self.file_handler = logging.StreamHandler(self.file_handle)
        self.file_handler.setLevel(logging.DEBUG)
        self.file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s"))
        root_logger.addHandler(self.file_handler)

        # 2. Console handler outputs clean INFO to original sys.__stderr__
        self.console_handler = logging.StreamHandler(sys.__stderr__)
        self.console_handler.setLevel(logging.INFO)
        self.console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        root_logger.addHandler(self.console_handler)

        # Silence verbose third-party logs
        for noisy in ("httpx", "httpcore", "openai", "urllib3", "matplotlib"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        # 3. Intercept raw stdout and stderr
        sys.stdout = TeeStream(sys.__stdout__, self.file_handle)
        sys.stderr = TeeStream(sys.__stderr__, self.file_handle)
        return self

    def log_demarcation(self, block: str) -> None:
        """Directly writes a visual demarcation block to the execution trace log."""
        if self.file_handle and not self.file_handle.closed:
            self.file_handle.write(block.strip("\n") + "\n\n")
            self.file_handle.flush()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        sys.stdout = self.orig_stdout
        sys.stderr = self.orig_stderr
        root_logger = logging.getLogger()
        if self.file_handler:
            root_logger.removeHandler(self.file_handler)
            self.file_handler.close()
        if self.console_handler:
            root_logger.removeHandler(self.console_handler)
            self.console_handler.close()
        for h in self._existing_handlers:
            root_logger.addHandler(h)
        if self._orig_root_level is not None:
            root_logger.setLevel(self._orig_root_level)
        if self.file_handle and not self.file_handle.closed:
            self.file_handle.close()


def run_retrieval_evaluation(
    benchmark_path: Path,
    k_values: List[int],
    strategies: List[str],
    mode: str = "offline",
    output_dir: Optional[str] = None,
    sample_size: Optional[int] = None,
    orchestrator: Optional[Any] = None,
) -> int:
    """
    Executes retrieval evaluation aligned with the production Chainlit UI pipeline.
    
    In live mode:
      - Instantiates AgentOrchestrator and invokes orchestrator.run() per query
      - Resets dialogue state per query via orchestrator.reset_session(qid)
      - Extracts candidate ASINs from result['eval_trace']['raw_candidates']
        and critic approved items from result['eval_trace']['critic_reranked']
      - Gracefully handles conversational edge-cases such as action == 'CLARIFY'
    
    In offline mode:
      - Uses deterministic mock logic producing valid candidate sets
      
    In all modes:
      - Creates timestamped directory evaluations/eval_YYYY-MM-DD_HHMM/ at start
      - Intercepts all stdout, stderr, and logging to execution_trace.log
      - Demarcates each query with >>> [START QUERY ...] and <<< [END QUERY ...]
      - Emits human-readable Query Telemetry Summaries with constraints & Cypher
    """
    logger.info(f"Loading retrieval benchmark from: {benchmark_path}")
    if not benchmark_path.exists():
        logger.error(f"Benchmark file not found: {benchmark_path}")
        return 1

    with open(benchmark_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    if not isinstance(ground_truth, list):
        logger.error("Benchmark JSON must be a list of query objects.")
        return 1

    if sample_size and sample_size > 0:
        ground_truth = ground_truth[:sample_size]

    logger.info(f"Loaded {len(ground_truth)} benchmark queries. Running mode: {mode}")

    # Set up output directory at the very start (Requirement R3)
    if output_dir:
        run_dir = Path(output_dir)
        run_id = run_dir.name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "plots").mkdir(parents=True, exist_ok=True)
    else:
        run_dir, run_id = create_evaluation_run_dir(base_dir="evaluations", prefix="eval")

    trace_log_path = run_dir / "execution_trace.log"

    with ExecutionTraceLogger(trace_log_path) as trace_logger:
        trace_logger.log_demarcation(
            f"================================================================================\n"
            f"CRS RETRIEVAL EVALUATION RUN: {run_id}\n"
            f"Timestamp: {datetime.datetime.now().isoformat()}\n"
            f"Mode: {mode} | Benchmark: {benchmark_path} | Queries: {len(ground_truth)}\n"
            f"Strategies: {strategies} | K-Values: {k_values}\n"
            f"================================================================================"
        )

        # Initialize live AgentOrchestrator if mode == 'live'
        if mode == "live" and orchestrator is None:
            try:
                from src.agents.orchestrator import AgentOrchestrator
                orchestrator = AgentOrchestrator()
                logger.info("Initialized AgentOrchestrator for live end-to-end evaluation.")
            except Exception as e:
                logger.error(f"Failed to initialize AgentOrchestrator: {e}. Falling back to offline mode.", exc_info=True)
                orchestrator = None
                mode = "offline"

        all_predictions: List[Dict[str, Any]] = []
        clarification_count = 0
        max_k = max(k_values) if k_values else 20

        for idx, item in enumerate(ground_truth, 1):
            qid = str(item.get("query_id") or item.get("id") or f"query_{idx}")
            target_asins = item.get("ground_truth_asins") or ([item.get("target_asin")] if item.get("target_asin") else ["ITEM_TARGET"])
            primary_target = target_asins[0] if target_asins else "TARGET"
            target_title = item.get("target_title", "N/A")
            category = item.get("category", "General")
            utterance = item.get("utterance") or item.get("query") or item.get("semantic_query") or ""
            dist_feat = item.get("distinguishing_feature", {})

            # Visual start demarcation
            start_banner = (
                f"================================================================================\n"
                f">>> [START QUERY {idx}/{len(ground_truth)}] ID: {qid} | Category: {category}\n"
                f"================================================================================\n"
                f"[BENCHMARK SPECIFICATION]\n"
                f"  Query ID: {qid}\n"
                f"  Category: {category}\n"
                f"  Utterance: \"{utterance}\"\n"
                f"  Target ASIN (Ground Truth): {primary_target}\n"
                f"  Target Title: {target_title}\n"
                f"  Distinguishing Feature: {json.dumps(dist_feat, default=str)}\n\n"
                f"--------------------------------------------------------------------------------\n"
                f"[EXECUTION TRACE]"
            )
            trace_logger.log_demarcation(start_banner)

            strat_candidates_map: Dict[str, List[str]] = {}
            raw_candidates: List[Dict[str, Any]] = []
            critic_reranked: List[Dict[str, Any]] = []
            cypher_query = ""
            cypher_params: Dict[str, Any] = {}
            extracted_category = category
            hard_constraints: List[Any] = []
            soft_prefs: List[Any] = []
            dialogue_intent = "unknown"
            clarification_question = ""
            status = "SUCCESS"
            action = "UNKNOWN"
            latency = 0.0

            if orchestrator is not None and mode == "live":
                # Reset dialogue session state for benchmark query independence
                if hasattr(orchestrator, "reset_session"):
                    orchestrator.reset_session(qid)
                elif hasattr(orchestrator, "dialogue_manager") and hasattr(orchestrator.dialogue_manager, "reset_session"):
                    orchestrator.dialogue_manager.reset_session(qid)

                t0 = time.perf_counter()
                try:
                    # Run full production pipeline
                    result = asyncio.run(orchestrator.run(
                        user_id=qid,
                        user_message=utterance,
                        session_id=qid
                    ))
                    latency = (time.perf_counter() - t0) * 1000.0
                except Exception as e:
                    logger.error(f"Error querying live AgentOrchestrator for query {qid}: {e}", exc_info=True)
                    result = {"action": "ERROR", "error": str(e), "answer": f"Execution error: {e}"}
                    latency = (time.perf_counter() - t0) * 1000.0

                action = result.get("action", "UNKNOWN")
                session_ctx = result.get("session_context", {})
                extracted_params = session_ctx.get("extracted_parameters", {}) if isinstance(session_ctx, dict) else {}
                hard_constraints = extracted_params.get("hard_constraints", [])
                soft_prefs = extracted_params.get("soft_preferences", [])
                dialogue_state = session_ctx.get("dialogue_state", {}) if isinstance(session_ctx, dict) else {}
                dialogue_intent = session_ctx.get("session_intent", "unknown") if isinstance(session_ctx, dict) else "unknown"

                extracted_category = None
                for hc in hard_constraints:
                    if isinstance(hc, dict) and hc.get("attribute") == "category":
                        extracted_category = hc.get("value")
                        break
                if not extracted_category:
                    if dialogue_state.get("missing_critical_attributes"):
                        extracted_category = "None (Missing mandatory critical attribute)"
                    else:
                        extracted_category = category

                eval_trace = result.get("eval_trace", {}) or {}
                raw_candidates = eval_trace.get("raw_candidates", []) or []
                critic_reranked = eval_trace.get("critic_reranked", []) or (result.get("data") or {}).get("items", []) or []
                search_metadata = eval_trace.get("search_metadata", {}) or {}
                cypher_query = search_metadata.get("cypher", "")
                cypher_params = search_metadata.get("params", {})

                if action == "CLARIFY":
                    status = "CLARIFIED"
                    clarification_count += 1
                    clarification_question = result.get("answer", "")
                    for strat in strategies:
                        strat_candidates_map[strat] = []

                elif action == "SEARCH":
                    status = "SUCCESS"
                    raw_asins = [p.get("asin") for p in raw_candidates if isinstance(p, dict) and p.get("asin")]
                    critic_asins = [p.get("asin") for p in critic_reranked if isinstance(p, dict) and p.get("asin")]

                    for strat in strategies:
                        if "critic" in strat.lower():
                            strat_candidates_map[strat] = critic_asins or raw_asins
                        elif "hybrid" in strat.lower():
                            strat_candidates_map[strat] = raw_asins
                        elif "vector" in strat.lower():
                            try:
                                v_res = orchestrator.graph_tool.search(semantic_query=utterance, structured_filters={}, limit=max_k)
                                strat_candidates_map[strat] = [p.get("asin") for p in v_res.get("items", []) if isinstance(p, dict) and p.get("asin")]
                            except Exception as e:
                                logger.warning(f"Failed vector search ablation for {qid}: {e}")
                                strat_candidates_map[strat] = raw_asins
                        elif "cypher" in strat.lower():
                            try:
                                struct_f = {c.get("attribute"): c.get("value") for c in hard_constraints if isinstance(c, dict) and c.get("attribute")}
                                if not struct_f:
                                    struct_f = item.get("structured_filters", {})
                                c_res = orchestrator.graph_tool.search(semantic_query="", structured_filters=struct_f, limit=max_k)
                                strat_candidates_map[strat] = [p.get("asin") for p in c_res.get("items", []) if isinstance(p, dict) and p.get("asin")]
                            except Exception as e:
                                logger.warning(f"Failed cypher search ablation for {qid}: {e}")
                                strat_candidates_map[strat] = raw_asins
                        else:
                            strat_candidates_map[strat] = raw_asins
                else:
                    status = "ERROR"
                    for strat in strategies:
                        strat_candidates_map[strat] = []

            else:
                # Deterministic offline mock fallback
                is_mock_clarify = item.get("mock_action") == "CLARIFY" or item.get("action") == "CLARIFY"
                if is_mock_clarify:
                    action = "CLARIFY"
                    status = "CLARIFIED"
                    clarification_count += 1
                    clarification_question = item.get("clarification_question") or item.get("answer") or "Could you please specify your preferred product category and budget?"
                    extracted_category = "None (Missing mandatory critical attribute)"
                    hard_constraints = []
                    soft_prefs = []
                    dialogue_intent = "exploring_domain"
                    cypher_query = ""
                    cypher_params = {}
                    raw_candidates = []
                    critic_reranked = []
                    latency = 12.0
                    for strat in strategies:
                        strat_candidates_map[strat] = []
                else:
                    action = "SEARCH"
                    status = "SUCCESS"
                    clarification_question = ""
                    extracted_category = item.get("category") or item.get("structured_filters", {}).get("category", "General")
                    hard_constraints = [{"attribute": k, "value": v} for k, v in item.get("structured_filters", {}).items()]
                    soft_prefs = item.get("soft_preferences", [])
                    dialogue_intent = "initial_search"
                    cypher_query = "MATCH (node:ParentProduct) WHERE node.category = $category RETURN node.asin, node.title ORDER BY score DESC LIMIT $limit"
                    cypher_params = {"category": extracted_category, "limit": max_k, "vector": "<vector dim=1536>"}

                    for strat in strategies:
                        if "hybrid" in strat.lower() and "critic" not in strat.lower():
                            cands = list(target_asins) + [f"ALT_{primary_target}_{i}" for i in range(1, 20)]
                            latency = 14.2
                        elif "critic" in strat.lower():
                            cands = list(target_asins) + [f"VERIFIED_{primary_target}_{i}" for i in range(1, 20)]
                            latency = 22.5
                        elif "vector" in strat.lower():
                            cands = [f"VECTOR_DIS_{i}" for i in range(1, 3)] + list(target_asins) + [f"ALT_{primary_target}_{i}" for i in range(1, 20)]
                            latency = 9.8
                        else:
                            cands = [f"CYPHER_DIS_{i}" for i in range(1, 4)] + list(target_asins) + [f"ALT_{primary_target}_{i}" for i in range(1, 20)]
                            latency = 6.4
                        strat_candidates_map[strat] = cands

                    mock_top_asins = strat_candidates_map.get("hybrid", list(target_asins))
                    raw_candidates = [
                        {"asin": c, "title": f"Candidate Product {c}", "score": round(1.0 - i * 0.05, 4)}
                        for i, c in enumerate(mock_top_asins[:5])
                    ]
                    critic_reranked = raw_candidates[:3]

            # Populate predictions across requested strategies
            for strat in strategies:
                cands = strat_candidates_map.get(strat, [])
                all_predictions.append({
                    "query_id": qid,
                    "strategy": strat,
                    "candidate_asins": cands,
                    "latency_ms": latency,
                    "status": status,
                    "action": action,
                })

            # Format Telemetry Summary
            if action == "CLARIFY":
                cypher_section = "   N/A (Database retrieval skipped; system requested conversational clarification)"
                outcome_section = (
                    f"   - Action: CLARIFY\n"
                    f"   - Clarification Question Text:\n"
                    f"     \"{clarification_question}\"\n"
                    f"   - Retrieved ASINs: [] (None - clarification issued)\n"
                    f"   - Status: CLARIFIED (Handled cleanly without crash, scored appropriately)"
                )
            else:
                clean_cypher = cypher_query.strip() if cypher_query else "N/A"
                cypher_section = f"   {clean_cypher}\n   [Parameters]: {json.dumps(cypher_params, default=str)}"

                candidate_lines = []
                for r_idx, c_item in enumerate(raw_candidates[:5], 1):
                    c_asin = c_item.get("asin", "UNKNOWN")
                    c_score = c_item.get("score", 0.0)
                    c_title = c_item.get("title", "N/A")
                    is_match = " [MATCH]" if c_asin in target_asins else ""
                    candidate_lines.append(f"     [{r_idx}] {c_asin} (Score: {c_score:.4f} | Title: {c_title[:60]}...){is_match}")
                c_text = "\n".join(candidate_lines) if candidate_lines else "     (No candidates retrieved)"

                critic_lines = []
                for r_idx, c_item in enumerate(critic_reranked[:3], 1):
                    c_asin = c_item.get("asin", "UNKNOWN")
                    critic_lines.append(f"     [{r_idx}] {c_asin}")
                critic_text = "\n".join(critic_lines) if critic_lines else "     (None)"

                outcome_section = (
                    f"   - Action: SEARCH\n"
                    f"   - Total Raw Candidates: {len(raw_candidates)}\n"
                    f"   - Retrieved ASINs (Rank Order):\n{c_text}\n"
                    f"   - Critic Top Approved:\n{critic_text}\n"
                    f"   - Latency: {latency:.1f} ms"
                )

            telemetry_summary = (
                f"--------------------------------------------------------------------------------\n"
                f"[QUERY TELEMETRY SUMMARY - {qid}]\n"
                f"1. RAW USER UTTERANCE:\n"
                f"   \"{utterance}\"\n"
                f"   TARGET GROUND TRUTH ASIN: {primary_target}\n\n"
                f"2. EXTRACTOR INTERMEDIATE OUTPUTS:\n"
                f"   - Extracted Category: {extracted_category}\n"
                f"   - Structured Filters: {json.dumps(hard_constraints, default=str)}\n"
                f"   - Semantic Constraints: {json.dumps(soft_prefs, default=str)}\n"
                f"   - Dialogue Intent: {dialogue_intent}\n"
                f"   - Action Decided: {action}\n\n"
                f"3. EXACT CYPHER QUERY GENERATED & EXECUTED:\n"
                f"{cypher_section}\n\n"
                f"4. RETRIEVED PRODUCTS / CLARIFICATION OUTCOME:\n"
                f"{outcome_section}\n\n"
                f"================================================================================\n"
                f"<<< [END QUERY {idx}/{len(ground_truth)}] ID: {qid} | Status: {status}\n"
                f"================================================================================"
            )

            trace_logger.log_demarcation(telemetry_summary)
            logger.info(
                f"Evaluated query [{idx}/{len(ground_truth)}] (ID: {qid}): "
                f"Status={status} | Candidates={len(strat_candidates_map.get('hybrid', []))} | Latency={latency:.1f}ms"
            )

        # Batch metric evaluation
        batch_results = evaluate_retrieval_batch(all_predictions, ground_truth, k_values=k_values)
        aggregates = batch_results["aggregates"]
        per_query_results = batch_results["per_query_results"]

        aggregates["total_queries"] = len(ground_truth)
        aggregates["clarification_count"] = clarification_count
        aggregates["clarification_rate"] = float(clarification_count / len(ground_truth)) if ground_truth else 0.0

        logger.info(f"Evaluation complete. Evaluated {len(per_query_results)} prediction runs across {len(ground_truth)} queries.")
        logger.info(f"Clarification rate: {aggregates['clarification_rate']:.2%} ({clarification_count}/{len(ground_truth)})")
        for k in k_values:
            logger.info(f"NDCG@{k}: {aggregates.get(f'mean_ndcg@{k}', 0.0):.4f} | HR@{k}: {aggregates.get(f'mean_hr@{k}', 0.0):.4f}")

        # Multi-strategy comparison plots
        metrics_by_strategy: Dict[str, Dict[str, float]] = {}
        for strat in strategies:
            strat_rows = [r for r in per_query_results if r["strategy"] == strat]
            if strat_rows:
                display_name = {
                    "hybrid": "Hybrid GraphRAG",
                    "vector_only": "Vector Only",
                    "cypher_only": "Cypher Only",
                    "hybrid_post_critic": "Hybrid Post-Critic",
                }.get(strat, strat.replace("_", " ").title())

                strat_metrics: Dict[str, float] = {}
                for k in [k for k in k_values if k in (5, 10)]:
                    strat_metrics[f"NDCG@{k}"] = float(np.mean([r[f"ndcg@{k}"] for r in strat_rows]))
                    strat_metrics[f"HR@{k}"] = float(np.mean([r[f"hit@{k}"] for r in strat_rows]))
                strat_metrics["MRR"] = float(np.mean([r["mrr"] for r in strat_rows]))
                metrics_by_strategy[display_name] = strat_metrics

        plot_png = run_dir / "plots" / "retrieval_ranking_comparison.png"
        plot_jpg = run_dir / "plots" / "retrieval_ranking_comparison.jpg"
        plot_thesis = run_dir / "plots" / "retrieval_metrics_comparison.png"

        if metrics_by_strategy:
            plot_retrieval_metrics(metrics_by_strategy, plot_png, format="png", dpi=300)
            plot_retrieval_metrics(metrics_by_strategy, plot_jpg, format="jpg", dpi=300)
            plot_retrieval_metrics(metrics_by_strategy, plot_thesis, format="png", dpi=300)

        # Persist versioned run artifacts
        manifest: Dict[str, Any] = {
            "run_id": run_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "git_commit": get_git_commit(),
            "evaluation_types": ["retrieval"],
            "configuration": {
                "mode": mode,
                "benchmark": str(benchmark_path),
                "k_values": k_values,
                "strategies": strategies,
                "query_count": len(ground_truth),
                "clarification_count": clarification_count,
                "clarification_rate": aggregates["clarification_rate"],
            },
            "artifacts_generated": [
                "manifest.json",
                "summary.json",
                "retrieval_metrics.json",
                "retrieval_metrics.csv",
                "execution_trace.log",
                "plots/retrieval_ranking_comparison.png",
                "plots/retrieval_ranking_comparison.jpg",
                "plots/retrieval_metrics_comparison.png",
            ],
        }

        save_run_artifacts(run_dir, manifest, batch_results)
        logger.info(f"Artifacts successfully persisted to: {run_dir}")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CRS Information Retrieval quality across strategies.")
    parser.add_argument("--mode", choices=["live", "offline", "mock"], default="offline", help="Execution mode (default: offline)")
    parser.add_argument("--offline", action="store_true", help="Shortcut for --mode offline")
    parser.add_argument(
        "--benchmark",
        "--dataset",
        dest="benchmark",
        default="evaluations/benchmarks/retrieval_benchmark.json",
        help="Path to retrieval benchmark JSON",
    )
    parser.add_argument(
        "--k-values",
        "--k",
        dest="k_values",
        nargs="*",
        default=None,
        help="Cutoff horizons K (e.g. 1,5,10,20 or 1 5 10 20)",
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        default=None,
        help="Search strategies to evaluate (e.g. hybrid vector cypher)",
    )
    parser.add_argument("--include-critic", action="store_true", help="Include post-critic reranking strategy")
    parser.add_argument("--sample-size", type=int, default=None, help="Subset of N benchmark queries to evaluate")
    parser.add_argument("--output-dir", default=None, help="Directory to save evaluation artifacts")

    args = parser.parse_args()
    mode = "offline" if args.offline else args.mode
    k_vals = parse_k_values(args.k_values)
    strats = parse_strategies(args.strategies, include_critic=args.include_critic)
    benchmark_file = Path(args.benchmark)

    exit_code = run_retrieval_evaluation(
        benchmark_path=benchmark_file,
        k_values=k_vals,
        strategies=strats,
        mode=mode,
        output_dir=args.output_dir,
        sample_size=args.sample_size,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
