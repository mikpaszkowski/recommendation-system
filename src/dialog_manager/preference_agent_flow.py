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
    ) -> None:
        self.history_manager = history_manager or InMemoryHistoryManager()
        self.preference_parser = preference_parser or LLMPreferenceParser()
        self.quantifier = quantifier or PreferenceQuantifier()
        self.profile_manager = profile_manager or InMemoryUserProfileManager()
        self.prompt_constructor = prompt_constructor or PromptConstructor()

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
        prompt_messages = self.prompt_constructor.construct_recommendation_prompt(
            user_query=user_message,
            user_profile=user_profile,
            conversation_history=history,
            retrieved_items=retrieved_items,
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

