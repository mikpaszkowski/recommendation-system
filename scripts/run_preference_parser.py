"""
scripts/run_preference_parser.py

Multi-turn conversation test script and preference parser CLI harness.
Fulfills Requirement R1, R2, R3 and Acceptance Criteria 1.1 (ORIGINAL_REQUEST.md).

Features:
- Multi-turn conversation tracking via DialogueManager
- LLM extraction via LLMPreferenceParser (with offline MockPreferenceParser fallback)
- Consolidated session context pretty-printing and canonical JSON schema display
- Automated demo mode (--demo) with realistic multi-turn scenarios
- Interactive CLI mode with session management commands (/reset, /summary, /json, /exit)
- Single-utterance evaluation mode (backward-compatible CLI arguments)
- Integrated category embedding vector search via Neo4j category_embedding_index

Usage:
  # Automated demo mode (category vector search enabled by default)
  python scripts/run_preference_parser.py --demo

  # Interactive multi-turn CLI session
  python scripts/run_preference_parser.py --interactive

  # Single utterance evaluation with category vector search
  python scripts/run_preference_parser.py "I want a lightweight laptop under $1000 without ChromeOS"

  # Force offline mock parser without vector resolution
  python scripts/run_preference_parser.py --demo --mock --no-resolve-categories
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure project root is on sys.path so `src` and `tests` imports resolve
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.dialog_manager.dialogue_manager import DialogueManager
from src.dialog_manager.session_adapter import (
    hard_constraints_to_structured_filters,
    session_context_to_legacy_preferences,
)
from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContextWrapper,
    HardConstraint,
    SessionContext,
    SessionIntent,
    SoftPreference,
    SuggestedSystemAction,
)

logger = logging.getLogger("run_preference_parser")


# ==============================================================================
# Deterministic Mock Parser for Offline / CI Execution
# ==============================================================================

class MockPreferenceParser:
    """
    Deterministic offline mock preference parser.
    Provides realistic, schema-valid extractions for demo scenarios and rule-based
    heuristic extractions for interactive mode when OPENAI_API_KEY is not configured.
    """

    def __init__(self) -> None:
        self.canned_responses: Dict[str, Dict[str, Any]] = {
            # College student scenario (Canonical 4-turn sequence)
            "college_turn1": {
                "session_intent": "initial_search",
                "situational_context": "User is starting college computer science; needs lightweight laptop with all-day battery.",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "category", "operator": "include", "value": "laptop"}
                    ],
                    "soft_preferences": [
                        {"category": "weight", "value": "lightweight", "polarity": 0.85, "confidence": 0.9, "evidence": "easy to carry on campus"},
                        {"category": "battery", "value": "all-day battery", "polarity": 0.9, "confidence": 0.9, "evidence": "last all day in lectures"}
                    ]
                },
                "dialogue_state": {
                    "ready_for_recommendation": False,
                    "missing_critical_attributes": ["price"],
                    "suggested_system_action": "ask_clarification"
                }
            },
            "college_turn2": {
                "session_intent": "refining_options",
                "situational_context": "User is setting hard $1000 budget and excluding ChromeOS.",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "price", "operator": "less_than", "value": 1000},
                        {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}
                    ],
                    "soft_preferences": []
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results"
                }
            },
            "college_turn3": {
                "session_intent": "comparing_items",
                "situational_context": "User is comparing Apple MacBooks against Dell XPS under $1000.",
                "extracted_parameters": {
                    "hard_constraints": [],
                    "soft_preferences": [
                        {"category": "brand", "value": "Apple", "polarity": 0.6, "confidence": 0.8, "evidence": "comparing Apple MacBooks"},
                        {"category": "brand", "value": "Dell", "polarity": 0.6, "confidence": 0.8, "evidence": "comparing Dell XPS"}
                    ]
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results"
                }
            },
            "college_turn4": {
                "session_intent": "finalizing_choice",
                "situational_context": "User finalized choice on MacBook Air M1 under $900.",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "model", "operator": "include", "value": "MacBook Air M1"},
                        {"attribute": "price", "operator": "less_than", "value": 900}
                    ],
                    "soft_preferences": []
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results"
                }
            },
            # Topic shift scenario
            "topic_turn1": {
                "session_intent": "initial_search",
                "situational_context": "User is looking for high-performance gaming PC under $1500.",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "category", "operator": "include", "value": "gaming pc"},
                        {"attribute": "price", "operator": "less_than", "value": 1500}
                    ],
                    "soft_preferences": [
                        {"category": "performance", "value": "high performance", "polarity": 0.9, "confidence": 0.9, "evidence": "high-performance gaming PC"}
                    ]
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results"
                }
            },
            "topic_turn2": {
                "session_intent": "refining_options",
                "situational_context": "User shifting domain to noise-cancelling headphones under $300 by Sony.",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "category", "operator": "include", "value": "headphones"},
                        {"attribute": "price", "operator": "less_than", "value": 300},
                        {"attribute": "brand", "operator": "include", "value": "Sony"}
                    ],
                    "soft_preferences": [
                        {"category": "feature", "value": "noise-cancelling", "polarity": 0.95, "confidence": 0.95, "evidence": "noise-cancelling headphones"}
                    ]
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "change_topic"
                }
            },
            "topic_turn3": {
                "session_intent": "refining_options",
                "situational_context": "User refining headphone preference for black color and over-ear design.",
                "extracted_parameters": {
                    "hard_constraints": [],
                    "soft_preferences": [
                        {"category": "form_factor", "value": "over-ear", "polarity": 0.8, "confidence": 0.85, "evidence": "over-ear design"},
                        {"category": "color", "value": "black", "polarity": 0.7, "confidence": 0.8, "evidence": "black color"}
                    ]
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results"
                }
            },
        }

    def extract_preferences(self, text: str) -> Dict[str, Any]:
        """Match canned responses or extract with rule-based heuristics."""
        t_clean = text.lower().strip()

        # Match canned college turns
        if "college" in t_clean or "starting college" in t_clean:
            return {"current_session_context": self.canned_responses["college_turn1"]}
        if ("under 1000" in t_clean or "under $1000" in t_clean) and ("chromeos" in t_clean or "budget" in t_clean or "definitely don't" in t_clean or "without chromeos" in t_clean):
            return {"current_session_context": self.canned_responses["college_turn2"]}
        if "macbook" in t_clean and ("compare" in t_clean or "xps" in t_clean or "how do" in t_clean):
            return {"current_session_context": self.canned_responses["college_turn3"]}
        if "air m1" in t_clean or "under 900" in t_clean or "under $900" in t_clean or "go with" in t_clean:
            return {"current_session_context": self.canned_responses["college_turn4"]}

        # Match canned topic turns
        if "gaming pc" in t_clean or "desktop" in t_clean:
            return {"current_session_context": self.canned_responses["topic_turn1"]}
        if "switch topic" in t_clean or "headphones" in t_clean:
            return {"current_session_context": self.canned_responses["topic_turn2"]}
        if "over-ear" in t_clean or "black color" in t_clean:
            return {"current_session_context": self.canned_responses["topic_turn3"]}

        # Heuristic fallback for arbitrary text
        return self._heuristic_extract(text)

    def _heuristic_extract(self, text: str) -> Dict[str, Any]:
        t_clean = text.lower().strip()
        hard_constraints: List[Dict[str, Any]] = []
        soft_preferences: List[Dict[str, Any]] = []
        intent = "initial_search"

        # Check intent keywords
        if any(w in t_clean for w in ["compare", "versus", "vs", "which is better"]):
            intent = "comparing_items"
        elif any(w in t_clean for w in ["buy", "choose", "go with", "final", "finalize", "order"]):
            intent = "finalizing_choice"
        elif any(w in t_clean for w in ["browse", "explore", "what do you have", "show me options"]):
            intent = "exploring_domain"
        elif any(w in t_clean for w in ["also", "and", "change", "actually", "prefer", "rather"]):
            intent = "refining_options"

        # Check category
        categories = ["laptop", "phone", "headphones", "monitor", "keyboard", "mouse", "tablet", "pc"]
        for cat in categories:
            if cat in t_clean:
                hard_constraints.append({"attribute": "category", "operator": "include", "value": cat})
                break

        # Check price
        price_match = re.search(r"(?:under|less than|budget)\s*[$€£]?\s*(\d+)", t_clean)
        if price_match:
            val = float(price_match.group(1))
            hard_constraints.append({"attribute": "price", "operator": "less_than", "value": int(val) if val.is_integer() else val})
        else:
            min_match = re.search(r"(?:above|more than|at least|min)\s*[$€£]?\s*(\d+)", t_clean)
            if min_match:
                val = float(min_match.group(1))
                hard_constraints.append({"attribute": "price", "operator": "greater_than", "value": int(val) if val.is_integer() else val})

        # Check exclusions
        excl_match = re.search(r"(?:no|exclude|don\'t want|without)\s+([a-zA-Z0-9_\-]+)", t_clean)
        if excl_match:
            excl_val = excl_match.group(1).strip()
            hard_constraints.append({
                "attribute": "brand" if excl_val in ["apple", "dell", "sony", "lenovo"] else "operating_system" if "chrome" in excl_val or "windows" in excl_val else "feature",
                "operator": "exclude",
                "value": excl_val,
            })

        # Check brands
        for brand in ["Apple", "Dell", "Sony", "Lenovo", "HP", "Asus", "Bose"]:
            if brand.lower() in t_clean and not any(hc.get("value") == brand for hc in hard_constraints if hc.get("operator") == "exclude"):
                soft_preferences.append({
                    "category": "brand",
                    "value": brand,
                    "polarity": 0.8,
                    "confidence": 0.9,
                    "evidence": f"User mentioned {brand}"
                })

        # Check soft features
        for feat in ["lightweight", "portable", "quiet", "fast", "durable", "battery"]:
            if feat in t_clean:
                soft_preferences.append({
                    "category": feat,
                    "value": feat,
                    "polarity": 0.8,
                    "confidence": 0.8,
                    "evidence": f"User mentioned {feat}"
                })

        has_cat = any(hc["attribute"] == "category" for hc in hard_constraints)
        ready = has_cat
        missing = [] if has_cat else ["category"]
        action = "present_results" if ready else "ask_clarification"

        return {
            "current_session_context": {
                "session_intent": intent,
                "situational_context": f"User inquiry: {text[:80]}",
                "extracted_parameters": {
                    "hard_constraints": hard_constraints,
                    "soft_preferences": soft_preferences,
                },
                "dialogue_state": {
                    "ready_for_recommendation": ready,
                    "missing_critical_attributes": missing,
                    "suggested_system_action": action,
                }
            }
        }

    def format_for_recommender(self, preferences: Any) -> Dict[str, Any]:
        return session_context_to_legacy_preferences(preferences)


# ==============================================================================
# Category Extraction and Vector Resolution
# ==============================================================================

def _extract_categories(payload: Union[Dict[str, Any], Any]) -> List[str]:
    """
    Extract category strings from either canonical SessionContext,
    CurrentSessionContextWrapper, or legacy preference payloads.
    """
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    if not isinstance(payload, dict):
        return []

    categories: List[str] = []

    # 1. Canonical current_session_context check
    inner = payload.get("current_session_context", payload)
    if isinstance(inner, dict):
        params = inner.get("extracted_parameters", {})
        if isinstance(params, dict):
            for hc in params.get("hard_constraints", []):
                if isinstance(hc, dict) and hc.get("attribute", "").lower().strip() in (
                    "category", "product_category", "product_type", "categories", "type"
                ):
                    val = str(hc.get("value", "")).strip()
                    if val and val not in categories:
                        categories.append(val)
            for sp in params.get("soft_preferences", []):
                if isinstance(sp, dict) and sp.get("category", "").lower().strip() in (
                    "category", "product_category", "product_type", "categories", "type"
                ):
                    val = str(sp.get("value", "")).strip()
                    if val and val not in categories:
                        categories.append(val)

    # 2. Legacy constraints.categories check
    constraints = payload.get("constraints", {})
    if isinstance(constraints, dict):
        cats = constraints.get("categories", [])
        if isinstance(cats, list):
            for c in cats:
                if c and str(c) not in categories:
                    categories.append(str(c))
        cat = constraints.get("category")
        if cat and str(cat) not in categories:
            categories.append(str(cat))

    # 3. Top-level categories key check
    top_cat = payload.get("categories")
    if top_cat:
        if isinstance(top_cat, list):
            for c in top_cat:
                if c and str(c) not in categories:
                    categories.append(str(c))
        elif isinstance(top_cat, str) and top_cat not in categories:
            categories.append(top_cat)

    return categories


# ------------------------------------------------------------------------------
# Cached ResolverService Singleton
# ------------------------------------------------------------------------------

_RESOLVER_INSTANCE: Optional[Any] = None
_RESOLVER_FAILED: bool = False


def get_category_resolver() -> Optional[Any]:
    """
    Get or create a cached ResolverService instance.
    Degrades gracefully if Neo4j or sentence-transformers is unavailable.
    """
    global _RESOLVER_INSTANCE, _RESOLVER_FAILED
    if _RESOLVER_FAILED:
        return None
    if _RESOLVER_INSTANCE is not None:
        return _RESOLVER_INSTANCE

    try:
        from src.knowledge_graph.graphdb.resolver_service import ResolverService
        _RESOLVER_INSTANCE = ResolverService()
        return _RESOLVER_INSTANCE
    except ImportError as e:
        logger.info(f"ResolverService could not be imported: {e}. Vector resolution disabled.")
        _RESOLVER_FAILED = True
        return None
    except Exception as e:
        logger.warning(f"Could not connect to Neo4j or initialize ResolverService: {e}")
        _RESOLVER_FAILED = True
        return None


def _format_category_path(path: Any) -> str:
    """Format category hierarchy path into a clean string (e.g. A > B > C)."""
    if isinstance(path, list):
        return " > ".join(str(p).strip() for p in path if str(p).strip())
    if isinstance(path, str) and path.strip():
        if path.startswith("[") and path.endswith("]"):
            try:
                import ast
                parsed = ast.literal_eval(path)
                if isinstance(parsed, list):
                    return " > ".join(str(p).strip() for p in parsed if str(p).strip())
            except Exception:
                pass
        return path.strip()
    return ""


def _resolve_categories(
    categories: List[str],
    resolver: Optional[Any] = None,
    k: int = 3,
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """
    Run an embedding vector search against the knowledge graph for each
    category string and return the matched Category nodes.
    Returns None gracefully if Neo4j or ResolverService is not reachable.
    """
    if not categories:
        return None

    active_resolver = resolver if resolver is not None else get_category_resolver()
    if active_resolver is None:
        return None

    results: Dict[str, List[Dict[str, Any]]] = {}
    for cat in categories:
        try:
            matches = active_resolver.resolve_category(cat, k=k)
            results[cat] = matches
        except Exception as e:
            logger.warning(f"Error resolving category '{cat}' via vector embedding search: {e}")
            results[cat] = []

    return results


def _print_resolved_categories(resolved: Dict[str, List[Dict[str, Any]]]) -> None:
    """Pretty-print the embedding-resolved category matches with similarity scores and paths."""
    print("\n[Category Vector Search (Embedding Index: category_embedding_index)]")
    for cat, matches in resolved.items():
        print(f"  • Query Category : '{cat}'")
        if not matches:
            print("    ↳ (no matches found above score threshold in knowledge graph)")
        else:
            print("    ↳ Matched Knowledge Graph Categories:")
            for idx, match in enumerate(matches, start=1):
                name = match.get("name", "Unknown")
                score = match.get("score", 0.0)
                path = _format_category_path(match.get("path"))
                path_info = f" | Hierarchy: {path}" if path else ""
                print(f"        {idx}. {name} (Similarity: {score:.4f}){path_info}")


# ==============================================================================
# Visual Formatting & Turn Evolution Display
# ==============================================================================

def print_turn_evolution(
    turn_num: int,
    user_utterance: str,
    turn_extraction: Dict[str, Any],
    consolidated_wrapper: CurrentSessionContextWrapper,
    prev_summary: Optional[Dict[str, Any]] = None,
    raw_json_only: bool = False,
    resolved_categories: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    Pretty-print the consolidated JSON schema (current_session_context) showing
    how session_intent, hard_constraints, soft_preferences, and dialogue_state evolve.
    Integrates category vector search results if resolved_categories is provided.
    """
    if raw_json_only:
        print(consolidated_wrapper.to_json(indent=2))
        ctx = consolidated_wrapper.current_session_context
        return {
            "intent": ctx.session_intent.value if hasattr(ctx.session_intent, "value") else str(ctx.session_intent),
            "hard_count": len(ctx.extracted_parameters.hard_constraints),
            "soft_count": len(ctx.extracted_parameters.soft_preferences),
            "resolved_categories": resolved_categories,
        }

    ctx = consolidated_wrapper.current_session_context
    curr_intent = ctx.session_intent.value if hasattr(ctx.session_intent, "value") else str(ctx.session_intent)
    curr_summary = {
        "intent": curr_intent,
        "hard_count": len(ctx.extracted_parameters.hard_constraints),
        "soft_count": len(ctx.extracted_parameters.soft_preferences),
        "ready": ctx.dialogue_state.ready_for_recommendation,
        "missing": list(ctx.dialogue_state.missing_critical_attributes),
        "action": ctx.dialogue_state.suggested_system_action.value if hasattr(ctx.dialogue_state.suggested_system_action, "value") else str(ctx.dialogue_state.suggested_system_action),
        "resolved_categories": resolved_categories,
    }

    print("\n" + "=" * 80)
    print(f"  TURN {turn_num} | User: \"{user_utterance}\"")
    print("=" * 80)

    # 1. Turn extraction summary
    extracted_inner = turn_extraction.get("current_session_context", turn_extraction)
    turn_intent = extracted_inner.get("session_intent", "initial_search")
    if hasattr(turn_intent, "value"):
        turn_intent = turn_intent.value
    turn_sit = extracted_inner.get("situational_context", "")

    print(f"\n[Turn Extraction -> LLMPreferenceParser]")
    print(f"  • Detected Turn Intent : {turn_intent}")
    if turn_sit:
        print(f"  • Situational Context  : {turn_sit}")

    # 2. Accumulated session context
    print(f"\n[Consolidated Session State -> DialogueManager]")
    if prev_summary and prev_summary.get("intent") != curr_summary["intent"]:
        print(f"  • Session Intent Transition : {prev_summary['intent']} ➔ {curr_summary['intent']}")
    else:
        print(f"  • Session Intent            : {curr_summary['intent']}")

    if ctx.situational_context:
        print(f"  • Situational Context       : {ctx.situational_context}")

    # Hard constraints
    hard_list = ctx.extracted_parameters.hard_constraints
    print(f"  • Hard Constraints ({len(hard_list)} accumulated):")
    if not hard_list:
        print("      (none)")
    else:
        for hc in hard_list:
            op_sym = {
                ConstraintOperator.LESS_THAN: "<",
                ConstraintOperator.GREATER_THAN: ">",
                ConstraintOperator.EQUAL: "==",
                ConstraintOperator.INCLUDE: "include",
                ConstraintOperator.EXCLUDE: "exclude",
            }.get(hc.operator, hc.operator.value if hasattr(hc.operator, "value") else str(hc.operator))
            op_label = hc.operator.value if hasattr(hc.operator, "value") else str(hc.operator)

            # Show vector resolution inline for category constraints
            if hc.attribute in ("category", "product_category", "product_type", "type") and resolved_categories:
                cat_val = str(hc.value).strip()
                matches = resolved_categories.get(cat_val) or resolved_categories.get(cat_val.lower(), [])
                if matches:
                    best = matches[0]
                    best_name = best.get("name", "")
                    best_score = best.get("score", 0.0)
                    best_path = _format_category_path(best.get("path"))
                    path_str = f" | {best_path}" if best_path else ""
                    print(f"      - [{hc.attribute}] {op_sym} {hc.value!r} ({op_label})")
                    print(f"          ↳ Vector Match: {best_name!r} (similarity: {best_score:.4f}{path_str})")
                    continue
            print(f"      - [{hc.attribute}] {op_sym} {hc.value!r} ({op_label})")

    # Soft preferences
    soft_list = ctx.extracted_parameters.soft_preferences
    print(f"  • Soft Preferences ({len(soft_list)} accumulated):")
    if not soft_list:
        print("      (none)")
    else:
        for sp in soft_list:
            pol_sign = f"+{sp.polarity:.2f}" if sp.polarity > 0 else f"{sp.polarity:.2f}"
            ev_str = f' -- "{sp.evidence}"' if sp.evidence else ""
            print(f"      - [{sp.category}] {sp.value!r} | polarity: {pol_sign} | confidence: {sp.confidence:.2f}{ev_str}")

    # Dialogue State
    ds = ctx.dialogue_state
    ready_str = "YES (True)" if ds.ready_for_recommendation else "NO (False)"
    missing_str = str(ds.missing_critical_attributes) if ds.missing_critical_attributes else "[] (All satisfied)"
    act_str = ds.suggested_system_action.value if hasattr(ds.suggested_system_action, "value") else str(ds.suggested_system_action)
    print(f"  • Dialogue State:")
    print(f"      - Ready for Recommendation : {ready_str}")
    print(f"      - Missing Critical Fields  : {missing_str}")
    print(f"      - Suggested System Action  : {act_str}")

    # 3. Vector Category Resolution Display
    if resolved_categories:
        _print_resolved_categories(resolved_categories)

    print(f"\n[Canonical JSON: current_session_context]")
    print(consolidated_wrapper.to_json(indent=2))
    print("-" * 80)

    return curr_summary


# ==============================================================================
# Turn Processing Core
# ==============================================================================

def process_dialogue_turn(
    parser_agent: Any,
    dialogue_manager: DialogueManager,
    session_id: str,
    user_utterance: str,
    turn_num: int = 1,
    prev_summary: Optional[Dict[str, Any]] = None,
    raw_json_only: bool = False,
    resolve_categories: bool = True,
    resolver: Optional[Any] = None,
) -> Tuple[Dict[str, Any], CurrentSessionContextWrapper, Dict[str, Any]]:
    """
    Process a single dialogue turn end-to-end:
    1. Parse preferences from utterance.
    2. Accumulate turn into DialogueManager.
    3. Retrieve canonical CurrentSessionContextWrapper.
    4. Perform category embedding vector search against Knowledge Graph.
    5. Pretty-print state evolution, category vector matches, and JSON schema.
    """
    turn_extraction = parser_agent.extract_preferences(user_utterance)
    dialogue_manager.update_turn(session_id, user_utterance, turn_extraction)
    wrapper = dialogue_manager.get_wrapper(session_id)

    # Perform category embedding vector search against Knowledge Graph
    resolved_categories: Optional[Dict[str, List[Dict[str, Any]]]] = None
    if resolve_categories and not raw_json_only:
        categories = _extract_categories(wrapper)
        if categories:
            resolved_categories = _resolve_categories(categories, resolver=resolver)

    curr_summary = print_turn_evolution(
        turn_num=turn_num,
        user_utterance=user_utterance,
        turn_extraction=turn_extraction,
        consolidated_wrapper=wrapper,
        prev_summary=prev_summary,
        raw_json_only=raw_json_only,
        resolved_categories=resolved_categories,
    )

    return turn_extraction, wrapper, curr_summary


# ==============================================================================
# Automated Demo Scenarios
# ==============================================================================

DEMO_SCENARIOS = {
    "college_laptop": [
        "Hi, I'm starting college next month and need a lightweight laptop for computer science with all-day battery.",
        "My budget is strictly under $1000, and I definitely don't want ChromeOS.",
        "How do Apple MacBooks compare to Dell XPS in this price range?",
        "I'll go with the M1 MacBook Air if it's under $900.",
    ],
    "topic_shift": [
        "Looking for a high-performance gaming PC under $1500",
        "Actually, let's switch topic, I need noise-cancelling headphones under $300 by Sony",
        "Prefer over-ear design and black color",
    ],
}


def run_demo_scenario(
    scenario_name: str,
    parser_agent: Any,
    dialogue_manager: DialogueManager,
    session_id: str = "demo_session",
    raw_json_only: bool = False,
    resolve_categories: bool = True,
    resolver: Optional[Any] = None,
) -> None:
    """Execute pre-configured multi-turn conversational sequence."""
    utterances = DEMO_SCENARIOS.get(scenario_name)
    if not utterances:
        print(f"Unknown scenario '{scenario_name}'. Available: {list(DEMO_SCENARIOS.keys())}")
        return

    if not raw_json_only:
        print("\n" + "#" * 80)
        print(f"  RUNNING DEMO SCENARIO: {scenario_name.upper()} ({len(utterances)} Turns)")
        print("#" * 80)

    dialogue_manager.reset_session(session_id)
    prev_summary: Optional[Dict[str, Any]] = None

    for idx, utterance in enumerate(utterances, start=1):
        _, _, prev_summary = process_dialogue_turn(
            parser_agent=parser_agent,
            dialogue_manager=dialogue_manager,
            session_id=session_id,
            user_utterance=utterance,
            turn_num=idx,
            prev_summary=prev_summary,
            raw_json_only=raw_json_only,
            resolve_categories=resolve_categories,
            resolver=resolver,
        )

    if not raw_json_only:
        summary = dialogue_manager.get_history_summary(session_id)
        print("\n=== Demo Scenario Completed Successfully ===")
        print(f"Final Intent : {summary['session_intent']}")
        print(f"Ready for DB : {summary['ready_for_recommendation']}")
        print(f"Hard Filters : {summary['hard_constraints_count']}")
        print(f"Soft Desires : {summary['soft_preferences_count']}")


# ==============================================================================
# Interactive CLI Loop
# ==============================================================================

def run_interactive_cli(
    parser_agent: Any,
    dialogue_manager: DialogueManager,
    session_id: str = "interactive_cli_user",
    raw_json_only: bool = False,
    resolve_categories: bool = True,
    resolver: Optional[Any] = None,
) -> None:
    """Run an interactive CLI dialogue session with integrated category vector resolution."""
    print("\n================================================================================")
    print("  Preference Parser & Multi-Turn Dialogue Manager (Interactive Mode)")
    print("================================================================================")
    print("Commands:")
    print("  /reset    - Reset active conversational session context back to empty baseline")
    print("  /summary  - Display compact session history summary")
    print("  /json     - Toggle raw JSON output mode")
    print("  /vector   - Toggle category vector embedding search")
    print("  /help     - Show this help message")
    print("  exit/quit - Exit interactive session\n")

    turn_count = 0
    prev_summary: Optional[Dict[str, Any]] = None

    while True:
        try:
            text = input("User > ").strip()
            if not text:
                continue

            if text.lower() in ("exit", "quit"):
                print("Exiting interactive dialogue session.")
                break

            if text == "/reset":
                dialogue_manager.reset_session(session_id)
                turn_count = 0
                prev_summary = None
                print("Session reset. Context wiped to initial baseline.")
                continue

            if text == "/summary":
                summary = dialogue_manager.get_history_summary(session_id)
                print(f"Session Summary: {json.dumps(summary, indent=2)}")
                continue

            if text == "/json":
                raw_json_only = not raw_json_only
                print(f"Raw JSON only mode: {raw_json_only}")
                continue

            if text == "/vector":
                resolve_categories = not resolve_categories
                status_str = "ENABLED" if resolve_categories else "DISABLED"
                print(f"Category Vector Embedding Search is now: {status_str}")
                continue

            if text == "/help":
                print("Commands: /reset, /summary, /json, /vector, /help, exit, quit")
                continue

            turn_count += 1
            _, _, prev_summary = process_dialogue_turn(
                parser_agent=parser_agent,
                dialogue_manager=dialogue_manager,
                session_id=session_id,
                user_utterance=text,
                turn_num=turn_count,
                prev_summary=prev_summary,
                raw_json_only=raw_json_only,
                resolve_categories=resolve_categories,
                resolver=resolver,
            )

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Turn Preference Parser and Dialogue State CLI Harness"
    )
    parser.add_argument(
        "utterance",
        nargs="*",
        help="Optional single user utterance to parse in direct CLI evaluation mode.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run automated multi-turn demo scenario(s).",
    )
    parser.add_argument(
        "--scenario",
        default="college_laptop",
        choices=["college_laptop", "topic_shift", "all"],
        help="Scenario to run in demo mode (default: college_laptop).",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run interactive turn-by-turn CLI session (default when no utterance provided).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force deterministic offline mock parser without calling OpenAI API.",
    )
    parser.add_argument(
        "--session-id",
        default="cli_session",
        help="Session identifier for state tracking (default: cli_session).",
    )
    parser.add_argument(
        "--critical-attributes",
        default="category,price",
        help="Comma-separated critical attributes for recommendation readiness (default: category,price).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw canonical JSON only.",
    )
    parser.add_argument(
        "--resolve-categories",
        action="store_true",
        default=True,
        help="Perform Neo4j vector category resolution via category_embedding_index (default: True).",
    )
    parser.add_argument(
        "--no-resolve-categories",
        "--skip-vector",
        dest="resolve_categories",
        action="store_false",
        help="Disable Neo4j vector category resolution.",
    )

    args = parser.parse_args()

    # Determine parser agent (live LLM vs. deterministic mock)
    has_api_key = bool(os.getenv("OPENAI_API_KEY"))
    use_mock = args.mock or not has_api_key

    if use_mock:
        if not args.json:
            if not has_api_key and not args.mock:
                print("[INFO] OPENAI_API_KEY not found in environment. Initializing MockPreferenceParser (offline mode).")
            else:
                print("[INFO] Running with deterministic MockPreferenceParser (--mock).")
        parser_agent: Any = MockPreferenceParser()
    else:
        from src.llm_interface.preference_parser import LLMPreferenceParser
        parser_agent = LLMPreferenceParser()

    # Initialize DialogueManager
    crit_attrs = [a.strip() for a in args.critical_attributes.split(",") if a.strip()]
    dialogue_manager = DialogueManager(critical_attributes=crit_attrs)

    # Initialize cached category resolver if vector resolution is requested
    resolver = None
    if args.resolve_categories and not args.json:
        resolver = get_category_resolver()

    # 1. Direct utterance evaluation mode
    if args.utterance:
        text = " ".join(args.utterance).strip()
        process_dialogue_turn(
            parser_agent=parser_agent,
            dialogue_manager=dialogue_manager,
            session_id=args.session_id,
            user_utterance=text,
            turn_num=1,
            raw_json_only=args.json,
            resolve_categories=args.resolve_categories,
            resolver=resolver,
        )
        return

    # 2. Automated demo mode
    if args.demo:
        if args.scenario == "all":
            for sc in ["college_laptop", "topic_shift"]:
                run_demo_scenario(
                    scenario_name=sc,
                    parser_agent=parser_agent,
                    dialogue_manager=dialogue_manager,
                    session_id=f"{args.session_id}_{sc}",
                    raw_json_only=args.json,
                    resolve_categories=args.resolve_categories,
                    resolver=resolver,
                )
        else:
            run_demo_scenario(
                scenario_name=args.scenario,
                parser_agent=parser_agent,
                dialogue_manager=dialogue_manager,
                session_id=args.session_id,
                raw_json_only=args.json,
                resolve_categories=args.resolve_categories,
                resolver=resolver,
            )
        return

    # 3. Interactive CLI mode (default)
    run_interactive_cli(
        parser_agent=parser_agent,
        dialogue_manager=dialogue_manager,
        session_id=args.session_id,
        raw_json_only=args.json,
        resolve_categories=args.resolve_categories,
        resolver=resolver,
    )


if __name__ == "__main__":
    main()
