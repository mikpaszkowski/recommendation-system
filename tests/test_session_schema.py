"""
Unit test suite for session context schema models (Milestone 1).
Tests Pydantic v2 schemas, root wrapper enforcement, enums, boundaries, and serialization.
"""

from __future__ import annotations

import json
import pytest
from pydantic import ValidationError

from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContext,
    CurrentSessionContextWrapper,
    DialogueState,
    ExtractedParameters,
    HardConstraint,
    HardConstraintOperator,
    SessionContext,
    SessionIntent,
    SoftPreference,
    SuggestedSystemAction,
)


@pytest.fixture
def canonical_session_context_dict():
    """Returns the canonical example payload from ORIGINAL_REQUEST.md."""
    return {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "User is looking for a lightweight laptop for college with a good battery life.",
            "extracted_parameters": {
                "hard_constraints": [
                    {
                        "attribute": "price",
                        "operator": "less_than",
                        "value": 1000
                    },
                    {
                        "attribute": "operating_system",
                        "operator": "exclude",
                        "value": "ChromeOS"
                    }
                ],
                "soft_preferences": [
                    {
                        "category": "weight",
                        "value": "lightweight",
                        "polarity": 0.8,
                        "confidence": 0.9,
                        "evidence": "User mentioned wanting something easy to carry around campus."
                    },
                    {
                        "category": "brand",
                        "value": "Apple",
                        "polarity": 0.4,
                        "confidence": 0.6,
                        "evidence": "User asked if MacBooks ever go on sale in this price range."
                    }
                ]
            },
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": ["screen_size"],
                "suggested_system_action": "ask_clarification"
            }
        }
    }


# ============================================================================
# Group A: Valid Instantiation & Root Wrapper Enforcement (F1, E1, E7)
# ============================================================================

def test_canonical_schema_instantiation_full(canonical_session_context_dict):
    """Verifies that the canonical JSON from ORIGINAL_REQUEST.md instantiates correctly."""
    root = CurrentSessionContext.model_validate(canonical_session_context_dict)
    ctx = root.current_session_context

    assert ctx.session_intent == SessionIntent.REFINING_OPTIONS
    assert ctx.session_intent == SessionIntent.refining_options
    assert "lightweight laptop for college" in ctx.situational_context
    assert len(ctx.extracted_parameters.hard_constraints) == 2
    assert len(ctx.extracted_parameters.soft_preferences) == 2

    # Check hard constraint fields
    c0 = ctx.extracted_parameters.hard_constraints[0]
    assert c0.attribute == "price"
    assert c0.operator == ConstraintOperator.LESS_THAN
    assert c0.operator == ConstraintOperator.less_than
    assert c0.value == 1000

    c1 = ctx.extracted_parameters.hard_constraints[1]
    assert c1.attribute == "operating_system"
    assert c1.operator == ConstraintOperator.EXCLUDE
    assert c1.operator == ConstraintOperator.exclude
    assert c1.value == "ChromeOS"

    # Check soft preference fields
    p0 = ctx.extracted_parameters.soft_preferences[0]
    assert p0.category == "weight"
    assert p0.value == "lightweight"
    assert p0.polarity == 0.8
    assert p0.confidence == 0.9
    assert "campus" in p0.evidence

    # Check dialogue state
    ds = ctx.dialogue_state
    assert ds.ready_for_recommendation is False
    assert ds.missing_critical_attributes == ["screen_size"]
    assert ds.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION
    assert ds.suggested_system_action == SuggestedSystemAction.ask_clarification

    # Wrapper delegating properties
    assert root.session_intent == SessionIntent.REFINING_OPTIONS
    assert len(root.hard_constraints) == 2
    assert len(root.soft_preferences) == 2
    assert root.dialogue_state.ready_for_recommendation is False


def test_minimal_instantiation_and_defaults_e7():
    """Verifies default values on empty cold-start instantiation (Edge Case E7)."""
    ctx = SessionContext()
    assert ctx.session_intent == SessionIntent.INITIAL_SEARCH
    assert ctx.session_intent == SessionIntent.initial_search
    assert ctx.situational_context == ""
    assert ctx.extracted_parameters.hard_constraints == []
    assert ctx.extracted_parameters.soft_preferences == []
    assert ctx.dialogue_state.ready_for_recommendation is False
    assert ctx.dialogue_state.missing_critical_attributes == []
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION

    # Factory methods
    ctx_empty = SessionContext.create_empty()
    assert ctx_empty.session_intent == SessionIntent.INITIAL_SEARCH

    # Root wrapper default
    root = CurrentSessionContext(current_session_context=ctx)
    assert root.current_session_context.session_intent == SessionIntent.INITIAL_SEARCH

    root_empty = CurrentSessionContextWrapper.create_empty()
    assert root_empty.current_session_context.session_intent == SessionIntent.INITIAL_SEARCH


def test_root_wrapper_missing_raises_validation_error_e1():
    """Passing flat dictionary missing 'current_session_context' must raise ValidationError (Edge Case E1)."""
    flat_data = {
        "session_intent": "initial_search",
        "situational_context": "Looking for laptop",
        "extracted_parameters": {"hard_constraints": [], "soft_preferences": []},
        "dialogue_state": {
            "ready_for_recommendation": False,
            "missing_critical_attributes": [],
            "suggested_system_action": "ask_clarification"
        }
    }
    with pytest.raises(ValidationError) as exc_info:
        CurrentSessionContext.model_validate(flat_data)
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("current_session_context",) for err in errors)

    # Auto-wrap option allows lenient ingestion when requested
    auto_wrapped = CurrentSessionContextWrapper.from_dict(flat_data, auto_wrap=True)
    assert auto_wrapped.session_intent == SessionIntent.INITIAL_SEARCH


# ============================================================================
# Group B: Serialization & Deserialization
# ============================================================================

def test_model_dump_modes(canonical_session_context_dict):
    """Verifies model_dump preserves keys and types."""
    model = CurrentSessionContext.model_validate(canonical_session_context_dict)
    dumped = model.model_dump()

    assert "current_session_context" in dumped
    assert dumped["current_session_context"]["session_intent"] == "refining_options"
    assert dumped["current_session_context"]["extracted_parameters"]["hard_constraints"][0]["operator"] == "less_than"

    # JSON mode dump must produce pure primitives
    dumped_json = model.model_dump(mode="json")
    assert isinstance(dumped_json["current_session_context"]["session_intent"], str)
    assert dumped_json["current_session_context"]["session_intent"] == "refining_options"

    # to_dict helper
    dict_out = model.to_dict()
    assert "current_session_context" in dict_out
    assert isinstance(dict_out["current_session_context"]["session_intent"], str)


def test_model_dump_json_roundtrip(canonical_session_context_dict):
    """Verifies full roundtrip serialization via model_dump_json and model_validate_json."""
    model = CurrentSessionContext.model_validate(canonical_session_context_dict)
    json_str = model.model_dump_json()

    # Valid JSON string
    parsed = json.loads(json_str)
    assert "current_session_context" in parsed

    # Deserialization matches original model
    reconstructed = CurrentSessionContext.model_validate_json(json_str)
    assert reconstructed == model

    # from_json helper
    reconstructed_from_json = CurrentSessionContext.from_json(json_str)
    assert reconstructed_from_json == model


def test_model_validate_json_malformed():
    """Verifies that invalid JSON syntax raises ValidationError / JSONDecodeError."""
    with pytest.raises(Exception):
        CurrentSessionContext.model_validate_json("{not valid json syntax")


# ============================================================================
# Group C: Enum Validation (F2, F4, F8, E2, E3)
# ============================================================================

@pytest.mark.parametrize("intent_val", [
    "initial_search",
    "exploring_domain",
    "refining_options",
    "comparing_items",
    "finalizing_choice"
])
def test_valid_session_intent_enums(intent_val):
    """All 5 defined session intents must be accepted."""
    ctx = SessionContext(session_intent=intent_val)
    assert ctx.session_intent == SessionIntent(intent_val)
    assert ctx.session_intent.value == intent_val


@pytest.mark.parametrize("invalid_intent", [
    "browsing",
    "search",
    "chitchat",
    "RECOMMENDATION",
    "",
    "unknown_action",
    123
])
def test_invalid_session_intent_raises_validation_error_e2(invalid_intent):
    """Invalid session intent strings must raise ValidationError (Edge Case E2)."""
    with pytest.raises(ValidationError):
        SessionContext(session_intent=invalid_intent)


@pytest.mark.parametrize("op_val", [
    "include",
    "exclude",
    "greater_than",
    "less_than",
    "equal"
])
def test_valid_constraint_operator_enums(op_val):
    """All 5 defined constraint operators must be accepted."""
    c = HardConstraint(attribute="price", operator=op_val, value=1000)
    assert c.operator == ConstraintOperator(op_val)
    assert c.operator == HardConstraintOperator(op_val)
    assert c.operator.value == op_val


@pytest.mark.parametrize("invalid_op", [
    "<",
    ">",
    "eq",
    "not_in",
    "contains",
    "LIKE",
    "",
    "inside"
])
def test_invalid_constraint_operator_raises_validation_error_e3(invalid_op):
    """Invalid constraint operators must raise ValidationError (Edge Case E3)."""
    with pytest.raises(ValidationError):
        HardConstraint(attribute="brand", operator=invalid_op, value="Apple")


@pytest.mark.parametrize("action_val", [
    "ask_clarification",
    "present_results",
    "change_topic"
])
def test_valid_suggested_system_action_enums(action_val):
    """All 3 defined suggested system actions must be accepted."""
    ds = DialogueState(suggested_system_action=action_val)
    assert ds.suggested_system_action == SuggestedSystemAction(action_val)
    assert ds.suggested_system_action.value == action_val


@pytest.mark.parametrize("invalid_action", [
    "clarify",
    "search",
    "recommend",
    "PRESENT",
    "",
    42
])
def test_invalid_suggested_system_action_raises_validation_error(invalid_action):
    """Invalid suggested system action strings must raise ValidationError."""
    with pytest.raises(ValidationError):
        DialogueState(suggested_system_action=invalid_action)


# ============================================================================
# Group D: Boundary Checks: Polarity & Confidence (F5, E4, E5)
# ============================================================================

@pytest.mark.parametrize("valid_polarity", [-1.0, -0.7, -0.01, 0.0, 0.45, 0.8, 1.0, -1, 1])
def test_valid_polarity_boundaries(valid_polarity):
    """Polarity within [-1.0, 1.0] must be accepted."""
    pref = SoftPreference(category="brand", value="Apple", polarity=valid_polarity, confidence=0.8, evidence="User said so")
    assert -1.0 <= pref.polarity <= 1.0


@pytest.mark.parametrize("invalid_polarity", [-1.001, 1.001, -2.0, 1.5, 100.0, -99.9])
def test_invalid_polarity_out_of_bounds_raises_error_e4(invalid_polarity):
    """Polarity outside [-1.0, 1.0] must raise ValidationError (Edge Case E4)."""
    with pytest.raises(ValidationError):
        SoftPreference(category="brand", value="Apple", polarity=invalid_polarity, confidence=0.8, evidence="text")


@pytest.mark.parametrize("valid_confidence", [0.0, 0.1, 0.5, 0.99, 1.0, 0, 1])
def test_valid_confidence_boundaries(valid_confidence):
    """Confidence within [0.0, 1.0] must be accepted."""
    pref = SoftPreference(category="weight", value="light", polarity=0.5, confidence=valid_confidence, evidence="reason")
    assert 0.0 <= pref.confidence <= 1.0


@pytest.mark.parametrize("invalid_confidence", [-0.001, -0.5, 1.001, 1.5, 10.0])
def test_invalid_confidence_out_of_bounds_raises_error_e5(invalid_confidence):
    """Confidence outside [0.0, 1.0] must raise ValidationError (Edge Case E5)."""
    with pytest.raises(ValidationError):
        SoftPreference(category="weight", value="light", polarity=0.5, confidence=invalid_confidence, evidence="text")


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_soft_preference_non_finite_values_rejected(non_finite):
    """NaN and Inf must be rejected for polarity and confidence."""
    with pytest.raises(ValidationError):
        SoftPreference(category="weight", value="light", polarity=non_finite, confidence=0.8, evidence="text")
    with pytest.raises(ValidationError):
        SoftPreference(category="weight", value="light", polarity=0.5, confidence=non_finite, evidence="text")


# ============================================================================
# Group E: Polymorphism & Attribute Validation for HardConstraint (E6)
# ============================================================================

@pytest.mark.parametrize("val", ["ChromeOS", 1000, 999.99, "Apple", True])
def test_hard_constraint_value_polymorphism_e6(val):
    """HardConstraint.value must accept strings, ints, floats, bools (Edge Case E6)."""
    c = HardConstraint(attribute="test_attr", operator="include", value=val)
    assert c.value == val


def test_hard_constraint_numeric_coercion_e6():
    """Range operators coerce formatted strings to numeric int/float."""
    c_dollar = HardConstraint(attribute="price", operator=ConstraintOperator.LESS_THAN, value="$1,000")
    assert c_dollar.value == 1000 and isinstance(c_dollar.value, int)

    c_float = HardConstraint(attribute="price", operator=ConstraintOperator.LESS_THAN, value="1000.50")
    assert c_float.value == 1000.5 and isinstance(c_float.value, float)

    c_cat = HardConstraint(attribute="os", operator=ConstraintOperator.EXCLUDE, value="ChromeOS")
    assert c_cat.value == "ChromeOS" and isinstance(c_cat.value, str)

    c_int_cat = HardConstraint(attribute="ram", operator=ConstraintOperator.EQUAL, value=16)
    assert c_int_cat.value == 16 and isinstance(c_int_cat.value, int)

    with pytest.raises(ValidationError):
        HardConstraint(attribute="price", operator=ConstraintOperator.LESS_THAN, value="no_number_here")


def test_whitespace_sanitization():
    """Attribute, category, and value strings must be trimmed and non-empty."""
    hc = HardConstraint(attribute=" Price ", operator=ConstraintOperator.LESS_THAN, value=500)
    assert hc.attribute == "price"

    sp = SoftPreference(category=" Brand ", value=" Apple ", polarity=0.5)
    assert sp.category == "Brand"
    assert sp.value == "Apple"

    with pytest.raises(ValidationError):
        HardConstraint(attribute="   ", operator=ConstraintOperator.LESS_THAN, value=500)

    with pytest.raises(ValidationError):
        SoftPreference(category="   ", value="Apple", polarity=0.5)

    with pytest.raises(ValidationError):
        SoftPreference(category="Brand", value="   ", polarity=0.5)


# ============================================================================
# Group F: Dialogue State & Dict Interface
# ============================================================================

def test_dialogue_state_missing_attributes():
    """DialogueState handles missing critical attributes list correctly."""
    ds = DialogueState(
        ready_for_recommendation=True,
        missing_critical_attributes=[],
        suggested_system_action="present_results"
    )
    assert ds.ready_for_recommendation is True
    assert ds.missing_critical_attributes == []

    ds_missing = DialogueState(
        ready_for_recommendation=False,
        missing_critical_attributes=["price", "screen_size"],
        suggested_system_action="ask_clarification"
    )
    assert ds_missing.ready_for_recommendation is False
    assert len(ds_missing.missing_critical_attributes) == 2


def test_dict_like_access_on_models(canonical_session_context_dict):
    """Models support dictionary-like get, __getitem__, and __contains__ access."""
    wrapper = CurrentSessionContext.model_validate(canonical_session_context_dict)
    ctx = wrapper.current_session_context

    assert wrapper["current_session_context"] == ctx
    assert wrapper["session_intent"] == SessionIntent.REFINING_OPTIONS
    assert wrapper.get("session_intent") == SessionIntent.REFINING_OPTIONS
    assert "session_intent" in wrapper
    assert "current_session_context" in wrapper

    assert ctx["session_intent"] == SessionIntent.REFINING_OPTIONS
    assert ctx.get("situational_context") != ""
    assert "extracted_parameters" in ctx


# ============================================================================
# Group G: Robust Number Parsing & Safe Dict Emulation (Remediation M1)
# ============================================================================

def test_extract_numeric_robust_international_currencies():
    """Verifies robust European and international decimal disambiguation."""
    from src.dialog_manager.session_schema import extract_numeric_robust, _extract_numeric

    # European comma decimals
    assert abs(extract_numeric_robust("2500,00 zł") - 2500.0) < 1e-4
    assert abs(extract_numeric_robust("1500,50 €") - 1500.5) < 1e-4
    assert abs(extract_numeric_robust("1.500,50 €") - 1500.5) < 1e-4
    assert abs(extract_numeric_robust("99,99 zł") - 99.99) < 1e-4
    assert abs(extract_numeric_robust("1500,5") - 1500.5) < 1e-4

    # Via _extract_numeric with disambiguate_comma=True
    assert abs(_extract_numeric("2500,00 zł", disambiguate_comma=True) - 2500.0) < 1e-4
    assert abs(_extract_numeric("1500,50 €", disambiguate_comma=True) - 1500.5) < 1e-4

    # US / UK standard formats
    assert abs(extract_numeric_robust("$1,200.50") - 1200.5) < 1e-4
    assert abs(extract_numeric_robust("£99.99") - 99.99) < 1e-4
    assert extract_numeric_robust("$1000") == 1000

    # Large numbers and scientific notation
    assert extract_numeric_robust("1,000,000") == 1000000
    assert abs(extract_numeric_robust("1.000.000,50") - 1000000.5) < 1e-4
    assert abs(extract_numeric_robust("1e3") - 1000.0) < 1e-4

    # Rejection of invalid inputs
    with pytest.raises(ValueError):
        extract_numeric_robust(True)
    with pytest.raises(ValueError):
        extract_numeric_robust(float("nan"))
    with pytest.raises(ValueError):
        extract_numeric_robust(float("inf"))
    with pytest.raises(ValueError):
        extract_numeric_robust("")
    with pytest.raises(ValueError):
        extract_numeric_robust("no digits here")


def test_dict_like_safe_access_on_models(canonical_session_context_dict):
    """Verifies that safe_get, safe_contains, and get(safe=True) handle non-string keys gracefully."""
    wrapper = CurrentSessionContext.model_validate(canonical_session_context_dict)
    ctx = wrapper.current_session_context

    # Safe get returns default on non-string keys
    assert wrapper.safe_get(None) is None
    assert wrapper.safe_get(0, "default_val") == "default_val"
    assert ctx.safe_get(None) is None
    assert ctx.safe_get(0, "default_val") == "default_val"

    # get(safe=True) returns default on non-string keys
    assert wrapper.get(None, safe=True) is None
    assert wrapper.get(0, "default_val", safe=True) == "default_val"
    assert ctx.get(None, safe=True) is None
    assert ctx.get(0, "default_val", safe=True) == "default_val"

    # Safe contains returns False on non-string keys
    assert wrapper.safe_contains(None) is False
    assert wrapper.safe_contains(0) is False
    assert ctx.safe_contains(None) is False
    assert ctx.safe_contains(0) is False
