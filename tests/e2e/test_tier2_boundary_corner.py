"""
Tier 2: Boundary & Corner Cases E2E Tests (F1 through F11).
Verifies strict validation, boundary limits, clampings, enum enforcement,
empty inputs, type coercions, and malformed inputs.
>= 5 test cases per feature.
"""
from typing import Any, Dict
import pytest

from tests.e2e.schema_validator import (
    validate_session_context_schema,
)


# ==============================================================================
# F1: Root Wrapper Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f1_null_root_wrapper():
    """T2.F1.1: Null/None as root value is rejected."""
    payload = {"current_session_context": None}
    is_valid, errors = validate_session_context_schema(payload)
    assert not is_valid
    assert len(errors) > 0


@pytest.mark.tier2
def test_t2_f1_primitive_root_wrapper():
    """T2.F1.2: String primitive as root wrapper value is rejected."""
    payload = {"current_session_context": "invalid_string_instead_of_object"}
    is_valid, errors = validate_session_context_schema(payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f1_list_root_wrapper():
    """T2.F1.3: Array/list as root wrapper value is rejected."""
    payload = {"current_session_context": []}
    is_valid, errors = validate_session_context_schema(payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f1_extra_keys_in_root(minimal_valid_payload: Dict[str, Any]):
    """T2.F1.4: Extra sibling keys alongside current_session_context are rejected."""
    payload = minimal_valid_payload.copy()
    payload["extra_unauthorized_key"] = "malicious_payload"
    is_valid, errors = validate_session_context_schema(payload)
    assert not is_valid
    assert any("extra_unauthorized_key" in e for e in errors)


@pytest.mark.tier2
def test_t2_f1_nested_duplicate_root(minimal_valid_payload: Dict[str, Any]):
    """T2.F1.5: Double wrapping root key is rejected."""
    payload = {"current_session_context": minimal_valid_payload}
    is_valid, errors = validate_session_context_schema(payload)
    assert not is_valid


# ==============================================================================
# F2: Session Intent Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
@pytest.mark.parametrize("invalid_intent", [
    "browsing",
    "search",
    "query",
    "recommendation",
    "clarification",
    "buying",
])
def test_t2_f2_invalid_intent_string(minimal_valid_payload: Dict[str, Any], invalid_intent: str):
    """T2.F2.1: Disallowed intent strings are rejected."""
    minimal_valid_payload["current_session_context"]["session_intent"] = invalid_intent
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("session_intent" in e for e in errors)


@pytest.mark.tier2
def test_t2_f2_uppercase_intent_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F2.2: Uppercase session intent is rejected (must be lowercase snake_case)."""
    minimal_valid_payload["current_session_context"]["session_intent"] = "INITIAL_SEARCH"
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f2_empty_string_intent_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F2.3: Empty string session intent is rejected."""
    minimal_valid_payload["current_session_context"]["session_intent"] = ""
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f2_null_intent_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F2.4: Null/None session intent is rejected."""
    minimal_valid_payload["current_session_context"]["session_intent"] = None
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f2_numeric_intent_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F2.5: Numeric session intent is rejected."""
    minimal_valid_payload["current_session_context"]["session_intent"] = 1
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


# ==============================================================================
# F3: Situational Context Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f3_whitespace_only(minimal_valid_payload: Dict[str, Any]):
    """T2.F3.1: Whitespace-only situational context remains a valid string."""
    minimal_valid_payload["current_session_context"]["situational_context"] = "   \t\n   "
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid


@pytest.mark.tier2
def test_t2_f3_huge_text(minimal_valid_payload: Dict[str, Any]):
    """T2.F3.2: 10,000 character situational context is validated without error."""
    minimal_valid_payload["current_session_context"]["situational_context"] = "A" * 10000
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid


@pytest.mark.tier2
def test_t2_f3_unicode_and_emojis(minimal_valid_payload: Dict[str, Any]):
    """T2.F3.3: Situational context with multilingual Unicode and emojis."""
    text = "Kupuję laptop dla córki na studia 🎓 w Warszawie. Szukam czegoś lekkiego 💻! €1000 max."
    minimal_valid_payload["current_session_context"]["situational_context"] = text
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid


@pytest.mark.tier2
def test_t2_f3_non_string_type_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F3.4: List or dict passed for situational_context is rejected."""
    minimal_valid_payload["current_session_context"]["situational_context"] = ["not", "a", "string"]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f3_null_context_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F3.5: Null/None for situational context is rejected (must be string)."""
    minimal_valid_payload["current_session_context"]["situational_context"] = None
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


# ==============================================================================
# F4: Hard Constraint Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
@pytest.mark.parametrize("invalid_op", ["<", ">", "!=", "contains", "between", "regex", ""])
def test_t2_f4_invalid_operator_rejected(minimal_valid_payload: Dict[str, Any], invalid_op: str):
    """T2.F4.1: Disallowed constraint operators are rejected."""
    bad_constraint = {"attribute": "price", "operator": invalid_op, "value": 1000}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"] = [bad_constraint]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("operator" in e for e in errors)


@pytest.mark.tier2
def test_t2_f4_empty_attribute_string_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F4.2: Empty attribute name is rejected (minLength: 1)."""
    bad_constraint = {"attribute": "", "operator": "equal", "value": "val"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"] = [bad_constraint]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f4_missing_required_field_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F4.3: Constraint missing 'value' is rejected."""
    bad_constraint = {"attribute": "price", "operator": "less_than"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"] = [bad_constraint]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f4_extra_fields_in_constraint_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F4.4: Extra unpermitted fields in hard constraint object are rejected."""
    bad_constraint = {"attribute": "price", "operator": "less_than", "value": 1000, "priority": 1}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"] = [bad_constraint]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f4_numeric_negative_and_zero_values(minimal_valid_payload: Dict[str, Any]):
    """T2.F4.5: Zero and negative numeric values are valid numeric types."""
    c1 = {"attribute": "offset", "operator": "equal", "value": 0}
    c2 = {"attribute": "temperature", "operator": "greater_than", "value": -10.5}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"] = [c1, c2]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid


# ==============================================================================
# F5: Soft Preference Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f5_polarity_exact_upper_bound(minimal_valid_payload: Dict[str, Any]):
    """T2.F5.1: Polarity exactly 1.0 is valid."""
    pref = {"category": "brand", "value": "Apple", "polarity": 1.0, "confidence": 1.0, "evidence": "love it"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"] = [pref]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid


@pytest.mark.tier2
def test_t2_f5_polarity_exact_lower_bound(minimal_valid_payload: Dict[str, Any]):
    """T2.F5.2: Polarity exactly -1.0 is valid."""
    pref = {"category": "brand", "value": "Dell", "polarity": -1.0, "confidence": 1.0, "evidence": "hate it"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"] = [pref]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid


@pytest.mark.tier2
@pytest.mark.parametrize("invalid_polarity", [1.01, 1.5, 2.0, 100.0, -1.01, -1.5, -5.0])
def test_t2_f5_polarity_out_of_bounds_rejected(minimal_valid_payload: Dict[str, Any], invalid_polarity: float):
    """T2.F5.3: Polarity outside [-1.0, 1.0] is rejected."""
    pref = {"category": "b", "value": "v", "polarity": invalid_polarity, "confidence": 0.5, "evidence": "e"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"] = [pref]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("polarity" in e for e in errors)


@pytest.mark.tier2
def test_t2_f5_confidence_exact_boundaries(minimal_valid_payload: Dict[str, Any]):
    """T2.F5.4: Confidence at 0.0 and 1.0 are valid."""
    p1 = {"category": "c", "value": "v1", "polarity": 0.5, "confidence": 0.0, "evidence": "e"}
    p2 = {"category": "c", "value": "v2", "polarity": 0.5, "confidence": 1.0, "evidence": "e"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"] = [p1, p2]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid


@pytest.mark.tier2
@pytest.mark.parametrize("invalid_conf", [-0.01, -0.5, 1.01, 1.5, 10.0])
def test_t2_f5_confidence_out_of_bounds_rejected(minimal_valid_payload: Dict[str, Any], invalid_conf: float):
    """T2.F5.5: Confidence outside [0.0, 1.0] is rejected."""
    pref = {"category": "c", "value": "v", "polarity": 0.5, "confidence": invalid_conf, "evidence": "e"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"] = [pref]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("confidence" in e for e in errors)


# ==============================================================================
# F6: Recommendation Readiness Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f6_string_boolean_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F6.1: String 'true' instead of boolean True is rejected by strict schema."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["ready_for_recommendation"] = "true"
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f6_numeric_boolean_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F6.2: Integer 1 instead of boolean True is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["ready_for_recommendation"] = 1
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f6_null_readiness_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F6.3: Null/None for readiness is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["ready_for_recommendation"] = None
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f6_inconsistent_readiness_heuristic(dialogue_manager_factory):
    """T2.F6.4: DialogueManager prevents readiness=True when critical attributes are missing."""
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    # Send only brand
    extraction = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Apple"}],
                "soft_preferences": [],
            }
        }
    }
    ctx = dm.update_turn("sess_inconsistent", "Apple", extraction)
    assert ctx.dialogue_state.ready_for_recommendation is False
    assert len(ctx.dialogue_state.missing_critical_attributes) > 0


@pytest.mark.tier2
def test_t2_f6_readiness_with_only_soft_preferences(dialogue_manager_factory):
    """T2.F6.5: DialogueManager with soft preferences fulfilling critical category."""
    dm = dialogue_manager_factory(critical_attributes=["category"])
    extraction = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [],
                "soft_preferences": [
                    {"category": "category", "value": "laptop", "polarity": 0.9, "confidence": 1.0, "evidence": "stated laptop"}
                ],
            }
        }
    }
    ctx = dm.update_turn("sess_soft_only", "laptop", extraction)
    assert ctx.dialogue_state.ready_for_recommendation is True


# ==============================================================================
# F7: Critical Attribute Gap Detection Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f7_string_instead_of_list_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F7.1: Single string instead of array of strings is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["missing_critical_attributes"] = "category"
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f7_list_with_non_string_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F7.2: Missing critical attributes list with integers is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["missing_critical_attributes"] = [123, 456]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f7_null_missing_attributes_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F7.3: Null instead of empty list is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["missing_critical_attributes"] = None
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f7_case_insensitivity_matching(dialogue_manager_factory):
    """T2.F7.4: Attribute gap matching is case-insensitive (CATEGORY matches category)."""
    dm = dialogue_manager_factory(critical_attributes=["category"])
    extraction = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "CATEGORY", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            }
        }
    }
    ctx = dm.update_turn("sess_case", "laptop", extraction)
    assert "category" not in ctx.dialogue_state.missing_critical_attributes
    assert len(ctx.dialogue_state.missing_critical_attributes) == 0


@pytest.mark.tier2
def test_t2_f7_duplicate_critical_requirements(dialogue_manager_factory):
    """T2.F7.5: DialogueManager handles duplicate critical attribute configurations cleanly."""
    dm = dialogue_manager_factory(critical_attributes=["category", "category"])
    ctx = dm.get_context("sess_dup")
    assert ctx.dialogue_state.missing_critical_attributes == ["category"]


# ==============================================================================
# F8: Next System Action Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
@pytest.mark.parametrize("invalid_action", ["recommend", "search", "clarify", "exit", "continue", "done"])
def test_t2_f8_invalid_action_rejected(minimal_valid_payload: Dict[str, Any], invalid_action: str):
    """T2.F8.1: Disallowed system action enums are rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["suggested_system_action"] = invalid_action
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("suggested_system_action" in e for e in errors)


@pytest.mark.tier2
def test_t2_f8_uppercase_action_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F8.2: Uppercase action enum is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["suggested_system_action"] = "PRESENT_RESULTS"
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f8_empty_action_string_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F8.3: Empty string system action is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["suggested_system_action"] = ""
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f8_null_action_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F8.4: Null/None system action is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["suggested_system_action"] = None
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f8_numeric_action_rejected(minimal_valid_payload: Dict[str, Any]):
    """T2.F8.5: Numeric system action is rejected."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["suggested_system_action"] = 0
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


# ==============================================================================
# F9: Dialogue Manager Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f9_empty_session_id(dialogue_manager_factory):
    """T2.F9.1: DialogueManager handles empty session ID string without raising."""
    dm = dialogue_manager_factory()
    ctx = dm.get_context("")
    assert ctx is not None
    assert ctx.session_intent.value == "initial_search"


@pytest.mark.tier2
def test_t2_f9_rapid_sequential_updates(dialogue_manager_factory):
    """T2.F9.2: 50 sequential updates within a session preserve state integrity."""
    dm = dialogue_manager_factory()
    sess = "rapid_user"
    for i in range(50):
        extraction = {
            "current_session_context": {
                "extracted_parameters": {
                    "hard_constraints": [{"attribute": f"attr_{i % 5}", "operator": "equal", "value": i}],
                    "soft_preferences": [],
                }
            }
        }
        dm.update_turn(sess, f"turn {i}", extraction)

    ctx = dm.get_context(sess)
    # Since attributes are attr_0 to attr_4, only 5 unique attributes should remain
    assert len(ctx.extracted_parameters.hard_constraints) == 5


@pytest.mark.tier2
def test_t2_f9_none_payload_in_turn(dialogue_manager_factory):
    """T2.F9.3: DialogueManager safely handles empty dict in update_turn."""
    dm = dialogue_manager_factory()
    ctx = dm.update_turn("sess_empty", "test message", {})
    assert ctx is not None


@pytest.mark.tier2
def test_t2_f9_double_reset(dialogue_manager_factory):
    """T2.F9.4: Calling reset_session multiple times cleanly resets state."""
    dm = dialogue_manager_factory()
    dm.reset_session("sess_double_reset")
    dm.reset_session("sess_double_reset")
    ctx = dm.get_context("sess_double_reset")
    assert len(ctx.extracted_parameters.hard_constraints) == 0


@pytest.mark.tier2
def test_t2_f9_override_different_operator_same_attribute(dialogue_manager_factory):
    """T2.F9.5: Updating same attribute with different operator preserves both."""
    dm = dialogue_manager_factory()
    turn1 = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "ram", "operator": "greater_than", "value": 8}],
                "soft_preferences": [],
            }
        }
    }
    turn2 = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "ram", "operator": "less_than", "value": 32}],
                "soft_preferences": [],
            }
        }
    }
    dm.update_turn("sess_ram", "at least 8gb", turn1)
    updated = dm.update_turn("sess_ram", "at most 32gb", turn2)
    assert len(updated.extracted_parameters.hard_constraints) == 2


# ==============================================================================
# F10: Recommender Adapter Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f10_empty_constraints_list(adapter_functions):
    """T2.F10.1: Adapter returns empty dictionary for empty constraints list."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    filters = fn([])
    assert filters == {}


@pytest.mark.tier2
def test_t2_f10_unknown_attribute_handling(adapter_functions):
    """T2.F10.2: Unknown attributes do not crash adapter and are mapped safely."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    constraints = [{"attribute": "form_factor", "operator": "equal", "value": "convertible"}]
    filters = fn(constraints)
    assert filters.get("form_factor_equal") == "convertible"


@pytest.mark.tier2
def test_t2_f10_string_price_conversion(adapter_functions):
    """T2.F10.3: Price passed as string number ('1200') is parsed to float."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    constraints = [{"attribute": "price", "operator": "less_than", "value": "1200"}]
    filters = fn(constraints)
    assert filters.get("price_max") == 1200.0


@pytest.mark.tier2
def test_t2_f10_non_numeric_price_ignored(adapter_functions):
    """T2.F10.4: Non-numeric price string ('expensive') does not crash adapter."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    constraints = [{"attribute": "price", "operator": "less_than", "value": "expensive"}]
    filters = fn(constraints)
    assert "price_max" not in filters


@pytest.mark.tier2
def test_t2_f10_legacy_projection_with_empty_context(adapter_functions):
    """T2.F10.5: Legacy projection handles completely empty session context."""
    fn = adapter_functions["session_context_to_legacy_preferences"]
    empty_ctx = {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "",
            "extracted_parameters": {"hard_constraints": [], "soft_preferences": []},
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": [],
                "suggested_system_action": "ask_clarification",
            }
        }
    }
    legacy = fn(empty_ctx)
    assert legacy["likes"] == []
    assert legacy["dislikes"] == []
    assert legacy["constraints"] == {}
    assert legacy["intent"] == "initial_search"


# ==============================================================================
# F11: Multi-Turn Test Script / Parser Boundaries & Corners
# ==============================================================================

@pytest.mark.tier2
def test_t2_f11_corrupted_json_string():
    """T2.F11.1: Non-dictionary input string rejected by validator."""
    is_valid, errors = validate_session_context_schema("INVALID_NON_JSON")
    assert not is_valid
    assert any("dictionary" in e.lower() for e in errors)


@pytest.mark.tier2
def test_t2_f11_partially_missing_subobjects(minimal_valid_payload: Dict[str, Any]):
    """T2.F11.2: Payload missing dialogue_state subobject rejected."""
    del minimal_valid_payload["current_session_context"]["dialogue_state"]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("dialogue_state" in e for e in errors)


@pytest.mark.tier2
def test_t2_f11_missing_extracted_parameters(minimal_valid_payload: Dict[str, Any]):
    """T2.F11.3: Payload missing extracted_parameters subobject rejected."""
    del minimal_valid_payload["current_session_context"]["extracted_parameters"]
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("extracted_parameters" in e for e in errors)


@pytest.mark.tier2
def test_t2_f11_extra_properties_in_extracted_parameters(minimal_valid_payload: Dict[str, Any]):
    """T2.F11.4: Extra property in extracted_parameters rejected."""
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["unauthorized"] = 123
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid


@pytest.mark.tier2
def test_t2_f11_schema_validation_error_formatting(minimal_valid_payload: Dict[str, Any]):
    """T2.F11.5: Error message contains exact JSON path to the violating field."""
    minimal_valid_payload["current_session_context"]["session_intent"] = "INVALID"
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert not is_valid
    assert any("current_session_context.session_intent" in e for e in errors)
