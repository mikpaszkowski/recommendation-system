import json
import logging
import os
from typing import Any, Dict, List, Optional

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.llm.abstract_llm_handler import LLMHandlerInterface
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm_interface.prompts import graph_cypher_prompt
from .cypher_generator import CypherQueryGenerator


class ExternalLLMCypherGenerator(CypherQueryGenerator):
    """
    Generates Cypher queries using an external LLM via LangChain.
    """

    def __init__(
        self,
        llm_handler: Optional[LLMHandlerInterface] = None,
        system_instruction: Optional[str] = None,
        default_limit: int = 10,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.default_limit = default_limit
        self.llm_handler: LLMHandlerInterface = llm_handler or SimpleLLMHandler()
        self.capture_query_tool = self._build_capture_tool()

        model = getattr(self.llm_handler, "llm", self.llm_handler)
        if isinstance(model, ChatOpenAI):
            llm = model
        else:
            # Recreate ChatOpenAI wrapper if needed, similar to original logic
            llm = ChatOpenAI(model=model, temperature=0)

        self.agent = create_agent(
            model=llm,
            tools=[self.capture_query_tool],
            system_prompt=system_instruction or self._default_system_prompt(),
        )

    def generate_query(
        self,
        user_query: str,
        preferences: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(
            user_query=user_query,
            preferences=preferences,
            user_profile=user_profile,
            conversation_history=conversation_history,
        )
        try:
            result = self.agent.invoke({"messages": [{"role": "user", "content": prompt}]})
            raw = self._extract_content(result)
            parsed = self._parse_response(raw)
            if not parsed.get("cypher"):
                self.logger.warning("Cypher generation returned empty payload.")
            return parsed
        except Exception as e:
            self.logger.error(f"Error generating Cypher query: {e}")
            return {"cypher": "", "parameters": {}, "notes": str(e)}

    def _default_system_prompt(self) -> str:
        return graph_cypher_prompt.prompt()

    def _build_prompt(
        self,
        user_query: str,
        preferences: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        context = {
            "user_query": user_query,
            "preferences": preferences,
            "user_profile": user_profile or {},
            "conversation_history": conversation_history or [],
            "default_limit": self.default_limit,
        }
        return (
            "Analyze the context and call `capture_cypher_query` with a Cypher query and parameters.\n"
            "WARNING: STRICT CYPHER SYNTAX ENFORCED.\n"
            "If you use `WITH` to aggregate variables (e.g. `collect(c.name) as categories`), "
            "you MUST use the alias (`categories`) in `RETURN`. "
            "Accessing `c` after it was aggregated will cause a crash.\n"
            f"{json.dumps(context, ensure_ascii=True, indent=2)}"
        )

    def _build_capture_tool(self):
        @tool
        def capture_cypher_query(
            cypher: str,
            parameters: Optional[Dict[str, Any]] = None,
            notes: str = "",
        ) -> Dict[str, Any]:
            """Return a Cypher query with parameter bindings."""
            payload = {
                "cypher": cypher or "",
                "parameters": parameters or {},
                "notes": notes,
            }
            self.logger.info("Captured Cypher query payload from LLM.")
            return payload

        return capture_cypher_query

    def _extract_content(self, result: Any) -> str:
        # Same extraction logic as original
        tool_calls = getattr(result, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                if tc.get("name") == "capture_cypher_query":
                    return json.dumps(tc.get("args", {}))

        messages = None
        if isinstance(result, dict) and "messages" in result:
            messages = result["messages"]
        if messages is None:
            messages = getattr(result, "messages", None)
        if messages:
            for msg in messages:
                content = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content")
                name = getattr(msg, "name", None) if not isinstance(msg, dict) else msg.get("name")
                if name == "capture_cypher_query" and content:
                    return content
                tool_calls_msg = getattr(msg, "tool_calls", None) if not isinstance(msg, dict) else msg.get("tool_calls")
                if tool_calls_msg:
                    for tc in tool_calls_msg:
                        if tc.get("name") == "capture_cypher_query":
                            return json.dumps(tc.get("args", {}))

        if isinstance(result, dict):
            if "output" in result:
                return result["output"]
            if "content" in result:
                return result["content"]
        content = getattr(result, "content", None)
        if content is not None:
            return content
        return str(result)

    def _parse_response(self, raw: str) -> Dict[str, Any]:
        try:
            data = json.loads(raw)
            if "parameters" not in data:
                data["parameters"] = {}
            return data
        except Exception:
            return {"cypher": "", "parameters": {}, "notes": raw.strip()}
