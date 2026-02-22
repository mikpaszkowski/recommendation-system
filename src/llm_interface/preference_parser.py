import json
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.llm.abstract_llm_handler import LLMHandlerInterface
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm_interface.abstract_preference_parser import PreferenceParserInterface
from src.llm_interface.prompts import preference_extract_prompt

import logging

class LLMPreferenceParser(PreferenceParserInterface):
    """
    LangChain-powered preference extractor.

    Keeps the interface surface tiny: provide text, receive a structured dict.
    Output is intentionally simple to stay readable and easy to extend.
    """

    def __init__(
        self,
        llm_handler: Optional[LLMHandlerInterface] = None,
        system_instruction: Optional[str] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        
        self.llm_handler: LLMHandlerInterface = llm_handler or SimpleLLMHandler()
        # Build a simple tool the LLM can call to emit structured prefs
        self.capture_preferences_tool = self._build_capture_tool()

        # Create a ChatOpenAI instance with the tool bound directly
        model = getattr(self.llm_handler, "llm", self.llm_handler)
        if isinstance(model, ChatOpenAI):
            llm = model
        else:
            llm = ChatOpenAI(model=model, temperature=0, api_key=getattr(self.llm_handler, "api_key", None))

        self.system_instruction = system_instruction or self._default_system_prompt()
        # Bind the tool so the LLM can call it in a single invocation
        self.llm_with_tools = llm.bind_tools([self.capture_preferences_tool])

    def extract_preferences(self, text: str) -> Dict[str, Any]:
        """Run LLM extraction with a JSON-structured response."""

        user_msg = self._build_prompt(text)
        messages = [
            ("system", self.system_instruction),
            ("human", user_msg),
        ]
        result = self.llm_with_tools.invoke(messages)
        raw = self._extract_content(result)
        return self._parse_response(raw)

    def format_for_recommender(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize extracted preferences for downstream use.

        Ensures expected keys exist and defaults are present.
        """
        return {
            "likes": preferences.get("likes") or [],
            "dislikes": preferences.get("dislikes") or [],
            "constraints": preferences.get("constraints", {}),
            "intent": preferences.get("intent", "recommendation"),
            "notes": preferences.get("notes", ""),
        }

    def _default_system_prompt(self) -> str:
        return preference_extract_prompt.prompt()

    def _build_prompt(self, conversation_text: str) -> str:
        """
        Build the user message content instructing the agent to call the tool.
        """
        return (
            "Analyze the conversation and call `capture_preferences` with:\n"
            "- likes: list of positive signals\n"
            "- dislikes: list of negative signals\n"
            "- constraints: optional object (price_range, brands, categories, "
            "must_have, must_not_have)\n"
            "- intent: recommendation | clarification | other\n"
            "- notes: brief helpful context\n"
            f"\n[CONVERSATION]\n{conversation_text}"
        )

    def _build_capture_tool(self):
        @tool
        def capture_preferences(
            likes: Optional[List[str]] = None,
            dislikes: Optional[List[str]] = None,
            constraints: Optional[Dict[str, Any]] = None,
            intent: str = "recommendation",
            notes: str = "",
        ) -> Dict[str, Any]:
            """Return structured user preferences as JSON-ready data."""
            self.logger.info(f"Capturing preferences: likes={likes}, dislikes={dislikes}, constraints={constraints}, intent={intent}, notes={notes}")
            return {
                "likes": likes or [],
                "dislikes": dislikes or [],
                "constraints": constraints or {},
                "intent": intent,
                "notes": notes,
            }

        return capture_preferences

    def _extract_content(self, result: Any) -> str:
        """
        Normalize agent output to a string or JSON-serializable payload.
        """
        # Prefer direct tool call payloads
        tool_calls = getattr(result, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                if tc.get("name") == "capture_preferences":
                    return json.dumps(tc.get("args", {}))

        # Look inside aggregated message lists (common agent output shape)
        messages = None
        if isinstance(result, dict) and "messages" in result:
            messages = result["messages"]
        if messages is None:
            messages = getattr(result, "messages", None)
        if messages:
            for msg in messages:
                # ToolMessage content often is already JSON string
                content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
                name = getattr(msg, "name", None) if not isinstance(msg, dict) else msg.get("name")
                if name == "capture_preferences" and content:
                    return content
                # Sometimes the tool call args are embedded
                tool_calls_msg = getattr(msg, "tool_calls", None) if not isinstance(msg, dict) else msg.get("tool_calls")
                if tool_calls_msg:
                    for tc in tool_calls_msg:
                        if tc.get("name") == "capture_preferences":
                            return json.dumps(tc.get("args", {}))

        # Fall back to dict fields
        if isinstance(result, dict):
            if "output" in result:
                return result["output"]
            if "content" in result:
                return result["content"]
        # LangChain messages
        content = getattr(result, "content", None)
        if content is not None:
            return content
        return str(result)

    def _parse_response(self, raw: str) -> Dict[str, Any]:
        try:
            data = json.loads(raw)
            # Ensure _thinking is present for downstream consumers
            if "_thinking" not in data:
                data["_thinking"] = data.get("notes", "")
            return data
        except Exception:
            # Fall back to a safe, empty structure on parse issues.
            return {
                "likes": [],
                "dislikes": [],
                "constraints": {},
                "intent": "recommendation",
                "notes": raw.strip(),
                "_thinking": raw.strip(),
            }
    
