"""
Tier 4: Real-World Application Scenarios E2E Tests.
Tests realistic multi-turn conversational sequences covering laptops,
electronics, and item comparison scenarios against schema and dialogue state.
"""
from typing import Any, Dict
import pytest

from tests.e2e.schema_validator import assert_valid_session_context


@pytest.mark.tier4
def test_t4_scenario_1_college_student_laptop_search(dialogue_manager_factory, adapter_functions):
    """
    Scenario 1: College Student Budget Laptop Search
    - Turn 1: Initial broad search for lightweight college laptop.
    - Turn 2: Hard budget and OS exclusion refinement.
    - Turn 3: Brand preference exploration.
    - Turn 4: Finalizing choice.
    """
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    sess_id = "scenario_1_college_student"

    # Turn 1
    t1_payload = {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "Starting college computer science; needs lightweight laptop with all-day battery.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "laptop"}
                ],
                "soft_preferences": [
                    {"category": "weight", "value": "lightweight", "polarity": 0.85, "confidence": 0.9, "evidence": "easy to carry on campus"},
                    {"category": "battery", "value": "long battery life", "polarity": 0.9, "confidence": 0.9, "evidence": "last all day in lectures"},
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": ["price"],
                "suggested_system_action": "ask_clarification",
            }
        }
    }
    assert_valid_session_context(t1_payload)
    ctx1 = dm.update_turn(sess_id, "Hi, I'm starting college next month and need a lightweight laptop.", t1_payload)
    assert ctx1.session_intent.value == "initial_search"
    assert ctx1.dialogue_state.ready_for_recommendation is False
    assert "price" in ctx1.dialogue_state.missing_critical_attributes

    # Turn 2
    t2_payload = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "Student setting hard $1000 budget and excluding ChromeOS.",
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
    assert_valid_session_context(t2_payload)
    ctx2 = dm.update_turn(sess_id, "My budget is under $1000, and I definitely don't want ChromeOS.", t2_payload)
    assert ctx2.session_intent.value == "refining_options"
    assert ctx2.dialogue_state.ready_for_recommendation is True
    assert len(ctx2.dialogue_state.missing_critical_attributes) == 0

    # Turn 3
    t3_payload = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "Student inquiring about Apple MacBooks in price range.",
            "extracted_parameters": {
                "hard_constraints": [],
                "soft_preferences": [
                    {"category": "brand", "value": "Apple", "polarity": 0.6, "confidence": 0.7, "evidence": "asking if MacBooks go on sale"}
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            }
        }
    }
    assert_valid_session_context(t3_payload)
    ctx3 = dm.update_turn(sess_id, "Are there any Apple MacBooks in this price range?", t3_payload)
    assert ctx3.session_intent.value == "refining_options"

    # Turn 4: Finalizing
    t4_payload = {
        "current_session_context": {
            "session_intent": "finalizing_choice",
            "situational_context": "Student deciding on MacBook Air M1 under $900.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "model", "operator": "include", "value": "MacBook Air M1"},
                    {"attribute": "price", "operator": "less_than", "value": 900},
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
    assert_valid_session_context(t4_payload)
    ctx4 = dm.update_turn(sess_id, "I'll go with the M1 MacBook Air if it's under $900.", t4_payload)
    assert ctx4.session_intent.value == "finalizing_choice"

    # Check adapter filters
    filters = filter_adapter(ctx4.extracted_parameters.hard_constraints)
    assert filters.get("category") == "laptop"
    assert filters.get("price_max") == 900.0


@pytest.mark.tier4
def test_t4_scenario_2_high_performance_gaming_rig(dialogue_manager_factory, adapter_functions):
    """
    Scenario 2: High-Performance Gaming Rig / Electronics Search
    - Turn 1: Exploring domain for 4K ray tracing PC.
    - Turn 2: Setting hard limits ($2500, RTX 4080, exclude refurbished).
    - Turn 3: Comparing specific builds.
    """
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    sess_id = "scenario_2_gaming_rig"

    # Turn 1
    t1 = {
        "current_session_context": {
            "session_intent": "exploring_domain",
            "situational_context": "Gamer looking for serious desktop PC capable of 4K ray tracing and 3D rendering.",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "desktop PC"}],
                "soft_preferences": [
                    {"category": "feature", "value": "ray tracing", "polarity": 0.95, "confidence": 0.9, "evidence": "run Cyberpunk at 4K ray tracing"},
                    {"category": "use_case", "value": "Blender 3D", "polarity": 0.9, "confidence": 0.85, "evidence": "Blender rendering"},
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
    dm.update_turn(sess_id, "I need a high-end PC for 4K ray tracing.", t1)

    # Turn 2
    t2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "User sets budget $2500, RTX 4080, and excludes refurbished.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "price", "operator": "less_than", "value": 2500},
                    {"attribute": "gpu", "operator": "include", "value": "RTX 4080"},
                    {"attribute": "condition", "operator": "exclude", "value": "refurbished"},
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
    assert_valid_session_context(t2)
    ctx2 = dm.update_turn(sess_id, "Budget $2500 max, RTX 4080, no refurbished.", t2)
    assert ctx2.dialogue_state.ready_for_recommendation is True

    # Turn 3: Comparing
    t3 = {
        "current_session_context": {
            "session_intent": "comparing_items",
            "situational_context": "Comparing Corsair Vengeance i7500 vs Alienware Aurora R16.",
            "extracted_parameters": {
                "hard_constraints": [],
                "soft_preferences": [
                    {"category": "brand", "value": "Corsair", "polarity": 0.7, "confidence": 0.8, "evidence": "prefers Corsair cooling"}
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            }
        }
    }
    assert_valid_session_context(t3)
    ctx3 = dm.update_turn(sess_id, "Can you compare Corsair vs Alienware?", t3)
    assert ctx3.session_intent.value == "comparing_items"


@pytest.mark.tier4
def test_t4_scenario_3_head_to_head_item_comparison(dialogue_manager_factory, adapter_functions):
    """
    Scenario 3: Head-to-Head Laptop Item Comparison
    - Turn 1: Comparing ThinkPad X1 Carbon vs Dell XPS 13 Plus.
    - Turn 2: Key deciding criteria (keyboard, Linux compatibility).
    - Turn 3: Finalizing on ThinkPad with 1TB SSD.
    """
    dm = dialogue_manager_factory(critical_attributes=["category"])
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    sess_id = "scenario_3_comparison"

    # Turn 1
    t1 = {
        "current_session_context": {
            "session_intent": "comparing_items",
            "situational_context": "Comparing ThinkPad X1 Carbon Gen 11 vs Dell XPS 13 Plus for executive business travel.",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "laptop"}],
                "soft_preferences": [
                    {"category": "portability", "value": "lightweight", "polarity": 0.9, "confidence": 0.95, "evidence": "frequent flyer"},
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            }
        }
    }
    assert_valid_session_context(t1)
    dm.update_turn(sess_id, "Comparing ThinkPad X1 Carbon vs Dell XPS 13.", t1)

    # Turn 2
    t2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "User prioritizing Linux support and keyboard quality.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "operating_system", "operator": "include", "value": "Linux"}
                ],
                "soft_preferences": [
                    {"category": "keyboard", "value": "deep travel", "polarity": 1.0, "confidence": 1.0, "evidence": "keyboard is absolute top priority"},
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            }
        }
    }
    assert_valid_session_context(t2)
    dm.update_turn(sess_id, "Linux compatibility and keyboard feel are top priority.", t2)

    # Turn 3
    t3 = {
        "current_session_context": {
            "session_intent": "finalizing_choice",
            "situational_context": "User chooses ThinkPad X1 with 1TB SSD.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "brand", "operator": "equal", "value": "Lenovo"},
                    {"attribute": "storage", "operator": "greater_than", "value": 1000},
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
    assert_valid_session_context(t3)
    ctx3 = dm.update_turn(sess_id, "Let's go with the Lenovo ThinkPad with 1TB storage.", t3)
    assert ctx3.session_intent.value == "finalizing_choice"
    filters = filter_adapter(ctx3.extracted_parameters.hard_constraints)
    assert filters.get("brand") == "Lenovo"


@pytest.mark.tier4
def test_t4_scenario_4_audio_electronics_with_topic_shift(dialogue_manager_factory):
    """
    Scenario 4: Audio Electronics with sudden topic shift from speakers to headphones.
    """
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    sess_id = "scenario_4_audio_shift"

    # Turn 1: Speakers
    t1 = {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "Setting up multi-room wireless speakers in apartment.",
            "extracted_parameters": {
                "hard_constraints": [{"attribute": "category", "operator": "include", "value": "speakers"}],
                "soft_preferences": [],
            },
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": ["price"],
                "suggested_system_action": "ask_clarification",
            }
        }
    }
    assert_valid_session_context(t1)
    dm.update_turn(sess_id, "Looking for wireless multi-room speakers.", t1)

    # Turn 2: Topic Shift to ANC headphones
    t2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "Roommate bought speakers; user shifts focus to noise-canceling headphones for home office.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "headphones"},
                    {"attribute": "price", "operator": "less_than", "value": 400},
                ],
                "soft_preferences": [
                    {"category": "feature", "value": "active noise cancellation", "polarity": 0.95, "confidence": 1.0, "evidence": "need ANC for studying"},
                    {"category": "brand", "value": "Sony", "polarity": 0.8, "confidence": 0.85, "evidence": "likes Sony WH-1000XM5"},
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            }
        }
    }
    assert_valid_session_context(t2)
    ctx2 = dm.update_turn(sess_id, "Forget speakers, need ANC headphones under $400, Sony preferred.", t2)
    assert ctx2.dialogue_state.ready_for_recommendation is True
    assert "headphones" in [c.value for c in ctx2.extracted_parameters.hard_constraints if c.attribute == "category"]


@pytest.mark.tier4
def test_t4_scenario_5_contradictory_constraints_and_negotiation(dialogue_manager_factory, adapter_functions):
    """
    Scenario 5: Contradictory Constraints & Mid-Course Negotiation
    - Turn 1: Impossible budget ($400 RTX 4090).
    - Turn 2: Realization and correction to $1800 budget with RTX 4060/4070.
    """
    dm = dialogue_manager_factory(critical_attributes=["category", "price"])
    filter_adapter = adapter_functions["hard_constraints_to_structured_filters"]
    sess_id = "scenario_5_negotiation"

    # Turn 1: Impossible budget
    t1 = {
        "current_session_context": {
            "session_intent": "initial_search",
            "situational_context": "Looking for ultra-high-end specs on impossible budget.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "category", "operator": "include", "value": "laptop"},
                    {"attribute": "price", "operator": "less_than", "value": 400},
                    {"attribute": "gpu", "operator": "include", "value": "RTX 4090"},
                ],
                "soft_preferences": [],
            },
            "dialogue_state": {
                "ready_for_recommendation": False,
                "missing_critical_attributes": [],
                "suggested_system_action": "ask_clarification",
            }
        }
    }
    assert_valid_session_context(t1)
    dm.update_turn(sess_id, "I want an RTX 4090 laptop for $400.", t1)

    # Turn 2: Correction
    t2 = {
        "current_session_context": {
            "session_intent": "refining_options",
            "situational_context": "User adjusted expectations: realistic $1800 budget for RTX 4060/4070 gaming laptop.",
            "extracted_parameters": {
                "hard_constraints": [
                    {"attribute": "price", "operator": "less_than", "value": 1800},
                    {"attribute": "gpu", "operator": "include", "value": "RTX 4070"},
                ],
                "soft_preferences": [
                    {"category": "brand", "value": "Lenovo", "polarity": 0.8, "confidence": 0.9, "evidence": "prefers Lenovo Legion"}
                ],
            },
            "dialogue_state": {
                "ready_for_recommendation": True,
                "missing_critical_attributes": [],
                "suggested_system_action": "present_results",
            }
        }
    }
    assert_valid_session_context(t2)
    ctx2 = dm.update_turn(sess_id, "My mistake, let's raise budget to $1800 and target RTX 4070 Lenovo.", t2)
    assert ctx2.dialogue_state.ready_for_recommendation is True
    filters = filter_adapter(ctx2.extracted_parameters.hard_constraints)
    assert filters.get("price_max") == 1800.0
