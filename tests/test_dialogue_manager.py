"""
tests/test_dialogue_manager.py

Comprehensive unit and integration test suite for DialogueManager (Milestone 3).
Verifies:
- Group A: Session Lifecycle Management (create, get, update, reset, idempotency, boundary IDs)
- Group B: Multi-Turn State Accumulation (3+ turn conversations, full intent progression, situational context)
- Group C: Constraint Override Verification (E8: same-attribute/operator overrides, range coexistence, budget expansion)
- Group D: Soft Preference Polarity Updates (E10: sentiment inversion, neutralization, case-insensitive deduplication)
- Group E: Invariant Enforcement (ready_for_recommendation == True iff missing_critical_attributes == [])
- Group F: Next System Action Determination (ask_clarification, present_results, change_topic, adapter mapping)
- Group G: Concurrency & Multi-Session Isolation (thread-safety, cross-session independence, mutation protection)
"""

from __future__ import annotations

import concurrent.futures
import pytest

from src.dialog_manager.dialogue_manager import DialogueManager
from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContextWrapper,
    ExtractedParameters,
    HardConstraint,
    SessionContext,
    SessionIntent,
    SuggestedSystemAction,
)
from src.dialog_manager.session_adapter import (
    hard_constraints_to_structured_filters,
    session_context_to_dialogue_action,
    session_context_to_legacy_preferences,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def dm_default() -> DialogueManager:
    """Returns a DialogueManager with default critical attributes (['category'])."""
    return DialogueManager()


@pytest.fixture
def dm_multi_critical() -> DialogueManager:
    """Returns a DialogueManager requiring both category and price."""
    return DialogueManager(critical_attributes=["category", "price"])


@pytest.fixture
def dm_triple_critical() -> DialogueManager:
    """Returns a DialogueManager requiring category, price, and brand."""
    return DialogueManager(critical_attributes=["category", "price", "brand"])


# ==============================================================================
# Group A: Session Lifecycle Management (Create, Get, Update, Reset)
# ==============================================================================

def test_session_create_on_first_get_context(dm_default: DialogueManager):
    """A1: Calling get_context on an uninitialized session creates default SessionContext."""
    session_id = "sess_new_lifecycle_001"
    ctx = dm_default.get_context(session_id)

    assert isinstance(ctx, SessionContext)
    assert ctx.session_intent == SessionIntent.INITIAL_SEARCH
    assert ctx.situational_context == ""
    assert len(ctx.extracted_parameters.hard_constraints) == 0
    assert len(ctx.extracted_parameters.soft_preferences) == 0
    assert ctx.dialogue_state.ready_for_recommendation is False
    assert ctx.dialogue_state.missing_critical_attributes == ["category"]
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION


def test_session_get_context_idempotency(dm_default: DialogueManager):
    """A2: Sequential get_context calls return the same session state without resetting."""
    session_id = "sess_idempotent_002"
    ctx1 = dm_default.get_context(session_id)
    ctx1.situational_context = "User searching for monitors."

    ctx2 = dm_default.get_context(session_id)
    assert ctx2.situational_context == "User searching for monitors."
    assert ctx1 is ctx2 or ctx1.to_dict() == ctx2.to_dict()


def test_session_id_boundary_values(dm_default: DialogueManager):
    """A3: DialogueManager handles empty strings, UUIDs, long strings, and special characters."""
    boundaries = [
        "",
        "550e8400-e29b-41d4-a716-446655440000",
        "user@domain.com#session/special?param=1",
        "long_session_id_" + ("x" * 500),
    ]
    for sid in boundaries:
        ctx = dm_default.get_context(sid)
        assert ctx is not None
        assert isinstance(ctx, SessionContext)
        assert ctx.session_intent == SessionIntent.INITIAL_SEARCH


def test_update_context_with_session_context_instance(dm_default: DialogueManager):
    """A4: update_context accepts a SessionContext instance and recomputes dialogue state."""
    session_id = "sess_update_instance_004"
    new_ctx = SessionContext(
        session_intent=SessionIntent.REFINING_OPTIONS,
        situational_context="Direct update via instance.",
        extracted_parameters=ExtractedParameters(
            hard_constraints=[
                HardConstraint(attribute="category", operator=ConstraintOperator.INCLUDE, value="laptop"),
                HardConstraint(attribute="price", operator=ConstraintOperator.LESS_THAN, value=1200),
            ]
        ),
    )

    res = dm_default.update_context(session_id, new_ctx)
    stored = dm_default.get_context(session_id)
    assert res is stored

    assert stored.session_intent == SessionIntent.REFINING_OPTIONS
    assert stored.situational_context == "Direct update via instance."
    assert len(stored.extracted_parameters.hard_constraints) == 2
    assert stored.dialogue_state.ready_for_recommendation is True
    assert stored.dialogue_state.missing_critical_attributes == []


def test_update_context_with_wrapped_and_unwrapped_dict(dm_default: DialogueManager):
    """A5: update_context accepts both wrapped and unwrapped dictionary payloads."""
    sess_wrapped = "sess_dict_wrapped_005"
    wrapped_payload = {
        "current_session_context": {
            "session_intent": "exploring_domain",
            "situational_context": "Wrapped dict context.",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "tablets"}],
                "soft_preferences": [],
            },
        }
    }
    dm_default.update_context(sess_wrapped, wrapped_payload)
    assert dm_default.get_context(sess_wrapped).session_intent == SessionIntent.EXPLORING_DOMAIN

    sess_unwrapped = "sess_dict_unwrapped_005"
    unwrapped_payload = {
        "session_intent": "comparing_items",
        "situational_context": "Unwrapped dict context.",
        "extracted_parameters": {
            "hard_constraints": [{"attribute": "category", "operator": "include", "value": "phones"}],
            "soft_preferences": [],
        },
    }
    dm_default.update_context(sess_unwrapped, unwrapped_payload)
    assert dm_default.get_context(sess_unwrapped).session_intent == SessionIntent.COMPARING_ITEMS


def test_reset_session_restores_empty_baseline(dm_default: DialogueManager):
    """A6: reset_session wipes accumulated state and restores clean baseline."""
    session_id = "sess_reset_006"
    dm_default.update_turn(
        session_id,
        "I want a MacBook under 2000",
        {
            "current_session_context": {
                "session_intent": "refining_options",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "category", "operator": "include", "value": "laptop"},
                        {"attribute": "brand", "operator": "include", "value": "Apple"},
                    ],
                    "soft_preferences": [
                        {"category": "weight", "value": "light", "polarity": 0.8, "confidence": 0.9}
                    ],
                },
            }
        },
    )
    assert len(dm_default.get_context(session_id).extracted_parameters.hard_constraints) == 2

    # Reset
    dm_default.reset_session(session_id)
    cleared = dm_default.get_context(session_id)
    assert len(cleared.extracted_parameters.hard_constraints) == 0
    assert len(cleared.extracted_parameters.soft_preferences) == 0
    assert cleared.session_intent == SessionIntent.INITIAL_SEARCH
    assert cleared.situational_context == ""
    assert cleared.dialogue_state.ready_for_recommendation is False
    assert cleared.dialogue_state.missing_critical_attributes == ["category"]


def test_reset_session_uninitialized_and_idempotent(dm_default: DialogueManager):
    """A7: Resetting an uninitialized session or resetting twice is safe and error-free."""
    dm_default.reset_session("uninitialized_session_999")
    ctx = dm_default.get_context("uninitialized_session_999")
    assert ctx.session_intent == SessionIntent.INITIAL_SEARCH

    # Double reset
    dm_default.reset_session("uninitialized_session_999")
    assert dm_default.get_context("uninitialized_session_999").dialogue_state.ready_for_recommendation is False


def test_reset_context_alias_method(dm_default: DialogueManager):
    """A8: reset_context alias behaves identically to reset_session if implemented."""
    assert hasattr(dm_default, "reset_context")
    session_id = "sess_alias_008"
    dm_default.update_turn(
        session_id,
        "laptop",
        {
            "current_session_context": {
                "extracted_parameters": {
                    "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]
                }
            }
        },
    )
    res = dm_default.reset_context(session_id)
    assert isinstance(res, SessionContext)
    assert len(dm_default.get_context(session_id).extracted_parameters.hard_constraints) == 0


# ==============================================================================
# Group B: Multi-Turn State Accumulation (3+ Turn Conversations)
# ==============================================================================

def test_three_turn_laptop_accumulation(dm_multi_critical: DialogueManager):
    """
    B1: 3-Turn conversational accumulation:
    - Turn 1: category=laptop -> missing price -> unready
    - Turn 2: price < 1000 + soft preference lightweight -> all critical satisfied -> ready
    - Turn 3: exclude ChromeOS + brand=Apple -> 4 constraints accumulated without loss
    """
    session_id = "sess_3turn_laptop"

    # Turn 1
    t1 = {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "Student looking for a laptop for college.",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [],
            },
        }
    }
    ctx1 = dm_multi_critical.update_turn(session_id, "Looking for a college laptop", t1)
    assert ctx1.session_intent == SessionIntent.INITIAL_SEARCH
    assert ctx1.dialogue_state.ready_for_recommendation is False
    assert ctx1.dialogue_state.missing_critical_attributes == ["price"]
    assert ctx1.dialogue_state.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION

    # Turn 2
    t2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "Student needs lightweight laptop under $1000.",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1000}],
                "soft_preferences": [
                    {"category": "weight", "value": "lightweight", "polarity": 0.8, "confidence": 0.9, "evidence": "easy carry"}
                ],
            },
        }
    }
    ctx2 = dm_multi_critical.update_turn(session_id, "Under 1000 and lightweight", t2)
    assert ctx2.session_intent == SessionIntent.REFINING_OPTIONS
    assert ctx2.dialogue_state.ready_for_recommendation is True
    assert ctx2.dialogue_state.missing_critical_attributes == []
    assert ctx2.dialogue_state.suggested_system_action == SuggestedSystemAction.PRESENT_RESULTS

    # Turn 3
    t3 = {
        "current_session_context": {
            "session_intent": "comparing_items",
            "situational_context": "Excluding ChromeOS and considering Apple.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"},
                    {"attribute": "brand", "operator": "include", "value": "Apple"},
                ],
                "soft_preferences": [],
            },
        }
    }
    ctx3 = dm_multi_critical.update_turn(session_id, "No ChromeOS, prefer Apple", t3)
    assert ctx3.session_intent == SessionIntent.COMPARING_ITEMS
    assert ctx3.dialogue_state.ready_for_recommendation is True

    # Validate accumulation
    hard_map = {c.attribute: (c.operator.value, c.value) for c in ctx3.extracted_parameters.hard_constraints}
    assert len(hard_map) == 4
    assert hard_map["category"] == ("include", "laptop")
    assert hard_map["price"] == ("less_than", 1000)
    assert hard_map["operating_system"] == ("exclude", "ChromeOS")
    assert hard_map["brand"] == ("include", "Apple")

    assert len(ctx3.extracted_parameters.soft_preferences) == 1
    assert ctx3.extracted_parameters.soft_preferences[0].value == "lightweight"


def test_four_turn_full_lifecycle_journey(dm_multi_critical: DialogueManager):
    """B2: Complete 4-turn traversal across the 5 canonical session intents."""
    session_id = "sess_4turn_journey"

    # Turn 1: initial_search
    dm_multi_critical.update_turn(session_id, "Looking for headphones", {
        "current_session_context": {
            "session_intent": "initial_search",
            "extracted_parameters": {"hard_constraints": [{"attribute": "category", "operator": "include", "value": "headphones"}]}
        }
    })
    assert dm_multi_critical.get_context(session_id).session_intent == SessionIntent.INITIAL_SEARCH

    # Turn 2: exploring_domain
    dm_multi_critical.update_turn(session_id, "What features should I look for?", {
        "current_session_context": {
            "session_intent": "exploring_domain",
            "extracted_parameters": {"soft_preferences": [{"category": "anc", "value": "active noise cancellation", "polarity": 0.7, "confidence": 0.8}]}
        }
    })
    assert dm_multi_critical.get_context(session_id).session_intent == SessionIntent.EXPLORING_DOMAIN

    # Turn 3: refining_options
    dm_multi_critical.update_turn(session_id, "Budget under 300 and Sony brand", {
        "current_session_context": {
            "session_intent": "refining_options",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "price", "operator": "less_than", "value": 300},
                    {"attribute": "brand", "operator": "include", "value": "Sony"},
                ]
            }
        }
    })
    ctx3 = dm_multi_critical.get_context(session_id)
    assert ctx3.session_intent == SessionIntent.REFINING_OPTIONS
    assert ctx3.dialogue_state.ready_for_recommendation is True

    # Turn 4: finalizing_choice
    dm_multi_critical.update_turn(session_id, "I'll take the Sony WH-1000XM4", {
        "current_session_context": {
            "session_intent": "finalizing_choice",
            "situational_context": "User finalized choice on Sony WH-1000XM4.",
            "extracted_parameters": {}
        }
    })
    ctx4 = dm_multi_critical.get_context(session_id)
    assert ctx4.session_intent == SessionIntent.FINALIZING_CHOICE
    assert len(ctx4.extracted_parameters.hard_constraints) == 3


def test_situational_context_continuous_refinement(dm_default: DialogueManager):
    """B3: situational_context updates and refines monotonically across turns."""
    session_id = "sess_sit_refinement"
    dm_default.update_turn(session_id, "Need audio gear", {
        "current_session_context": {"situational_context": "User needs audio equipment."}
    })
    assert dm_default.get_context(session_id).situational_context == "User needs audio equipment."

    dm_default.update_turn(session_id, "Wireless over-ear headphones", {
        "current_session_context": {"situational_context": "User looking for wireless over-ear headphones."}
    })
    assert dm_default.get_context(session_id).situational_context == "User looking for wireless over-ear headphones."


def test_empty_extraction_turn_preserves_existing_state(dm_default: DialogueManager):
    """B4: An empty extraction payload or empty parameter dict does not wipe existing state."""
    session_id = "sess_empty_preservation"
    dm_default.update_turn(session_id, "Laptop under 1000", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "laptop"},
                    {"attribute": "price", "operator": "less_than", "value": 1000},
                ],
                "soft_preferences": [{"category": "brand", "value": "Dell", "polarity": 0.5, "confidence": 0.8}],
            }
        }
    })

    # Empty follow-up turn
    ctx_after = dm_default.update_turn(session_id, "What do you think about that?", {})
    assert len(ctx_after.extracted_parameters.hard_constraints) == 2
    assert len(ctx_after.extracted_parameters.soft_preferences) == 1


# ==============================================================================
# Group C: Constraint Override Verification (E8)
# ==============================================================================

def test_constraint_override_same_attribute_and_operator(dm_default: DialogueManager):
    """C1 (E8): Updating constraint with same attribute and operator replaces the prior value."""
    session_id = "sess_override_price"

    dm_default.update_turn(session_id, "Under 1000", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1000}]
            }
        }
    })
    dm_default.update_turn(session_id, "Actually make it under 800", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 800}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    price_constraints = [c for c in ctx.extracted_parameters.hard_constraints if c.attribute == "price"]
    assert len(price_constraints) == 1
    assert price_constraints[0].value == 800
    assert price_constraints[0].operator == ConstraintOperator.LESS_THAN


def test_constraint_override_budget_expansion(dm_default: DialogueManager):
    """C2 (E8): User raises budget after realizing initial budget was insufficient."""
    session_id = "sess_override_budget_expansion"

    dm_default.update_turn(session_id, "Gaming laptop under 700", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 700}]
            }
        }
    })
    dm_default.update_turn(session_id, "I realize dedicated GPU needs more, raise budget to 1500", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1500}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    prices = [c.value for c in ctx.extracted_parameters.hard_constraints if c.attribute == "price"]
    assert prices == [1500]


def test_constraint_range_coexistence_different_operators(dm_default: DialogueManager):
    """
    C3 (E8): Constraints on the same attribute with complementary operators (greater_than & less_than)
    must coexist to define a valid range interval.
    """
    session_id = "sess_range_coexistence"

    # Turn 1: lower bound
    dm_default.update_turn(session_id, "At least $500", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "greater_than", "value": 500}]
            }
        }
    })

    # Turn 2: upper bound
    dm_default.update_turn(session_id, "And at most $1200", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1200}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    price_constraints = [c for c in ctx.extracted_parameters.hard_constraints if c.attribute == "price"]

    # Both bounds must be retained
    ops = {c.operator for c in price_constraints}
    assert ConstraintOperator.GREATER_THAN in ops
    assert ConstraintOperator.LESS_THAN in ops

    # Downstream adapter reflects structured range filters
    filters = hard_constraints_to_structured_filters(ctx.extracted_parameters.hard_constraints)
    assert filters.get("price_min") == 500.0
    assert filters.get("price_max") == 1200.0


def test_categorical_constraint_replacement(dm_default: DialogueManager):
    """C4 (E8): Replacing an inclusion constraint for the same attribute updates cleanly."""
    session_id = "sess_categorical_override"

    dm_default.update_turn(session_id, "Looking for Dell", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Dell"}]
            }
        }
    })
    dm_default.update_turn(session_id, "Actually switch brand to Lenovo", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Lenovo"}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    brands = [c.value for c in ctx.extracted_parameters.hard_constraints if c.attribute == "brand"]
    assert brands == ["Lenovo"]


def test_rapid_attribute_overrides_stability(dm_default: DialogueManager):
    """C5 (E8): 50 sequential rapid updates on 5 distinct attributes preserve exact latest values."""
    session_id = "sess_rapid_stability"
    for i in range(50):
        attr_name = f"attr_{i % 5}"
        dm_default.update_turn(session_id, f"turn {i}", {
            "current_session_context": {
                "extracted_parameters": {
                    "hard_constraints": [{"attribute": attr_name, "operator": "equal", "value": i}]
                }
            }
        })

    ctx = dm_default.get_context(session_id)
    assert len(ctx.extracted_parameters.hard_constraints) == 5
    # The last round was i in [45, 49]
    expected_values = {f"attr_{i % 5}": i for i in range(45, 50)}
    actual_values = {c.attribute: c.value for c in ctx.extracted_parameters.hard_constraints}
    assert actual_values == expected_values


# ==============================================================================
# Group D: Soft Preference Polarity Updates (E10)
# ==============================================================================

def test_polarity_inversion_positive_to_negative(dm_default: DialogueManager):
    """
    D1 (E10): Soft preference sentiment flips from positive to negative.
    Verifies that the preference entry is updated in place and legacy dislikes reflect inversion.
    """
    session_id = "sess_inversion_pos_neg"

    # Turn 1: Likes touchscreen (+0.8)
    dm_default.update_turn(session_id, "I love touchscreen laptops", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [
                    {"category": "feature", "value": "touchscreen", "polarity": 0.8, "confidence": 0.9, "evidence": "love touchscreen"}
                ]
            }
        }
    })
    leg1 = session_context_to_legacy_preferences(dm_default.get_context(session_id))
    assert "touchscreen" in leg1["likes"]
    assert "touchscreen" not in leg1["dislikes"]

    # Turn 2: Reverses opinion (-0.7)
    dm_default.update_turn(session_id, "Actually touchscreens smudge too easily, I dislike them", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [
                    {"category": "feature", "value": "touchscreen", "polarity": -0.7, "confidence": 0.95, "evidence": "smudges too easily"}
                ]
            }
        }
    })
    ctx2 = dm_default.get_context(session_id)
    assert len(ctx2.extracted_parameters.soft_preferences) == 1
    sp = ctx2.extracted_parameters.soft_preferences[0]
    assert sp.polarity == -0.7
    assert sp.confidence == 0.95
    assert "smudges" in sp.evidence

    leg2 = session_context_to_legacy_preferences(ctx2)
    assert "touchscreen" in leg2["dislikes"]
    assert "touchscreen" not in leg2["likes"]


def test_polarity_inversion_negative_to_positive(dm_default: DialogueManager):
    """D2 (E10): Preference flips from negative to positive."""
    session_id = "sess_inversion_neg_pos"

    dm_default.update_turn(session_id, "I dislike Apple products", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "brand", "value": "Apple", "polarity": -0.85, "confidence": 0.9}]
            }
        }
    })
    leg1 = session_context_to_legacy_preferences(dm_default.get_context(session_id))
    assert "Apple" in leg1["dislikes"]

    dm_default.update_turn(session_id, "Actually Apple M3 laptops are amazing, I want one", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "brand", "value": "Apple", "polarity": 0.9, "confidence": 0.95}]
            }
        }
    })
    ctx2 = dm_default.get_context(session_id)
    assert len(ctx2.extracted_parameters.soft_preferences) == 1
    assert ctx2.extracted_parameters.soft_preferences[0].polarity == 0.9

    leg2 = session_context_to_legacy_preferences(ctx2)
    assert "Apple" in leg2["likes"]
    assert "Apple" not in leg2["dislikes"]


def test_polarity_neutralization_to_zero(dm_default: DialogueManager):
    """D3 (E10): Polarity updated to 0.0 results in removal from both likes and dislikes."""
    session_id = "sess_polarity_neutral"

    dm_default.update_turn(session_id, "I like silver color", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "color", "value": "silver", "polarity": 0.7, "confidence": 0.8}]
            }
        }
    })
    dm_default.update_turn(session_id, "I don't care about color anymore", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "color", "value": "silver", "polarity": 0.0, "confidence": 0.8}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    assert ctx.extracted_parameters.soft_preferences[0].polarity == 0.0
    leg = session_context_to_legacy_preferences(ctx)
    assert "silver" not in leg["likes"]
    assert "silver" not in leg["dislikes"]


def test_soft_preference_case_insensitive_matching(dm_default: DialogueManager):
    """D4 (E10): Soft preference deduplication is case-insensitive for category and value."""
    session_id = "sess_case_insensitive_soft"

    dm_default.update_turn(session_id, "Lightweight", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "Weight", "value": "Lightweight", "polarity": 0.6, "confidence": 0.8}]
            }
        }
    })
    dm_default.update_turn(session_id, "Very lightweight", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "weight", "value": "lightweight", "polarity": 0.95, "confidence": 0.99}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    assert len(ctx.extracted_parameters.soft_preferences) == 1
    assert ctx.extracted_parameters.soft_preferences[0].polarity == 0.95


def test_distinct_values_same_category_accumulate(dm_default: DialogueManager):
    """D5 (E10): Multiple distinct values under the same category accumulate rather than overwrite."""
    session_id = "sess_multi_value_category"

    dm_default.update_turn(session_id, "Backlit keyboard", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "feature", "value": "backlit keyboard", "polarity": 0.8, "confidence": 0.9}]
            }
        }
    })
    dm_default.update_turn(session_id, "And fingerprint reader", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [{"category": "feature", "value": "fingerprint reader", "polarity": 0.7, "confidence": 0.8}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    assert len(ctx.extracted_parameters.soft_preferences) == 2
    values = {p.value for p in ctx.extracted_parameters.soft_preferences}
    assert values == {"backlit keyboard", "fingerprint reader"}


# ==============================================================================
# Group E: Invariant Verification (ready_for_recommendation == True ⇔ missing == [])
# ==============================================================================

def test_invariant_unready_when_critical_attributes_missing(dm_multi_critical: DialogueManager):
    """E1: When any critical attribute is missing, ready_for_recommendation MUST be False."""
    session_id = "sess_inv_missing"
    # Provide only category; price remains missing
    dm_multi_critical.update_turn(session_id, "Laptops", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]
            }
        }
    })

    ctx = dm_multi_critical.get_context(session_id)
    assert ctx.dialogue_state.ready_for_recommendation is False
    assert "price" in ctx.dialogue_state.missing_critical_attributes
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION


def test_invariant_ready_when_critical_attributes_satisfied(dm_multi_critical: DialogueManager):
    """E2: When all critical attributes are provided, ready_for_recommendation transitions to True."""
    session_id = "sess_inv_satisfied"
    dm_multi_critical.update_turn(session_id, "Laptop under 1000", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "laptop"},
                    {"attribute": "price", "operator": "less_than", "value": 1000},
                ]
            }
        }
    })

    ctx = dm_multi_critical.get_context(session_id)
    assert ctx.dialogue_state.ready_for_recommendation is True
    assert ctx.dialogue_state.missing_critical_attributes == []
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.PRESENT_RESULTS


def test_invariant_progressive_clearing_across_turns(dm_triple_critical: DialogueManager):
    """E3: Missing critical attributes are cleared progressively across turns."""
    session_id = "sess_inv_progressive"

    # Turn 1: category provided
    dm_triple_critical.update_turn(session_id, "Looking for laptops", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]
            }
        }
    })
    ctx1 = dm_triple_critical.get_context(session_id)
    assert ctx1.dialogue_state.ready_for_recommendation is False
    assert set(ctx1.dialogue_state.missing_critical_attributes) == {"price", "brand"}

    # Turn 2: price provided
    dm_triple_critical.update_turn(session_id, "Under 1200", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1200}]
            }
        }
    })
    ctx2 = dm_triple_critical.get_context(session_id)
    assert ctx2.dialogue_state.ready_for_recommendation is False
    assert ctx2.dialogue_state.missing_critical_attributes == ["brand"]

    # Turn 3: brand provided
    dm_triple_critical.update_turn(session_id, "Brand Apple", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Apple"}]
            }
        }
    })
    ctx3 = dm_triple_critical.get_context(session_id)
    assert ctx3.dialogue_state.ready_for_recommendation is True
    assert ctx3.dialogue_state.missing_critical_attributes == []


def test_invariant_soft_preference_satisfies_critical_attribute(dm_default: DialogueManager):
    """E4: Soft preference matching a critical category fulfills that attribute requirement."""
    session_id = "sess_inv_soft_fulfill"
    dm_default.update_turn(session_id, "I prefer laptops", {
        "current_session_context": {
            "extracted_parameters": {
                "soft_preferences": [
                    {"category": "category", "value": "laptop", "polarity": 0.8, "confidence": 0.9}
                ]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    assert ctx.dialogue_state.missing_critical_attributes == []
    assert ctx.dialogue_state.ready_for_recommendation is True


def test_invariant_malicious_llm_ready_flag_overridden(dm_multi_critical: DialogueManager):
    """
    E5: Defensive validation: if incoming extraction payload asserts ready_for_recommendation=True
    while critical attributes are missing, DialogueManager re-evaluates and enforces False.
    """
    session_id = "sess_inv_override_bad_llm"
    bad_payload = {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "brand", "operator": "include", "value": "Dell"}]
            },
            "dialogue_state": {
                "ready_for_recommendation": True,  # Malicious / hallucinated flag
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            },
        }
    }
    ctx = dm_multi_critical.update_turn(session_id, "Dell laptop", bad_payload)
    # DialogueManager must enforce reality
    assert ctx.dialogue_state.ready_for_recommendation is False
    assert "category" in ctx.dialogue_state.missing_critical_attributes
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION


# ==============================================================================
# Group F: Next System Action Determination
# ==============================================================================

def test_action_ask_clarification_when_unready(dm_default: DialogueManager):
    """F1: When not ready for recommendation, action is ask_clarification."""
    ctx = dm_default.get_context("sess_action_clarify")
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.ASK_CLARIFICATION


def test_action_present_results_when_ready(dm_default: DialogueManager):
    """F2: When ready for recommendation, action is present_results."""
    session_id = "sess_action_present"
    dm_default.update_turn(session_id, "Laptop", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]
            }
        }
    })
    ctx = dm_default.get_context(session_id)
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.PRESENT_RESULTS


def test_action_change_topic_signal_preserved(dm_default: DialogueManager):
    """F3: When extraction flags change_topic, DialogueManager honors the topic shift."""
    session_id = "sess_action_topic_shift"
    # Seed state
    dm_default.update_turn(session_id, "Laptops", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]
            }
        }
    })
    # Topic change
    dm_default.update_turn(session_id, "Do you have warranty info?", {
        "current_session_context": {
            "dialogue_state": {
                "suggested_system_action": "change_topic"
            }
        }
    })
    ctx = dm_default.get_context(session_id)
    assert ctx.dialogue_state.suggested_system_action == SuggestedSystemAction.CHANGE_TOPIC


def test_action_downstream_adapter_mapping(dm_default: DialogueManager):
    """F4: DialogueManager state maps cleanly to downstream DialogueAction enums."""
    # 1. ask_clarification -> CLARIFY
    ctx_clarify = dm_default.get_context("sess_downstream_clarify")
    action1 = session_context_to_dialogue_action(ctx_clarify)
    action1_val = action1.value if hasattr(action1, "value") else str(action1)
    assert action1_val == "CLARIFY"

    # 2. present_results -> SEARCH
    dm_default.update_turn("sess_downstream_search", "Laptops", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]
            }
        }
    })
    ctx_search = dm_default.get_context("sess_downstream_search")
    action2 = session_context_to_dialogue_action(ctx_search)
    action2_val = action2.value if hasattr(action2, "value") else str(action2)
    assert action2_val == "SEARCH"


# ==============================================================================
# Group G: Concurrency & Multi-Session Isolation
# ==============================================================================

def test_multi_session_isolation_independent_states(dm_default: DialogueManager):
    """G1: Multiple sessions operating concurrently do not cross-contaminate state."""
    sess_a = "user_alpha_laptop"
    sess_b = "user_beta_earbuds"
    sess_c = "user_gamma_keyboard"

    # Interleaved turn updates
    dm_default.update_turn(sess_a, "Need laptop", {
        "current_session_context": {
            "extracted_parameters": {"hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}]}
        }
    })
    dm_default.update_turn(sess_b, "Need earbuds", {
        "current_session_context": {
            "extracted_parameters": {"hard_constraints": [{"attribute": "category", "operator": "include", "value": "earbuds"}]}
        }
    })
    dm_default.update_turn(sess_c, "Need keyboard", {
        "current_session_context": {
            "extracted_parameters": {"hard_constraints": [{"attribute": "category", "operator": "include", "value": "keyboard"}]}
        }
    })

    # Update Turn 2 on sess_a
    dm_default.update_turn(sess_a, "Budget 1200", {
        "current_session_context": {
            "extracted_parameters": {"hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 1200}]}
        }
    })

    # Verify isolation
    ctx_a = dm_default.get_context(sess_a)
    ctx_b = dm_default.get_context(sess_b)
    ctx_c = dm_default.get_context(sess_c)

    assert len(ctx_a.extracted_parameters.hard_constraints) == 2
    assert len(ctx_b.extracted_parameters.hard_constraints) == 1
    assert len(ctx_c.extracted_parameters.hard_constraints) == 1

    assert ctx_a.extracted_parameters.hard_constraints[0].value == "laptop"
    assert ctx_b.extracted_parameters.hard_constraints[0].value == "earbuds"
    assert ctx_c.extracted_parameters.hard_constraints[0].value == "keyboard"


def test_session_reset_isolation_others_untouched(dm_default: DialogueManager):
    """G2: Resetting one session leaves all other active sessions completely intact."""
    sess_keep = "sess_active_preserved"
    sess_kill = "sess_to_be_reset"

    dm_default.update_turn(sess_keep, "Keep this", {
        "current_session_context": {
            "extracted_parameters": {"hard_constraints": [{"attribute": "category", "operator": "include", "value": "monitors"}]}
        }
    })
    dm_default.update_turn(sess_kill, "Reset this", {
        "current_session_context": {
            "extracted_parameters": {"hard_constraints": [{"attribute": "category", "operator": "include", "value": "mice"}]}
        }
    })

    dm_default.reset_session(sess_kill)

    assert len(dm_default.get_context(sess_keep).extracted_parameters.hard_constraints) == 1
    assert dm_default.get_context(sess_keep).extracted_parameters.hard_constraints[0].value == "monitors"
    assert len(dm_default.get_context(sess_kill).extracted_parameters.hard_constraints) == 0


def test_no_shared_mutable_defaults_across_sessions(dm_default: DialogueManager):
    """G3: Appending to constraints list of one session context does not mutate another."""
    ctx1 = dm_default.get_context("sess_mut_1")
    ctx2 = dm_default.get_context("sess_mut_2")

    ctx1.extracted_parameters.hard_constraints.append(
        HardConstraint(attribute="test", operator=ConstraintOperator.EQUAL, value=123)
    )

    assert len(ctx1.extracted_parameters.hard_constraints) == 1
    assert len(ctx2.extracted_parameters.hard_constraints) == 0


def test_concurrent_multi_threaded_updates(dm_default: DialogueManager):
    """G4: High-concurrency stress test with 20 concurrent threads across 20 distinct sessions."""
    num_sessions = 20
    turns_per_session = 15

    def worker_task(session_idx: int) -> bool:
        session_id = f"concurrent_worker_sess_{session_idx}"
        for turn_idx in range(turns_per_session):
            dm_default.update_turn(session_id, f"turn {turn_idx}", {
                "current_session_context": {
                    "extracted_parameters": {
                        "hard_constraints": [
                            {"attribute": f"attr_{turn_idx}", "operator": "equal", "value": turn_idx}
                        ]
                    }
                }
            })
        ctx = dm_default.get_context(session_id)
        return len(ctx.extracted_parameters.hard_constraints) == turns_per_session

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker_task, i) for i in range(num_sessions)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(results)
    assert len(results) == num_sessions


# ==============================================================================
# Group H: Extended Methods & Specific Edge Cases
# ==============================================================================

def test_get_context_as_wrapper_and_get_wrapper(dm_default: DialogueManager):
    """H1: get_context(as_wrapper=True) and get_wrapper return CurrentSessionContextWrapper."""
    session_id = "sess_wrapper_test"
    ctx = dm_default.get_context(session_id)
    assert isinstance(ctx, SessionContext)

    wrapper1 = dm_default.get_context(session_id, as_wrapper=True)
    assert isinstance(wrapper1, CurrentSessionContextWrapper)
    assert wrapper1.current_session_context is ctx

    wrapper2 = dm_default.get_wrapper(session_id)
    assert isinstance(wrapper2, CurrentSessionContextWrapper)
    assert wrapper2.current_session_context is ctx


def test_session_exists_list_and_delete(dm_default: DialogueManager):
    """H2: Verify session_exists, list_sessions, and delete_session behavior."""
    session_id = "sess_crud_test"
    assert not dm_default.session_exists(session_id)

    dm_default.get_context(session_id)
    assert dm_default.session_exists(session_id)
    assert session_id in dm_default.list_sessions()

    deleted = dm_default.delete_session(session_id)
    assert deleted is True
    assert not dm_default.session_exists(session_id)
    assert session_id not in dm_default.list_sessions()

    # Deleting already deleted session returns False
    assert dm_default.delete_session(session_id) is False


def test_get_history_summary(dm_default: DialogueManager):
    """H3: get_history_summary returns structured dictionary summary."""
    session_id = "sess_summary_test"
    dm_default.update_turn(session_id, "Looking for a laptop under 1000", {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "User needs laptop under $1000.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "laptop"},
                    {"attribute": "price", "operator": "less_than", "value": 1000},
                ],
                "soft_preferences": [
                    {"category": "brand", "value": "Dell", "polarity": 0.8, "confidence": 0.9}
                ],
            }
        }
    })

    summary = dm_default.get_history_summary(session_id)
    assert summary["session_id"] == session_id
    assert summary["session_intent"] == "refining_options"
    assert summary["ready_for_recommendation"] is True
    assert summary["missing_critical_attributes"] == []
    assert summary["suggested_system_action"] == "present_results"
    assert summary["hard_constraints_count"] == 2
    assert summary["soft_preferences_count"] == 1
    assert summary["situational_context"] == "User needs laptop under $1000."


def test_inclusion_vs_exclusion_contradiction_cancellation(dm_default: DialogueManager):
    """H4: Incoming operator cancels opposite operator on same attribute/value."""
    session_id = "sess_contradiction_test"

    # Turn 1: Exclude ChromeOS
    dm_default.update_turn(session_id, "No ChromeOS", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}]
            }
        }
    })
    ctx1 = dm_default.get_context(session_id)
    assert len(ctx1.extracted_parameters.hard_constraints) == 1
    assert ctx1.extracted_parameters.hard_constraints[0].operator == ConstraintOperator.EXCLUDE

    # Turn 2: Include ChromeOS -> cancels prior exclude
    dm_default.update_turn(session_id, "Actually ChromeOS is fine, include it", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "operating_system", "operator": "include", "value": "ChromeOS"}]
            }
        }
    })
    ctx2 = dm_default.get_context(session_id)
    assert len(ctx2.extracted_parameters.hard_constraints) == 1
    assert ctx2.extracted_parameters.hard_constraints[0].operator == ConstraintOperator.INCLUDE
    assert ctx2.extracted_parameters.hard_constraints[0].value == "ChromeOS"

    # Turn 3: Exclude ChromeOS -> cancels prior include
    dm_default.update_turn(session_id, "Nevermind, definitely exclude ChromeOS", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}]
            }
        }
    })
    ctx3 = dm_default.get_context(session_id)
    assert len(ctx3.extracted_parameters.hard_constraints) == 1
    assert ctx3.extracted_parameters.hard_constraints[0].operator == ConstraintOperator.EXCLUDE


def test_range_bound_contradiction_override(dm_default: DialogueManager):
    """H5: Contradictory range bound (new min > old max) replaces contradictory bound."""
    session_id = "sess_bound_contradiction"

    # Turn 1: Upper bound under 400
    dm_default.update_turn(session_id, "Under 400", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "less_than", "value": 400}]
            }
        }
    })

    # Turn 2: Lower bound at least 1000 (impossible range [1000, 400], contradicts prior max 400)
    dm_default.update_turn(session_id, "Actually I want a flagship, at least 1000", {
        "current_session_context": {
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "price", "operator": "greater_than", "value": 1000}]
            }
        }
    })

    ctx = dm_default.get_context(session_id)
    price_constraints = [c for c in ctx.extracted_parameters.hard_constraints if c.attribute == "price"]
    assert len(price_constraints) == 1
    assert price_constraints[0].operator == ConstraintOperator.GREATER_THAN
    assert price_constraints[0].value == 1000

