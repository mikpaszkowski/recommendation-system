"""
Reference Implementation of Session Context, Adapters, and Dialogue Manager.
Strictly derived from interface contracts in PROJECT.md and ORIGINAL_REQUEST.md.
Used as an authoritative reference model for opaque-box testing and fallback
when evaluating test suite execution prior to M1-M4 completion.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionIntent(str, Enum):
    INITIAL_SEARCH = "initial_search"
    EXPLORING_DOMAIN = "exploring_domain"
    REFINING_OPTIONS = "refining_options"
    COMPARING_ITEMS = "comparing_items"
    FINALIZING_CHOICE = "finalizing_choice"


class ConstraintOperator(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    EQUAL = "equal"


class SuggestedSystemAction(str, Enum):
    ASK_CLARIFICATION = "ask_clarification"
    PRESENT_RESULTS = "present_results"
    CHANGE_TOPIC = "change_topic"


class HardConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute: str = Field(..., min_length=1)
    operator: ConstraintOperator
    value: Union[str, int, float]

    @field_validator("attribute")
    @classmethod
    def attribute_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("attribute cannot be empty or whitespace only")
        return v.strip()


class SoftPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    polarity: float = Field(..., ge=-1.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str = Field(default="")

    @field_validator("category", "value")
    @classmethod
    def string_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or whitespace only")
        return v.strip()


class ExtractedParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_constraints: List[HardConstraint] = Field(default_factory=list)
    soft_preferences: List[SoftPreference] = Field(default_factory=list)


class DialogueState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready_for_recommendation: bool = Field(default=False)
    missing_critical_attributes: List[str] = Field(default_factory=list)
    suggested_system_action: SuggestedSystemAction = Field(
        default=SuggestedSystemAction.ASK_CLARIFICATION
    )


class SessionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_intent: SessionIntent = Field(default=SessionIntent.INITIAL_SEARCH)
    situational_context: str = Field(default="")
    extracted_parameters: ExtractedParameters = Field(
        default_factory=ExtractedParameters
    )
    dialogue_state: DialogueState = Field(default_factory=DialogueState)


class CurrentSessionContextWrapper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_session_context: SessionContext


# =====================================================================
# Adapter implementations (Contract: PROJECT.md lines 43-51)
# =====================================================================

def hard_constraints_to_structured_filters(
    constraints: List[Union[HardConstraint, Dict[str, Any]]]
) -> Dict[str, Any]:
    """
    Translates hard constraints to GraphSearchTool filters:
    - attribute="price", operator="less_than" -> price_max (float)
    - attribute="price", operator="greater_than" -> price_min (float)
    - attribute="brand", operator="include" | "equal" -> brand (str)
    - attribute="brand", operator="exclude" -> exclude_brand (str)
    - attribute="category", operator="include" -> category (str)
    """
    filters: Dict[str, Any] = {}
    for c in constraints:
        if isinstance(c, dict):
            attr = c.get("attribute", "")
            op = c.get("operator", "")
            val = c.get("value")
        else:
            attr = c.attribute
            op = c.operator.value if hasattr(c.operator, "value") else str(c.operator)
            val = c.value

        attr_lower = attr.lower()
        op_lower = op.lower()

        if attr_lower == "price":
            try:
                num_val = float(val)
                if op_lower == "less_than":
                    filters["price_max"] = num_val
                elif op_lower == "greater_than":
                    filters["price_min"] = num_val
            except (ValueError, TypeError):
                pass
        elif attr_lower == "brand":
            if op_lower in ("include", "equal"):
                filters["brand"] = str(val)
            elif op_lower == "exclude":
                filters["exclude_brand"] = str(val)
        elif attr_lower == "category":
            if op_lower in ("include", "equal"):
                filters["category"] = str(val)
        else:
            # Preserve generic attribute filter
            filters[f"{attr_lower}_{op_lower}"] = val

    return filters


def session_context_to_legacy_preferences(
    context: Union[SessionContext, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Converts session context into legacy format expected by existing tools:
    {likes, dislikes, constraints, intent, notes}
    """
    if isinstance(context, dict):
        ctx_data = context.get("current_session_context", context)
        extracted = ctx_data.get("extracted_parameters", {})
        soft_prefs = extracted.get("soft_preferences", [])
        hard_cons = extracted.get("hard_constraints", [])
        intent_val = ctx_data.get("session_intent", "initial_search")
        sit_ctx = ctx_data.get("situational_context", "")
    else:
        ctx_data = context
        soft_prefs = [sp.model_dump() for sp in context.extracted_parameters.soft_preferences]
        hard_cons = [hc.model_dump() for hc in context.extracted_parameters.hard_constraints]
        intent_val = (
            context.session_intent.value
            if hasattr(context.session_intent, "value")
            else str(context.session_intent)
        )
        sit_ctx = context.situational_context

    likes = [p["value"] for p in soft_prefs if p.get("polarity", 0) > 0]
    dislikes = [p["value"] for p in soft_prefs if p.get("polarity", 0) < 0]
    filters = hard_constraints_to_structured_filters(hard_cons)

    return {
        "likes": likes,
        "dislikes": dislikes,
        "constraints": filters,
        "intent": intent_val,
        "notes": sit_ctx,
    }


# =====================================================================
# Dialogue Manager reference implementation (Contract: PROJECT.md lines 52-60)
# =====================================================================

class DialogueManager:
    """
    Lightweight, high-cohesion dialogue manager tracking multi-turn session context.
    """

    def __init__(self, critical_attributes: Optional[List[str]] = None) -> None:
        self._sessions: Dict[str, SessionContext] = {}
        raw_attrs = critical_attributes if critical_attributes is not None else ["category"]
        # Deduplicate while preserving order
        self._critical_attributes = list(dict.fromkeys(raw_attrs))

    def get_context(self, session_id: str) -> SessionContext:
        """Retrieve current session context, initializing if not present."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionContext()
            self._evaluate_dialogue_state(self._sessions[session_id])
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        """Reset session context back to initial empty state."""
        self._sessions[session_id] = SessionContext()
        self._evaluate_dialogue_state(self._sessions[session_id])

    def update_context(
        self, session_id: str, new_context: Union[Dict[str, Any], SessionContext]
    ) -> SessionContext:
        """Directly update or replace context for session."""
        if isinstance(new_context, dict):
            raw = new_context.get("current_session_context", new_context)
            parsed = SessionContext.model_validate(raw)
        else:
            parsed = new_context

        self._evaluate_dialogue_state(parsed)
        self._sessions[session_id] = parsed
        return parsed

    def update_turn(
        self, session_id: str, user_message: str, extraction: Dict[str, Any]
    ) -> SessionContext:
        """
        Process a new dialogue turn, merging newly extracted parameters into
        running session context.
        """
        current = self.get_context(session_id)
        raw_extraction = extraction.get("current_session_context", extraction)

        # 1. Update session intent if provided
        if "session_intent" in raw_extraction:
            try:
                current.session_intent = SessionIntent(raw_extraction["session_intent"])
            except ValueError:
                pass

        # 2. Update situational context
        new_sit = raw_extraction.get("situational_context")
        if new_sit:
            current.situational_context = new_sit

        # 3. Merge hard constraints (override matching attribute + operator, or append)
        new_params = raw_extraction.get("extracted_parameters", {})
        new_hard = new_params.get("hard_constraints", [])
        for nh in new_hard:
            hc = nh if isinstance(nh, HardConstraint) else HardConstraint.model_validate(nh)
            # Find if attribute already exists
            replaced = False
            for idx, existing in enumerate(current.extracted_parameters.hard_constraints):
                if existing.attribute.lower() == hc.attribute.lower() and existing.operator == hc.operator:
                    current.extracted_parameters.hard_constraints[idx] = hc
                    replaced = True
                    break
                elif existing.attribute.lower() == hc.attribute.lower() and hc.attribute.lower() == "price":
                    # Override price with same operator or general price override
                    current.extracted_parameters.hard_constraints[idx] = hc
                    replaced = True
                    break
            if not replaced:
                current.extracted_parameters.hard_constraints.append(hc)

        # 4. Merge soft preferences (update polarity/confidence if category+value match)
        new_soft = new_params.get("soft_preferences", [])
        for ns in new_soft:
            sp = ns if isinstance(ns, SoftPreference) else SoftPreference.model_validate(ns)
            replaced = False
            for idx, existing in enumerate(current.extracted_parameters.soft_preferences):
                if existing.category.lower() == sp.category.lower() and existing.value.lower() == sp.value.lower():
                    current.extracted_parameters.soft_preferences[idx] = sp
                    replaced = True
                    break
            if not replaced:
                current.extracted_parameters.soft_preferences.append(sp)

        # 5. Re-evaluate dialogue state
        self._evaluate_dialogue_state(current)
        return current

    def _evaluate_dialogue_state(self, context: SessionContext) -> None:
        """Evaluate readiness, missing critical attributes, and suggested action."""
        present_attrs = {
            hc.attribute.lower() for hc in context.extracted_parameters.hard_constraints
        }
        present_categories = {
            sp.category.lower() for sp in context.extracted_parameters.soft_preferences
        }
        all_present = present_attrs.union(present_categories)

        missing = [
            req for req in self._critical_attributes if req.lower() not in all_present
        ]
        context.dialogue_state.missing_critical_attributes = missing

        # Determine readiness
        has_sufficient_context = len(missing) == 0 and (
            len(context.extracted_parameters.hard_constraints) > 0
            or len(context.extracted_parameters.soft_preferences) > 0
        )
        context.dialogue_state.ready_for_recommendation = has_sufficient_context

        # Determine suggested action
        if not has_sufficient_context:
            context.dialogue_state.suggested_system_action = (
                SuggestedSystemAction.ASK_CLARIFICATION
            )
        else:
            if context.session_intent == SessionIntent.COMPARING_ITEMS:
                context.dialogue_state.suggested_system_action = (
                    SuggestedSystemAction.PRESENT_RESULTS
                )
            else:
                context.dialogue_state.suggested_system_action = (
                    SuggestedSystemAction.PRESENT_RESULTS
                )
