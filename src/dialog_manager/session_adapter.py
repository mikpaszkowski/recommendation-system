"""
src/dialog_manager/session_adapter.py

Bidirectional compatibility and translation layer between canonical SessionContext
models and existing subsystem components (GraphSearchTool, PromptConstructor,
GraphQueryManager, CriticAgent, PreferenceQuantifier, AgentOrchestrator).

Fulfills Requirement R4: Minimal Architectural Intrusion.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Union

from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContextWrapper,
    DialogueState,
    ExtractedParameters,
    HardConstraint,
    SessionContext,
    SessionIntent,
    SoftPreference,
    SuggestedSystemAction,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility & Normalization Helpers
# ---------------------------------------------------------------------------

def _get_field(obj: Any, field: str, default: Any = None) -> Any:
    """
    Safely retrieve a field from a dict, Pydantic model, or generic object.
    Supports both attribute access (.field) and dict key access (['field']).
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _coerce_numeric(val: Any) -> Optional[float]:
    """
    Coerce numbers, currency strings, or formatted numbers into a float.
    Handles:
      - 1000 -> 1000.0
      - 1000.5 -> 1000.5
      - "$1000" -> 1000.0
      - "$1,200.50" -> 1200.50
      - "1 000" -> 1000.0
      - "1000 USD" -> 1000.0
      - "< 1000" -> 1000.0
    Returns None if coercion fails.
    """
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r"[$,€£zł\s]", "", val)
        match = re.search(r"[-+]?\d*\.?\d+", cleaned)
        if match:
            num_str = match.group(0)
            if num_str and num_str not in ("-", "+", "."):
                try:
                    return float(num_str)
                except ValueError:
                    pass
    return None


def _clamp(val: float, min_val: float, max_val: float) -> float:
    """Clamp a float value within [min_val, max_val]."""
    return max(min_val, min(max_val, val))


def _unwrap_session_context(context: Any) -> Dict[str, Any]:
    """
    Normalize various session context inputs into a standard dictionary.
    Supports:
      - Pydantic models with .model_dump()
      - Dicts wrapped under 'current_session_context'
      - Raw unwrapped dicts
      - None / empty inputs
    """
    if context is None:
        return {}
    if hasattr(context, "model_dump"):
        data = context.model_dump()
    elif isinstance(context, dict):
        data = context
    else:
        return {}

    # If wrapped in "current_session_context", extract the inner payload
    if "current_session_context" in data and isinstance(data["current_session_context"], dict):
        return data["current_session_context"]
    return data


# ---------------------------------------------------------------------------
# Mapping Function 1: Hard Constraints -> GraphSearchTool Structured Filters
# ---------------------------------------------------------------------------

def hard_constraints_to_structured_filters(
    hard_constraints: Union[List[Any], Dict[str, Any], Any]
) -> Dict[str, Any]:
    """
    Translate hard constraints into structured filters compatible with
    GraphSearchTool._build_filters and GraphSearchTool._normalize_filters.

    Target keys:
      - price_max: float
      - price_min: float
      - brand: str
      - exclude_brand: str
      - category: str
      + additional constraint keys preserved for downstream consumers.

    Args:
        hard_constraints: List of HardConstraint objects/dicts, or a dict/SessionContext
                          containing 'hard_constraints' or 'extracted_parameters'.

    Returns:
        Dict[str, Any] matching GraphSearchTool filter requirements.
    """
    filters: Dict[str, Any] = {}
    if not hard_constraints:
        logger.debug("[Adapter] No hard constraints provided, returning empty filters.")
        return filters

    logger.debug(f"[Adapter] Processing constraints of type: {type(hard_constraints)}")

    # Extract constraint list if wrapped in a session dict or model
    raw_list: List[Any] = []
    
    # Unwrap 'current_session_context' if present (either via dot access or dict)
    if hasattr(hard_constraints, "current_session_context") and getattr(hard_constraints, "current_session_context"):
        logger.debug("[Adapter] Unwrapping CurrentSessionContextWrapper object.")
        hard_constraints = getattr(hard_constraints, "current_session_context")
    elif isinstance(hard_constraints, dict) and "current_session_context" in hard_constraints:
        logger.debug("[Adapter] Unwrapping current_session_context dict.")
        hard_constraints = hard_constraints["current_session_context"]

    if isinstance(hard_constraints, dict):
        extracted_params = hard_constraints.get("extracted_parameters")
        if isinstance(extracted_params, dict) and "hard_constraints" in extracted_params:
            raw_list = extracted_params["hard_constraints"]
        elif "hard_constraints" in hard_constraints:
            raw_list = hard_constraints["hard_constraints"]
        else:
            raw_list = []
    elif hasattr(hard_constraints, "extracted_parameters"):
        extracted_params = getattr(hard_constraints, "extracted_parameters", None)
        raw_list = getattr(extracted_params, "hard_constraints", [])
    elif isinstance(hard_constraints, list):
        raw_list = hard_constraints
    else:
        raw_list = []

    included_brands: List[str] = []
    excluded_brands: List[str] = []
    included_categories: List[str] = []

    for item in raw_list:
        attr = str(_get_field(item, "attribute", "")).lower().strip()
        op = _get_field(item, "operator", "")
        raw_val = _get_field(item, "value")

        if not attr or raw_val is None:
            continue

        # Normalise operator enum / string
        if hasattr(op, "value"):
            op_str = str(op.value).lower().strip()
        else:
            op_str = str(op).lower().strip()

        # 1. Price Constraints
        if attr in ("price", "budget", "cost", "price_max", "max_price", "price_min", "min_price"):
            num_val = _coerce_numeric(raw_val)
            if num_val is not None:
                if op_str in ("less_than", "less_than_or_equal", "<", "<=") or attr in ("price_max", "max_price"):
                    filters["price_max"] = num_val
                elif op_str in ("greater_than", "greater_than_or_equal", ">", ">=") or attr in ("price_min", "min_price"):
                    filters["price_min"] = num_val
                elif op_str in ("equal", "==", "include"):
                    filters["price_max"] = num_val
                else:
                    logger.debug(f"[Adapter] Unhandled price operator '{op_str}' for value {raw_val}")

        # 2. Brand Constraints
        elif attr in ("brand", "make", "manufacturer", "store"):
            brand_str = str(raw_val).strip()
            if op_str in ("include", "equal", "=="):
                filters["brand"] = brand_str
                if brand_str not in included_brands:
                    included_brands.append(brand_str)
            elif op_str == "exclude":
                filters["exclude_brand"] = brand_str
                filters["brand_exclude"] = brand_str
                if brand_str not in excluded_brands:
                    excluded_brands.append(brand_str)

        elif attr in ("exclude_brand", "excluded_brand"):
            brand_str = str(raw_val).strip()
            filters["exclude_brand"] = brand_str
            filters["brand_exclude"] = brand_str
            if brand_str not in excluded_brands:
                excluded_brands.append(brand_str)

        # 3. Category Constraints
        elif attr in ("category", "categories", "product_category", "product_type", "type"):
            cat_str = str(raw_val).strip()
            if op_str in ("include", "equal", "=="):
                filters["category"] = cat_str
                if cat_str not in included_categories:
                    included_categories.append(cat_str)
            elif op_str == "exclude":
                filters["exclude_category"] = cat_str

        # 4. Other Attributes (e.g. operating_system, ram, storage, model, form_factor)
        else:
            if op_str == "exclude":
                filters[f"exclude_{attr}"] = raw_val
                filters[f"{attr}_exclude"] = raw_val
            elif op_str in ("less_than", "less_than_or_equal"):
                num_val = _coerce_numeric(raw_val)
                val = num_val if num_val is not None else raw_val
                filters[f"{attr}_max"] = val
                filters[f"{attr}_{op_str}"] = val
            elif op_str in ("greater_than", "greater_than_or_equal"):
                num_val = _coerce_numeric(raw_val)
                val = num_val if num_val is not None else raw_val
                filters[f"{attr}_min"] = val
                filters[f"{attr}_{op_str}"] = val
            elif op_str in ("equal", "=="):
                filters[attr] = raw_val
                filters[f"{attr}_equal"] = raw_val
            else:
                filters[attr] = raw_val

    # If multiple brands/categories were collected, expose plural lists without breaking single-string keys
    if len(included_brands) > 1:
        filters["brands"] = included_brands
    if len(excluded_brands) > 1:
        filters["exclude_brands"] = excluded_brands
    if len(included_categories) > 1:
        filters["categories"] = included_categories

    return filters


def session_context_to_structured_filters(
    session_context: Any
) -> Dict[str, Any]:
    """
    Translate a SessionContext, CurrentSessionContextWrapper, or context dict
    directly into structured filters compatible with GraphSearchTool.
    Delegates to hard_constraints_to_structured_filters after payload unwrapping.
    """
    ctx = _unwrap_session_context(session_context)
    extracted = ctx.get("extracted_parameters", {})
    if hasattr(extracted, "hard_constraints"):
        hard_constraints = getattr(extracted, "hard_constraints")
    elif isinstance(extracted, dict):
        hard_constraints = extracted.get("hard_constraints", [])
    else:
        hard_constraints = ctx.get("hard_constraints", [])

    return hard_constraints_to_structured_filters(hard_constraints)


# ---------------------------------------------------------------------------
# Mapping Function 2: Session Context -> Legacy Preferences
# ---------------------------------------------------------------------------

def session_context_to_legacy_preferences(session_context: Any) -> Dict[str, Any]:
    """
    Translate SessionContext into the legacy dictionary format expected by:
      - PromptConstructor._format_preferences
      - GraphQueryManager._ground_preferences
      - PreferenceQuantifier.quantify
      - ProfileTool

    Returns dict containing:
      - likes: List[str]
      - dislikes: List[str]
      - constraints: Dict[str, Any]
      - intent: str
      - notes: str
      - weighted_preferences: Dict[str, Any]
      - current_session_context: Dict[str, Any]
    """
    ctx = _unwrap_session_context(session_context)
    if not ctx:
        return {
            "likes": [],
            "dislikes": [],
            "constraints": {},
            "intent": "initial_search",
            "notes": "",
            "weighted_preferences": {
                "likes": [],
                "dislikes": [],
                "constraints": {}
            },
            "current_session_context": {}
        }

    extracted = ctx.get("extracted_parameters", {})
    if hasattr(extracted, "model_dump"):
        extracted = extracted.model_dump()
    elif not isinstance(extracted, dict):
        extracted = {}

    hard_constraints = extracted.get("hard_constraints", [])
    soft_preferences = extracted.get("soft_preferences", [])

    # Process soft preferences into likes / dislikes and weighted entries
    likes: List[str] = []
    dislikes: List[str] = []
    weighted_likes: List[Dict[str, Any]] = []
    weighted_dislikes: List[Dict[str, Any]] = []

    for sp in soft_preferences:
        val = str(_get_field(sp, "value", "")).strip()
        cat = str(_get_field(sp, "category", "")).strip()
        polarity = _coerce_numeric(_get_field(sp, "polarity", 1.0))
        if polarity is None:
            polarity = 1.0
        polarity = _clamp(polarity, -1.0, 1.0)

        confidence = _coerce_numeric(_get_field(sp, "confidence", 1.0))
        if confidence is None:
            confidence = 1.0
        confidence = _clamp(confidence, 0.0, 1.0)

        evidence = str(_get_field(sp, "evidence", "")).strip()

        if not val:
            continue

        weight = round(polarity * confidence, 2)
        entry = {
            "value": val,
            "weight": weight,
            "category": cat,
            "confidence": confidence,
            "evidence": evidence
        }

        # Polarity == 0.0 is neutral and does not pollute likes or dislikes
        if polarity > 0.0:
            if val not in likes:
                likes.append(val)
            weighted_likes.append(entry)
        elif polarity < 0.0:
            if val not in dislikes:
                dislikes.append(val)
            weighted_dislikes.append(entry)

    # Process hard constraints into constraints dictionary
    structured_filters = hard_constraints_to_structured_filters(hard_constraints)
    constraints_dict: Dict[str, Any] = dict(structured_filters)

    # Guarantee "categories" list exists for GraphQueryManager._ground_preferences
    categories_list: List[str] = []
    if "category" in structured_filters and structured_filters["category"]:
        categories_list.append(str(structured_filters["category"]))
    if "categories" in structured_filters and isinstance(structured_filters["categories"], list):
        for c in structured_filters["categories"]:
            if str(c) not in categories_list:
                categories_list.append(str(c))

    if categories_list:
        constraints_dict["categories"] = categories_list

    # Intent and Notes
    intent = ctx.get("session_intent", "initial_search")
    if hasattr(intent, "value"):
        intent_str = str(intent.value)
    else:
        intent_str = str(intent)

    notes = str(ctx.get("situational_context", ""))

    return {
        "likes": likes,
        "dislikes": dislikes,
        "constraints": constraints_dict,
        "intent": intent_str,
        "notes": notes,
        "weighted_preferences": {
            "likes": weighted_likes,
            "dislikes": weighted_dislikes,
            "constraints": constraints_dict
        },
        "current_session_context": ctx
    }


# ---------------------------------------------------------------------------
# Mapping Function 3: Session Context -> User Persona for CriticAgent
# ---------------------------------------------------------------------------

def session_context_to_user_persona(
    session_context: Any,
    as_string: bool = False
) -> Union[Dict[str, Any], str]:
    """
    Translate SessionContext into the user persona representation required by
    CriticAgent.evaluate_candidates for contextual candidate reranking.

    Args:
        session_context: SessionContext model, CurrentSessionContextWrapper, or dict.
        as_string: If True, returns a human-readable multi-line narrative string.
                   If False, returns a rich structured dictionary suitable for json.dumps.

    Returns:
        Union[Dict[str, Any], str] representing user persona.
    """
    ctx = _unwrap_session_context(session_context)
    if not ctx:
        empty_persona = {
            "situational_context": "",
            "hard_requirements": [],
            "must_avoid": [],
            "preferred_qualities": [],
            "disliked_qualities": [],
            "session_intent": "initial_search"
        }
        return "" if as_string else empty_persona

    situational = str(ctx.get("situational_context", ""))
    intent = ctx.get("session_intent", "initial_search")
    if hasattr(intent, "value"):
        intent_str = str(intent.value)
    else:
        intent_str = str(intent)

    extracted = ctx.get("extracted_parameters", {})
    if hasattr(extracted, "model_dump"):
        extracted = extracted.model_dump()
    elif not isinstance(extracted, dict):
        extracted = {}

    hard_constraints = extracted.get("hard_constraints", [])
    soft_preferences = extracted.get("soft_preferences", [])

    must_have: List[str] = []
    must_avoid: List[str] = []

    for hc in hard_constraints:
        attr = _get_field(hc, "attribute", "")
        op = _get_field(hc, "operator", "")
        val = _get_field(hc, "value", "")
        if hasattr(op, "value"):
            op = str(op.value)

        if op == "exclude":
            must_avoid.append(f"{attr} != {val}")
        elif op in ("less_than", "less_than_or_equal", "<", "<="):
            must_have.append(f"{attr} < {val}")
        elif op in ("greater_than", "greater_than_or_equal", ">", ">="):
            must_have.append(f"{attr} > {val}")
        elif op in ("equal", "include", "=="):
            must_have.append(f"{attr} == {val}")
        else:
            must_have.append(f"{attr} {op} {val}")

    preferred: List[str] = []
    disliked: List[str] = []

    for sp in soft_preferences:
        val = _get_field(sp, "value", "")
        cat = _get_field(sp, "category", "")
        polarity = _coerce_numeric(_get_field(sp, "polarity", 1.0))
        if polarity is None:
            polarity = 1.0
        evidence = _get_field(sp, "evidence", "")

        desc = f"{val} (category: {cat}, polarity: {polarity:+.1f}"
        if evidence:
            desc += f", evidence: '{evidence}'"
        desc += ")"

        if polarity >= 0.0:
            preferred.append(desc)
        else:
            disliked.append(desc)

    persona_dict = {
        "situational_context": situational,
        "session_intent": intent_str,
        "hard_requirements": must_have,
        "must_avoid": must_avoid,
        "preferred_qualities": preferred,
        "disliked_qualities": disliked
    }

    if not as_string:
        return persona_dict

    lines = []
    if situational:
        lines.append(f"User Goal & Context: {situational}")
    lines.append(f"Dialogue Phase: {intent_str}")
    if must_have:
        lines.append("Strict Requirements (Must Have):")
        for req in must_have:
            lines.append(f"  - {req}")
    if must_avoid:
        lines.append("Strict Exclusions (Must Avoid):")
        for av in must_avoid:
            lines.append(f"  - {av}")
    if preferred:
        lines.append("Preferred Qualities (Likes):")
        for p in preferred:
            lines.append(f"  - {p}")
    if disliked:
        lines.append("Disliked Qualities (Avoid if possible):")
        for d in disliked:
            lines.append(f"  - {d}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mapping Function 4: Dialogue State -> Orchestrator Router Action
# ---------------------------------------------------------------------------

def session_context_to_dialogue_action(session_context: Any) -> str:
    """
    Map dialogue_state.suggested_system_action to AgentOrchestrator router action.

    Mappings:
      - ask_clarification -> "CLARIFY"
      - present_results   -> "SEARCH"
      - change_topic       -> "ANSWER"

    Fallback defaults to "CLARIFY".
    """
    ctx = _unwrap_session_context(session_context)
    dialogue_state = ctx.get("dialogue_state")
    if hasattr(dialogue_state, "model_dump"):
        dialogue_state = dialogue_state.model_dump()

    action = _get_field(dialogue_state, "suggested_system_action")
    if hasattr(action, "value"):
        action_str = str(action.value)
    else:
        action_str = str(action) if action else ""

    mapping = {
        "ask_clarification": "CLARIFY",
        "present_results": "SEARCH",
        "change_topic": "ANSWER",
    }
    return mapping.get(action_str, "CLARIFY")


# ---------------------------------------------------------------------------
# Mapping Function 5 (Bidirectional): Legacy Preferences -> Session Context
# ---------------------------------------------------------------------------

def legacy_preferences_to_session_context(
    preferences: Dict[str, Any],
    as_dict: bool = False,
    unpack_plural_constraints: bool = False,
) -> Union[SessionContext, Dict[str, Any]]:
    """
    Reverse-adapter converting legacy preferences dict (likes, dislikes, constraints)
    into a canonical SessionContext (or wrapped dictionary).
    If unpack_plural_constraints is True, list values in constraints (e.g. brands: [...])
    are unpacked into individual HardConstraint objects.
    """
    if not preferences:
        empty_ctx = SessionContext.create_empty()
        return {"current_session_context": empty_ctx.to_dict()} if as_dict else empty_ctx

    if isinstance(preferences, CurrentSessionContextWrapper):
        return {"current_session_context": preferences.to_dict()} if as_dict else preferences.current_session_context
    if isinstance(preferences, SessionContext):
        return {"current_session_context": preferences.to_dict()} if as_dict else preferences

    if "current_session_context" in preferences and isinstance(preferences["current_session_context"], dict):
        ctx = SessionContext.model_validate(preferences["current_session_context"])
        return {"current_session_context": ctx.to_dict()} if as_dict else ctx

    hard_constraints: List[HardConstraint] = []
    soft_preferences: List[SoftPreference] = []

    # Map legacy constraints -> hard_constraints
    raw_constraints = preferences.get("constraints", {})
    if isinstance(raw_constraints, dict):
        for k, v in raw_constraints.items():
            if v is None:
                continue
            if k == "categories" and isinstance(v, list):
                for cat in v:
                    hard_constraints.append(
                        HardConstraint(attribute="category", operator=ConstraintOperator.INCLUDE, value=str(cat))
                    )
            elif unpack_plural_constraints and k in ("brands", "brand") and isinstance(v, list):
                for b in v:
                    hard_constraints.append(
                        HardConstraint(attribute="brand", operator=ConstraintOperator.INCLUDE, value=str(b))
                    )
            elif unpack_plural_constraints and isinstance(v, list):
                attr = k[:-1] if k.endswith("s") and not k.endswith("ss") else k
                for item in v:
                    if isinstance(item, (str, int, float, bool)):
                        hard_constraints.append(
                            HardConstraint(attribute=str(attr), operator=ConstraintOperator.INCLUDE, value=item)
                        )
            elif k == "price_max":
                hard_constraints.append(
                    HardConstraint(attribute="price", operator=ConstraintOperator.LESS_THAN, value=v)
                )
            elif k == "price_min":
                hard_constraints.append(
                    HardConstraint(attribute="price", operator=ConstraintOperator.GREATER_THAN, value=v)
                )
            elif k == "brand":
                hard_constraints.append(
                    HardConstraint(attribute="brand", operator=ConstraintOperator.INCLUDE, value=str(v))
                )
            elif k == "exclude_brand":
                hard_constraints.append(
                    HardConstraint(attribute="brand", operator=ConstraintOperator.EXCLUDE, value=str(v))
                )
            elif k == "category":
                hard_constraints.append(
                    HardConstraint(attribute="category", operator=ConstraintOperator.INCLUDE, value=str(v))
                )
            else:
                hard_constraints.append(
                    HardConstraint(attribute=str(k), operator=ConstraintOperator.EQUAL, value=v)
                )

    # Map legacy likes -> soft_preferences (positive)
    raw_likes = preferences.get("likes", [])
    if isinstance(raw_likes, list):
        for item in raw_likes:
            val = item.get("value", "") if isinstance(item, dict) else str(item)
            val = str(val).strip()
            if val:
                soft_preferences.append(
                    SoftPreference(
                        category="general",
                        value=val,
                        polarity=0.8,
                        confidence=0.8,
                        evidence="Imported from legacy likes",
                    )
                )

    # Map legacy dislikes -> soft_preferences (negative)
    raw_dislikes = preferences.get("dislikes", [])
    if isinstance(raw_dislikes, list):
        for item in raw_dislikes:
            val = item.get("value", "") if isinstance(item, dict) else str(item)
            val = str(val).strip()
            if val:
                soft_preferences.append(
                    SoftPreference(
                        category="general",
                        value=val,
                        polarity=-0.8,
                        confidence=0.8,
                        evidence="Imported from legacy dislikes",
                    )
                )

    # Map intent
    raw_intent = str(preferences.get("intent", "initial_search")).lower().strip()
    intent_map = {
        "recommendation": SessionIntent.INITIAL_SEARCH,
        "clarification": SessionIntent.REFINING_OPTIONS,
        "other": SessionIntent.EXPLORING_DOMAIN,
        "initial_search": SessionIntent.INITIAL_SEARCH,
        "exploring_domain": SessionIntent.EXPLORING_DOMAIN,
        "refining_options": SessionIntent.REFINING_OPTIONS,
        "comparing_items": SessionIntent.COMPARING_ITEMS,
        "finalizing_choice": SessionIntent.FINALIZING_CHOICE,
    }
    session_intent = intent_map.get(raw_intent, SessionIntent.INITIAL_SEARCH)
    situational_context = str(preferences.get("notes", ""))

    ctx = SessionContext(
        session_intent=session_intent,
        situational_context=situational_context,
        extracted_parameters=ExtractedParameters(
            hard_constraints=hard_constraints,
            soft_preferences=soft_preferences,
        ),
        dialogue_state=DialogueState(
            ready_for_recommendation=len(hard_constraints) > 0,
            missing_critical_attributes=[],
            suggested_system_action=SuggestedSystemAction.PRESENT_RESULTS if len(hard_constraints) > 0 else SuggestedSystemAction.ASK_CLARIFICATION,
        ),
    )

    if as_dict:
        return {"current_session_context": ctx.to_dict()}
    return ctx


# ---------------------------------------------------------------------------
# Mapping Function 6: Semantic Query Extraction
# ---------------------------------------------------------------------------

def extract_semantic_query(
    context: Union[SessionContext, CurrentSessionContextWrapper, Dict[str, Any]]
) -> str:
    """
    Build a dense semantic query string for GraphSearchTool from situational context
    and positive soft preferences.
    """
    if isinstance(context, CurrentSessionContextWrapper):
        ctx = context.current_session_context
    elif isinstance(context, SessionContext):
        ctx = context
    elif isinstance(context, dict):
        ctx_data = context.get("current_session_context", context)
        ctx = SessionContext.model_validate(ctx_data)
    else:
        return ""

    tokens: List[str] = []
    if ctx.situational_context:
        tokens.append(ctx.situational_context.strip())

    for sp in ctx.extracted_parameters.soft_preferences:
        if sp.polarity > 0.0:
            tokens.append(sp.value.strip())

    return " ".join(tokens)
