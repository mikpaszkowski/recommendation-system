"""
tests/test_profile_tool.py

Comprehensive test suite for ProfileTool and InMemoryUserProfileManager integration
with SessionContext, CurrentSessionContextWrapper, enrichment, and safe synchronization (Milestone 4).

Verifies:
1. Basic Profile Operations: get_profile, save_item_interaction, clean dictionary unwrapping.
2. High-Confidence Synchronization (confidence >= 0.8 persisted, confidence < 0.8 omitted).
3. Ephemeral Constraint Exclusion (price, budget, price_max never synced to long-term profile).
4. Session Context Enrichment (seeding enduring brand/OS priors without overwriting session-explicit filters).
5. Canonical Schema Conformance (assert_valid_session_context validation).
6. Backward Compatibility for legacy callers (update_preferences_from_conversation returning dict with current_session_context).
"""

from __future__ import annotations

import pytest
from typing import Any, Dict

from src.tools.profile_tool import ProfileTool, EPHEMERAL_ATTRIBUTES
from src.user.profile_manager import InMemoryUserProfileManager
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
from tests.e2e.schema_validator import assert_valid_session_context


class MockPreferenceParser:
    """Mock preference parser returning canned extractions."""

    def __init__(self, extraction: Optional[Dict[str, Any]] = None):
        self.extraction = extraction or {
            "current_session_context": {
                "session_intent": "initial_search",
                "situational_context": "Looking for Apple laptop",
                "extracted_parameters": {
                    "hard_constraints": [
                        {"attribute": "brand", "operator": "include", "value": "Apple"},
                        {"attribute": "price", "operator": "less_than", "value": 1200}
                    ],
                    "soft_preferences": [
                        {"category": "brand", "value": "Apple", "polarity": 0.8, "confidence": 0.9, "evidence": "I love Apple"},
                        {"category": "weight", "value": "lightweight", "polarity": 0.5, "confidence": 0.5, "evidence": "Maybe light"}
                    ]
                },
                "dialogue_state": {
                    "ready_for_recommendation": True,
                    "missing_critical_attributes": [],
                    "suggested_system_action": "present_results"
                }
            }
        }

    def extract_preferences(self, conversation_text: str) -> Dict[str, Any]:
        return self.extraction

    def format_for_recommender(self, extracted: Any) -> Dict[str, Any]:
        return {"brand": "Apple", "price_max": 1200.0}


# ==============================================================================
# Group A: Basic Profile Operations & Nested Structure Unwrapping
# ==============================================================================

class TestProfileToolBasics:
    """Tests basic operations and unwrapping."""

    def test_in_memory_profile_manager_unwraps_nested_preferences(self):
        """
        Verify that InMemoryUserProfileManager.update_profile unwraps
        {'preferences': {'brand': 'Apple'}} so profile['preferences'] has {'brand': 'Apple'}
        rather than {'preferences': {'preferences': ...}}.
        """
        pm = InMemoryUserProfileManager()
        user_id = "user_unwrap_test"

        # Update with single-key nested dictionary
        pm.update_profile(user_id, {"preferences": {"brand": "Apple", "likes": ["Apple"]}})
        profile = pm.get_profile(user_id)

        assert "preferences" in profile
        assert profile["preferences"].get("brand") == "Apple"
        assert "preferences" not in profile["preferences"]

    def test_save_item_interaction(self):
        """Verify save_item_interaction prepends to profile history."""
        tool = ProfileTool()
        user_id = "user_hist_test"
        item = {"asin": "B123", "title": "MacBook Air"}

        tool.save_item_interaction(user_id, item)
        profile = tool.get_profile(user_id)
        assert len(profile["history"]) == 1
        assert profile["history"][0]["asin"] == "B123"


# ==============================================================================
# Group B & C: Safe High-Confidence Synchronization & Ephemeral Filtering
# ==============================================================================

class TestSafeProfileSynchronization:
    """Tests sync_session_preferences_to_profile filters confidence and ephemeral attributes."""

    def test_high_confidence_filtering(self):
        """
        Verify that soft preferences with confidence >= 0.8 are synchronized,
        while preferences with confidence < 0.8 are omitted.
        """
        tool = ProfileTool()
        user_id = "user_conf_test"

        ctx = SessionContext(
            session_intent=SessionIntent.INITIAL_SEARCH,
            situational_context="Test query",
            extracted_parameters=ExtractedParameters(
                hard_constraints=[],
                soft_preferences=[
                    SoftPreference(category="brand", value="Apple", polarity=0.9, confidence=0.95, evidence="Verified Apple lover"),
                    SoftPreference(category="display", value="OLED", polarity=0.6, confidence=0.6, evidence="Guessed preference")
                ]
            ),
            dialogue_state=DialogueState(ready_for_recommendation=True, missing_critical_attributes=[], suggested_system_action=SuggestedSystemAction.PRESENT_RESULTS)
        )

        tool.sync_session_preferences_to_profile(user_id, ctx, min_confidence=0.8)
        profile = tool.get_profile(user_id)
        prefs = profile.get("preferences", {})

        # High confidence (Apple, 0.95) should be saved
        assert "Apple" in prefs.get("likes", [])
        long_term_soft = prefs.get("long_term_soft_preferences", [])
        assert any(p["value"] == "Apple" for p in long_term_soft)

        # Low confidence (OLED, 0.6) should NOT be saved
        assert "OLED" not in prefs.get("likes", [])
        assert not any(p["value"] == "OLED" for p in long_term_soft)

    def test_ephemeral_attributes_rejection(self):
        """
        Verify that ephemeral attributes (price, budget, cost, shipping)
        are NEVER synchronized to the persistent user profile.
        """
        tool = ProfileTool()
        user_id = "user_ephemeral_test"

        ctx = SessionContext(
            session_intent=SessionIntent.INITIAL_SEARCH,
            situational_context="Need laptop for trip",
            extracted_parameters=ExtractedParameters(
                hard_constraints=[
                    HardConstraint(attribute="price", operator=ConstraintOperator.LESS_THAN, value=1000),
                    HardConstraint(attribute="budget", operator=ConstraintOperator.LESS_THAN, value=800),
                    HardConstraint(attribute="operating_system", operator=ConstraintOperator.EXCLUDE, value="ChromeOS"),
                ],
                soft_preferences=[
                    SoftPreference(category="price", value="cheap", polarity=0.8, confidence=0.9),
                    SoftPreference(category="brand", value="Dell", polarity=0.8, confidence=0.9),
                ]
            ),
            dialogue_state=DialogueState(ready_for_recommendation=True, missing_critical_attributes=[], suggested_system_action=SuggestedSystemAction.PRESENT_RESULTS)
        )

        tool.sync_session_preferences_to_profile(user_id, ctx, min_confidence=0.8)
        profile = tool.get_profile(user_id)
        prefs = profile.get("preferences", {})

        # Enduring OS exclusion and brand should be saved
        assert prefs.get("exclude_operating_system") == "ChromeOS"
        assert "Dell" in prefs.get("likes", [])

        # Ephemeral price/budget MUST NOT be saved
        assert "price" not in prefs
        assert "budget" not in prefs
        assert "price_max" not in prefs
        long_term_hard = prefs.get("long_term_hard_constraints", [])
        assert not any(h["attribute"] in ("price", "budget") for h in long_term_hard)
        long_term_soft = prefs.get("long_term_soft_preferences", [])
        assert not any(s["category"] == "price" for s in long_term_soft)


# ==============================================================================
# Group D: Session Context Enrichment
# ==============================================================================

class TestSessionContextEnrichment:
    """Tests enrich_session_context seeds priors without overwriting session constraints."""

    def test_enrich_session_context_seeds_priors(self):
        """
        Verify that persistent brand preferences from profile seed a fresh session context.
        """
        tool = ProfileTool()
        user_id = "user_enrich_seed"

        # Populate persistent profile
        tool.profile_manager.update_profile(user_id, {
            "preferences": {
                "long_term_soft_preferences": [
                    {"category": "brand", "value": "Apple", "polarity": 0.9, "confidence": 0.85, "evidence": "Long term profile"}
                ],
                "long_term_hard_constraints": [
                    {"attribute": "operating_system", "operator": "exclude", "value": "ChromeOS"}
                ]
            }
        })

        # Fresh empty session context
        fresh_ctx = SessionContext(
            session_intent=SessionIntent.INITIAL_SEARCH,
            situational_context="New search",
            extracted_parameters=ExtractedParameters(hard_constraints=[], soft_preferences=[]),
            dialogue_state=DialogueState(ready_for_recommendation=False, missing_critical_attributes=["category"], suggested_system_action=SuggestedSystemAction.ASK_CLARIFICATION)
        )

        enriched = tool.enrich_session_context(user_id, fresh_ctx)
        assert isinstance(enriched, CurrentSessionContextWrapper)
        assert_valid_session_context(enriched.to_dict())

        ctx = enriched.current_session_context
        # Brand should be seeded into soft_preferences
        brands = [sp.value for sp in ctx.extracted_parameters.soft_preferences if sp.category == "brand"]
        assert "Apple" in brands

        # Hard exclusion should be seeded
        os_excl = [hc for hc in ctx.extracted_parameters.hard_constraints if hc.attribute == "operating_system"]
        assert len(os_excl) == 1
        assert os_excl[0].value == "ChromeOS"
        assert os_excl[0].operator == ConstraintOperator.EXCLUDE

    def test_session_explicit_constraints_override_seeded_priors(self):
        """
        Verify that if session context already explicitly specifies brand="Dell",
        enrich_session_context does NOT inject brand="Apple" prior.
        """
        tool = ProfileTool()
        user_id = "user_override_test"

        tool.profile_manager.update_profile(user_id, {
            "preferences": {
                "long_term_soft_preferences": [
                    {"category": "brand", "value": "Apple", "polarity": 0.9, "confidence": 0.85}
                ]
            }
        })

        # Active session explicitly requested Dell
        session_ctx = SessionContext(
            session_intent=SessionIntent.INITIAL_SEARCH,
            situational_context="Looking for Dell",
            extracted_parameters=ExtractedParameters(
                hard_constraints=[HardConstraint(attribute="brand", operator=ConstraintOperator.INCLUDE, value="Dell")],
                soft_preferences=[SoftPreference(category="brand", value="Dell", polarity=0.9, confidence=0.95)]
            ),
            dialogue_state=DialogueState(ready_for_recommendation=True, missing_critical_attributes=[], suggested_system_action=SuggestedSystemAction.PRESENT_RESULTS)
        )

        enriched = tool.enrich_session_context(user_id, session_ctx)
        ctx = enriched.current_session_context

        # Dell remains, Apple was suppressed
        brands = [sp.value for sp in ctx.extracted_parameters.soft_preferences if sp.category == "brand"]
        assert "Dell" in brands
        assert "Apple" not in brands


# ==============================================================================
# Group E: Schema Conformance & Backward Compatibility
# ==============================================================================

class TestSchemaConformanceAndCompatibility:
    """Tests schema validation and legacy caller compatibility."""

    def test_get_session_context_schema_conformance(self):
        """Verify get_session_context(as_wrapper=True) produces schema-valid payload."""
        tool = ProfileTool()
        user_id = "user_schema_test"
        tool.profile_manager.update_profile(user_id, {
            "preferences": {
                "likes": ["Apple", "Sony"],
                "dislikes": ["Acer"]
            }
        })

        wrapper = tool.get_session_context(user_id, as_wrapper=True)
        assert isinstance(wrapper, CurrentSessionContextWrapper)
        assert_valid_session_context(wrapper.to_dict())

    def test_update_preferences_from_conversation_legacy_and_wrapper(self):
        """
        Verify update_preferences_from_conversation returns legacy dict with
        current_session_context by default, and wrapper when requested.
        """
        mock_parser = MockPreferenceParser()
        tool = ProfileTool(parser=mock_parser)
        user_id = "user_conv_test"

        # Default: legacy dict with current_session_context
        legacy_res = tool.update_preferences_from_conversation(user_id, "I love Apple laptops under $1200")
        assert isinstance(legacy_res, dict)
        assert "current_session_context" in legacy_res
        assert_valid_session_context({"current_session_context": legacy_res["current_session_context"]})

        # return_session_context=True
        wrapper_res = tool.update_preferences_from_conversation(user_id, "I love Apple laptops under $1200", return_session_context=True)
        assert isinstance(wrapper_res, CurrentSessionContextWrapper)
        assert_valid_session_context(wrapper_res.to_dict())
