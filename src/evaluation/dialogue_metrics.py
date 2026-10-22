"""
Dialogue-level evaluation metrics for RS-23 (R2a, FR-014 … FR-018; Technical Specification §5.1.6).

Works on compact per-query records (one per benchmark query, built by `build_query_record`
from the orchestrator result) and reports every share as {value, numerator, n}:
- category-extraction recall (parser-only and pipeline);
- target-admitting category rate (+ categories dropped by MACS);
- spurious-CLARIFY rate (by clarify_reason) and type-explicit non-SEARCH actions;
- clarification recall and precision against gold_action = "CLARIFY".
Items without gold dialogue fields are excluded from the denominators.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from src.agents.orchestrator import CATEGORY_FILTER_KEYS, AgentOrchestrator

FUSION_CHANNELS = ("product", "attribute", "review")
MACS_CATEGORY_DROP_MARKER = "dropped explicit category constraint"

__all__ = [
    "CATEGORY_FILTER_KEYS",
    "category_from_hard_constraints",
    "build_query_record",
    "annotate_target_admission",
    "compute_dialogue_metrics",
    "search_intersection",
    "format_share",
]


def _share(numerator: int, n: int) -> Dict[str, Any]:
    """{value, numerator, n}; value is None when the denominator is 0."""
    return {"value": (numerator / n) if n else None, "numerator": numerator, "n": n}


def category_from_hard_constraints(hard_constraints: Optional[Sequence[Any]]) -> Optional[str]:
    """First non-null category value among session-context hard constraints (attribute in CATEGORY_FILTER_KEYS)."""
    return AgentOrchestrator._category_from_hard_constraints(list(hard_constraints or []))


def _target_channel_ranks(raw_candidates: Sequence[Any], target_asin: Optional[str]) -> Optional[Dict[str, Optional[int]]]:
    """Per-channel ranks of the target in the default search's candidates; None if not retrieved."""
    if not target_asin:
        return None
    for candidate in raw_candidates or []:
        if isinstance(candidate, Mapping) and candidate.get("asin") == target_asin:
            channels = ((candidate.get("fusion") or {}).get("channels") or {}) if isinstance(candidate.get("fusion"), Mapping) else {}
            return {c: (channels.get(c) or {}).get("rank") if isinstance(channels.get(c), Mapping) else None for c in FUSION_CHANNELS}
    return None


def build_query_record(
    item: Mapping[str, Any],
    result: Optional[Mapping[str, Any]],
    latency_ms: float,
) -> Dict[str, Any]:
    """
    Builds the dialogue part of a per-query record from a benchmark item and an
    `AgentOrchestrator.run` result: query_id, action, clarify_reason, type_explicit,
    gold_action, gold_product_type, parser_category, pipeline_category, category_source,
    recovery_outcome, applied_category {normalized, raw}, category_dropped_by_macs,
    relaxed_constraints, target_asin, target_channel_ranks, latency_ms.
    `target_admitted`, `target_review_embedded`, gold labels and per-strategy fields are
    added by the evaluation script.

    `pipeline_category` is `category_resolution.category`, else the category of the executed
    search request. `category_source` is the resolution source, or "search_request" when only
    the search request carried the category (the SEARCH branch's own search-params call).
    """
    result = result or {}
    eval_trace = result.get("eval_trace") or {}
    session_context = result.get("session_context") or {}
    extracted = (session_context.get("extracted_parameters") or {}) if isinstance(session_context, Mapping) else {}
    resolution = eval_trace.get("category_resolution") or {}
    search_request = eval_trace.get("search_request") or {}
    search_metadata = eval_trace.get("search_metadata") or {}
    relaxed = list(eval_trace.get("relaxed_constraints") or [])

    parser_category = category_from_hard_constraints(extracted.get("hard_constraints"))
    request_category = AgentOrchestrator._category_from_filters(search_request.get("structured_filters"))
    normalized_category = AgentOrchestrator._category_from_filters(search_metadata.get("normalized_filters"))
    resolved_category = resolution.get("category")
    if resolved_category:
        pipeline_category, category_source = resolved_category, resolution.get("source")
    elif request_category:
        pipeline_category, category_source = request_category, "search_request"
    else:
        pipeline_category, category_source = None, None

    target_asin = item.get("target_asin") or next(iter(item.get("ground_truth_asins") or []), None)
    return {
        "query_id": str(item.get("query_id") or item.get("id") or ""),
        "action": result.get("action") or "UNKNOWN",
        "clarify_reason": eval_trace.get("clarify_reason"),
        "type_explicit": item.get("type_explicit"),
        "gold_action": item.get("gold_action"),
        "gold_product_type": item.get("gold_product_type"),
        "parser_category": parser_category,
        "pipeline_category": pipeline_category,
        "category_source": category_source,
        "recovery_attempted": bool(resolution.get("recovery_attempted", False)),
        "recovery_outcome": resolution.get("recovery_outcome"),
        "applied_category": {"normalized": normalized_category or request_category, "raw": request_category} if request_category else None,
        "target_admitted": None,
        "category_dropped_by_macs": any(MACS_CATEGORY_DROP_MARKER in str(r).lower() for r in relaxed),
        "relaxed_constraints": relaxed,
        "target_asin": target_asin,
        "target_review_embedded": None,
        "target_channel_ranks": _target_channel_ranks(eval_trace.get("raw_candidates") or [], target_asin),
        "latency_ms": latency_ms,
        "legacy_reconstructed": False,
    }


def annotate_target_admission(record: Dict[str, Any], graph_tool: Any) -> Optional[bool]:
    """
    Sets record["target_admitted"] (FR-015) for SEARCH records whose request carried a category:
    whether the target satisfies the category predicate as applied, i.e.
    `graph_tool.match_category([target], normalized_category, raw_category=request_category)`.
    Other records keep None and are excluded from the rate's denominator.
    """
    applied = record.get("applied_category")
    target = record.get("target_asin")
    if graph_tool is None or record.get("action") != "SEARCH" or not isinstance(applied, Mapping) or not applied.get("raw") or not target:
        return None
    matched = graph_tool.match_category([target], applied.get("normalized") or applied["raw"], raw_category=applied["raw"]) or set()
    record["target_admitted"] = target in matched
    return record["target_admitted"]


def compute_dialogue_metrics(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Computes the summary.json["dialogue"] block (§5.1.6): n_queries, cer_parser,
    cer_pipeline, spurious_clarify (with query_ids and by_reason), type_explicit_non_search,
    clarification_recall, clarification_precision, target_admitting_category (with
    category_dropped_by_macs), category_source_counts and recovery_calls. A zero
    denominator gives value None.

    `type_explicit_non_search` counts ANSWER, ERROR and other actions that are neither SEARCH
    nor CLARIFY (CLARIFY on type-explicit queries is the spurious-CLARIFY metric).
    """
    records = list(records)
    explicit = [r for r in records if r.get("type_explicit") is True]
    gold_annotated = [r for r in records if r.get("gold_action") in ("SEARCH", "CLARIFY")]
    gold_clarify = [r for r in gold_annotated if r.get("gold_action") == "CLARIFY"]
    clarify_actions = [r for r in gold_annotated if r.get("action") == "CLARIFY"]

    spurious = [r for r in explicit if r.get("action") == "CLARIFY"]
    non_search = [r for r in explicit if r.get("action") not in ("SEARCH", "CLARIFY")]

    admitting_rows = [
        r for r in records
        if r.get("action") == "SEARCH" and isinstance(r.get("applied_category"), Mapping)
        and r["applied_category"].get("raw") and r.get("target_admitted") is not None
    ]
    target_admitting = _share(sum(1 for r in admitting_rows if r.get("target_admitted") is True), len(admitting_rows))
    target_admitting["category_dropped_by_macs"] = sum(1 for r in admitting_rows if r.get("category_dropped_by_macs"))

    spurious_block = _share(len(spurious), len(explicit))
    spurious_block["query_ids"] = [r.get("query_id") for r in spurious]
    spurious_block["by_reason"] = dict(Counter(str(r.get("clarify_reason") or "unknown") for r in spurious))

    return {
        "n_queries": len(records),
        "cer_parser": _share(sum(1 for r in explicit if r.get("parser_category")), len(explicit)),
        "cer_pipeline": _share(sum(1 for r in explicit if r.get("pipeline_category")), len(explicit)),
        "spurious_clarify": spurious_block,
        "type_explicit_non_search": {
            "numerator": len(non_search), "n": len(explicit), "query_ids": [r.get("query_id") for r in non_search],
        },
        "clarification_recall": _share(sum(1 for r in gold_clarify if r.get("action") == "CLARIFY"), len(gold_clarify)),
        "clarification_precision": _share(sum(1 for r in clarify_actions if r.get("gold_action") == "CLARIFY"), len(clarify_actions)),
        "target_admitting_category": target_admitting,
        "category_source_counts": dict(Counter(
            str(r.get("category_source")) for r in records if r.get("action") == "SEARCH" and r.get("category_source")
        )),
        "recovery_calls": sum(1 for r in records if r.get("recovery_attempted")),
    }


def search_intersection(records_by_run: Mapping[str, Sequence[Mapping[str, Any]]]) -> Set[str]:
    """Query IDs whose action was SEARCH in every run (records without `action` count as SEARCH)."""
    result: Optional[Set[str]] = None
    for records in records_by_run.values():
        ids = {
            str(r.get("query_id")) for r in records
            if r.get("query_id") is not None and r.get("action", "SEARCH") in (None, "SEARCH")
        }
        result = ids if result is None else result & ids
    return result or set()


def format_share(block: Optional[Mapping[str, Any]]) -> str:
    """Log formatting for a share block: "0.810 (17/21)", or "n/a (n=0)" when the denominator is 0."""
    if not isinstance(block, Mapping):
        return "n/a (n=0)"
    n = block.get("n") or 0
    value = block.get("value")
    if not n or value is None:
        return f"n/a (n={n})"
    return f"{value:.3f} ({block.get('numerator', 0)}/{n})"
