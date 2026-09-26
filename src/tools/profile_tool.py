from typing import Dict, Any, Optional, Union, List
import logging

from src.user.profile_manager import InMemoryUserProfileManager
from src.user.abstract_profile_manager import AbstractProfileManager
from src.llm_interface.preference_parser import LLMPreferenceParser
from src.personalization.preference_quantifier import PreferenceQuantifier
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
from src.dialog_manager.session_adapter import (
    hard_constraints_to_structured_filters,
    legacy_preferences_to_session_context,
    session_context_to_legacy_preferences,
)
from src.dialog_manager.dialogue_manager import DialogueManager

logger = logging.getLogger(__name__)

EPHEMERAL_ATTRIBUTES = {
    "price", "budget", "cost", "price_max", "price_min", "max_price", "min_price",
    "pricing", "discount", "deal", "shipping", "delivery", "date", "availability",
    "in_stock", "gift", "temporary", "urgency", "query", "search_term"
}


class ProfileTool:
    """
    Tool for managing user profile (reading and updating preferences).
    Wraps ProfileManager, PreferenceParser, and Quantifier while integrating
    with canonical CurrentSessionContextWrapper and SessionContext models.
    """
    def __init__(self, 
                 profile_manager: Optional[AbstractProfileManager] = None,
                 parser: Optional[LLMPreferenceParser] = None,
                 quantifier: Optional[PreferenceQuantifier] = None,
                 dialogue_manager: Optional[DialogueManager] = None):
        self.profile_manager = profile_manager or InMemoryUserProfileManager()
        self.parser = parser or LLMPreferenceParser()
        self.quantifier = quantifier or PreferenceQuantifier()
        self.dialogue_manager = dialogue_manager

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Reads the full user profile dictionary."""
        return self.profile_manager.get_profile(user_id)

    def get_session_context(
        self, user_id: str, as_wrapper: bool = False
    ) -> Union[SessionContext, CurrentSessionContextWrapper]:
        """
        Reads user's persistent profile and maps long-term preferences to a canonical SessionContext.
        """
        profile = self.get_profile(user_id)
        prefs = profile.get("preferences", {})

        hard_constraints: List[HardConstraint] = []
        soft_preferences: List[SoftPreference] = []

        # 1. Load long-term soft preferences
        for sp_data in prefs.get("long_term_soft_preferences", []):
            try:
                sp = sp_data if isinstance(sp_data, SoftPreference) else SoftPreference.model_validate(sp_data)
                soft_preferences.append(sp)
            except Exception as e:
                logger.warning(f"Error parsing long-term soft preference: {e}")

        # Fallback to legacy likes/dislikes
        if not soft_preferences:
            for like in prefs.get("likes", []):
                val = str(like).strip()
                if val:
                    soft_preferences.append(
                        SoftPreference(
                            category="brand" if val in ("Apple", "Dell", "HP", "Lenovo", "Asus") else "general",
                            value=val,
                            polarity=0.8,
                            confidence=0.8,
                            evidence="Imported from profile likes",
                        )
                    )
            for dislike in prefs.get("dislikes", []):
                val = str(dislike).strip()
                if val:
                    soft_preferences.append(
                        SoftPreference(
                            category="brand" if val in ("Apple", "Dell", "HP", "Lenovo", "Asus") else "general",
                            value=val,
                            polarity=-0.8,
                            confidence=0.8,
                            evidence="Imported from profile dislikes",
                        )
                    )

        # 2. Load long-term hard constraints
        for hc_data in prefs.get("long_term_hard_constraints", []):
            try:
                hc = hc_data if isinstance(hc_data, HardConstraint) else HardConstraint.model_validate(hc_data)
                if hc.attribute.lower().strip() not in EPHEMERAL_ATTRIBUTES:
                    hard_constraints.append(hc)
            except Exception as e:
                logger.warning(f"Error parsing long-term hard constraint: {e}")

        ctx = SessionContext(
            session_intent=SessionIntent.INITIAL_SEARCH,
            situational_context="",
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
        if as_wrapper:
            return CurrentSessionContextWrapper(current_session_context=ctx)
        return ctx

    def enrich_session_context(
        self,
        user_id: str,
        context: Union[SessionContext, CurrentSessionContextWrapper, Dict[str, Any]],
    ) -> CurrentSessionContextWrapper:
        """
        Enriches current_session_context with long-term user profile preferences.
        Priors (e.g. brand affinities, persistent exclusions, soft preferences) are seeded
        into extracted_parameters without overwriting existing session-explicit parameters.
        Ephemeral attributes (price, budget, situational context) are NEVER seeded.
        """
        if isinstance(context, CurrentSessionContextWrapper):
            wrapper = context
        elif isinstance(context, SessionContext):
            wrapper = CurrentSessionContextWrapper(current_session_context=context)
        elif isinstance(context, dict):
            wrapper = CurrentSessionContextWrapper.from_dict(context, auto_wrap=True)
        else:
            raise TypeError(f"Unsupported context type: {type(context)}")

        ctx = wrapper.current_session_context
        profile = self.get_profile(user_id)
        prefs = profile.get("preferences", {})

        existing_hard_attrs = {hc.attribute.lower().strip() for hc in ctx.extracted_parameters.hard_constraints}
        existing_soft_categories = {sp.category.lower().strip() for sp in ctx.extracted_parameters.soft_preferences}
        existing_soft_pairs = {(sp.category.lower().strip(), sp.value.lower().strip()) for sp in ctx.extracted_parameters.soft_preferences}

        # Seed enduring soft preferences
        for sp_data in prefs.get("long_term_soft_preferences", []):
            cat = sp_data.get("category", "general").lower().strip()
            val = str(sp_data.get("value", "")).strip()
            if (cat, val.lower()) not in existing_soft_pairs and cat not in EPHEMERAL_ATTRIBUTES:
                if cat in ("brand", "category") and cat in existing_soft_categories:
                    continue  # Session already explicitly constrained brand/category
                ctx.extracted_parameters.soft_preferences.append(
                    SoftPreference(
                        category=cat,
                        value=val,
                        polarity=float(sp_data.get("polarity", 0.8)),
                        confidence=float(sp_data.get("confidence", 0.7)),
                        evidence="Seeded from persistent user profile",
                    )
                )
                existing_soft_pairs.add((cat, val.lower()))

        # Fallback to legacy likes/dislikes
        if not prefs.get("long_term_soft_preferences"):
            for like in prefs.get("likes", []):
                val = str(like).strip()
                if ("general", val.lower()) not in existing_soft_pairs:
                    ctx.extracted_parameters.soft_preferences.append(
                        SoftPreference(
                            category="general",
                            value=val,
                            polarity=0.8,
                            confidence=0.7,
                            evidence="Seeded from profile likes",
                        )
                    )
                    existing_soft_pairs.add(("general", val.lower()))

        # Seed enduring hard constraints
        for hc_data in prefs.get("long_term_hard_constraints", []):
            attr = hc_data.get("attribute", "").lower().strip()
            if attr not in existing_hard_attrs and attr not in EPHEMERAL_ATTRIBUTES:
                try:
                    ctx.extracted_parameters.hard_constraints.append(
                        HardConstraint(
                            attribute=attr,
                            operator=ConstraintOperator(hc_data.get("operator")),
                            value=hc_data.get("value"),
                        )
                    )
                    existing_hard_attrs.add(attr)
                except Exception as e:
                    logger.warning(f"Error seeding hard constraint: {e}")

        return wrapper

    def sync_session_preferences_to_profile(
        self,
        user_id: str,
        context: Union[SessionContext, CurrentSessionContextWrapper, Dict[str, Any]],
        min_confidence: float = 0.8,
    ) -> Dict[str, Any]:
        """
        Safely synchronizes high-confidence preferences (confidence >= min_confidence)
        from session_context into the user profile.
        
        Guarantees:
        1. Ephemeral parameters (price, budget, dates, situational goals) are strictly rejected.
        2. Only preferences with confidence >= min_confidence are persisted.
        3. Persists both structured format and legacy keys (likes, dislikes, active_filters).
        """
        if isinstance(context, CurrentSessionContextWrapper):
            ctx = context.current_session_context
        elif isinstance(context, SessionContext):
            ctx = context
        elif isinstance(context, dict):
            wrapper = CurrentSessionContextWrapper.from_dict(context, auto_wrap=True)
            ctx = wrapper.current_session_context
        else:
            raise TypeError(f"Unsupported context type: {type(context)}")

        high_conf_soft = [
            sp for sp in ctx.extracted_parameters.soft_preferences
            if sp.confidence >= min_confidence
            and sp.category.lower().strip() not in EPHEMERAL_ATTRIBUTES
        ]

        enduring_hard = [
            hc for hc in ctx.extracted_parameters.hard_constraints
            if hc.attribute.lower().strip() not in EPHEMERAL_ATTRIBUTES
        ]

        profile = self.get_profile(user_id)
        prefs = profile.get("preferences", {}).copy()

        # Update structured long-term soft preferences
        existing_soft = prefs.get("long_term_soft_preferences", [])
        for sp in high_conf_soft:
            sp_dict = sp.model_dump()
            existing_soft = [
                s for s in existing_soft
                if not (s.get("category", "").lower() == sp.category.lower() and s.get("value", "").lower() == sp.value.lower())
            ]
            existing_soft.append(sp_dict)
        prefs["long_term_soft_preferences"] = existing_soft

        # Update structured long-term hard constraints
        existing_hard = prefs.get("long_term_hard_constraints", [])
        for hc in enduring_hard:
            hc_dict = hc.model_dump()
            existing_hard = [
                h for h in existing_hard
                if not (h.get("attribute", "").lower() == hc.attribute.lower() and h.get("operator") == hc.operator)
            ]
            existing_hard.append(hc_dict)
        prefs["long_term_hard_constraints"] = existing_hard

        # Flatten into legacy keys for backward compatibility
        likes = list(prefs.get("likes", []))
        dislikes = list(prefs.get("dislikes", []))
        for sp in high_conf_soft:
            if sp.polarity > 0:
                if sp.value not in likes:
                    likes.append(sp.value)
                if sp.value in dislikes:
                    dislikes.remove(sp.value)
            elif sp.polarity < 0:
                if sp.value not in dislikes:
                    dislikes.append(sp.value)
                if sp.value in likes:
                    likes.remove(sp.value)
        prefs["likes"] = likes
        prefs["dislikes"] = dislikes

        for hc in enduring_hard:
            attr = hc.attribute.lower().strip()
            val = hc.value
            if hc.operator in (ConstraintOperator.INCLUDE, ConstraintOperator.EQUAL):
                prefs[attr] = val
            elif hc.operator == ConstraintOperator.EXCLUDE:
                prefs[f"exclude_{attr}"] = val

        self.profile_manager.update_profile(user_id, prefs)
        return prefs

    def update_preferences_from_conversation(
        self,
        user_id: str,
        conversation_text: str,
        return_session_context: bool = False,
    ) -> Union[Dict[str, Any], CurrentSessionContextWrapper]:
        """
        Extracts preferences from text, quantifies them, safely synchronizes
        high-confidence preferences (confidence >= 0.8) to profile, and returns
        updated preferences.
        """
        logger.info(f"ProfileTool: Extracting preferences for user {user_id}")

        # 1. Extract session context
        extracted = self.parser.extract_preferences(conversation_text)
        wrapper = CurrentSessionContextWrapper.from_dict(extracted, auto_wrap=True)

        # 2. Synchronize high-confidence preferences safely (confidence >= 0.8, no ephemeral constraints)
        self.sync_session_preferences_to_profile(user_id, wrapper, min_confidence=0.8)

        # 3. Format legacy weighted preferences for backward compatibility
        normalized = self.parser.format_for_recommender(extracted)
        weighted_prefs = self.quantifier.quantify(normalized)

        # 4. Update profile manager with legacy view
        self.profile_manager.update_profile(user_id, {"preferences": weighted_prefs})

        # Ensure current_session_context is available in the returned dictionary
        if isinstance(weighted_prefs, dict) and "current_session_context" not in weighted_prefs:
            weighted_prefs["current_session_context"] = wrapper.to_dict()["current_session_context"]

        if return_session_context:
            return wrapper
        return weighted_prefs

    def save_item_interaction(self, user_id: str, item: Dict[str, Any]) -> None:
        """Saves an interaction (e.g. user viewed/liked an item)."""
        self.profile_manager.update_interaction_history(user_id, item)
