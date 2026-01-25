import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.conversation.history_manager import InMemoryHistoryManager
from src.llm_interface.preference_parser import LLMPreferenceParser
from src.llm_interface.prompt_constructor import PromptConstructor
from src.personalization.preference_quantifier import PreferenceQuantifier
from src.user.profile_manager import InMemoryUserProfileManager


class PreferenceAgentFlow:
    """
    Orchestrates Phase I agents:
    history -> extraction -> quantification -> profile update -> prompt build.
    """

    def __init__(
        self,
        history_manager: Optional[InMemoryHistoryManager] = None,
        preference_parser: Optional[LLMPreferenceParser] = None,
        quantifier: Optional[PreferenceQuantifier] = None,
        profile_manager: Optional[InMemoryUserProfileManager] = None,
        prompt_constructor: Optional[PromptConstructor] = None,
        graph_query_manager: Optional[Any] = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.history_manager = history_manager or InMemoryHistoryManager()
        self.preference_parser = preference_parser or LLMPreferenceParser()
        self.quantifier = quantifier or PreferenceQuantifier()
        self.profile_manager = profile_manager or InMemoryUserProfileManager()
        self.prompt_constructor = prompt_constructor or PromptConstructor()
        self.graph_query_manager = graph_query_manager or self._init_graph_query_manager()

    def run(
        self,
        user_id: str,
        user_message: str,
        retrieved_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the Phase I pipeline and return enriched context plus prompts.
        """
        history = self.history_manager.get_history(user_id)
        conversation_text = self._combine_history_text(history, user_message)

        extracted = self.preference_parser.extract_preferences(conversation_text)
        normalized = self.preference_parser.format_for_recommender(extracted)
        weighted = self.quantifier.quantify(normalized)

        # Persist profile and history
        self.profile_manager.update_profile(user_id, {"preferences": weighted})
        self.history_manager.add_turn(user_id, user_message)

        user_profile = self.profile_manager.get_profile(user_id)
        graph_items = self._retrieve_graph_items(
            user_message=user_message,
            preferences=weighted,
            user_profile=user_profile,
            history=history,
        )
        combined_items = self._combine_retrieved_items(retrieved_items, graph_items)
        prompt_messages = self.prompt_constructor.construct_recommendation_prompt(
            user_query=user_message,
            user_profile=user_profile,
            conversation_history=history,
            retrieved_items=combined_items,
            preferences=weighted,
        )

        return {
            "prompt_messages": prompt_messages,
            "preferences": weighted,
            "raw_extraction": extracted,
            "history": history,
            "user_profile": user_profile,
        }

    def _combine_history_text(
        self, history: List[Dict[str, str]], latest_user_message: str
    ) -> str:
        """
        Create a compact text block for extraction.
        """
        parts: List[str] = []
        for turn in reversed(history[-5:]):  # chronological for readability
            if "user" in turn:
                parts.append(f"User: {turn['user']}")
            if "assistant" in turn:
                parts.append(f"Assistant: {turn['assistant']}")
        parts.append(f"User: {latest_user_message}")
        return "\n".join(parts)

    def _init_graph_query_manager(self) -> Optional[Any]:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "knowledge-graph"
            / "graphdb"
            / "graph_query_manager.py"
        )
        if not module_path.exists():
            self.logger.warning("Graph query manager module not found: %s", module_path)
            return None
        try:
            module_parent = str(module_path.parent)
            if module_parent not in sys.path:
                sys.path.insert(0, module_parent)
            spec = importlib.util.spec_from_file_location("graph_query_manager", module_path)
            if spec is None or spec.loader is None:
                self.logger.error("Failed to load GraphQueryManager module spec.")
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.GraphQueryManager()
        except Exception as exc:
            self.logger.error("Failed to initialize GraphQueryManager: %s", exc)
            return None

    def _retrieve_graph_items(
        self,
        user_message: str,
        preferences: Dict[str, Any],
        user_profile: Dict[str, Any],
        history: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        if not self.graph_query_manager:
            return []
        try:
            self.logger.info("Starting graph retrieval.")
            return self.graph_query_manager.retrieve_items(
                user_query=user_message,
                preferences=preferences,
                user_profile=user_profile,
                conversation_history=history,
            )
        except Exception as exc:
            self.logger.error("Graph retrieval error: %s", exc)
            return []

    def _combine_retrieved_items(
        self,
        existing_items: Optional[List[Dict[str, Any]]],
        graph_items: Optional[List[Dict[str, Any]]],
    ) -> Optional[List[Dict[str, Any]]]:
        combined: List[Dict[str, Any]] = []
        if graph_items:
            combined.extend(graph_items)
        if existing_items:
            combined.extend(existing_items)
        return combined or None

