"""
Tier 3: Cross-Feature Interactions E2E Tests.
Verifies pairwise and multi-feature combinations across hard constraints,
soft preferences, multi-turn state tracking, readiness transitions,
system action determination, and downstream adapter integration.
"""
from typing import Any, Dict
import pytest

from tests.e2e.schema_validator import assert_valid_session_context


@pytest.mark.tier3
def test_t3_hard_constraints_and_soft_preferences_coexistence(canonical_sample_payload: Dict[str, Any]):
    """T3.1: Hard constraints and soft preferences coexist harmoniously in context."""
    assert_valid_session_context(canonical_sample_payload)
    params = canonical_sample_payload["current_session_context"]["extracted_parameters"]
    assert len(params["hard_constraints"]) == 2
    assert len(params["soft_preferences"]) == 2

    # Check hard constraint types
    ops = {c["operator"] for c in params["hard_constraints"]}
    assert "less_than" in ops
    assert "exclude" in ops

    # Check soft preferences
    polarities = [p["polarity"] for p in params["soft_preferences"]]
    assert all(p > 0 for p in polarities)


@pytest.mark.tier3
def test_t3_constraint_accumulation_with_adapter_projection(dialogue_manager_factory, adapter_functions):
    """T3.2: Multi-turn constraint accumulation directly feeds the downstream adapter."""
    dm = dialogue_manager_factory(critical_attributes=["category"])
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    sess = "sess_accum_adapter"

    # Turn 1: category
    turn1 = {
        "current_session_context": {
            "session_intent": "initial_search",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            }
        }
    }
    dm.update_turn(sess, "Looking for a laptop", turn1)

    # Turn 2: price
    turn2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1200}],
                "soft_preferences": [],
            }
        }
    }
    dm.update_turn(sess, "Under 1200", turn2)

    # Turn 3: brand
    turn3 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Lenovo"}],
                "soft_preferences": [],
            }
        }
    }
    ctx = dm.update_turn(sess, "Must be Lenovo", turn3)

    # Run adapter on accumulated constraints
    filters = filter_adapter(ctx.extracted_parameters.hard_constraints)
    assert filters.get("category") == "laptop"
    assert filters.get("price_max") == 1200.0
    assert filters.get("brand") == "Lenovo"


@pytest.mark.tier3
def test_t3_constraint_override_reflected_in_adapter(dialogue_manager_factory, adapter_functions):
    """T3.3: Constraint override is reflected cleanly in adapter output without stale values."""
    dm = dialogue_manager_factory()
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    sess = "sess_override_adapter"

    # Turn 1: price < 1500
    dm.update_turn(sess, "Under 1500", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1500}],
                "soft_preferences": [],
            }
        }
    })

    # Turn 2: user lowers budget to 1000
    ctx = dm.update_turn(sess, "Actually make that under 1000", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1000}],
                "soft_preferences": [],
            }
        }
    })

    filters = filter_adapter(ctx.extracted_parameters.hard_constraints)
    assert filters.get("price_max") == 1000.0


@pytest.mark.tier3
def test_t3_readiness_and_system_action_transition(dialogue_manager_factory):
    """T3.4: Readiness and action transitions synchronously when missing critical attributes are fulfilled."""
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    sess = "sess_readiness_sync"

    ctx0 = dm.get_context(sess)
    assert ctx0.dialogue_state.ready_for_recommendation is False
    assert ctx0.dialogue_state.suggested_system_action.value == "ask_clarification"
    assert "category" in ctx0.dialogue_state.missing_critical_attributes
    assert "price" in ctx0.dialogue_state.missing_critical_attributes

    # Supply only category
    ctx1 = dm.update_turn(sess, "I want a laptop", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            }
        }
    })
    assert ctx1.dialogue_state.ready_for_recommendation is False
    assert ctx1.dialogue_state.suggested_system_action.value == "ask_clarification"
    assert "price" in ctx1.dialogue_state.missing_critical_attributes

    # Supply price
    ctx2 = dm.update_turn(sess, "Under 1000", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1000}],
                "soft_preferences": [],
            }
        }
    })
    assert ctx2.dialogue_state.ready_for_recommendation is True
    assert ctx2.dialogue_state.suggested_system_action.value == "present_results"
    assert len(ctx2.dialogue_state.missing_critical_attributes) == 0


@pytest.mark.tier3
def test_t3_soft_preference_polarity_update_in_dialogue_manager(dialogue_manager_factory, adapter_functions):
    """T3.5: Updating polarity flips soft preference from like to dislike in legacy projection."""
    dm = dialogue_manager_factory()
    legacy_adapter = adapter_functions["session_context_to_legacy_preferences"]
    sess = "sess_polarity_flip"

    # Turn 1: Loves Apple
    turn1 = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [],
                "soft_preferences": [
                    {"category": "brand", "value": "Apple", "polarity": 0.9, "confidence": 0.95, "evidence": "love Apple"}
                ],
            }
        }
    }
    ctx1 = dm.update_turn(sess, "I love Apple products", turn1)
    legacy1 = legacy_adapter(ctx1)
    assert "Apple" in legacy1["likes"]
    assert "Apple" not in legacy1["dislikes"]

    # Turn 2: Dislikes Apple
    turn2 = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [],
                "soft_preferences": [
                    {"category": "brand", "value": "Apple", "polarity": -0.8, "confidence": 0.9, "evidence": "actually too fragile"}
                ],
            }
        }
    }
    ctx2 = dm.update_turn(sess, "Actually Apple is too fragile for my work", turn2)
    legacy2 = legacy_adapter(ctx2)
    assert "Apple" in legacy2["dislikes"]
    assert "Apple" not in legacy2["likes"]


@pytest.mark.tier3
def test_t3_exclusion_hard_constraint_with_positive_soft_preference(dialogue_manager_factory, adapter_functions):
    """T3.6: User wants brand X generally, but excludes specific model Y."""
    dm = dialogue_manager_factory()
    legacy_adapter = adapter_functions["session_context_to_legacy_preferences"]
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    sess = "sess_brand_model_mix"

    extraction = {
        "current_session_context": {
            "session_intent": "refining_options",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "model", "operator": "exclude", "value": "MacBook Air"}
                ],
                "soft_preferences": [
                    {"category": "brand", "value": "Apple", "polarity": 0.8, "confidence": 0.9, "evidence": "prefers Apple"}
                ],
            }
        }
    }
    ctx = dm.update_turn(sess, "I want Apple but definitely not MacBook Air", extraction)
    filters = filter_adapter(ctx.extracted_parameters.hard_constraints)
    legacy = legacy_adapter(ctx)

    assert "model_exclude" in filters
    assert filters["model_exclude"] == "MacBook Air"
    assert "Apple" in legacy["likes"]


@pytest.mark.tier3
def test_t3_multiple_sessions_concurrency_and_cross_contamination(dialogue_manager_factory):
    """T3.7: Interleaved execution across 3 sessions maintains strict isolation."""
    dm = dialogue_manager_factory()

    sessions = ["user_alpha", "user_beta", "user_gamma"]
    brands = ["Dell", "HP", "Asus"]

    for sess, brand in zip(sessions, brands):
        dm.update_turn(sess, f"I want {brand}", {
            "current_session_context": {
                "extracted_parameters": {
                    "hard_constraints": [{"attribute": "brand", "operator": "include", "value": brand}],
                    "soft_preferences": [],
                }
            }
        })

    for sess, brand in zip(sessions, brands):
        ctx = dm.get_context(sess)
        assert len(ctx.extracted_parameters.hard_constraints) == 1
        assert ctx.extracted_parameters.hard_constraints[0].value == brand


@pytest.mark.tier3
def test_t3_high_vs_low_confidence_filtering(canonical_sample_payload: Dict[str, Any]):
    """T3.8: Differentiating high confidence (>0.8) vs lower confidence soft preferences."""
    prefs = canonical_sample_payload["current_session_context"]["extracted_parameters"]["soft_preferences"]
    high_conf = [p for p in prefs if p["confidence"] >= 0.8]
    low_conf = [p for p in prefs if p["confidence"] < 0.8]

    assert len(high_conf) == 1
    assert high_conf[0]["value"] == "lightweight"
    assert len(low_conf) == 1
    assert low_conf[0]["value"] == "Apple"


@pytest.mark.tier3
def test_t3_full_pipeline_roundtrip(dialogue_manager_factory, adapter_functions):
    """T3.9: Full multi-turn pipeline from raw payload to validated context and adapter filters."""
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    legacy_adapter = adapter_functions["session_context_to_legacy_preferences"]
    sess = "full_pipeline_sess"

    # Turn 1
    t1 = {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "Looking for electronics",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [
                    {"category": "brand", "value": "Dell", "polarity": 0.7, "confidence": 0.8, "evidence": "likes Dell"}
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": ["price"],
                "suggested_system_action": "ask_clarification",
            }
        }
    }
    assert_valid_session_context(t1)
    dm.update_turn(sess, "I want a Dell laptop", t1)

    # Turn 2
    t2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "Looking for Dell laptop under $1000",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1000}],
                "soft_preferences": [],
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            }
        }
    }
    assert_valid_session_context(t2)
    ctx2 = dm.update_turn(sess, "Budget is $1000", t2)

    # Validate final state
    dumped = {"current_session_context": ctx2.model_dump()}
    assert_valid_session_context(dumped)

    # Validate adapters
    filters = filter_adapter(ctx2.extracted_parameters.hard_constraints)
    assert filters.get("category") == "laptop"
    assert filters.get("price_max") == 1000.0

    legacy = legacy_adapter(ctx2)
    assert "Dell" in legacy["likes"]
    assert legacy["intent"] == "refining_options"
