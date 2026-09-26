"""
src/dialog_manager/dialogue_manager.py

Core Dialogue State Manager for Conversational Recommender System (CRS 2.0).
Satisfies Requirement R3:
  - In-memory storage mapping session_id (or user_id) to active CurrentSessionContextWrapper.
  - Multi-turn state accumulation, constraint overrides, and soft preference updates.
  - Lifecycle tracking across canonical SessionIntent phases.
  - Synchronous dialogue state computation (readiness, critical attribute gap detection, next system action).

Thread-safe and fully compliant with Pydantic v2 session schemas and downstream adapters.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Set, Union

from src.dialog_manager.session_schema import (
    ConstraintOperator,
    CurrentSessionContextWrapper,
    HardConstraint,
    SessionContext,
    SessionIntent,
    SoftPreference,
    SuggestedSystemAction,
)

logger = logging.getLogger(__name__)


class DialogueManager:
    """
    Lightweight, high-cohesion dialogue manager tracking multi-turn session context.
    Maintains active session states wrapped in CurrentSessionContextWrapper and provides
    state-machine evaluation of recommendation readiness.
    """

    def __init__(
        self,
        critical_attributes: Optional[List[str]] = None,
        attribute_synonyms: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """
        Initialize DialogueManager.

        Args:
            critical_attributes: Mandatory attribute names required before readiness is granted.
                                 Defaults to ["category"]. Duplicates are cleanly removed.
            attribute_synonyms: Optional mapping of canonical attributes to domain synonyms.
        """
        self._lock = threading.RLock()
        self._sessions: Dict[str, CurrentSessionContextWrapper] = {}

        # Default critical attribute is 'category'
        raw_attrs = critical_attributes if critical_attributes is not None else ["category"]
        # Deduplicate while preserving order
        self._critical_attributes: List[str] = list(dict.fromkeys(raw_attrs))

        # Default attribute synonyms for robust matching (e.g. budget fulfills price)
        self._synonyms: Dict[str, Set[str]] = {
            "price": {"price", "budget", "cost", "price_max", "max_price", "pricing"},
            "budget": {"price", "budget", "cost", "price_max", "max_price", "pricing"},
            "category": {"category", "product_category", "product_type", "type"},
            "brand": {"brand", "make", "manufacturer"},
        }
        if attribute_synonyms:
            for k, syn_list in attribute_synonyms.items():
                k_clean = k.lower().strip()
                syn_set = {s.lower().strip() for s in syn_list}
                syn_set.add(k_clean)
                if k_clean in self._synonyms:
                    self._synonyms[k_clean].update(syn_set)
                else:
                    self._synonyms[k_clean] = syn_set

    @property
    def critical_attributes(self) -> List[str]:
        """Return the list of configured critical attributes."""
        return list(self._critical_attributes)

    # -------------------------------------------------------------------------
    # Core Retrieval & Lifecycle API
    # -------------------------------------------------------------------------

    def get_context(
        self, session_id: str, as_wrapper: bool = False
    ) -> Union[SessionContext, CurrentSessionContextWrapper]:
        """
        Retrieve active session context. Initializes an empty session if not present.

        Args:
            session_id: Session or user identifier (handles empty string safely).
            as_wrapper: If True, returns CurrentSessionContextWrapper.
                        If False (default), returns SessionContext.

        Returns:
            SessionContext or CurrentSessionContextWrapper.
        """
        with self._lock:
            wrapper = self._get_or_create_wrapper(session_id)
            if as_wrapper:
                return wrapper
            return wrapper.current_session_context

    def get_wrapper(self, session_id: str) -> CurrentSessionContextWrapper:
        """Direct accessor returning the root CurrentSessionContextWrapper."""
        with self._lock:
            return self._get_or_create_wrapper(session_id)

    def update_context(
        self,
        session_id: str,
        updates: Union[Dict[str, Any], SessionContext, CurrentSessionContextWrapper],
    ) -> SessionContext:
        """
        Directly update or replace context for a session.

        Args:
            session_id: Session identifier.
            updates: New context payload (dict, SessionContext, or wrapper).

        Returns:
            Updated SessionContext.
        """
        with self._lock:
            if isinstance(updates, CurrentSessionContextWrapper):
                wrapper = updates
            elif isinstance(updates, SessionContext):
                wrapper = CurrentSessionContextWrapper(current_session_context=updates)
            elif isinstance(updates, dict):
                wrapper = CurrentSessionContextWrapper.from_dict(updates, auto_wrap=True)
            else:
                raise TypeError(f"Unsupported context update type: {type(updates).__name__}")

            self._evaluate_dialogue_state(wrapper.current_session_context)
            self._sessions[session_id] = wrapper
            return wrapper.current_session_context

    def reset_context(self, session_id: str) -> SessionContext:
        """
        Reset session context back to initial empty state.

        Args:
            session_id: Session identifier.

        Returns:
            Freshly initialized SessionContext.
        """
        with self._lock:
            wrapper = CurrentSessionContextWrapper.create_empty()
            self._evaluate_dialogue_state(wrapper.current_session_context)
            self._sessions[session_id] = wrapper
            return wrapper.current_session_context

    def reset_session(self, session_id: str) -> None:
        """
        Alias for reset_context for backward compatibility with PROJECT.md and E2E fixtures.
        """
        self.reset_context(session_id)

    def session_exists(self, session_id: str) -> bool:
        """Check if a session ID is currently active in memory."""
        with self._lock:
            return session_id in self._sessions

    def list_sessions(self) -> List[str]:
        """Return a list of all active session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def delete_session(self, session_id: str) -> bool:
        """Remove a session from memory. Returns True if removed, False if not found."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def get_history_summary(self, session_id: str) -> Dict[str, Any]:
        """Return a compact dictionary summary of the session for inspection."""
        with self._lock:
            ctx = self.get_context(session_id)
            return {
                "session_id": session_id,
                "session_intent": ctx.session_intent.value if hasattr(ctx.session_intent, "value") else str(ctx.session_intent),
                "ready_for_recommendation": ctx.dialogue_state.ready_for_recommendation,
                "missing_critical_attributes": list(ctx.dialogue_state.missing_critical_attributes),
                "suggested_system_action": ctx.dialogue_state.suggested_system_action.value if hasattr(ctx.dialogue_state.suggested_system_action, "value") else str(ctx.dialogue_state.suggested_system_action),
                "hard_constraints_count": len(ctx.extracted_parameters.hard_constraints),
                "soft_preferences_count": len(ctx.extracted_parameters.soft_preferences),
                "situational_context": ctx.situational_context,
            }

    # -------------------------------------------------------------------------
    # Multi-Turn Turn Processing & Merging Engine
    # -------------------------------------------------------------------------

    def update_turn(
        self,
        session_id: str,
        user_message: str,
        extraction: Union[Dict[str, Any], SessionContext, CurrentSessionContextWrapper, None] = None,
    ) -> SessionContext:
        """
        Process a new dialogue turn, merging newly extracted parameters into the
        running session context and re-evaluating dialogue state.

        Args:
            session_id: Session identifier.
            user_message: Latest user utterance.
            extraction: Extracted parameters dictionary, SessionContext, or wrapper.

        Returns:
            Updated running SessionContext.
        """
        with self._lock:
            wrapper = self._get_or_create_wrapper(session_id)
            current = wrapper.current_session_context

            # Safely handle None or empty extraction payloads
            if extraction is None:
                self._evaluate_dialogue_state(current)
                return current

            raw_extraction = self._unwrap_payload(extraction)
            if not raw_extraction:
                self._evaluate_dialogue_state(current)
                return current

            # 1. Update session_intent
            self._update_session_intent(current, user_message, raw_extraction)

            # 2. Update situational_context
            new_sit = raw_extraction.get("situational_context")
            if new_sit and isinstance(new_sit, str) and new_sit.strip():
                current.situational_context = new_sit.strip()

            # 3. Merge hard constraints
            self._merge_hard_constraints(current, raw_extraction)

            # 4. Merge soft preferences
            self._merge_soft_preferences(current, raw_extraction)

            # 5. Re-evaluate dialogue state
            self._evaluate_dialogue_state(current, raw_extraction=raw_extraction)

            return current

    # -------------------------------------------------------------------------
    # Internal Merging & Evaluation Helpers
    # -------------------------------------------------------------------------

    def _get_or_create_wrapper(self, session_id: str) -> CurrentSessionContextWrapper:
        """Retrieve existing wrapper or initialize empty wrapper for session_id."""
        if session_id not in self._sessions:
            wrapper = CurrentSessionContextWrapper.create_empty()
            self._evaluate_dialogue_state(wrapper.current_session_context)
            self._sessions[session_id] = wrapper
        return self._sessions[session_id]

    def _unwrap_payload(
        self, payload: Union[Dict[str, Any], SessionContext, CurrentSessionContextWrapper, None]
    ) -> Dict[str, Any]:
        """Normalize payload into an unwrapped dictionary."""
        if payload is None:
            return {}
        if isinstance(payload, CurrentSessionContextWrapper):
            data = payload.to_dict()
        elif isinstance(payload, SessionContext):
            data = payload.to_dict()
        elif hasattr(payload, "model_dump"):
            data = payload.model_dump()
        elif isinstance(payload, dict):
            data = payload
        else:
            return {}

        if "current_session_context" in data and isinstance(data["current_session_context"], dict):
            return data["current_session_context"]
        return data

    def _update_session_intent(
        self, current: SessionContext, user_message: str, raw_extraction: Dict[str, Any]
    ) -> None:
        """Update session intent from explicit extraction or conversational heuristic."""
        if "session_intent" in raw_extraction and raw_extraction["session_intent"]:
            raw_intent = raw_extraction["session_intent"]
            try:
                if isinstance(raw_intent, SessionIntent):
                    current.session_intent = raw_intent
                else:
                    current.session_intent = SessionIntent(str(raw_intent).lower().strip())
                return
            except (ValueError, KeyError):
                logger.warning("Unrecognized session_intent '%s', preserving existing.", raw_intent)

        # Fallback heuristic: Transition from INITIAL_SEARCH to REFINING_OPTIONS once parameters exist
        if current.session_intent == SessionIntent.INITIAL_SEARCH:
            has_params = (
                len(current.extracted_parameters.hard_constraints) > 0
                or len(current.extracted_parameters.soft_preferences) > 0
            )
            if has_params:
                current.session_intent = SessionIntent.REFINING_OPTIONS

    def _merge_hard_constraints(
        self, current: SessionContext, raw_extraction: Dict[str, Any]
    ) -> None:
        """
        Merge incoming hard constraints into running context.
        Applies attribute + operator override rules, range coexistence rules,
        contradiction cancellation, and categorical pivots.
        """
        extracted_params = raw_extraction.get("extracted_parameters", {})
        if hasattr(extracted_params, "model_dump"):
            extracted_params = extracted_params.model_dump()
        elif not isinstance(extracted_params, dict):
            extracted_params = {}

        new_hard = extracted_params.get("hard_constraints", [])
        if not new_hard and "hard_constraints" in raw_extraction:
            new_hard = raw_extraction["hard_constraints"]

        if not isinstance(new_hard, list):
            return

        target_list = current.extracted_parameters.hard_constraints

        for nh in new_hard:
            try:
                hc = nh if isinstance(nh, HardConstraint) else HardConstraint.model_validate(nh)
            except Exception as exc:
                logger.warning("Skipping invalid hard constraint %s: %s", nh, exc)
                continue

            attr_clean = hc.attribute.lower().strip()
            op = hc.operator
            val = hc.value

            # 1. Inclusion vs exclusion contradiction cancellation
            if op == ConstraintOperator.EXCLUDE:
                target_list[:] = [
                    c for c in target_list
                    if not (
                        c.attribute.lower().strip() == attr_clean
                        and c.operator in (ConstraintOperator.INCLUDE, ConstraintOperator.EQUAL)
                        and str(c.value).lower().strip() == str(val).lower().strip()
                    )
                ]
            elif op in (ConstraintOperator.INCLUDE, ConstraintOperator.EQUAL):
                target_list[:] = [
                    c for c in target_list
                    if not (
                        c.attribute.lower().strip() == attr_clean
                        and c.operator == ConstraintOperator.EXCLUDE
                        and str(c.value).lower().strip() == str(val).lower().strip()
                    )
                ]

            # 2. Contradictory range bound removal
            if op == ConstraintOperator.LESS_THAN:
                try:
                    new_num = float(val)
                    target_list[:] = [
                        c for c in target_list
                        if not (
                            c.attribute.lower().strip() == attr_clean
                            and c.operator == ConstraintOperator.GREATER_THAN
                            and float(c.value) >= new_num
                        )
                    ]
                except (ValueError, TypeError):
                    pass
            elif op == ConstraintOperator.GREATER_THAN:
                try:
                    new_num = float(val)
                    target_list[:] = [
                        c for c in target_list
                        if not (
                            c.attribute.lower().strip() == attr_clean
                            and c.operator == ConstraintOperator.LESS_THAN
                            and float(c.value) <= new_num
                        )
                    ]
                except (ValueError, TypeError):
                    pass

            # 3. Categorical pivot / direct override / scan
            replaced = False
            for idx, existing in enumerate(target_list):
                ex_attr = existing.attribute.lower().strip()
                ex_op = existing.operator

                if ex_attr != attr_clean:
                    continue

                # Rule 1: Same attribute and same operator -> Direct override (E8)
                if ex_op == op:
                    target_list[idx] = hc
                    replaced = True
                    break

                # Rule 2: Categorical pivot (category, brand) with include/equal operator
                if attr_clean in ("category", "product_category", "brand"):
                    if ex_op in (ConstraintOperator.INCLUDE, ConstraintOperator.EQUAL) and \
                       op in (ConstraintOperator.INCLUDE, ConstraintOperator.EQUAL):
                        target_list[idx] = hc
                        replaced = True
                        break

                # Rule 3: Exact equality override
                if op == ConstraintOperator.EQUAL or ex_op == ConstraintOperator.EQUAL:
                    target_list[idx] = hc
                    replaced = True
                    break

            if not replaced:
                target_list.append(hc)

    def _merge_soft_preferences(
        self, current: SessionContext, raw_extraction: Dict[str, Any]
    ) -> None:
        """
        Merge incoming soft preferences into running context.
        Matches on category + value (case-insensitive) to update polarity, confidence, and evidence.
        """
        extracted_params = raw_extraction.get("extracted_parameters", {})
        if hasattr(extracted_params, "model_dump"):
            extracted_params = extracted_params.model_dump()
        elif not isinstance(extracted_params, dict):
            extracted_params = {}

        new_soft = extracted_params.get("soft_preferences", [])
        if not new_soft and "soft_preferences" in raw_extraction:
            new_soft = raw_extraction["soft_preferences"]

        if not isinstance(new_soft, list):
            return

        target_list = current.extracted_parameters.soft_preferences

        for ns in new_soft:
            try:
                sp = ns if isinstance(ns, SoftPreference) else SoftPreference.model_validate(ns)
            except Exception as exc:
                logger.warning("Skipping invalid soft preference %s: %s", ns, exc)
                continue

            cat_clean = sp.category.lower().strip()
            val_clean = sp.value.lower().strip()
            replaced = False

            for idx, existing in enumerate(target_list):
                if (
                    existing.category.lower().strip() == cat_clean
                    and existing.value.lower().strip() == val_clean
                ):
                    target_list[idx] = sp
                    replaced = True
                    break

            if not replaced:
                target_list.append(sp)

    def _evaluate_dialogue_state(
        self, context: SessionContext, raw_extraction: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Evaluate readiness, missing critical attributes, and suggested next system action.

        Invariants:
        1. If missing_critical_attributes is non-empty, ready_for_recommendation MUST be False.
        2. When ready_for_recommendation is False, suggested action defaults to ask_clarification.
        3. When ready_for_recommendation is True, suggested action defaults to present_results.
        4. If extraction explicitly indicates change_topic, suggested action is change_topic.
        """
        present_hard_attrs = {
            hc.attribute.lower().strip()
            for hc in context.extracted_parameters.hard_constraints
        }
        present_soft_categories = {
            sp.category.lower().strip()
            for sp in context.extracted_parameters.soft_preferences
        }
        present_soft_values = {
            sp.value.lower().strip()
            for sp in context.extracted_parameters.soft_preferences
        }

        all_present = present_hard_attrs.union(present_soft_categories).union(present_soft_values)

        missing: List[str] = []
        for req in self._critical_attributes:
            req_clean = req.lower().strip()
            if req_clean in all_present:
                continue
            synonyms = self._synonyms.get(req_clean, {req_clean})
            if any(syn in all_present for syn in synonyms):
                continue
            missing.append(req)

        has_params = (
            len(context.extracted_parameters.hard_constraints) > 0
            or len(context.extracted_parameters.soft_preferences) > 0
        )
        has_sufficient_context = len(missing) == 0 and has_params

        context.dialogue_state.ready_for_recommendation = has_sufficient_context
        context.dialogue_state.missing_critical_attributes = missing

        incoming_action = None
        if raw_extraction:
            raw_ds = raw_extraction.get("dialogue_state", {})
            if hasattr(raw_ds, "suggested_system_action"):
                incoming_action = getattr(raw_ds, "suggested_system_action")
            elif isinstance(raw_ds, dict):
                incoming_action = raw_ds.get("suggested_system_action")

            if not incoming_action and "suggested_system_action" in raw_extraction:
                incoming_action = raw_extraction["suggested_system_action"]

            if hasattr(incoming_action, "value"):
                incoming_action = incoming_action.value
            if incoming_action:
                incoming_action = str(incoming_action).lower().strip()

        if incoming_action == "change_topic":
            context.dialogue_state.suggested_system_action = SuggestedSystemAction.CHANGE_TOPIC
            context.dialogue_state.ready_for_recommendation = False
        elif not has_sufficient_context:
            context.dialogue_state.suggested_system_action = SuggestedSystemAction.ASK_CLARIFICATION
        else:
            context.dialogue_state.suggested_system_action = SuggestedSystemAction.PRESENT_RESULTS
