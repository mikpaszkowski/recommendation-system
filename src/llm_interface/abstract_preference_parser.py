from abc import ABC, abstractmethod
from typing import Any, Dict


class PreferenceParserInterface(ABC):
    """
    Abstract interface for preference extraction and formatting components.
    Guarantees consistent method signatures across all parser implementations.
    """

    @abstractmethod
    def extract_preferences(self, text: str) -> Dict[str, Any]:
        """
        Extract structured preferences from natural language text.

        Returns a dictionary strictly wrapped in 'current_session_context'
        conforming to CurrentSessionContextWrapper JSON schema.
        """
        pass

    @abstractmethod
    def format_for_recommender(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format extracted preferences for downstream recommendation engines.

        Returns a dictionary containing both canonical 'current_session_context'
        and legacy backward-compatible keys ('likes', 'dislikes', 'constraints',
        'intent', 'notes', 'weighted_preferences').
        """
        pass