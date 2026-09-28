"""
src/llm_interface/preference_parser.py

LangChain-powered preference extractor conforming to current_session_context JSON schema.
Integrates with CurrentSessionContextWrapper and session_adapter.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.dialog_manager.session_adapter import (
    legacy_preferences_to_session_context,
    session_context_to_legacy_preferences,
)
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
from src.llm.abstract_llm_handler import LLMHandlerInterface
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm_interface.abstract_preference_parser import PreferenceParserInterface
from src.llm_interface.prompts import preference_extract_prompt


class LLMPreferenceParser(PreferenceParserInterface):
    """
    LangChain-powered preference extractor.
    Extracts multi-turn conversational session context conforming to CurrentSessionContextWrapper.
    """

    def __init__(
        self,
        llm_handler: Optional[LLMHandlerInterface] = None,
        system_instruction: Optional[str] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)

        self.llm_handler: LLMHandlerInterface = llm_handler or SimpleLLMHandler()
        # Build tool defining the current_session_context schema
        self.capture_preferences_tool = self._build_capture_tool()

        # Handle underlying model extraction (supports ChatOpenAI, mocks, or generic handlers)
        model = getattr(self.llm_handler, "llm", self.llm_handler)
        if hasattr(model, "bind_tools"):
            llm = model
        elif isinstance(model, ChatOpenAI):
            llm = model
        else:
            llm = ChatOpenAI(
                model=model,
                temperature=0,
                api_key=getattr(self.llm_handler, "api_key", None),
            )

        self.system_instruction = system_instruction or self._default_system_prompt()
        if hasattr(llm, "bind_tools"):
            self.llm_with_tools = llm.bind_tools([self.capture_preferences_tool])
        else:
            self.llm_with_tools = llm

    def extract_preferences(self, text: str) -> Dict[str, Any]:
        """
        Run LLM extraction and return structured dictionary strictly wrapped in 'current_session_context'.
        Guarantees that the returned dictionary conforms to CurrentSessionContextWrapper.
        """
        self.logger.debug(f"Starting extraction for input text: '{text}'")
        user_msg = self._build_prompt(text)
        messages = [
            ("system", self.system_instruction),
            ("human", user_msg),
        ]
        try:
            self.logger.debug(f"Invoking LLM with {len(messages)} messages.")
            result = self.llm_with_tools.invoke(messages)
            
            self.logger.debug("LLM invocation completed. Extracting content.")
            raw = self._extract_content(result)
            self.logger.debug(f"Raw extracted content: {raw}")
            
            parsed = self._parse_response(raw)
            self.logger.debug("Successfully parsed response into dict.")
            return parsed
        except Exception as e:
            self.logger.warning(
                f"Preference extraction invocation failed: {e}. Falling back to empty session context.",
                exc_info=True,
            )
            return CurrentSessionContextWrapper.create_empty().to_dict()

    def format_for_recommender(self, preferences: Any) -> Dict[str, Any]:
        """
        Normalize extracted preferences for downstream use.
        Employs session_adapter.session_context_to_legacy_preferences to provide
        backward compatibility ('likes', 'dislikes', 'constraints', 'intent', 'notes',
        'weighted_preferences') while preserving 'current_session_context'.
        """
        if hasattr(preferences, "model_dump"):
            preferences = preferences.model_dump(mode="json")

        if not isinstance(preferences, dict):
            return session_context_to_legacy_preferences({})

        # 1. If payload contains canonical session context
        if "current_session_context" in preferences or "extracted_parameters" in preferences:
            return session_context_to_legacy_preferences(preferences)

        # 2. If payload is a legacy dictionary without session context
        if any(k in preferences for k in ("likes", "dislikes", "constraints")):
            try:
                ctx = legacy_preferences_to_session_context(
                    preferences, unpack_plural_constraints=True
                )
                return session_context_to_legacy_preferences(ctx.model_dump(mode="json"))
            except Exception as e:
                self.logger.warning(f"Error adapting legacy preferences in format_for_recommender: {e}")

        # 3. Default fallback
        return session_context_to_legacy_preferences(preferences)

    def _default_system_prompt(self) -> str:
        if hasattr(preference_extract_prompt, "get_system_prompt"):
            return preference_extract_prompt.get_system_prompt()
        return preference_extract_prompt.prompt()

    def _build_prompt(self, conversation_text: str) -> str:
        """
        Build the user message content instructing the agent to call the tool.
        """
        return (
            "Analyze the conversation and call `capture_preferences` with `current_session_context` containing:\n"
            "- session_intent: (REQUIRED) one of 'initial_search', 'exploring_domain', 'refining_options', 'comparing_items', 'finalizing_choice'\n"
            "- situational_context: (REQUIRED) concise summary of user situation and underlying goal\n"
            "- extracted_parameters: (REQUIRED)\n"
            "  * hard_constraints: list of {attribute, operator ('include'|'exclude'|'greater_than'|'less_than'|'equal'), value}\n"
            "  * soft_preferences: list of {category, value, polarity (-1.0 to 1.0), confidence (0.0 to 1.0), evidence}\n"
            "- dialogue_state: (REQUIRED)\n"
            "  * ready_for_recommendation: bool (true if sufficient context for DB retrieval)\n"
            "  * missing_critical_attributes: list of strings (mandatory missing query attributes)\n"
            "  * suggested_system_action: one of 'ask_clarification', 'present_results', 'change_topic'\n"
            f"\n[CONVERSATION]\n{conversation_text}"
        )

    def _build_capture_tool(self):
        """
        Build the LangChain tool defining the current_session_context schema.
        Conforms strictly to CurrentSessionContextWrapper.
        """
        @tool("capture_preferences", args_schema=CurrentSessionContextWrapper)
        def capture_preferences(current_session_context: SessionContext) -> Dict[str, Any]:
            """Return structured user preferences as JSON-ready current_session_context data."""
            self.logger.info(f"Captured current_session_context: {current_session_context}")
            return {"current_session_context": current_session_context.model_dump(mode="json")}

        return capture_preferences

    def _extract_content(self, result: Any) -> Any:
        """
        Normalize agent output to raw dictionary args or string.
        """
        # Prefer direct tool call payloads
        tool_calls = getattr(result, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                name = tc.get("name", "")
                if name in ("capture_preferences", "CurrentSessionContextWrapper"):
                    return tc.get("args", {})
            # If tool calls were present but none matched expected tool name, return empty
            return ""

        # Look inside aggregated message lists
        messages = None
        if isinstance(result, dict) and "messages" in result:
            messages = result["messages"]
        if messages is None:
            messages = getattr(result, "messages", None)
        if messages:
            for msg in messages:
                tool_calls_msg = getattr(msg, "tool_calls", None) if not isinstance(msg, dict) else msg.get("tool_calls")
                if tool_calls_msg:
                    for tc in tool_calls_msg:
                        if tc.get("name") in ("capture_preferences", "CurrentSessionContextWrapper"):
                            return tc.get("args", {})
                content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
                name = getattr(msg, "name", None) if not isinstance(msg, dict) else msg.get("name")
                if name in ("capture_preferences", "CurrentSessionContextWrapper") and content:
                    return content

        # Fall back to output/content strings
        if isinstance(result, dict):
            if "output" in result:
                return result["output"]
            if "content" in result:
                return result["content"]

        content = getattr(result, "content", None)
        if content is not None:
            return content
        return str(result)

    def _parse_response(self, raw: Any) -> Dict[str, Any]:
        """
        Parse raw response, validate against CurrentSessionContextWrapper, and sanitize fallbacks.
        Guarantees that the returned dictionary strictly validates against the schema.
        """
        data: Dict[str, Any] = {}
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str):
            clean_str = raw.strip()
            # Strip markdown code blocks if present
            if clean_str.startswith("```"):
                lines = clean_str.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_str = "\n".join(lines).strip()
            try:
                data = json.loads(clean_str)
            except Exception:
                # Attempt to extract JSON slice if surrounded by text
                start = clean_str.find("{")
                end = clean_str.rfind("}")
                if start != -1 and end != -1 and end > start:
                    try:
                        data = json.loads(clean_str[start : end + 1])
                    except Exception:
                        data = {}
                else:
                    data = {}

        if not isinstance(data, dict) or not data:
            return CurrentSessionContextWrapper.create_empty().to_dict()

        # Handle case where current_session_context is a string-encoded JSON
        if "current_session_context" in data and isinstance(data["current_session_context"], str):
            try:
                data["current_session_context"] = json.loads(data["current_session_context"])
            except Exception:
                pass

        # 1. Direct validation if wrapped
        if "current_session_context" in data and isinstance(data["current_session_context"], dict):
            try:
                wrapper = CurrentSessionContextWrapper.model_validate(data)
                return wrapper.to_dict()
            except Exception as e:
                self.logger.debug(f"Direct wrapper validation failed, attempting sanitization: {e}")

        # 2. Auto-wrap if unwrapped SessionContext
        if any(k in data for k in ("session_intent", "extracted_parameters", "dialogue_state", "situational_context")):
            try:
                wrapper = CurrentSessionContextWrapper.from_dict(data, auto_wrap=True)
                return wrapper.to_dict()
            except Exception as e:
                self.logger.debug(f"Unwrapped from_dict validation failed, attempting sanitization: {e}")

        # 3. Legacy dictionary adaptation
        if any(k in data for k in ("likes", "dislikes", "constraints")):
            try:
                ctx = legacy_preferences_to_session_context(data, unpack_plural_constraints=True)
                return CurrentSessionContextWrapper(current_session_context=ctx).to_dict()
            except Exception as e:
                self.logger.debug(f"Legacy adaptation failed: {e}")

        # 4. Sanitization and repair fallback
        try:
            repaired = self._sanitize_session_context_dict(data)
            return repaired
        except Exception as e:
            self.logger.warning(f"Session context repair failed: {e}. Returning empty valid context.")
            return CurrentSessionContextWrapper.create_empty().to_dict()

    def _sanitize_session_context_dict(self, raw_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize and repair a partially valid or malformed dictionary to conform to schema.
        """
        inner = raw_dict.get("current_session_context", raw_dict)
        if not isinstance(inner, dict):
            return CurrentSessionContextWrapper.create_empty().to_dict()

        # Session Intent
        intent_val = inner.get("session_intent", "initial_search")
        if hasattr(intent_val, "value"):
            intent_val = intent_val.value
        intent_val = str(intent_val).lower().strip()
        intent_map = {
            "initial_search": SessionIntent.INITIAL_SEARCH,
            "exploring_domain": SessionIntent.EXPLORING_DOMAIN,
            "refining_options": SessionIntent.REFINING_OPTIONS,
            "comparing_items": SessionIntent.COMPARING_ITEMS,
            "finalizing_choice": SessionIntent.FINALIZING_CHOICE,
            "recommendation": SessionIntent.INITIAL_SEARCH,
            "clarification": SessionIntent.REFINING_OPTIONS,
            "other": SessionIntent.EXPLORING_DOMAIN,
        }
        session_intent = intent_map.get(intent_val, SessionIntent.INITIAL_SEARCH)

        # Situational Context
        situational_context = str(inner.get("situational_context") or inner.get("notes") or "")

        # Extracted Parameters
        raw_params = inner.get("extracted_parameters")
        if not isinstance(raw_params, dict):
            raw_params = {}

        raw_hard = raw_params.get("hard_constraints") or []
        hard_constraints: List[HardConstraint] = []
        op_map = {
            "include": ConstraintOperator.INCLUDE,
            "exclude": ConstraintOperator.EXCLUDE,
            "greater_than": ConstraintOperator.GREATER_THAN,
            "less_than": ConstraintOperator.LESS_THAN,
            "equal": ConstraintOperator.EQUAL,
            "==": ConstraintOperator.EQUAL,
            "<": ConstraintOperator.LESS_THAN,
            "<=": ConstraintOperator.LESS_THAN,
            ">": ConstraintOperator.GREATER_THAN,
            ">=": ConstraintOperator.GREATER_THAN,
        }
        if isinstance(raw_hard, list):
            for item in raw_hard:
                if isinstance(item, dict):
                    attr = str(item.get("attribute", "")).strip().lower()
                    op_raw = str(item.get("operator", "")).strip().lower()
                    val = item.get("value")
                    op = op_map.get(op_raw)
                    if attr and op and val is not None:
                        try:
                            hard_constraints.append(HardConstraint(attribute=attr, operator=op, value=val))
                        except Exception:
                            pass

        raw_soft = raw_params.get("soft_preferences") or []
        soft_preferences: List[SoftPreference] = []
        if isinstance(raw_soft, list):
            for item in raw_soft:
                if isinstance(item, dict):
                    cat = str(item.get("category", "")).strip() or "general"
                    val = str(item.get("value", "")).strip()
                    try:
                        pol = float(item.get("polarity", 1.0))
                        pol = max(-1.0, min(1.0, pol))
                    except Exception:
                        pol = 1.0
                    try:
                        conf = float(item.get("confidence", 1.0))
                        conf = max(0.0, min(1.0, conf))
                    except Exception:
                        conf = 1.0
                    ev = str(item.get("evidence", "") or "")
                    if val:
                        try:
                            soft_preferences.append(
                                SoftPreference(
                                    category=cat,
                                    value=val,
                                    polarity=pol,
                                    confidence=conf,
                                    evidence=ev,
                                )
                            )
                        except Exception:
                            pass

        # Dialogue State
        raw_ds = inner.get("dialogue_state")
        if not isinstance(raw_ds, dict):
            raw_ds = {}

        ready = bool(raw_ds.get("ready_for_recommendation", len(hard_constraints) > 0))
        raw_missing = raw_ds.get("missing_critical_attributes", [])
        missing = [str(m).strip() for m in raw_missing if isinstance(m, (str, int))] if isinstance(raw_missing, list) else []

        # Invariant: If ready_for_recommendation is True, missing_critical_attributes must be empty
        if ready:
            missing = []

        act_val = str(raw_ds.get("suggested_system_action", "")).strip().lower()
        act_map = {
            "ask_clarification": SuggestedSystemAction.ASK_CLARIFICATION,
            "present_results": SuggestedSystemAction.PRESENT_RESULTS,
            "change_topic": SuggestedSystemAction.CHANGE_TOPIC,
            "clarify": SuggestedSystemAction.ASK_CLARIFICATION,
            "search": SuggestedSystemAction.PRESENT_RESULTS,
        }
        default_act = SuggestedSystemAction.PRESENT_RESULTS if ready else SuggestedSystemAction.ASK_CLARIFICATION
        action = act_map.get(act_val, default_act)

        wrapper = CurrentSessionContextWrapper(
            current_session_context=SessionContext(
                session_intent=session_intent,
                situational_context=situational_context,
                extracted_parameters=ExtractedParameters(
                    hard_constraints=hard_constraints,
                    soft_preferences=soft_preferences,
                ),
                dialogue_state=DialogueState(
                    ready_for_recommendation=ready,
                    missing_critical_attributes=missing,
                    suggested_system_action=action,
                ),
            )
        )
        return wrapper.to_dict()
