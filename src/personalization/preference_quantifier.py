from abc import ABC, abstractmethod
from typing import Any, Dict, List


class QuantificationStrategy(ABC):
    """Strategy interface so we can swap in BERT or other scorers later."""

    @abstractmethod
    def quantify(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Return preferences with weights/confidence values applied."""
        raise NotImplementedError


class HeuristicQuantificationStrategy(QuantificationStrategy):
    """
    Lightweight, deterministic quantifier.

    - Likes -> positive weight
    - Dislikes -> negative weight
    - Constraints -> neutral weight to keep downstream logic simple
    """

    def __init__(self, like_weight: float = 0.8, dislike_weight: float = -0.7) -> None:
        self.like_weight = like_weight
        self.dislike_weight = dislike_weight

    def quantify(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        weighted_likes = self._apply_weight(preferences.get("likes", []), self.like_weight)
        weighted_dislikes = self._apply_weight(
            preferences.get("dislikes", []), self.dislike_weight
        )
        constraints = preferences.get("constraints", {})

        return {
            "weighted_preferences": {
                "likes": weighted_likes,
                "dislikes": weighted_dislikes,
                "constraints": constraints,
            },
            "intent": preferences.get("intent", "recommendation"),
            "notes": preferences.get("notes", ""),
        }

    def _apply_weight(self, entries: List[Any], weight: float) -> List[Dict[str, Any]]:
        return [{"value": entry, "weight": weight} for entry in entries]


class PreferenceQuantifier:
    """Facade over a quantification strategy."""

    def __init__(self, strategy: QuantificationStrategy | None = None) -> None:
        self.strategy = strategy or HeuristicQuantificationStrategy()

    def quantify(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        return self.strategy.quantify(preferences)

