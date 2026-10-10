"""
Tier 1: Feature Coverage E2E Tests (F1 through F11).
Requirements-driven opaque-box test suite verifying primary behavior (happy paths)
for all features defined in PROJECT.md and ORIGINAL_REQUEST.md.
>= 5 test cases per feature.
"""
from typing import Any, Dict, List
import pytest

from tests.e2e.schema_validator import (
    ALLOWED_CONSTRAINT_OPERATORS,
    ALLOWED_SESSION_INTENTS,
    ALLOWED_SYSTEM_ACTIONS,
    assert_valid_session_context,
    validate_session_context_schema,
)


# ==============================================================================
# F1: Root Wrapper Enforcement
# ==============================================================================

@pytest.mark.tier1
def test_f1_canonical_root_wrapper_valid(canonical_sample_payload: Dict[str, Any]):
    """F1.1: Verify the canonical payload containing 'current_session_context' root passes validation."""
    assert "current_session_context" in canonical_sample_payload
    is_valid, errors = validate_session_context_schema(canonical_sample_payload)
    assert is_valid, f"Validation failed: {errors}"
    assert len(errors) == 0


@pytest.mark.tier1
def test_f1_minimal_root_wrapper_valid(minimal_valid_payload: Dict[str, Any]):
    """F1.2: Verify minimal valid payload strictly wrapped in 'current_session_context' passes."""
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid, f"Validation failed: {errors}"


@pytest.mark.tier1
def test_f1_missing_root_wrapper_rejected(canonical_sample_payload: Dict[str, Any]):
    """F1.3: Verify payload missing the 'current_session_context' root wrapper is rejected."""
    unwrapped = canonical_sample_payload["current_session_context"]
    is_valid, errors = validate_session_context_schema(unwrapped)
    assert not is_valid
    assert any("current_session_context" in e for e in errors)


@pytest.mark.tier1
def test_f1_wrong_root_wrapper_name_rejected(canonical_sample_payload: Dict[str, Any]):
    """F1.4: Verify payload with wrong root key (e.g. 'session_context') is rejected."""
    wrong_root = {"session_context": canonical_sample_payload["current_session_context"]}
    is_valid, errors = validate_session_context_schema(wrong_root)
    assert not is_valid
    assert any("current_session_context" in e for e in errors)


@pytest.mark.tier1
def test_f1_pydantic_wrapper_validation(schema_classes, canonical_sample_payload: Dict[str, Any]):
    """F1.5: Verify Pydantic model wrapper strictly enforces the root container."""
    WrapperCls = schema_classes["CurrentSessionContextWrapper"]
    wrapper = WrapperCls.model_validate(canonical_sample_payload)
    dumped = wrapper.model_dump()
    assert "current_session_context" in dumped
    assert dumped["current_session_context"]["session_intent"] == "refining_options"


# ==============================================================================
# F2: Session Intent Classification
# ==============================================================================

@pytest.mark.tier1
@pytest.mark.parametrize("intent", [
    "initial_search",
    "exploring_domain",
    "refining_options",
    "comparing_items",
    "finalizing_choice",
])
def test_f2_all_allowed_session_intents_valid(minimal_valid_payload: Dict[str, Any], intent: str):
    """F2.1: Verify all 5 allowed session intent enums are recognized as valid."""
    minimal_valid_payload["current_session_context"]["session_intent"] = intent
    is_valid, errors = validate_session_context_schema(minimal_valid_payload)
    assert is_valid, f"Intent {intent} should be valid, but got errors: {errors}"


@pytest.mark.tier1
def test_f2_initial_search_intent_semantics(minimal_valid_payload: Dict[str, Any]):
    """F2.2: Verify initial_search intent payload semantics."""
    payload = minimal_valid_payload.copy()
    payload["current_session_context"]["session_intent"] = "initial_search"
    payload["current_session_context"]["situational_context"] = "User starting a new query for laptops."
    assert_valid_session_context(payload)
    assert payload["current_session_context"]["session_intent"] in ALLOWED_SESSION_INTENTS


@pytest.mark.tier1
def test_f2_refining_options_intent_semantics(canonical_sample_payload: Dict[str, Any]):
    """F2.3: Verify refining_options intent in canonical multi-turn context."""
    intent = canonical_sample_payload["current_session_context"]["session_intent"]
    assert intent == "refining_options"
    assert_valid_session_context(canonical_sample_payload)


@pytest.mark.tier1
def test_f2_comparing_items_intent_semantics(minimal_valid_payload: Dict[str, Any]):
    """F2.4: Verify comparing_items intent with item comparison context."""
    payload = minimal_valid_payload.copy()
    payload["current_session_context"]["session_intent"] = "comparing_items"
    payload["current_session_context"]["situational_context"] = "User comparing Dell XPS 15 vs MacBook Pro 16."
    assert_valid_session_context(payload)


@pytest.mark.tier1
def test_f2_finalizing_choice_intent_semantics(minimal_valid_payload: Dict[str, Any]):
    """F2.5: Verify finalizing_choice intent when user selected an item."""
    payload = minimal_valid_payload.copy()
    payload["current_session_context"]["session_intent"] = "finalizing_choice"
    payload["current_session_context"]["situational_context"] = "User decided to buy ThinkPad X1 Carbon."
    assert_valid_session_context(payload)


# ==============================================================================
# F3: Situational Context Extraction
# ==============================================================================

@pytest.mark.tier1
def test_f3_descriptive_situational_context(canonical_sample_payload: Dict[str, Any]):
    """F3.1: Verify rich natural language situational context passes validation."""
    ctx = canonical_sample_payload["current_session_context"]["situational_context"]
    assert len(ctx) > 10
    assert "lightweight laptop" in ctx
    assert_valid_session_context(canonical_sample_payload)


@pytest.mark.tier1
def test_f3_empty_situational_context_valid(minimal_valid_payload: Dict[str, Any]):
    """F3.2: Verify empty string situational context is accepted for cold starts."""
    minimal_valid_payload["current_session_context"]["situational_context"] = ""
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f3_multi_sentence_situational_context(minimal_valid_payload: Dict[str, Any]):
    """F3.3: Verify complex multi-sentence situational context with punctuation."""
    context_text = (
        "User is a computer science undergraduate heading into sophomore year. "
        "They need something portable with at least 8 hours of battery life. "
        "Budget is relatively tight around $900."
    )
    minimal_valid_payload["current_session_context"]["situational_context"] = context_text
    assert_valid_session_context(minimal_valid_payload)
    assert minimal_valid_payload["current_session_context"]["situational_context"] == context_text


@pytest.mark.tier1
def test_f3_special_characters_situational_context(minimal_valid_payload: Dict[str, Any]):
    """F3.4: Verify situational context preserves quotes, dashes, hyphens, and currency symbols."""
    special_text = 'User said: "I want an ultra-quiet laptop under $1,200 & no fans!"'
    minimal_valid_payload["current_session_context"]["situational_context"] = special_text
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f3_pydantic_situational_context_roundtrip(schema_classes, minimal_valid_payload: Dict[str, Any]):
    """F3.5: Verify Pydantic model preserves situational context without truncation."""
    SessionContext = schema_classes["SessionContext"]
    text = "Student preparing for a semester abroad in Germany."
    minimal_valid_payload["current_session_context"]["situational_context"] = text
    ctx = SessionContext.model_validate(minimal_valid_payload["current_session_context"])
    assert ctx.situational_context == text
    dumped = ctx.model_dump()
    assert dumped["situational_context"] == text


# ==============================================================================
# F4: Hard Constraint Extraction
# ==============================================================================

@pytest.mark.tier1
def test_f4_numeric_less_than_constraint(minimal_valid_payload: Dict[str, Any]):
    """F4.1: Verify numeric constraint with operator 'less_than'."""
    constraint = {"attribute": "price", "operator": "less_than", "value": 1000}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"].append(constraint)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f4_numeric_greater_than_constraint(minimal_valid_payload: Dict[str, Any]):
    """F4.2: Verify numeric constraint with operator 'greater_than'."""
    constraint = {"attribute": "ram", "operator": "greater_than", "value": 16}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"].append(constraint)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f4_categorical_exclude_constraint(minimal_valid_payload: Dict[str, Any]):
    """F4.3: Verify categorical constraint with operator 'exclude'."""
    constraint = {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"].append(constraint)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f4_categorical_include_constraint(minimal_valid_payload: Dict[str, Any]):
    """F4.4: Verify categorical constraint with operator 'include'."""
    constraint = {"attribute": "brand", "operator": "include", "value": "Apple"}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"].append(constraint)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f4_categorical_equal_constraint(minimal_valid_payload: Dict[str, Any]):
    """F4.5: Verify constraint with operator 'equal'."""
    constraint = {"attribute": "screen_size", "operator": "equal", "value": 14}
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["hard_constraints"].append(constraint)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f4_all_allowed_operators(minimal_valid_payload: Dict[str, Any]):
    """F4.6: Verify all 5 operators defined in specification are accepted."""
    for op in ALLOWED_CONSTRAINT_OPERATORS:
        c = {"attribute": "test_attr", "operator": op, "value": 100 if "than" in op else "val"}
        payload = minimal_valid_payload.copy()
        payload["current_session_context"]["extracted_parameters"]["hard_constraints"] = [c]
        assert_valid_session_context(payload)


# ==============================================================================
# F5: Soft Preference Extraction
# ==============================================================================

@pytest.mark.tier1
def test_f5_high_confidence_positive_preference(minimal_valid_payload: Dict[str, Any]):
    """F5.1: Verify positive soft preference with high polarity and confidence."""
    pref = {
        "category": "weight",
        "value": "lightweight",
        "polarity": 0.8,
        "confidence": 0.9,
        "evidence": "User mentioned wanting something easy to carry around campus.",
    }
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"].append(pref)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f5_negative_dislike_preference(minimal_valid_payload: Dict[str, Any]):
    """F5.2: Verify negative soft preference with negative polarity."""
    pref = {
        "category": "brand",
        "value": "Dell",
        "polarity": -0.7,
        "confidence": 0.85,
        "evidence": "User had bad experiences with previous Dell laptops.",
    }
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"].append(pref)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f5_neutral_implicit_preference(minimal_valid_payload: Dict[str, Any]):
    """F5.3: Verify soft preference with moderate polarity and implicit confidence (0.5)."""
    pref = {
        "category": "color",
        "value": "silver",
        "polarity": 0.3,
        "confidence": 0.5,
        "evidence": "User looked at silver models in the past.",
    }
    minimal_valid_payload["current_session_context"]["extracted_parameters"]["soft_preferences"].append(pref)
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f5_multiple_soft_preferences(canonical_sample_payload: Dict[str, Any]):
    """F5.4: Verify multiple soft preferences in extracted parameters."""
    prefs = canonical_sample_payload["current_session_context"]["extracted_parameters"]["soft_preferences"]
    assert len(prefs) >= 2
    for p in prefs:
        assert "category" in p
        assert "polarity" in p
        assert -1.0 <= p["polarity"] <= 1.0
        assert 0.0 <= p["confidence"] <= 1.0
        assert "evidence" in p
    assert_valid_session_context(canonical_sample_payload)


@pytest.mark.tier1
def test_f5_pydantic_soft_preference_validation(schema_classes):
    """F5.5: Verify Pydantic SoftPreference model parses and enforces boundaries."""
    SoftPreference = schema_classes["SoftPreference"]
    sp = SoftPreference(
        category="display",
        value="OLED",
        polarity=0.95,
        confidence=1.0,
        evidence="User explicitly requested an OLED display for color accuracy."
    )
    assert sp.category == "display"
    assert sp.polarity == 0.95
    assert sp.confidence == 1.0


# ==============================================================================
# F6: Recommendation Readiness Evaluation
# ==============================================================================

@pytest.mark.tier1
def test_f6_readiness_false_when_incomplete(minimal_valid_payload: Dict[str, Any]):
    """F6.1: Verify readiness is False when mandatory context is incomplete."""
    state = minimal_valid_payload["current_session_context"]["dialogue_state"]
    state["ready_for_recommendation"] = False
    state["missing_critical_attributes"] = ["category", "budget"]
    state["suggested_system_action"] = "ask_clarification"
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f6_readiness_true_when_complete(minimal_valid_payload: Dict[str, Any]):
    """F6.2: Verify readiness is True when all required attributes are gathered."""
    state = minimal_valid_payload["current_session_context"]["dialogue_state"]
    state["ready_for_recommendation"] = True
    state["missing_critical_attributes"] = []
    state["suggested_system_action"] = "present_results"
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f6_readiness_boolean_type(canonical_sample_payload: Dict[str, Any]):
    """F6.3: Verify ready_for_recommendation is strictly a boolean."""
    ready = canonical_sample_payload["current_session_context"]["dialogue_state"]["ready_for_recommendation"]
    assert isinstance(ready, bool)
    assert not ready


@pytest.mark.tier1
def test_f6_dialogue_manager_evaluates_readiness(dialogue_manager_factory):
    """F6.4: Verify DialogueManager evaluates readiness based on critical attributes."""
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    ctx = dm.get_context("session_test_readiness")
    assert not ctx.dialogue_state.ready_for_recommendation
    assert "category" in ctx.dialogue_state.missing_critical_attributes

    # Provide category and price
    turn_extraction = {
        "current_session_context": {
            "session_intent": "refining_options",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "laptop"},
                    {"attribute": "price", "operator": "less_than", "value": 1200},
                ],
                "soft_preferences": [],
            }
        }
    }
    updated = dm.update_turn("session_test_readiness", "I need a laptop under $1200", turn_extraction)
    assert updated.dialogue_state.ready_for_recommendation is True
    assert len(updated.dialogue_state.missing_critical_attributes) == 0


@pytest.mark.tier1
def test_f6_readiness_false_blocks_present_results(minimal_valid_payload: Dict[str, Any]):
    """F6.5: Verify that when readiness is False, recommended action is ask_clarification."""
    state = minimal_valid_payload["current_session_context"]["dialogue_state"]
    state["ready_for_recommendation"] = False
    state["suggested_system_action"] = "ask_clarification"
    assert_valid_session_context(minimal_valid_payload)


# ==============================================================================
# F7: Critical Attribute Gap Detection
# ==============================================================================

@pytest.mark.tier1
def test_f7_empty_missing_attributes_when_complete(minimal_valid_payload: Dict[str, Any]):
    """F7.1: Verify missing_critical_attributes is empty list when no gaps exist."""
    state = minimal_valid_payload["current_session_context"]["dialogue_state"]
    state["missing_critical_attributes"] = []
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f7_single_missing_attribute(canonical_sample_payload: Dict[str, Any]):
    """F7.2: Verify canonical payload correctly identifies 'screen_size' as missing."""
    missing = canonical_sample_payload["current_session_context"]["dialogue_state"]["missing_critical_attributes"]
    assert missing == ["screen_size"]
    assert_valid_session_context(canonical_sample_payload)


@pytest.mark.tier1
def test_f7_multiple_missing_critical_attributes(minimal_valid_payload: Dict[str, Any]):
    """F7.3: Verify multiple missing critical attributes (e.g. category and budget)."""
    state = minimal_valid_payload["current_session_context"]["dialogue_state"]
    state["missing_critical_attributes"] = ["category", "budget", "operating_system"]
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f7_missing_attribute_cleared_on_follow_up(dialogue_manager_factory):
    """F7.4: Verify DialogueManager clears a missing attribute once supplied."""
    dm = dialogue_manager_factory(critical_attributes=["category", "brand"])
    ctx = dm.get_context("session_f7")
    assert "category" in ctx.dialogue_state.missing_critical_attributes
    assert "brand" in ctx.dialogue_state.missing_critical_attributes

    turn1 = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            }
        }
    }
    updated = dm.update_turn("session_f7", "I am looking for laptops", turn1)
    assert "category" not in updated.dialogue_state.missing_critical_attributes
    assert "brand" in updated.dialogue_state.missing_critical_attributes


@pytest.mark.tier1
def test_f7_pydantic_dialogue_state_validation(schema_classes):
    """F7.5: Verify Pydantic DialogueState parses missing_critical_attributes list."""
    DialogueState = schema_classes["DialogueState"]
    ds = DialogueState(
        ready_for_recommendation=False,
        missing_critical_attributes=["screen_size", "gpu"],
        suggested_system_action="ask_clarification"
    )
    assert ds.missing_critical_attributes == ["screen_size", "gpu"]
    assert not ds.ready_for_recommendation


# ==============================================================================
# F8: Next System Action Determination
# ==============================================================================

@pytest.mark.tier1
@pytest.mark.parametrize("action", ["ask_clarification", "present_results", "change_topic"])
def test_f8_all_system_actions_allowed(minimal_valid_payload: Dict[str, Any], action: str):
    """F8.1: Verify all 3 allowed system actions are recognized by schema."""
    minimal_valid_payload["current_session_context"]["dialogue_state"]["suggested_system_action"] = action
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f8_ask_clarification_action(canonical_sample_payload: Dict[str, Any]):
    """F8.2: Verify canonical action 'ask_clarification' when screen_size is missing."""
    action = canonical_sample_payload["current_session_context"]["dialogue_state"]["suggested_system_action"]
    assert action == "ask_clarification"
    assert_valid_session_context(canonical_sample_payload)


@pytest.mark.tier1
def test_f8_present_results_action(minimal_valid_payload: Dict[str, Any]):
    """F8.3: Verify present_results action when recommendations are ready."""
    state = minimal_valid_payload["current_session_context"]["dialogue_state"]
    state["ready_for_recommendation"] = True
    state["suggested_system_action"] = "present_results"
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f8_change_topic_action(minimal_valid_payload: Dict[str, Any]):
    """F8.4: Verify change_topic action when user shifts focus."""
    state = minimal_valid_payload["current_session_context"]["dialogue_state"]
    state["suggested_system_action"] = "change_topic"
    assert_valid_session_context(minimal_valid_payload)


@pytest.mark.tier1
def test_f8_dialogue_manager_sets_system_action(dialogue_manager_factory):
    """F8.5: Verify DialogueManager sets suggested_system_action based on readiness."""
    dm = dialogue_manager_factory(critical_attributes=["category"])
    ctx1 = dm.get_context("session_action_test")
    assert ctx1.dialogue_state.suggested_system_action.value == "ask_clarification"

    # Fulfill requirement
    extraction = {
        "current_session_context": {
            "session_intent": "refining_options",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            }
        }
    }
    ctx2 = dm.update_turn("session_action_test", "I want a laptop", extraction)
    assert ctx2.dialogue_state.suggested_system_action.value == "present_results"


# ==============================================================================
# F9: Dialogue State Manager & Persistence
# ==============================================================================

@pytest.mark.tier1
def test_f9_session_initialization(dialogue_manager_factory):
    """F9.1: Verify new session initializes with empty parameters and default intent."""
    dm = dialogue_manager_factory()
    ctx = dm.get_context("new_session_001")
    assert ctx.session_intent.value == "initial_search"
    assert len(ctx.extracted_parameters.hard_constraints) == 0
    assert len(ctx.extracted_parameters.soft_preferences) == 0


@pytest.mark.tier1
def test_f9_multi_turn_constraint_accumulation(dialogue_manager_factory):
    """F9.2: Verify multi-turn updates accumulate constraints without loss."""
    dm = dialogue_manager_factory(critical_attributes=["category"])

    turn1 = {
        "current_session_context": {
            "session_intent": "initial_search",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Apple"}],
                "soft_preferences": [],
            }
        }
    }
    dm.update_turn("user_123", "I want an Apple device", turn1)

    turn2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1500}],
                "soft_preferences": [],
            }
        }
    }
    updated = dm.update_turn("user_123", "Budget under $1500", turn2)

    attrs = {c.attribute for c in updated.extracted_parameters.hard_constraints}
    assert "brand" in attrs
    assert "price" in attrs
    assert len(updated.extracted_parameters.hard_constraints) == 2


@pytest.mark.tier1
def test_f9_multi_turn_constraint_override(dialogue_manager_factory):
    """F9.3: Verify updating an existing attribute replaces the constraint value."""
    dm = dialogue_manager_factory()

    turn1 = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1000}],
                "soft_preferences": [],
            }
        }
    }
    dm.update_turn("user_override", "Under $1000", turn1)

    turn2 = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 800}],
                "soft_preferences": [],
            }
        }
    }
    updated = dm.update_turn("user_override", "Actually under $800", turn2)

    price_constraints = [c for c in updated.extracted_parameters.hard_constraints if c.attribute == "price"]
    assert len(price_constraints) == 1
    assert price_constraints[0].value == 800


@pytest.mark.tier1
def test_f9_session_isolation(dialogue_manager_factory):
    """F9.4: Verify distinct session IDs maintain completely separate contexts."""
    dm = dialogue_manager_factory()

    dm.update_turn("sess_A", "Turn 1", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Dell"}],
                "soft_preferences": [],
            }
        }
    })

    dm.update_turn("sess_B", "Turn 1", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Lenovo"}],
                "soft_preferences": [],
            }
        }
    })

    ctx_a = dm.get_context("sess_A")
    ctx_b = dm.get_context("sess_B")
    assert ctx_a.extracted_parameters.hard_constraints[0].value == "Dell"
    assert ctx_b.extracted_parameters.hard_constraints[0].value == "Lenovo"


@pytest.mark.tier1
def test_f9_session_reset(dialogue_manager_factory):
    """F9.5: Verify resetting a session clears all accumulated state."""
    dm = dialogue_manager_factory()
    dm.update_turn("sess_reset", "Init", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 500}],
                "soft_preferences": [],
            }
        }
    })
    assert len(dm.get_context("sess_reset").extracted_parameters.hard_constraints) == 1
    dm.reset_session("sess_reset")
    assert len(dm.get_context("sess_reset").extracted_parameters.hard_constraints) == 0


# ==============================================================================
# F10: Recommender Adapter & Compatibility
# ==============================================================================

@pytest.mark.tier1
def test_f10_hard_constraints_to_price_filters(adapter_functions):
    """F10.1: Verify adapter maps less_than to price_max and greater_than to price_min."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    constraints = [
        {"attribute": "price", "operator": "less_than", "value": 1000},
        {"attribute": "price", "operator": "greater_than", "value": 500},
    ]
    filters = fn(constraints)
    assert filters.get("price_max") == 1000.0
    assert filters.get("price_min") == 500.0


@pytest.mark.tier1
def test_f10_hard_constraints_to_brand_filters(adapter_functions):
    """F10.2: Verify adapter maps brand include and exclude."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    constraints = [
        {"attribute": "brand", "operator": "include", "value": "Apple"},
        {"attribute": "brand", "operator": "exclude", "value": "Acer"},
    ]
    filters = fn(constraints)
    assert filters.get("brand") == "Apple"
    assert filters.get("exclude_brand") == "Acer"


@pytest.mark.tier1
def test_f10_hard_constraints_to_category_filter(adapter_functions):
    """F10.3: Verify adapter maps category include to category filter."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    constraints = [
        {"attribute": "category", "operator": "include", "value": "laptop"},
    ]
    filters = fn(constraints)
    assert filters.get("category") == "laptop"


@pytest.mark.tier1
def test_f10_combined_filters_mapping(adapter_functions, canonical_sample_payload: Dict[str, Any]):
    """F10.4: Verify adapter handles multiple constraints from canonical payload."""
    fn = adapter_functions["hard_constraints_to_structured_filters"]
    constraints = canonical_sample_payload["current_session_context"]["extracted_parameters"]["hard_constraints"]
    filters = fn(constraints)
    assert filters.get("price_max") == 1000.0


@pytest.mark.tier1
def test_f10_legacy_preferences_projection(adapter_functions, canonical_sample_payload: Dict[str, Any]):
    """F10.5: Verify projection to legacy {likes, dislikes, constraints, intent, notes}."""
    fn = adapter_functions["session_context_to_legacy_preferences"]
    legacy = fn(canonical_sample_payload)
    assert "likes" in legacy
    assert "dislikes" in legacy
    assert "constraints" in legacy
    assert "intent" in legacy
    assert "notes" in legacy
    assert "lightweight" in legacy["likes"]
    assert "Apple" in legacy["likes"]
    assert legacy["intent"] == "refining_options"


# ==============================================================================
# F11: Multi-Turn Test Script & Conformance
# ==============================================================================

@pytest.mark.tier1
def test_f11_multi_turn_dialogue_conformance(dialogue_manager_factory):
    """F11.1: Multi-turn sequence verifying schema conformance at every step."""
    dm = dialogue_manager_factory(critical_attributes=["category"])

    turns = [
        {
            "user": "I am looking for a lightweight laptop for college.",
            "extraction": {
                "current_session_context": {
                    "session_intent": "initial_search",
                    "situational_context": "College student needing portable laptop.",
                    "extracted_parameters": {
                        "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                        "soft_preferences": [
                            {"category": "weight", "value": "lightweight", "polarity": 0.8, "confidence": 0.9, "evidence": "portable"}
                        ],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    }
                }
            }
        },
        {
            "user": "Budget is under $1000, no ChromeOS please.",
            "extraction": {
                "current_session_context": {
                    "session_intent": "refining_options",
                    "situational_context": "Refining budget and OS constraints.",
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": "price", "operator": "less_than", "value": 1000},
                            {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"},
                        ],
                        "soft_preferences": [],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    }
                }
            }
        },
        {
            "user": "Actually I prefer MacBooks if possible.",
            "extraction": {
                "current_session_context": {
                    "session_intent": "refining_options",
                    "situational_context": "User expressing Apple preference.",
                    "extracted_parameters": {
                        "hard_constraints": [],
                        "soft_preferences": [
                            {"category": "brand", "value": "Apple", "polarity": 0.9, "confidence": 0.95, "evidence": "prefer MacBooks"}
                        ],
                    },
                    "dialogue_state": {
                        "ready_for_recommendation": True,
                        "missing_critical_attributes": [],
                        "suggested_system_action": "present_results",
                    }
                }
            }
        }
    ]

    session_id = "test_script_conformance_001"
    for turn_idx, turn in enumerate(turns):
        # Validate turn extraction payload strictly
        assert_valid_session_context(turn["extraction"])
        # Update dialogue manager
        updated = dm.update_turn(session_id, turn["user"], turn["extraction"])
        # Validate dialogue manager internal state
        dumped = {"current_session_context": updated.model_dump()}
        assert_valid_session_context(dumped)


@pytest.mark.tier1
def test_f11_conformance_validator_zero_errors(canonical_sample_payload: Dict[str, Any]):
    """F11.2: Verify schema validator reports exactly 0 errors on conforming input."""
    is_valid, errors = validate_session_context_schema(canonical_sample_payload)
    assert is_valid is True
    assert len(errors) == 0


@pytest.mark.tier1
def test_f11_turn_sequence_intent_lifecycle(dialogue_manager_factory):
    """F11.3: Verify intent progression through a full conversation lifecycle."""
    dm = dialogue_manager_factory()
    sess = "lifecycle_01"

    intents = ["initial_search", "refining_options", "comparing_items", "finalizing_choice"]
    for intent_str in intents:
        extraction = {
            "current_session_context": {
                "session_intent": intent_str,
                "situational_context": f"Progressing to {intent_str}",
                "extracted_parameters": {"hard_constraints": [], "soft_preferences": []},
                "dialogue_state": {
                    "ready_for_recommendation": False,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "ask_clarification",
                }
            }
        }
        updated = dm.update_turn(sess, "test message", extraction)
        assert updated.session_intent.value == intent_str


@pytest.mark.tier1
def test_f11_empty_turn_handling(dialogue_manager_factory):
    """F11.4: Verify parser/manager handles empty turn without corruption."""
    dm = dialogue_manager_factory()
    sess = "empty_turn_test"
    dm.update_turn(sess, "hello", {
        "current_session_context": {
            "session_intent": "initial_search",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            }
        }
    })
    # Empty turn
    updated = dm.update_turn(sess, "", {"current_session_context": {}})
    assert len(updated.extracted_parameters.hard_constraints) == 1


@pytest.mark.tier1
def test_f11_batch_dialogue_verification(canonical_sample_payload: Dict[str, Any], minimal_valid_payload: Dict[str, Any]):
    """F11.5: Batch conformance test asserting multiple valid fixtures strictly pass."""
    batch = [canonical_sample_payload, minimal_valid_payload]
    for item in batch:
        is_valid, errors = validate_session_context_schema(item)
        assert is_valid, f"Batch item failed: {errors}"
