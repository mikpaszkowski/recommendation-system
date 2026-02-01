from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class CypherQueryGenerator(ABC):
    """
    Abstract base class for generating Cypher queries.
    """

    @abstractmethod
    def generate_query(
        self,
        user_query: str,
        preferences: Dict[str, Any],
        user_profile: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Generates a Cypher query based on the user's input and context.

        Args:
            user_query: The user's natural language query.
            preferences: Extracted and quantized user preferences.
            user_profile: The persistent user profile.
            conversation_history: Recent conversation history.

        Returns:
            A dictionary containing the generated 'cypher' query string,
            'parameters' dict, and optional 'notes'.
        """
        pass
