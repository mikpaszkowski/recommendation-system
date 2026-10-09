"""
Unit test suite for session context adapters (Milestone 1).
Tests downstream conversion to GraphSearchTool filters, PromptConstructor legacy preferences,
CriticAgent user persona, dialogue action mapping, and legacy round-trips.
"""

from __future__ import annotations

import json
import pytest

from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContext,
    CurrentSessionContextWrapper,
    DialogueState,
    ExtractedParameters,
    HardConstraint,
    SessionContext,
    SessionIntent,
    SoftPreference,
    SuggestedSystemAction,
)
from src.dialog_manager.session_adapter import (
    extract_semantic_query,
    hard_constraints_to_structured_filters,
    legacy_preferences_to_session_context,
    session_context_to_dialogue_action,
    session_context_to_legacy_preferences,
    session_context_to_user_persona,
)
from src.tools.graph_search_tool import GraphSearchTool
from src.llm_interface.prompt_constructor import PromptConstructor


@pytest.fixture
def sample_context():
    """Builds a rich sample SessionContext instance."""
    return SessionContext(
        session_intent=SessionIntent.REFINING_OPTIONS,
        situational_context="User is looking for a lightweight college laptop with good battery under $1000 without ChromeOS.",
        extracted_parameters=ExtractedParameters(
            hard_constraints=[
                HardConstraint(attribute="price", operator=ConstraintOperator.LESS_THAN, value=1000),
                HardConstraint(attribute="operating_system", operator=ConstraintOperator.EXCLUDE, value="ChromeOS"),
                HardConstraint(attribute="brand", operator=ConstraintOperator.INCLUDE, value="Apple"),
                HardConstraint(attribute="category", operator=ConstraintOperator.INCLUDE, value="Laptops"),
            ],
            soft_preferences=[
                SoftPreference(
                    category="weight",
                    value="lightweight",
                    polarity=0.8,
                    confidence=0.9,
                    evidence="User mentioned wanting something easy to carry."
                ),
                SoftPreference(
                    category="noise",
                    value="loud fan",
                    polarity=-0.6,
                    confidence=0.8,
                    evidence="User dislikes loud fan noises."
                )
            ]
        ),
        dialogue_state=DialogueState(
            ready_for_recommendation=True,
            missing_critical_attributes=[],
            suggested_system_action=SuggestedSystemAction.PRESENT_RESULTS
        )
    )


# ============================================================================
# Group A: hard_constraints_to_structured_filters Verification
# ============================================================================

def test_price_less_than_maps_to_price_max():
    """operator='less_than' on price maps to price_max (float)."""
    constraints = [HardConstraint(attribute="price", operator="less_than", value=1200)]
    filters = hard_constraints_to_structured_filters(constraints)
    assert filters.get("price_max") == 1200.0


def test_price_greater_than_maps_to_price_min():
    """operator='greater_than' on price maps to price_min (float)."""
    constraints = [HardConstraint(attribute="price", operator="greater_than", value=400)]
    filters = hard_constraints_to_structured_filters(constraints)
    assert filters.get("price_min") == 400.0


def test_price_range_both_bounds():
    """Both price_min and price_max are populated when both operators are present."""
    constraints = [
        HardConstraint(attribute="price", operator="greater_than", value=500),
        HardConstraint(attribute="price", operator="less_than", value=1500),
    ]
    filters = hard_constraints_to_structured_filters(constraints)
    assert filters["price_min"] == 500.0
    assert filters["price_max"] == 1500.0


def test_brand_include_and_equal_maps_to_brand():
    """operator='include' or 'equal' on brand maps to 'brand'."""
    c_inc = [HardConstraint(attribute="brand", operator="include", value="Apple")]
    assert hard_constraints_to_structured_filters(c_inc).get("brand") == "Apple"

    c_eq = [HardConstraint(attribute="brand", operator="equal", value="Dell")]
    assert hard_constraints_to_structured_filters(c_eq).get("brand") == "Dell"


def test_brand_exclude_maps_to_exclude_brand():
    """operator='exclude' on brand maps to 'exclude_brand'."""
    constraints = [HardConstraint(attribute="brand", operator="exclude", value="Acer")]
    filters = hard_constraints_to_structured_filters(constraints)
    assert filters.get("exclude_brand") == "Acer"


def test_category_include_maps_to_category():
    """operator='include' or 'equal' on category maps to 'category'."""
    constraints = [HardConstraint(attribute="category", operator="include", value="Laptops")]
    filters = hard_constraints_to_structured_filters(constraints)
    assert filters.get("category") == "Laptops"


def test_numeric_coercion_from_currency_string_e6():
    """Currency strings like '$1,200.50' must coerce cleanly to numeric float (Edge Case E6)."""
    constraints = [
        HardConstraint(attribute="price", operator="less_than", value="$1,200.50"),
        HardConstraint(attribute="price", operator="greater_than", value="400")
    ]
    filters = hard_constraints_to_structured_filters(constraints)
    assert filters["price_max"] == 1200.50
    assert filters["price_min"] == 400.0


def test_empty_hard_constraints_returns_empty_dict():
    """Empty constraints list returns empty dict."""
    assert hard_constraints_to_structured_filters([]) == {}


def test_constraint_override_last_one_wins():
    """When multiple conflicting constraints exist for the same attribute/op, the latest one takes precedence."""
    constraints = [
        HardConstraint(attribute="price", operator="less_than", value=1000),
        HardConstraint(attribute="price", operator="less_than", value=800),
    ]
    filters = hard_constraints_to_structured_filters(constraints)
    assert filters["price_max"] == 800.0


def test_accepts_raw_dict_list():
    """Adapter can accept raw list of dicts as well as HardConstraint instances."""
    raw_dicts = [{"attribute": "brand", "operator": "include", "value": "Lenovo"}]
    filters = hard_constraints_to_structured_filters(raw_dicts)
    assert filters.get("brand") == "Lenovo"


def test_downstream_graph_search_tool_filter_compatibility(sample_context):
    """Directly verifies that adapted filters are accepted by GraphSearchTool._build_filters."""
    tool = object.__new__(GraphSearchTool)
    filters = hard_constraints_to_structured_filters(sample_context.extracted_parameters.hard_constraints)

    where_clauses, params = tool._build_filters(filters)
    assert isinstance(where_clauses, list)
    assert isinstance(params, dict)
    assert any("node.price <= $price_max" in clause for clause in where_clauses)
    assert params["price_max"] == 1000.0
    assert any("HAS_BRAND" in clause for clause in where_clauses)
    assert params["brand_filter"] == "Apple"


# ============================================================================
# Group B: session_context_to_legacy_preferences Verification
# ============================================================================

def test_legacy_preferences_soft_preferences_split(sample_context):
    """Verifies that soft preferences are split into likes (polarity > 0) and dislikes (polarity < 0)."""
    legacy = session_context_to_legacy_preferences(sample_context)

    assert "weighted_preferences" in legacy
    wp = legacy["weighted_preferences"]

    # likes
    likes = wp.get("likes", [])
    assert len(likes) == 1
    assert likes[0]["value"] == "lightweight"
    assert likes[0]["weight"] > 0

    # dislikes
    dislikes = wp.get("dislikes", [])
    assert len(dislikes) == 1
    assert dislikes[0]["value"] == "loud fan"
    assert dislikes[0]["weight"] < 0

    # top-level likes and dislikes lists
    assert "lightweight" in legacy["likes"]
    assert "loud fan" in legacy["dislikes"]


def test_legacy_preferences_neutral_handling():
    """Polarity == 0 does not pollute likes or dislikes."""
    ctx = SessionContext(
        extracted_parameters=ExtractedParameters(
            soft_preferences=[
                SoftPreference(category="color", value="silver", polarity=0.0, confidence=1.0, evidence="neutral")
            ]
        )
    )
    legacy = session_context_to_legacy_preferences(ctx)
    assert len(legacy["weighted_preferences"]["likes"]) == 0
    assert len(legacy["weighted_preferences"]["dislikes"]) == 0
    assert len(legacy["likes"]) == 0
    assert len(legacy["dislikes"]) == 0


def test_legacy_preferences_top_level_keys(sample_context):
    """Verifies intent, notes, and current_session_context preservation."""
    legacy = session_context_to_legacy_preferences(sample_context)
    assert legacy["intent"] == "refining_options"
    assert "college laptop" in legacy["notes"]
    assert "current_session_context" in legacy
    assert "categories" in legacy["constraints"]
    assert "Laptops" in legacy["constraints"]["categories"]


def test_downstream_prompt_constructor_compatibility(sample_context):
    """Directly verifies that PromptConstructor formats adapted legacy preferences without error."""
    legacy = session_context_to_legacy_preferences(sample_context)
    pc = PromptConstructor()
    formatted = pc._format_preferences(legacy)

    assert "Positive signals:" in formatted
    assert "lightweight" in formatted
    assert "Negative signals:" in formatted
    assert "loud fan" in formatted
    assert "Constraints:" in formatted


# ============================================================================
# Group C: session_context_to_user_persona Verification
# ============================================================================

def test_user_persona_generation(sample_context):
    """Verifies persona dictionary creation and JSON serializability for CriticAgent."""
    persona = session_context_to_user_persona(sample_context)
    assert isinstance(persona, dict)
    assert "hard_requirements" in persona
    assert "must_avoid" in persona
    assert "preferred_qualities" in persona
    assert "disliked_qualities" in persona

    # Must be JSON-serializable
    json_str = json.dumps(persona, ensure_ascii=False)
    assert len(json_str) > 0
    assert "lightweight" in json_str
    assert "ChromeOS" in json_str

    # Narrative string version
    narrative = session_context_to_user_persona(sample_context, as_string=True)
    assert isinstance(narrative, str)
    assert "User Goal & Context:" in narrative
    assert "Strict Requirements" in narrative
    assert "Strict Exclusions" in narrative


# ============================================================================
# Group D: session_context_to_dialogue_action Verification
# ============================================================================

@pytest.mark.parametrize("action_enum,expected_router_action", [
    (SuggestedSystemAction.ASK_CLARIFICATION, "CLARIFY"),
    (SuggestedSystemAction.PRESENT_RESULTS, "SEARCH"),
    (SuggestedSystemAction.CHANGE_TOPIC, "ANSWER"),
    (SuggestedSystemAction.ask_clarification, "CLARIFY"),
    (SuggestedSystemAction.present_results, "SEARCH"),
    (SuggestedSystemAction.change_topic, "ANSWER"),
])
def test_dialogue_action_mapping(action_enum, expected_router_action):
    """Verifies that dialogue state suggested actions map to router actions."""
    ctx = SessionContext(
        dialogue_state=DialogueState(suggested_system_action=action_enum)
    )
    action = session_context_to_dialogue_action(ctx)
    assert action == expected_router_action


# ============================================================================
# Group E: Edge Cases & Round-Trip Verification
# ============================================================================

def test_adapter_accepts_root_wrapper_or_unwrapped(sample_context):
    """Adapter can accept CurrentSessionContext, SessionContext, or dict."""
    wrapped = CurrentSessionContext(current_session_context=sample_context)

    # From CurrentSessionContext
    legacy1 = session_context_to_legacy_preferences(wrapped)
    assert legacy1["intent"] == "refining_options"

    # From SessionContext
    legacy2 = session_context_to_legacy_preferences(sample_context)
    assert legacy2["intent"] == "refining_options"

    # From dict
    legacy3 = session_context_to_legacy_preferences(wrapped.model_dump())
    assert legacy3["intent"] == "refining_options"


def test_adapter_empty_session_context_e7():
    """Empty session context produces valid empty structures."""
    ctx = SessionContext()
    filters = hard_constraints_to_structured_filters(ctx.extracted_parameters.hard_constraints)
    assert filters == {}

    legacy = session_context_to_legacy_preferences(ctx)
    assert legacy["weighted_preferences"]["likes"] == []
    assert legacy["weighted_preferences"]["dislikes"] == []
    assert legacy["intent"] == "initial_search"


def test_legacy_round_trip():
    """Verifies bidirectional conversion: legacy dict -> SessionContext -> legacy dict."""
    legacy_input = {
        "likes": ["portable", "fast"],
        "dislikes": ["plastic casing"],
        "constraints": {
            "price_max": 999.0,
            "brand": "Dell",
            "category": "laptop"
        },
        "intent": "recommendation",
        "notes": "Student budget."
    }

    ctx = legacy_preferences_to_session_context(legacy_input)
    assert ctx.session_intent == SessionIntent.INITIAL_SEARCH
    assert ctx.situational_context == "Student budget."

    reprojected = session_context_to_legacy_preferences(ctx)
    assert "portable" in reprojected["likes"]
    assert "fast" in reprojected["likes"]
    assert "plastic casing" in reprojected["dislikes"]
    assert reprojected["constraints"]["price_max"] == 999.0
    assert reprojected["constraints"]["brand"] == "Dell"
    assert reprojected["constraints"]["category"] == "laptop"


def test_extract_semantic_query():
    """Verifies extraction of semantic dense query string from session context."""
    ctx = SessionContext(
        situational_context="College student needs a laptop for CS",
        extracted_parameters=ExtractedParameters(
            hard_constraints=[],
            soft_preferences=[
                SoftPreference(category="weight", value="lightweight", polarity=0.9),
                SoftPreference(category="battery", value="all day battery", polarity=0.8),
                SoftPreference(category="brand", value="Dell", polarity=-0.5),
            ]
        )
    )
    query = extract_semantic_query(ctx)
    assert "College student needs a laptop for CS" in query
    assert "lightweight" in query
    assert "all day battery" in query
    assert "Dell" not in query


# ============================================================================
# Group G: Key Aliases, Empty Fallback, & Plural Unpacking (Remediation M1)
# ============================================================================

def test_generic_attribute_key_aliases():
    """Verifies that unknown/generic attributes produce {attr}_{op} and dual keys."""
    constraints = [
        HardConstraint(attribute="form_factor", operator=ConstraintOperator.EQUAL, value="convertible"),
        HardConstraint(attribute="model", operator=ConstraintOperator.EXCLUDE, value="MacBook Air"),
        HardConstraint(attribute="storage", operator=ConstraintOperator.LESS_THAN, value="512"),
    ]
    filters = hard_constraints_to_structured_filters(constraints)

    # Equality dual mapping
    assert filters.get("form_factor_equal") == "convertible"
    assert filters.get("form_factor") == "convertible"

    # Exclusion dual mapping
    assert filters.get("model_exclude") == "MacBook Air"
    assert filters.get("exclude_model") == "MacBook Air"

    # Numeric inequality dual mapping
    assert filters.get("storage_less_than") == 512.0
    assert filters.get("storage_max") == 512.0


def test_empty_context_constraints_cleanliness():
    """Verifies that empty contexts produce empty constraints dictionary without empty categories."""
    legacy = session_context_to_legacy_preferences({})
    assert legacy["constraints"] == {}
    assert legacy["weighted_preferences"]["constraints"] == {}

    # Empty SessionContext
    empty_ctx = SessionContext.create_empty()
    legacy_from_empty = session_context_to_legacy_preferences(empty_ctx)
    assert legacy_from_empty["constraints"] == {}
    assert legacy_from_empty["weighted_preferences"]["constraints"] == {}


def test_legacy_preferences_plural_list_unpacking():
    """Verifies unpacking of plural list constraints when unpack_plural_constraints=True."""
    legacy_with_brands = {
        "constraints": {
            "brands": ["Apple", "Dell"],
            "categories": ["Laptops", "Ultrabooks"],
        }
    }
    ctx = legacy_preferences_to_session_context(legacy_with_brands, unpack_plural_constraints=True)
    brand_constraints = [c for c in ctx.extracted_parameters.hard_constraints if c.attribute == "brand"]
    cat_constraints = [c for c in ctx.extracted_parameters.hard_constraints if c.attribute == "category"]

    assert len(brand_constraints) == 2
    assert {c.value for c in brand_constraints} == {"Apple", "Dell"}
    assert all(c.operator == ConstraintOperator.INCLUDE for c in brand_constraints)

    assert len(cat_constraints) == 2
    assert {c.value for c in cat_constraints} == {"Laptops", "Ultrabooks"}
