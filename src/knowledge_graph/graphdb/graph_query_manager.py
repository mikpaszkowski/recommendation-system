import json
import logging
import os
import re
from typing import Any, Dict, List, Optional



from src.llm.simple_llm_handler import SimpleLLMHandler
from src.llm.abstract_llm_handler import LLMHandlerInterface

try:
    from .cypher_generator import CypherQueryGenerator
except ImportError:
    from cypher_generator import CypherQueryGenerator

try:
    from .neo4j_connector import Neo4jConnector
except ImportError:  # Allow direct script execution without package context.
    from neo4j_connector import Neo4jConnector

try:
    from .resolver_service import ResolverService
except ImportError:
    from resolver_service import ResolverService


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
        query_generator: Optional[CypherQueryGenerator] = None,
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

        # If a generator is provided, use it.
        # Otherwise, fall back to the ExternalLLMCypherGenerator (default behavior).
        if query_generator:
            self.query_generator = query_generator
        else:
            try:
                from .external_llm_cypher_generator import ExternalLLMCypherGenerator
            except ImportError:
                from external_llm_cypher_generator import ExternalLLMCypherGenerator
            
            self.query_generator = ExternalLLMCypherGenerator(
                llm_handler=llm_handler,
                system_instruction=system_instruction,
                default_limit=default_limit,
            )
        
        # Initialize Resolver Service
        try:
            self.resolver = ResolverService()
        except Exception as e:
            self.logger.warning(f"Failed to initialize ResolverService: {e}")
            self.resolver = None

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

        # Semantic Grounding Step
        grounded_prefs = self._ground_preferences(preferences)
        
        query_payload = self.build_query(
            user_query=user_query,
            preferences=grounded_prefs,
            user_profile=user_profile,
            conversation_history=conversation_history,
        )
        cypher = query_payload.get("cypher", "").strip()
        if not cypher:
            self.logger.warning("No Cypher generated; returning empty results.")
            return []

        parameters = query_payload.get("parameters") or {}
        parameters.setdefault("limit", self.default_limit)

        # Safety: Ensure all parameters used in Cypher are present provided
        # This prevents "Expected parameter(s): dislikes" errors if LLM forgets them.
        import re
        used_params = set(re.findall(r"\$(\w+)", cypher))
        for param in used_params:
            if param not in parameters:
                self.logger.warning(f"Parameter '${param}' found in Cypher but missing in parameters. Defaulting to [].")
                # Defaulting to empty list is safer for IN clauses like "WHERE b.name IN $brands"
                # For scalars it might break logic but better than crashing.
                parameters[param] = []

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
        return self.query_generator.generate_query(
            user_query=user_query,
            preferences=preferences,
            user_profile=user_profile,
            conversation_history=conversation_history,
        )

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

    def _ground_preferences(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance preferences by resolving loose terms to canonical Graph Attributes/Categories.
        """
        if not self.resolver or not preferences:
            return preferences

        import copy
        grounded = copy.deepcopy(preferences)
        weighted = grounded.get("weighted_preferences", {})
        
        # 1. Resolve Attributes (from 'likes')
        # We assume 'likes' contains attribute-like features e.g. "pulse reader"
        likes = weighted.get("likes", [])
        grounded_attributes = []
        
        for item in likes:
            text = item.get("value")
            if not text:
                continue
                
            # Try to resolve to attributes
            matches = self.resolver.resolve_attribute(text, k=1)
            if matches:
                best = matches[0]
                # Append the canonical info to the item
                # We can modify the 'value' or add a new field. 
                # Better to keep original 'value' for reference but add 'canonical'
                item["canonical_attribute"] = {
                    "name": best["name"],
                    "value": best["value"],
                    "normalized": best["normalized_value"]
                }
                grounded_attributes.append(f"{best['name']}: {best['normalized_value']}")
                self.logger.info(f"Resolved attribute '{text}' -> {best['name']}: {best['normalized_value']}")
            else:
                grounded_attributes.append(text)

        # 2. Resolve Categories (from 'constraints.categories')
        constraints = weighted.get("constraints", {})
        categories = constraints.get("categories", [])
        grounded_categories = []
        
        if categories:
            for cat in categories:
                matches = self.resolver.resolve_category(cat, k=1)
                if matches:
                    best = matches[0]
                    # We might want to use the full path or just the name
                    # Using the exact name node found is best for matching
                    grounded_categories.append(best["name"])
                    self.logger.info(f"Resolved category '{cat}' -> {best['name']} (Path: {best['path']})")
                else:
                    grounded_categories.append(cat)
            
            constraints["categories"] = grounded_categories

        # 3. Inject explicit "grounded_context" into preferences for the Prompt to use
        # This is a bit of a hack to pass data to the prompt template without changing the signature
        grounded["grounded_context"] = {
            "resolved_attributes": grounded_attributes,
            "resolved_categories": grounded_categories
        }

        return grounded

    def _as_float(self, value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

