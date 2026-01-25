import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.llm.abstract_llm_handler import LLMHandlerInterface
from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm_interface.prompts import graph_cypher_prompt

try:
    from .neo4j_connector import Neo4jConnector
except ImportError:  # Allow direct script execution without package context.
    from neo4j_connector import Neo4jConnector


class GraphQueryManager:
    """
    Generates Cypher via an LLM tool, executes it, and maps results into
    the retrieved_items format expected by the prompt constructor.
    """

    def __init__(
        self,
        llm_handler: Optional[LLMHandlerInterface] = None,
        system_instruction: Optional[str] = None,
        enabled: Optional[bool] = None,
        default_limit: int = 10,
    ) -> None:
        self.logger = logging.getLogger(__name__)

        env_enabled = os.getenv("ENABLE_GRAPH_RETRIEVAL", "true").lower() not in {
            "false",
            "0",
            "no",
            "off",
        }
        self.enabled = env_enabled if enabled is None else enabled
        self.default_limit = default_limit

        self.llm_handler: LLMHandlerInterface = llm_handler or SimpleLLMHandler()
        self.capture_query_tool = self._build_capture_tool()

        model = getattr(self.llm_handler, "llm", self.llm_handler)
        if isinstance(model, ChatOpenAI):
            llm = model
        else:
            llm = ChatOpenAI(model=model, temperature=0)

        self.agent = create_agent(
            model=llm,
            tools=[self.capture_query_tool],
            system_prompt=system_instruction or self._default_system_prompt(),
        )

    def retrieve_items(
        self,
        user_query: str,
        preferences: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            self.logger.info("Graph retrieval disabled; skipping.")
            return []

        query_payload = self.build_query(
            user_query=user_query,
            preferences=preferences,
            user_profile=user_profile,
            conversation_history=conversation_history,
        )
        cypher = query_payload.get("cypher", "").strip()
        if not cypher:
            self.logger.warning("No Cypher generated; returning empty results.")
            return []

        parameters = query_payload.get("parameters") or {}
        parameters.setdefault("limit", self.default_limit)

        self.logger.info("Executing Cypher query for graph retrieval.")
        self.logger.info("Final Cypher (rendered): %s", self._render_cypher_with_params(cypher, parameters))
        self.logger.debug("Cypher: %s", cypher)
        self.logger.debug("Parameters: %s", parameters)

        try:
            with Neo4jConnector() as connector:
                records = connector.execute_read_transaction(cypher, parameters)
        except Exception as exc:
            self.logger.error("Graph retrieval failed: %s", exc)
            return []

        mapped = self._map_records(records)
        self.logger.info("Graph retrieval returned %d items.", len(mapped))
        self.logger.debug("Mapped items sample: %s", mapped[:3])
        return mapped

    def build_query(
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
        result = self.agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        raw = self._extract_content(result)
        parsed = self._parse_response(raw)
        if not parsed.get("cypher"):
            self.logger.warning("Cypher generation returned empty payload.")
        return parsed

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

    def _render_cypher_with_params(self, cypher: str, parameters: Dict[str, Any]) -> str:
        if not cypher or not parameters:
            return cypher

        def encode(value: Any) -> str:
            if value is None:
                return "NULL"
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, (int, float)):
                return str(value)
            if isinstance(value, str):
                escaped = value.replace("\\", "\\\\").replace("'", "\\'")
                return f"'{escaped}'"
            if isinstance(value, list):
                return "[" + ", ".join(encode(item) for item in value) + "]"
            if isinstance(value, dict):
                items = (f"{key}: {encode(val)}" for key, val in value.items())
                return "{" + ", ".join(items) + "}"
            return repr(value)

        rendered = cypher
        for key, value in parameters.items():
            rendered = re.sub(rf"\${re.escape(str(key))}\b", encode(value), rendered)
        return rendered

    def _map_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        mapped: List[Dict[str, Any]] = []
        for record in records:
            item = self._map_record(record)
            if item:
                mapped.append(item)
        return mapped

    def _map_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not record:
            return None

        node = self._extract_node(record)
        title = record.get("title") or node.get("title")
        main_category = record.get("main_category") or node.get("main_category")
        price = record.get("price") or node.get("price")
        rating = record.get("avg_rating") or record.get("rating") or node.get("avg_rating")
        brand = record.get("brand") or node.get("brand")
        categories = record.get("categories") or record.get("category") or []
        attributes = record.get("attributes") or record.get("features") or []
        score = record.get("score", 0.0)

        details = {
            "title": title or "Unknown",
            "main_category": main_category or (categories[0] if isinstance(categories, list) and categories else "Unknown"),
            "store": brand or "Unknown",
            "price": price if price is not None else "Unknown",
            "rating": rating if rating is not None else "Unknown",
            "features": attributes or "None specified",
            "score": self._as_float(score),
        }
        return {"details": details}

    def _extract_node(self, record: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("pp", "product", "parent", "item"):
            if key in record:
                return self._node_to_dict(record[key])
        return {}

    def _node_to_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "_properties"):
            return dict(getattr(value, "_properties"))
        if hasattr(value, "items"):
            try:
                return dict(value.items())
            except Exception:
                return {}
        return {}

    def _as_float(self, value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

